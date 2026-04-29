"""AWS RDS / Aurora MySQL IAM database authentication.

Production deployments connect to Aurora MySQL behind RDS IAM database
authentication: instead of a static password, ``rds:GenerateDBAuthToken``
mints a short-lived (~15 min) auth token per physical SQLAlchemy
connection. Local development uses the static ``rebuild:rebuild`` MySQL
container password from ``infra/docker-compose.yml`` and never imports
boto3.

The on/off flag is :func:`is_iam_auth_enabled`, which reads
``settings.DATABASE_IAM_AUTH``. When on:

* ``DATABASE_URL`` carries the IAM database username and **no password**.
* :func:`attach_iam_auth_to_engine` registers a SQLAlchemy ``do_connect``
  listener on the engine's sync side. The hook fires once per *physical*
  connection — before the driver's ``connect()`` call — so pool churn
  (recycle / pre-ping / overflow) is the only thing that needs to outpace
  the token's TTL. ``settings.DB_POOL_RECYCLE_SECONDS`` is the single
  knob; set below 900 if you want belt-and-braces.
* boto3 is imported lazily inside :func:`generate_iam_auth_token` so the
  dev path never pays for it.

Concrete shape of a production ``DATABASE_URL``:

    mysql+asyncmy://rebuild_app@cluster-XYZ.us-east-1.rds.amazonaws.com:3306/rebuild?ssl=true

Aurora rejects IAM auth over an unencrypted connection, so the ``ssl=true``
query parameter (or driver-equivalent) is mandatory in prod. The helper
does not flip TLS on for you.

For one-shot consumers that don't sit behind a SQLAlchemy pool we can
hook (e.g. an out-of-band repair script), :func:`url_with_iam_token`
returns ``database_url`` with a freshly-minted token URL-encoded into the
password slot.

Reference: `AWS Aurora User Guide — Connecting using IAM authentication
and boto3 <https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/UsingWithRDS.IAMDBAuth.Connecting.Python.html>`_.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any
from urllib.parse import quote_plus, urlparse, urlunparse

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
    from sqlalchemy.ext.asyncio import AsyncEngine

log = logging.getLogger(__name__)


def is_iam_auth_enabled() -> bool:
    """Return ``True`` when ``settings.DATABASE_IAM_AUTH`` is on.

    Reads the live ``settings`` object so test fixtures that flip the
    field via ``override_settings`` are reflected immediately. The import
    is deferred so this module remains importable in environments where
    pydantic-settings hasn't yet been initialised (e.g. early Alembic
    bootstrap before the settings singleton has constructed).
    """
    from app.core.config import settings

    return bool(settings.DATABASE_IAM_AUTH)


def _resolve_region() -> str | None:
    """Resolve the AWS region for the ``rds:GenerateDBAuthToken`` call.

    Falls through ``settings.DATABASE_IAM_AUTH_REGION`` →
    ``AWS_REGION`` → ``AWS_DEFAULT_REGION`` (the standard boto3 lookup
    chain). Returns ``None`` if none are set; the caller is expected to
    raise with a clear message in that case.
    """
    from app.core.config import settings

    return (
        settings.DATABASE_IAM_AUTH_REGION
        or os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
    )


def resolve_iam_endpoint(
    database_url: str,
    *,
    user_override: str | None = None,
) -> tuple[str, int, str]:
    """Resolve ``(host, port, user)`` to pass to ``generate_db_auth_token``.

    RDS IAM tokens are signed for a specific cluster/instance endpoint —
    a token minted against a CNAME / Route 53 alias is rejected at
    connect time. ``settings.DATABASE_IAM_AUTH_HOST`` lets the caller
    override the host the token is signed for when ``DATABASE_URL`` has
    to use a friendlier alias.

    ``user_override`` is the per-engine IAM database user to authenticate
    as. The runtime engine passes ``settings.DATABASE_IAM_AUTH_USER`` and
    the Alembic engine passes ``settings.DATABASE_IAM_AUTH_MIGRATE_USER``;
    both fall back to the username embedded in ``database_url`` when the
    override is ``None``. The two-setting split is what lets
    ``values-prod.yaml`` flip the migration credential to a separate
    least-privilege IAM user (``rebuild_migrate``) without a code change
    — see ``rebuild/plans/database-best-practises.md`` § B.9.

    Raises ``RuntimeError`` if either host or user is missing — IAM auth
    cannot proceed without both.
    """
    from app.core.config import settings

    parsed = urlparse(database_url)
    host = settings.DATABASE_IAM_AUTH_HOST or parsed.hostname

    port: int
    if settings.DATABASE_IAM_AUTH_PORT is not None:
        port = settings.DATABASE_IAM_AUTH_PORT
    elif parsed.port is not None:
        port = parsed.port
    else:
        port = 3306

    user = user_override or parsed.username

    if not host or not user:
        raise RuntimeError(
            f"DATABASE_IAM_AUTH=True but DATABASE_URL does not carry the IAM "
            f"host and username (host={host!r}, user={user!r}). Override via "
            f"DATABASE_IAM_AUTH_HOST / DATABASE_IAM_AUTH_USER / "
            f"DATABASE_IAM_AUTH_MIGRATE_USER, or fix DATABASE_URL.",
        )
    return host, port, user


def generate_iam_auth_token(
    host: str,
    port: int,
    user: str,
    region: str | None = None,
) -> str:
    """Mint a fresh RDS IAM auth token for ``user@host:port``.

    boto3 is imported lazily so callers that never enable IAM auth (i.e.
    every local-dev path) pay neither the import time nor the on-disk
    cost. Credentials are picked up from the standard boto3 chain — in
    production that resolves to the IRSA / EKS Pod Identity-injected
    web-identity token; locally (if anyone ever turns this on) it walks
    ``~/.aws/credentials``.
    """
    region = region or _resolve_region()
    if not region:
        raise RuntimeError(
            "DATABASE_IAM_AUTH=True but no AWS region resolved. Set "
            "DATABASE_IAM_AUTH_REGION, AWS_REGION, or AWS_DEFAULT_REGION."
        )

    import boto3

    client = boto3.client("rds", region_name=region)
    token: str = client.generate_db_auth_token(
        DBHostname=host,
        Port=int(port),
        DBUsername=user,
        Region=region,
    )
    return token


def attach_iam_auth_to_engine(
    engine: AsyncEngine | Engine,
    *,
    dialect: str = "mysql",
    user: str | None = None,
) -> None:
    """Register a ``do_connect`` listener that injects fresh IAM tokens.

    The listener fires once per *physical* connection, before the
    driver's ``connect()`` call, so pool churn (recycle / pre-ping /
    overflow) is the only path that needs a fresh token. Per-query
    minting would burn an ``rds:GenerateDBAuthToken`` API call on every
    statement; per-startup minting would bake a 15-minute TTL into a
    multi-hour pool member.

    Parameters
    ----------
    engine:
        Either a sync :class:`sqlalchemy.engine.Engine` or an async
        :class:`sqlalchemy.ext.asyncio.AsyncEngine`. For the latter we
        attach to ``engine.sync_engine`` because the SQLAlchemy event
        system runs against the sync core.
    dialect:
        ``"mysql"`` (the rebuild's only target) or ``"postgresql"``
        (kept as a future-proofing seam, mirroring the legacy fork).
        Controls the MySQL-specific ``auth_plugin_map`` connect-arg.
    user:
        Optional per-engine IAM database user override. Pass
        ``settings.DATABASE_IAM_AUTH_USER`` from the runtime engine and
        ``settings.DATABASE_IAM_AUTH_MIGRATE_USER`` from the Alembic
        engine. ``None`` falls back to the username embedded in the
        engine URL — the dev path and the today-prod path
        (``DATABASE_IAM_AUTH_USER == DATABASE_IAM_AUTH_MIGRATE_USER ==
        URL username``) both rely on that fallback.
    """
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import AsyncEngine

    sync_target = engine.sync_engine if isinstance(engine, AsyncEngine) else engine
    host, port, resolved_user = resolve_iam_endpoint(
        str(sync_target.url), user_override=user
    )
    region = _resolve_region()

    if dialect == "mysql":
        # libmysqlclient reads this env var to allow sending the password
        # in clear text. PyMySQL / asyncmy ignore it but it is harmless
        # to set and forecloses a foot-gun if a libmysqlclient build ever
        # slips into the runtime image.
        os.environ.setdefault("LIBMYSQL_ENABLE_CLEARTEXT_PLUGIN", "1")

    @event.listens_for(sync_target, "do_connect")
    def _set_iam_token(  # noqa: ARG001  (SQLAlchemy contract requires the unused params)
        dialect_: Any,
        conn_rec: Any,
        cargs: Any,
        cparams: dict[str, Any],
    ) -> None:
        cparams["password"] = generate_iam_auth_token(host, port, resolved_user, region)
        if dialect == "mysql":
            # RDS expects the IAM token verbatim — not hashed against a
            # random salt the way native ``mysql_native_password`` does.
            # ``mysql_clear_password`` tells PyMySQL / asyncmy to hand
            # the token straight to the server.
            cparams.setdefault("auth_plugin_map", {"mysql_clear_password": None})
        # Override the URL-derived username on the cparams dict too —
        # otherwise asyncmy/PyMySQL will authenticate as the URL user even
        # when the caller asked for a separate IAM identity (e.g. the
        # Alembic engine's DATABASE_IAM_AUTH_MIGRATE_USER override).
        cparams["user"] = resolved_user

    log.info(
        "IAM database authentication enabled for %s as %s@%s:%s (region=%s)",
        dialect,
        resolved_user,
        host,
        port,
        region or "<default>",
    )


def url_with_iam_token(database_url: str) -> str:
    """Return ``database_url`` with a freshly-minted token URL-encoded
    into the password slot.

    Used only by one-shot consumers that do not sit behind a SQLAlchemy
    pool we can hook ``do_connect`` onto. Both the runtime engine
    (:mod:`app.core.db`) and Alembic (:mod:`alembic.env`) use the
    ``do_connect`` path; this helper exists for ad-hoc repair scripts
    and as a parity point with the legacy fork.
    """
    parsed = urlparse(database_url)
    host, port, user = resolve_iam_endpoint(database_url)
    token = generate_iam_auth_token(host, port, user)
    encoded_token = quote_plus(token)

    netloc = f"{quote_plus(user)}:{encoded_token}@{host}"
    if parsed.port is not None:
        netloc += f":{parsed.port}"
    else:
        netloc += f":{port}"

    return urlunparse(parsed._replace(netloc=netloc))
