"""Project-wide ``Settings(BaseSettings)``.

Single source of truth for every deployment knob in the rebuild. Loaded once
at import time (``settings = Settings()``); values are immutable after
construction. Field naming is locked to UPPER_SNAKE_CASE matching the env-var
name verbatim — see ``rebuild/plans/m0-foundations.md`` § Settings(BaseSettings)
"Casing convention (locked)" — so every call site reads
``settings.MODEL_GATEWAY_BASE_URL``, never the lower-case form.

Later milestones extend this class in-place with new fields (M1's
``SSE_STREAM_TIMEOUT_SECONDS``, M4's ``AUTOMATION_*`` knobs, M5's ``OTEL_*``,
``LOG_FORMAT``, ``TRUSTED_PROXY_CIDRS``, ``RATELIMIT_*``,
``ALLOWED_FILE_TYPES``). No per-domain ``BaseSettings`` subclasses (locked
in ``rebuild/plans/FastAPI-best-practises.md`` § A.1).
"""

from __future__ import annotations

from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment + optional ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    ENV: Literal["dev", "test", "staging", "prod"] = "dev"
    HOST: str = "0.0.0.0"
    PORT: int = 8080
    LOG_LEVEL: str = "INFO"

    DATABASE_URL: str = "mysql+asyncmy://rebuild:rebuild@mysql:3306/rebuild?charset=utf8mb4"
    DB_POOL_SIZE: int = 10
    DB_POOL_MAX_OVERFLOW: int = 5
    # The IAM auth token TTL is ~900 s; this default sits above that and
    # leans on ``pool_pre_ping`` to discard stalled connections. Set
    # below 900 if you want belt-and-braces token rotation.
    DB_POOL_RECYCLE_SECONDS: int = 1800

    # AWS RDS / Aurora MySQL IAM database authentication. Off in dev
    # compose; on in staging + prod against Aurora behind IRSA. See
    # ``app.core.iam_auth`` and ``rebuild/plans/m0-foundations.md``
    # § IAM database authentication for the full surface.
    DATABASE_IAM_AUTH: bool = False
    DATABASE_IAM_AUTH_REGION: str | None = None
    DATABASE_IAM_AUTH_HOST: str | None = None
    DATABASE_IAM_AUTH_PORT: int | None = None
    # IAM database user the *runtime* engine authenticates as.
    # Defaults to ``DATABASE_URL``'s username slot when unset.
    DATABASE_IAM_AUTH_USER: str | None = None
    # IAM database user the *Alembic migration Job* authenticates as.
    # Defaults to ``DATABASE_URL``'s username slot when unset. Today this
    # holds the same value as ``DATABASE_IAM_AUTH_USER`` (we operate one
    # IAM user with ALL PRIVILEGES); future least-privilege split flips
    # this to ``rebuild_migrate`` without a code change. See
    # ``rebuild/plans/database-best-practises.md`` § B.9.
    DATABASE_IAM_AUTH_MIGRATE_USER: str | None = None

    REDIS_URL: str = "redis://redis:6379/0"

    MODEL_GATEWAY_BASE_URL: str | None = None
    MODEL_GATEWAY_API_KEY: SecretStr | None = None

    TRUSTED_EMAIL_HEADER: str = "X-Forwarded-Email"
    TRUSTED_NAME_HEADER: str = "X-Forwarded-Name"
    # `NoDecode` opts these list[str] fields out of pydantic-settings' default
    # JSON decoding so the env-var input is handed to ``_split_csv`` below as
    # a raw string. Without it, ``CORS_ALLOW_ORIGINS=a,b`` would error before
    # the validator ever runs.
    TRUSTED_EMAIL_DOMAIN_ALLOWLIST: Annotated[list[str], NoDecode] = []

    MAX_UPLOAD_BYTES: int = 5_242_880  # 5 MiB; matches rebuild.md §9.

    CORS_ALLOW_ORIGINS: Annotated[list[str], NoDecode] = []

    READYZ_DB_TIMEOUT_MS: int = 1000
    READYZ_REDIS_TIMEOUT_MS: int = 500

    @field_validator(
        "TRUSTED_EMAIL_DOMAIN_ALLOWLIST",
        "CORS_ALLOW_ORIGINS",
        mode="before",
    )
    @classmethod
    def _split_csv(cls, v: object) -> object:
        # pydantic-settings v2 only auto-decodes list fields as JSON; CSV from
        # env vars (the documented input shape per the m0 plan acceptance
        # criteria) needs an explicit splitter. Direct list instantiation is
        # passed through unchanged so test fixtures keep working.
        if v is None or v == "":
            return []
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @model_validator(mode="after")
    def _validate_iam_auth(self) -> Settings:
        # IAM auth is mutually exclusive with a static URL password — silently
        # accepting both would let the static password win by string position
        # and mask a misconfigured deploy. Fail fast at construction so the
        # error surfaces in startup logs, not in a slow-burn token-mint miss.
        if not self.DATABASE_IAM_AUTH:
            return self
        parsed = urlparse(self.DATABASE_URL)
        if parsed.password:
            raise ValueError(
                "DATABASE_IAM_AUTH=True but DATABASE_URL still carries a "
                "static password. Drop the password from DATABASE_URL — the "
                "IAM token is minted at connect time."
            )
        # The runtime engine resolves its IAM user via DATABASE_IAM_AUTH_USER
        # → DATABASE_URL's username; the migration engine via
        # DATABASE_IAM_AUTH_MIGRATE_USER → DATABASE_URL's username. At least
        # one of those chains has to terminate in a value or the helper has
        # nothing to sign the token for. Fail clearly here rather than let
        # ``resolve_iam_endpoint`` raise a less-obvious RuntimeError on the
        # first connection attempt.
        runtime_user = self.DATABASE_IAM_AUTH_USER or parsed.username
        migrate_user = self.DATABASE_IAM_AUTH_MIGRATE_USER or parsed.username
        if not runtime_user or not migrate_user:
            raise ValueError(
                "DATABASE_IAM_AUTH=True but no IAM database username could "
                "be resolved. Set DATABASE_IAM_AUTH_USER and "
                "DATABASE_IAM_AUTH_MIGRATE_USER explicitly, or put the user "
                "in DATABASE_URL (e.g. mysql+asyncmy://rebuild_app@host/db)."
            )
        return self


settings = Settings()
