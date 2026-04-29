"""Tests for ``app.core.iam_auth``.

boto3 is monkey-patched throughout — none of these tests make a real AWS
API call. The contract we care about is:

1. The on/off flag honours ``settings.DATABASE_IAM_AUTH``.
2. ``resolve_iam_endpoint`` parses the URL, applies the host/port
   overrides, honours the ``user_override`` kwarg, and rejects a URL
   without a username when no override is supplied.
3. ``generate_iam_auth_token`` raises a clear error when no AWS region
   can be resolved through the standard chain (DATABASE_IAM_AUTH_REGION
   → AWS_REGION → AWS_DEFAULT_REGION).
4. ``attach_iam_auth_to_engine`` registers a ``do_connect`` listener
   that injects the minted token into ``cparams['password']``, threads
   the per-engine ``user`` override (``DATABASE_IAM_AUTH_USER`` for
   runtime / ``DATABASE_IAM_AUTH_MIGRATE_USER`` for Alembic) into both
   the token mint and ``cparams['user']``, and (on MySQL) seeds
   ``auth_plugin_map={'mysql_clear_password': None}`` for asyncmy /
   PyMySQL to hand the token to RDS verbatim.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.core import iam_auth
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine

# ---------------------------------------------------------------------------
# is_iam_auth_enabled
# ---------------------------------------------------------------------------


def test_is_iam_auth_enabled_reflects_settings(override_settings: Any) -> None:
    with override_settings(DATABASE_IAM_AUTH=False):
        assert iam_auth.is_iam_auth_enabled() is False
    with override_settings(DATABASE_IAM_AUTH=True):
        assert iam_auth.is_iam_auth_enabled() is True


# ---------------------------------------------------------------------------
# resolve_iam_endpoint
# ---------------------------------------------------------------------------


def test_resolve_iam_endpoint_uses_url_components(override_settings: Any) -> None:
    """No overrides set: pull host/port/user straight from the URL."""
    with override_settings(
        DATABASE_IAM_AUTH_HOST=None,
        DATABASE_IAM_AUTH_PORT=None,
    ):
        host, port, user = iam_auth.resolve_iam_endpoint(
            "mysql+asyncmy://rebuild_app@cluster.us-east-1.rds.amazonaws.com:3307/rebuild"
        )
    assert host == "cluster.us-east-1.rds.amazonaws.com"
    assert port == 3307
    assert user == "rebuild_app"


def test_resolve_iam_endpoint_default_port_is_3306(override_settings: Any) -> None:
    """No port in URL or override: fall back to the MySQL default."""
    with override_settings(
        DATABASE_IAM_AUTH_HOST=None,
        DATABASE_IAM_AUTH_PORT=None,
    ):
        host, port, user = iam_auth.resolve_iam_endpoint(
            "mysql+asyncmy://rebuild_app@cluster.us-east-1.rds.amazonaws.com/rebuild"
        )
    assert host == "cluster.us-east-1.rds.amazonaws.com"
    assert port == 3306
    assert user == "rebuild_app"


def test_resolve_iam_endpoint_host_override_wins(override_settings: Any) -> None:
    """RDS signs tokens for the cluster endpoint; alias must be overridden."""
    with override_settings(
        DATABASE_IAM_AUTH_HOST="cluster-XYZ.us-east-1.rds.amazonaws.com",
        DATABASE_IAM_AUTH_PORT=None,
    ):
        host, _, _ = iam_auth.resolve_iam_endpoint(
            "mysql+asyncmy://rebuild_app@db.canva-internal.com:3306/rebuild"
        )
    assert host == "cluster-XYZ.us-east-1.rds.amazonaws.com"


def test_resolve_iam_endpoint_port_override_wins(override_settings: Any) -> None:
    with override_settings(
        DATABASE_IAM_AUTH_HOST=None,
        DATABASE_IAM_AUTH_PORT=3308,
    ):
        _, port, _ = iam_auth.resolve_iam_endpoint(
            "mysql+asyncmy://rebuild_app@cluster.us-east-1.rds.amazonaws.com:3306/rebuild"
        )
    assert port == 3308


def test_resolve_iam_endpoint_rejects_missing_user(override_settings: Any) -> None:
    """No username and no override is a hard fail — RDS signs ``user@host``."""
    with (
        override_settings(
            DATABASE_IAM_AUTH_HOST=None,
            DATABASE_IAM_AUTH_PORT=None,
        ),
        pytest.raises(RuntimeError, match="user="),
    ):
        iam_auth.resolve_iam_endpoint("mysql+asyncmy://cluster.us-east-1.rds.amazonaws.com/rebuild")


def test_resolve_iam_endpoint_user_override_wins(override_settings: Any) -> None:
    """``user_override`` beats the URL username — that's what lets
    ``DATABASE_IAM_AUTH_MIGRATE_USER=rebuild_migrate`` swap the migration
    Job's IAM identity without touching ``DATABASE_URL``.
    """
    with override_settings(
        DATABASE_IAM_AUTH_HOST=None,
        DATABASE_IAM_AUTH_PORT=None,
    ):
        _, _, user = iam_auth.resolve_iam_endpoint(
            "mysql+asyncmy://rebuild_app@cluster.us-east-1.rds.amazonaws.com:3306/rebuild",
            user_override="rebuild_migrate",
        )
    assert user == "rebuild_migrate"


def test_resolve_iam_endpoint_user_override_satisfies_missing_url_user(
    override_settings: Any,
) -> None:
    """``user_override`` alone is enough — the URL doesn't need a username
    when the per-engine setting supplies one. This is the hardened-deploy
    shape where the URL only carries the host and the IAM user lives
    entirely in ``DATABASE_IAM_AUTH_USER`` / ``DATABASE_IAM_AUTH_MIGRATE_USER``.
    """
    with override_settings(
        DATABASE_IAM_AUTH_HOST=None,
        DATABASE_IAM_AUTH_PORT=None,
    ):
        host, _, user = iam_auth.resolve_iam_endpoint(
            "mysql+asyncmy://cluster.us-east-1.rds.amazonaws.com:3306/rebuild",
            user_override="rebuild_app",
        )
    assert host == "cluster.us-east-1.rds.amazonaws.com"
    assert user == "rebuild_app"


def test_resolve_iam_endpoint_falls_back_to_url_user_when_override_is_none(
    override_settings: Any,
) -> None:
    """``user_override=None`` falls back to the URL username — that's the
    dev-path / today-prod shape where both engines share one IAM user.
    """
    with override_settings(
        DATABASE_IAM_AUTH_HOST=None,
        DATABASE_IAM_AUTH_PORT=None,
    ):
        _, _, user = iam_auth.resolve_iam_endpoint(
            "mysql+asyncmy://rebuild_app@cluster.us-east-1.rds.amazonaws.com:3306/rebuild",
            user_override=None,
        )
    assert user == "rebuild_app"


# ---------------------------------------------------------------------------
# generate_iam_auth_token
# ---------------------------------------------------------------------------


def test_generate_token_calls_boto3(
    monkeypatch: pytest.MonkeyPatch,
    override_settings: Any,
) -> None:
    """Mints via ``boto3.client('rds').generate_db_auth_token(...)``.

    Asserts the helper passes the host/port/user/region through unchanged.
    """
    captured: dict[str, Any] = {}

    class _FakeRdsClient:
        def generate_db_auth_token(
            self,
            *,
            DBHostname: str,
            Port: int,
            DBUsername: str,
            Region: str,
        ) -> str:
            captured.update(
                DBHostname=DBHostname,
                Port=Port,
                DBUsername=DBUsername,
                Region=Region,
            )
            return f"token-for-{DBUsername}@{DBHostname}:{Port}/{Region}"

    class _FakeBoto3Module:
        @staticmethod
        def client(service: str, *, region_name: str) -> _FakeRdsClient:
            assert service == "rds"
            captured["client_region"] = region_name
            return _FakeRdsClient()

    monkeypatch.setitem(__import__("sys").modules, "boto3", _FakeBoto3Module)

    with override_settings(DATABASE_IAM_AUTH_REGION="us-east-1"):
        token = iam_auth.generate_iam_auth_token(
            host="cluster.us-east-1.rds.amazonaws.com",
            port=3306,
            user="rebuild_app",
        )
    assert token == "token-for-rebuild_app@cluster.us-east-1.rds.amazonaws.com:3306/us-east-1"
    assert captured == {
        "DBHostname": "cluster.us-east-1.rds.amazonaws.com",
        "Port": 3306,
        "DBUsername": "rebuild_app",
        "Region": "us-east-1",
        "client_region": "us-east-1",
    }


def test_generate_token_falls_back_to_aws_region(
    monkeypatch: pytest.MonkeyPatch,
    override_settings: Any,
) -> None:
    """Standard boto3 chain: setting ≥ AWS_REGION ≥ AWS_DEFAULT_REGION."""

    class _FakeBoto3Module:
        @staticmethod
        def client(_service: str, *, region_name: str) -> Any:
            class _Client:
                def generate_db_auth_token(self, **_kw: Any) -> str:
                    return f"region={region_name}"

            return _Client()

    monkeypatch.setitem(__import__("sys").modules, "boto3", _FakeBoto3Module)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.setenv("AWS_REGION", "ap-southeast-2")

    with override_settings(DATABASE_IAM_AUTH_REGION=None):
        token = iam_auth.generate_iam_auth_token(
            host="h",
            port=3306,
            user="u",
        )
    assert token == "region=ap-southeast-2"


def test_generate_token_without_region_fails_clearly(
    monkeypatch: pytest.MonkeyPatch,
    override_settings: Any,
) -> None:
    """No region anywhere → refuse to call boto3."""
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    with (
        override_settings(DATABASE_IAM_AUTH_REGION=None),
        pytest.raises(RuntimeError, match="no AWS region"),
    ):
        iam_auth.generate_iam_auth_token(host="h", port=3306, user="u")


# ---------------------------------------------------------------------------
# attach_iam_auth_to_engine
# ---------------------------------------------------------------------------


def _fire_do_connect(engine: Any) -> dict[str, Any]:
    """Invoke the registered ``do_connect`` listener and return cparams.

    SQLAlchemy's ``do_connect`` event normally fires inside
    ``Pool._do_get`` before the driver's ``connect()`` runs. The
    listener's contract is "mutate ``cparams`` in place"; we don't need
    a real DB connection to observe that side effect.

    ``do_connect`` is defined on ``DialectEvents`` (not
    ``ConnectionEvents``), so even though `event.listens_for(engine,
    'do_connect', ...)` reads naturally, the listener is actually
    registered against ``engine.dialect.dispatch`` after SQLAlchemy's
    ``_accept_with`` rewrites the target. Calling the dispatcher
    directly therefore goes through ``dialect.dispatch.do_connect``.
    """
    sync_target = getattr(engine, "sync_engine", engine)
    cparams: dict[str, Any] = {}
    sync_target.dialect.dispatch.do_connect(
        sync_target.dialect,
        None,
        [],
        cparams,
    )
    return cparams


def test_attach_iam_auth_async_engine_injects_token(
    monkeypatch: pytest.MonkeyPatch,
    override_settings: Any,
) -> None:
    """``do_connect`` mints a token and stuffs it into ``cparams['password']``.

    Uses :func:`create_async_engine` to verify the helper unwraps to
    ``async_engine.sync_engine`` correctly. The fake boto3 returns a
    sentinel string we can assert on directly. With no ``user`` kwarg
    the helper falls back to the URL username (``rebuild_app``) — that
    fallback is what makes the dev path keep working unmodified.
    """
    monkeypatch.setattr(
        iam_auth,
        "generate_iam_auth_token",
        lambda *args, **kwargs: "FAKE_IAM_TOKEN",
    )

    async_engine = create_async_engine(
        "mysql+asyncmy://rebuild_app@cluster.us-east-1.rds.amazonaws.com:3306/rebuild"
    )
    try:
        with override_settings(
            DATABASE_IAM_AUTH=True,
            DATABASE_IAM_AUTH_HOST=None,
            DATABASE_IAM_AUTH_PORT=None,
            DATABASE_IAM_AUTH_REGION="us-east-1",
        ):
            iam_auth.attach_iam_auth_to_engine(async_engine, dialect="mysql")
            cparams = _fire_do_connect(async_engine)
    finally:
        # Sync dispose because the async engine never opened a real
        # connection — sync_engine.dispose() is the right teardown.
        async_engine.sync_engine.dispose()

    assert cparams["password"] == "FAKE_IAM_TOKEN"
    assert cparams["user"] == "rebuild_app"
    # MySQL branch: asyncmy / PyMySQL must hand the token to RDS as-is,
    # not hashed against a random salt the way mysql_native_password does.
    assert cparams["auth_plugin_map"] == {"mysql_clear_password": None}


def test_attach_iam_auth_user_override_threads_to_token_and_cparams(
    monkeypatch: pytest.MonkeyPatch,
    override_settings: Any,
) -> None:
    """The per-engine ``user`` kwarg flows into both the token mint and
    ``cparams['user']`` — the contract the Alembic engine relies on to
    swap the migration IAM identity (``DATABASE_IAM_AUTH_MIGRATE_USER``)
    without touching ``DATABASE_URL``.
    """
    captured_user: dict[str, str] = {}

    def _fake_mint(host: str, port: int, user: str, region: Any) -> str:
        captured_user["user"] = user
        return f"TOKEN_FOR_{user}"

    monkeypatch.setattr(iam_auth, "generate_iam_auth_token", _fake_mint)

    async_engine = create_async_engine(
        "mysql+asyncmy://rebuild_app@cluster.us-east-1.rds.amazonaws.com:3306/rebuild"
    )
    try:
        with override_settings(
            DATABASE_IAM_AUTH=True,
            DATABASE_IAM_AUTH_HOST=None,
            DATABASE_IAM_AUTH_PORT=None,
            DATABASE_IAM_AUTH_REGION="us-east-1",
        ):
            iam_auth.attach_iam_auth_to_engine(
                async_engine, dialect="mysql", user="rebuild_migrate"
            )
            cparams = _fire_do_connect(async_engine)
    finally:
        async_engine.sync_engine.dispose()

    assert captured_user["user"] == "rebuild_migrate"
    assert cparams["password"] == "TOKEN_FOR_rebuild_migrate"
    # Critical: the URL says ``rebuild_app`` but the override must win,
    # otherwise asyncmy/PyMySQL would authenticate as the URL user.
    assert cparams["user"] == "rebuild_migrate"


def test_attach_iam_auth_sync_engine_works(
    monkeypatch: pytest.MonkeyPatch,
    override_settings: Any,
) -> None:
    """The helper accepts a sync :class:`Engine` too (used by Alembic)."""
    monkeypatch.setattr(
        iam_auth,
        "generate_iam_auth_token",
        lambda *args, **kwargs: "ANOTHER_TOKEN",
    )

    sync_engine = create_engine(
        "mysql+pymysql://rebuild_app@cluster.us-east-1.rds.amazonaws.com:3306/rebuild"
    )
    try:
        with override_settings(
            DATABASE_IAM_AUTH=True,
            DATABASE_IAM_AUTH_HOST=None,
            DATABASE_IAM_AUTH_PORT=None,
            DATABASE_IAM_AUTH_REGION="us-east-1",
        ):
            iam_auth.attach_iam_auth_to_engine(sync_engine, dialect="mysql")
            cparams = _fire_do_connect(sync_engine)
    finally:
        sync_engine.dispose()

    assert cparams["password"] == "ANOTHER_TOKEN"
    assert cparams["user"] == "rebuild_app"


def test_attach_iam_auth_non_mysql_dialect_skips_auth_plugin_map(
    monkeypatch: pytest.MonkeyPatch,
    override_settings: Any,
) -> None:
    """The MySQL-only ``auth_plugin_map`` fixup is gated on ``dialect``.

    The rebuild only ever passes ``dialect='mysql'`` (rebuild.md §2 pins
    MySQL), but the parameter exists on the helper for symmetry with
    the legacy fork — assert the branch is honoured. We reuse a MySQL
    URL here purely to avoid pulling psycopg2 in as a test dep; the
    helper's branching is on the keyword arg, not on the engine's
    actual dialect, so this exercises the contract we care about.
    """
    monkeypatch.setattr(
        iam_auth,
        "generate_iam_auth_token",
        lambda *args, **kwargs: "PG_TOKEN",
    )

    sync_engine = create_engine(
        "mysql+pymysql://rebuild_app@cluster.us-east-1.rds.amazonaws.com:3306/rebuild"
    )
    try:
        with override_settings(
            DATABASE_IAM_AUTH=True,
            DATABASE_IAM_AUTH_HOST=None,
            DATABASE_IAM_AUTH_PORT=None,
            DATABASE_IAM_AUTH_REGION="us-east-1",
        ):
            iam_auth.attach_iam_auth_to_engine(sync_engine, dialect="postgresql")
            cparams = _fire_do_connect(sync_engine)
    finally:
        sync_engine.dispose()

    assert cparams["password"] == "PG_TOKEN"
    # The user override hook fires regardless of dialect — only the
    # MySQL-specific ``auth_plugin_map`` fixup is gated.
    assert cparams["user"] == "rebuild_app"
    assert "auth_plugin_map" not in cparams


# ---------------------------------------------------------------------------
# url_with_iam_token (one-shot helper)
# ---------------------------------------------------------------------------


def test_url_with_iam_token_embeds_minted_token(
    monkeypatch: pytest.MonkeyPatch,
    override_settings: Any,
) -> None:
    """One-shot consumers can embed a fresh token into the URL."""
    monkeypatch.setattr(
        iam_auth,
        "generate_iam_auth_token",
        lambda *args, **kwargs: "tok with/special?chars",
    )

    with override_settings(
        DATABASE_IAM_AUTH_HOST=None,
        DATABASE_IAM_AUTH_PORT=None,
    ):
        url = iam_auth.url_with_iam_token(
            "mysql+asyncmy://rebuild_app@cluster.us-east-1.rds.amazonaws.com:3306/rebuild"
        )

    # Token's special chars must be URL-encoded so the password slot
    # parses cleanly back out at the driver.
    assert "tok+with%2Fspecial%3Fchars" in url
    assert "rebuild_app:" in url
    assert "@cluster.us-east-1.rds.amazonaws.com:3306" in url
