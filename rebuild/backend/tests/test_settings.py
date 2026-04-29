"""Tests for ``app.core.config.Settings``.

Each test instantiates a fresh ``Settings()`` with monkeypatched env so it
does not depend on (or pollute) the global ``settings`` singleton built at
import time.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError


def _fresh_settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> object:
    """Drop pollution from the conftest defaults + apply the given env."""
    for key in (
        "ENV",
        "HOST",
        "PORT",
        "LOG_LEVEL",
        "DATABASE_URL",
        "DB_POOL_SIZE",
        "DB_POOL_MAX_OVERFLOW",
        "DB_POOL_RECYCLE_SECONDS",
        "DATABASE_IAM_AUTH",
        "DATABASE_IAM_AUTH_REGION",
        "DATABASE_IAM_AUTH_HOST",
        "DATABASE_IAM_AUTH_PORT",
        "DATABASE_IAM_AUTH_USER",
        "DATABASE_IAM_AUTH_MIGRATE_USER",
        "REDIS_URL",
        "MODEL_GATEWAY_BASE_URL",
        "MODEL_GATEWAY_API_KEY",
        "TRUSTED_EMAIL_HEADER",
        "TRUSTED_NAME_HEADER",
        "TRUSTED_EMAIL_DOMAIN_ALLOWLIST",
        "MAX_UPLOAD_BYTES",
        "CORS_ALLOW_ORIGINS",
        "READYZ_DB_TIMEOUT_MS",
        "READYZ_REDIS_TIMEOUT_MS",
    ):
        monkeypatch.delenv(key, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    # Pretend there's no .env file so test env is hermetic. SettingsConfigDict
    # in app/core/config.py points at ".env"; Pydantic silently ignores a
    # missing file, but we set _env_file=None to be doubly explicit.
    from app.core.config import Settings

    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_defaults_match_table(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spot-check every default in the m0 plan § Settings(BaseSettings) table."""
    s = _fresh_settings(monkeypatch)
    assert s.ENV == "dev"
    assert s.HOST == "0.0.0.0"
    assert s.PORT == 8080
    assert s.LOG_LEVEL == "INFO"
    assert s.DATABASE_URL == ("mysql+asyncmy://rebuild:rebuild@mysql:3306/rebuild?charset=utf8mb4")
    assert s.DB_POOL_SIZE == 10
    assert s.DB_POOL_MAX_OVERFLOW == 5
    assert s.DB_POOL_RECYCLE_SECONDS == 1800
    assert s.REDIS_URL == "redis://redis:6379/0"
    assert s.MODEL_GATEWAY_BASE_URL is None
    assert s.MODEL_GATEWAY_API_KEY is None
    assert s.TRUSTED_EMAIL_HEADER == "X-Forwarded-Email"
    assert s.TRUSTED_NAME_HEADER == "X-Forwarded-Name"
    assert s.TRUSTED_EMAIL_DOMAIN_ALLOWLIST == []
    assert s.MAX_UPLOAD_BYTES == 5_242_880
    assert s.CORS_ALLOW_ORIGINS == []
    assert s.READYZ_DB_TIMEOUT_MS == 1000
    assert s.READYZ_REDIS_TIMEOUT_MS == 500
    # IAM auth is off by default — the dev compose stack uses the static
    # MySQL container password baked into infra/docker-compose.yml.
    assert s.DATABASE_IAM_AUTH is False
    assert s.DATABASE_IAM_AUTH_REGION is None
    assert s.DATABASE_IAM_AUTH_HOST is None
    assert s.DATABASE_IAM_AUTH_PORT is None
    # Per-engine IAM user overrides default to None — the runtime and
    # Alembic engines fall back to the URL username when these are unset.
    # Production sets both explicitly (today they hold the same value).
    assert s.DATABASE_IAM_AUTH_USER is None
    assert s.DATABASE_IAM_AUTH_MIGRATE_USER is None


def test_iam_auth_with_static_password_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``DATABASE_IAM_AUTH=True`` + a password-bearing URL is a hard error.

    Silently accepting both would let the static password win by string
    position and mask a misconfigured prod deploy. The validator must
    fail at construction time with a clear message.
    """
    with pytest.raises(ValidationError) as excinfo:
        _fresh_settings(
            monkeypatch,
            DATABASE_IAM_AUTH="true",
            DATABASE_URL="mysql+asyncmy://rebuild_app:leaked@host/db",
        )
    assert "static password" in str(excinfo.value)


def test_iam_auth_without_any_username_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """IAM auth needs an IAM database username from somewhere.

    The validator accepts a username from any of three sources — the URL,
    ``DATABASE_IAM_AUTH_USER``, or ``DATABASE_IAM_AUTH_MIGRATE_USER`` — but
    refusing to start when none of them is set keeps the misconfiguration
    out of the per-connection token-mint hot path.
    """
    with pytest.raises(ValidationError) as excinfo:
        _fresh_settings(
            monkeypatch,
            DATABASE_IAM_AUTH="true",
            DATABASE_URL="mysql+asyncmy://host/db",
        )
    assert "no IAM database username" in str(excinfo.value)


def test_iam_auth_with_username_only_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The happy dev-path / today-prod shape: URL carries the IAM user
    that both the runtime and Alembic engines fall back to.
    """
    s = _fresh_settings(
        monkeypatch,
        DATABASE_IAM_AUTH="true",
        DATABASE_URL="mysql+asyncmy://rebuild_app@cluster.us-east-1.rds.amazonaws.com:3306/rebuild?ssl=true",
        DATABASE_IAM_AUTH_REGION="us-east-1",
    )
    assert s.DATABASE_IAM_AUTH is True
    assert s.DATABASE_IAM_AUTH_REGION == "us-east-1"


def test_iam_auth_today_prod_shape_with_explicit_users_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The today-prod shape: ``DATABASE_IAM_AUTH_USER`` and
    ``DATABASE_IAM_AUTH_MIGRATE_USER`` are both set explicitly, even
    though they hold the same single-IAM-user value. The credential
    mapping is auditable from ``values-prod.yaml`` alone.
    """
    s = _fresh_settings(
        monkeypatch,
        DATABASE_IAM_AUTH="true",
        DATABASE_URL="mysql+asyncmy://rebuild_app@cluster.us-east-1.rds.amazonaws.com:3306/rebuild?ssl=true",
        DATABASE_IAM_AUTH_REGION="us-east-1",
        DATABASE_IAM_AUTH_USER="rebuild_app",
        DATABASE_IAM_AUTH_MIGRATE_USER="rebuild_app",
    )
    assert s.DATABASE_IAM_AUTH_USER == "rebuild_app"
    assert s.DATABASE_IAM_AUTH_MIGRATE_USER == "rebuild_app"


def test_iam_auth_future_split_shape_with_distinct_users_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The future least-privilege shape: a values-file change flips the
    migration user without touching code or ``DATABASE_URL``. Validator
    must allow the two settings to disagree (that's the whole point of
    the split).
    """
    s = _fresh_settings(
        monkeypatch,
        DATABASE_IAM_AUTH="true",
        DATABASE_URL="mysql+asyncmy://rebuild_app@cluster.us-east-1.rds.amazonaws.com:3306/rebuild?ssl=true",
        DATABASE_IAM_AUTH_REGION="us-east-1",
        DATABASE_IAM_AUTH_USER="rebuild_app",
        DATABASE_IAM_AUTH_MIGRATE_USER="rebuild_migrate",
    )
    assert s.DATABASE_IAM_AUTH_USER == "rebuild_app"
    assert s.DATABASE_IAM_AUTH_MIGRATE_USER == "rebuild_migrate"


def test_iam_auth_url_userless_with_overrides_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hardened-deploy shape: the URL is completely user-less and both
    engines authenticate via the per-engine settings. Validator must
    accept this — the IAM user lives entirely in the override settings.
    """
    s = _fresh_settings(
        monkeypatch,
        DATABASE_IAM_AUTH="true",
        DATABASE_URL="mysql+asyncmy://cluster.us-east-1.rds.amazonaws.com:3306/rebuild?ssl=true",
        DATABASE_IAM_AUTH_REGION="us-east-1",
        DATABASE_IAM_AUTH_USER="rebuild_app",
        DATABASE_IAM_AUTH_MIGRATE_USER="rebuild_app",
    )
    assert s.DATABASE_IAM_AUTH_USER == "rebuild_app"
    assert s.DATABASE_IAM_AUTH_MIGRATE_USER == "rebuild_app"


def test_cors_allow_origins_csv_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    """``CORS_ALLOW_ORIGINS=a,b`` -> ``["a", "b"]``.

    pydantic-settings 2 splits comma-separated env values into ``list[str]``
    when the field is annotated as such (per the m0 plan § Settings table
    note "Pydantic-settings 2 reads CSVs into list[str] automatically when
    annotated"). If this assertion fails on the verifier, ``Settings``
    needs an explicit ``@field_validator(..., mode="before")`` to split
    on commas — the dispatch flagged this as the contract.
    """
    s = _fresh_settings(monkeypatch, CORS_ALLOW_ORIGINS="a,b")
    assert s.CORS_ALLOW_ORIGINS == ["a", "b"]


def test_trusted_email_domain_allowlist_csv_parses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _fresh_settings(
        monkeypatch,
        TRUSTED_EMAIL_DOMAIN_ALLOWLIST="canva.com,example.org",
    )
    assert s.TRUSTED_EMAIL_DOMAIN_ALLOWLIST == ["canva.com", "example.org"]


def test_secret_str_does_not_leak_in_repr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _fresh_settings(monkeypatch, MODEL_GATEWAY_API_KEY="super-secret-key")
    assert isinstance(s.MODEL_GATEWAY_API_KEY, SecretStr)
    # Neither repr nor str of the SecretStr (or the parent Settings) should
    # contain the literal value. SecretStr renders `**********`.
    assert "super-secret-key" not in repr(s.MODEL_GATEWAY_API_KEY)
    assert "super-secret-key" not in str(s.MODEL_GATEWAY_API_KEY)
    assert "super-secret-key" not in repr(s)
    # Caller still has an escape hatch.
    assert s.MODEL_GATEWAY_API_KEY.get_secret_value() == "super-secret-key"


def test_env_literal_rejects_qa(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ENV`` is ``Literal["dev","test","staging","prod"]``; "qa" -> ValidationError."""
    with pytest.raises(ValidationError):
        _fresh_settings(monkeypatch, ENV="qa")


def test_env_literal_accepts_staging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sibling positive: ``staging`` is required by m4/m5 gates."""
    s = _fresh_settings(monkeypatch, ENV="staging")
    assert s.ENV == "staging"
