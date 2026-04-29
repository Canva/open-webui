"""AWS RDS IAM database authentication.

When ``DATABASE_IAM_AUTH=True`` we treat ``DATABASE_USER`` as an IAM
principal and use boto3 to mint a short-lived auth token (≈15 min TTL)
via ``rds:GenerateDBAuthToken``. The token is then handed to the
underlying DB driver in place of a static password.

Tokens are injected into every new physical connection via SQLAlchemy's
``do_connect`` event, which fires before the driver's ``connect()`` call
on each new pool member. To avoid hammering ``rds:GenerateDBAuthToken``
under heavy connection churn we cache the minted token for
``_TOKEN_TTL_SECONDS`` (10 minutes — comfortably under AWS' 15 minute
token TTL), keyed by ``(host, port, user, region)``. RDS only validates
the token during the AUTH handshake, so a connection authenticated
with a now-expired cached token keeps working; the cache TTL only
governs how long we hand out the same string for *new* connection
attempts. ``pool_pre_ping=True`` (already configured on every engine)
silently re-establishes broken connections, at which point the next
mint pulls a fresh token if the cache has expired.

For one-shot consumers that don't sit behind a SQLAlchemy pool
(peewee_migrate), call :func:`url_with_iam_token` to embed a freshly
minted token in the URL before handing it off.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional
from urllib.parse import quote_plus, urlparse, urlunparse

log = logging.getLogger(__name__)

# boto3 client construction is non-trivial (~100 ms to load JSON service
# models). Clients are documented thread-safe, so we keep one per region
# behind a lock and reuse it across every token mint.
_rds_clients: dict[str, object] = {}
_rds_clients_lock = threading.Lock()

# Cached IAM auth tokens. AWS tokens are valid for ~15 min; we hand out
# the same one for 10 min before re-minting so that bursts of connection
# establishment don't translate into a burst of `rds:GenerateDBAuthToken`
# API calls. Keyed by ``(host, port, user, region)`` so different
# clusters / users can coexist (rare, but cheap to support).
_TOKEN_TTL_SECONDS = 600  # 10 minutes
_token_cache: dict[tuple[str, int, str, str], tuple[str, float]] = {}
_token_cache_lock = threading.Lock()


def _get_rds_client(region: str):
    client = _rds_clients.get(region)
    if client is not None:
        return client
    with _rds_clients_lock:
        client = _rds_clients.get(region)
        if client is None:
            import boto3

            client = boto3.client('rds', region_name=region)
            _rds_clients[region] = client
        return client


def is_iam_auth_enabled() -> bool:
    """Return True when ``DATABASE_IAM_AUTH`` is truthy."""
    return os.environ.get('DATABASE_IAM_AUTH', 'False').lower() == 'true'


def _resolve_region() -> Optional[str]:
    return (
        os.environ.get('DATABASE_IAM_AUTH_REGION')
        or os.environ.get('AWS_REGION')
        or os.environ.get('AWS_DEFAULT_REGION')
    )


def resolve_iam_endpoint(database_url: str) -> tuple[str, int, str]:
    """Resolve ``(host, port, user)`` to pass to ``generate_db_auth_token``.

    RDS IAM tokens are bound to the cluster/instance endpoint, so any
    custom DNS alias must be overridden via ``DATABASE_IAM_AUTH_HOST``.
    """
    parsed = urlparse(database_url)

    host = os.environ.get('DATABASE_IAM_AUTH_HOST') or parsed.hostname

    port_env = os.environ.get('DATABASE_IAM_AUTH_PORT')
    if port_env:
        port = int(port_env)
    elif parsed.port:
        port = parsed.port
    else:
        port = 3306 if parsed.scheme.startswith('mysql') else 5432

    user = os.environ.get('DATABASE_USER') or parsed.username

    if not host or not user:
        raise RuntimeError(
            'DATABASE_IAM_AUTH is enabled but a host and user are required. '
            'Provide them via DATABASE_URL or DATABASE_IAM_AUTH_HOST / DATABASE_USER.'
        )
    return host, port, user


def generate_iam_auth_token(
    host: str,
    port: int,
    user: str,
    region: Optional[str] = None,
) -> str:
    """Return a fresh RDS IAM auth token for ``user@host:port``.

    boto3 is imported lazily so the rest of the application can run
    without it being installed when IAM auth is disabled.
    """
    region = region or _resolve_region()
    if not region:
        raise RuntimeError(
            'DATABASE_IAM_AUTH is enabled but no AWS region could be resolved. '
            'Set DATABASE_IAM_AUTH_REGION, AWS_REGION, or AWS_DEFAULT_REGION.'
        )

    cache_key = (host, int(port), user, region)
    now = time.monotonic()

    # Lock-free fast path: dict.get() is atomic under the GIL, so even
    # if another thread is concurrently writing inside the lock below
    # we'll see either the old tuple or the new one — never a torn read.
    cached = _token_cache.get(cache_key)
    if cached is not None and cached[1] > now:
        return cached[0]

    with _token_cache_lock:
        # Double-checked locking: another thread may have minted while
        # we were waiting on the lock.
        cached = _token_cache.get(cache_key)
        if cached is not None and cached[1] > now:
            return cached[0]

        client = _get_rds_client(region)
        token = client.generate_db_auth_token(
            DBHostname=host,
            Port=int(port),
            DBUsername=user,
            Region=region,
        )
        _token_cache[cache_key] = (token, now + _TOKEN_TTL_SECONDS)
        return token


def attach_iam_auth_to_engine(engine, *, dialect: str) -> None:
    """Register a ``do_connect`` listener that injects fresh IAM tokens.

    Parameters
    ----------
    engine:
        Either a sync ``Engine`` or an async ``AsyncEngine`` (we
        transparently target ``async_engine.sync_engine`` for the
        latter).
    dialect:
        ``'mysql'`` or ``'postgresql'`` — controls a couple of
        MySQL-specific connect-arg fixups.
    """
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import AsyncEngine

    sync_target = engine.sync_engine if isinstance(engine, AsyncEngine) else engine
    host, port, user = resolve_iam_endpoint(str(sync_target.url))
    region = _resolve_region()

    if dialect == 'mysql':
        # libmysqlclient reads this env var to allow sending the password
        # in clear text; PyMySQL / aiomysql ignore it but it's harmless
        # to set and avoids gotchas if a libmysqlclient build slips in.
        os.environ.setdefault('LIBMYSQL_ENABLE_CLEARTEXT_PLUGIN', '1')

    @event.listens_for(sync_target, 'do_connect')
    def _set_iam_token(dialect_, conn_rec, cargs, cparams):  # noqa: ARG001
        cparams['password'] = generate_iam_auth_token(host, port, user, region)
        if dialect == 'mysql':
            # Tell PyMySQL / aiomysql to use the cleartext-password handler:
            # RDS expects the IAM token verbatim, not hashed against a
            # random salt the way native mysql_native_password does.
            cparams.setdefault('auth_plugin_map', {'mysql_clear_password': None})

    log.info(
        'IAM database authentication enabled for %s as %s@%s:%s (region=%s)',
        dialect,
        user,
        host,
        port,
        region or '<default>',
    )


def url_with_iam_token(database_url: str) -> str:
    """Return ``database_url`` with a freshly-minted IAM token embedded
    as the URL password.

    Used by one-shot consumers (peewee_migrate) that don't sit behind a
    SQLAlchemy pool we can hook ``do_connect`` onto.
    """
    parsed = urlparse(database_url)
    host, port, user = resolve_iam_endpoint(database_url)
    token = generate_iam_auth_token(host, port, user)
    encoded_token = quote_plus(token)

    # Rebuild netloc as user:token@host[:port]
    netloc = f'{quote_plus(user)}:{encoded_token}@{host}'
    if parsed.port:
        netloc += f':{parsed.port}'
    elif port_env := os.environ.get('DATABASE_IAM_AUTH_PORT'):
        netloc += f':{port_env}'

    return urlunparse(parsed._replace(netloc=netloc))
