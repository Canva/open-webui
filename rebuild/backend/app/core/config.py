"""Project-wide ``Settings(BaseSettings)``.

Single source of truth for every deployment knob in the rebuild. Loaded once
at import time (``settings = Settings()``); values are immutable after
construction. Python attribute names follow PEP 8 ``snake_case``; env-var
keys remain the canonical UPPER_SNAKE shell convention. The bridge is
``model_config = SettingsConfigDict(case_sensitive=False, ...)``, which lets
pydantic-settings populate ``settings.database_url`` from a ``DATABASE_URL``
env var without per-field aliasing. See
``rebuild/docs/plans/m0-foundations.md`` § Settings(BaseSettings)
"Casing convention (locked)" and
``rebuild/docs/best-practises/FastAPI-best-practises.md`` § B.3 for the full
rule.

Later milestones extend this class in-place with new fields (M5's
``automation_*`` knobs, M6's ``otel_*``, ``log_format``,
``trusted_proxy_cidrs``, ``ratelimit_*``, ``allowed_file_types``). M2 adds
``sse_stream_timeout_seconds``. No per-domain ``BaseSettings`` subclasses
(locked in ``rebuild/docs/best-practises/FastAPI-best-practises.md`` § A.1).
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
        case_sensitive=False,
        extra="ignore",
    )

    env: Literal["dev", "test", "staging", "prod"] = "dev"
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "INFO"

    database_url: str = "mysql+asyncmy://rebuild:rebuild@mysql:3306/rebuild?charset=utf8mb4"
    db_pool_size: int = 10
    db_pool_max_overflow: int = 5
    # The IAM auth token TTL is ~900 s; this default sits above that and
    # leans on ``pool_pre_ping`` to discard stalled connections. Set
    # below 900 if you want belt-and-braces token rotation.
    db_pool_recycle_seconds: int = 1800

    # AWS RDS / Aurora MySQL IAM database authentication. Off in dev
    # compose; on in staging + prod against Aurora behind IRSA. See
    # ``app.core.iam_auth`` and ``rebuild/docs/plans/m0-foundations.md``
    # § IAM database authentication for the full surface.
    database_iam_auth: bool = False
    database_iam_auth_region: str | None = None
    database_iam_auth_host: str | None = None
    database_iam_auth_port: int | None = None
    # IAM database user the *runtime* engine authenticates as.
    # Defaults to ``database_url``'s username slot when unset.
    database_iam_auth_user: str | None = None
    # IAM database user the *Alembic migration Job* authenticates as.
    # Defaults to ``database_url``'s username slot when unset. Today this
    # holds the same value as ``database_iam_auth_user`` (we operate one
    # IAM user with ALL PRIVILEGES); future least-privilege split flips
    # this to ``rebuild_migrate`` without a code change. See
    # ``rebuild/docs/best-practises/database-best-practises.md`` § B.9.
    database_iam_auth_migrate_user: str | None = None

    redis_url: str = "redis://redis:6379/0"

    model_gateway_base_url: str | None = None
    model_gateway_api_key: SecretStr | None = None

    trusted_email_header: str = "X-Forwarded-Email"
    trusted_name_header: str = "X-Forwarded-Name"
    # `NoDecode` opts these list[str] fields out of pydantic-settings' default
    # JSON decoding so the env-var input is handed to ``_split_csv`` below as
    # a raw string. Without it, ``CORS_ALLOW_ORIGINS=a,b`` would error before
    # the validator ever runs.
    trusted_email_domain_allowlist: Annotated[list[str], NoDecode] = []

    max_upload_bytes: int = 5_242_880  # 5 MiB; matches rebuild.md §9.

    cors_allow_origins: Annotated[list[str], NoDecode] = []

    readyz_db_timeout_ms: int = 1000
    readyz_redis_timeout_ms: int = 500

    # Whole-request cap on ``POST /api/chats/{id}/messages``. Wrapped around
    # the provider iteration via ``async with asyncio.timeout(...)`` *inside*
    # the M2 streaming generator so the persist-partial branch owns the
    # cleanup path. MUST equal the M6 per-route HTTP timeout for
    # ``/api/chats/{id}/messages`` (see
    # ``rebuild/docs/plans/m6-hardening.md`` § Per-route HTTP timeouts) —
    # diverging the two means the route timeout can fire before the
    # executor's persist-partial branch runs. See
    # ``rebuild/docs/plans/m2-conversations.md`` § Settings additions.
    sse_stream_timeout_seconds: int = 300

    @field_validator(
        "trusted_email_domain_allowlist",
        "cors_allow_origins",
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
        if not self.database_iam_auth:
            return self
        parsed = urlparse(self.database_url)
        if parsed.password:
            raise ValueError(
                "DATABASE_IAM_AUTH=True but DATABASE_URL still carries a "
                "static password. Drop the password from DATABASE_URL — the "
                "IAM token is minted at connect time."
            )
        # The runtime engine resolves its IAM user via database_iam_auth_user
        # → database_url's username; the migration engine via
        # database_iam_auth_migrate_user → database_url's username. At least
        # one of those chains has to terminate in a value or the helper has
        # nothing to sign the token for. Fail clearly here rather than let
        # ``resolve_iam_endpoint`` raise a less-obvious RuntimeError on the
        # first connection attempt.
        runtime_user = self.database_iam_auth_user or parsed.username
        migrate_user = self.database_iam_auth_migrate_user or parsed.username
        if not runtime_user or not migrate_user:
            raise ValueError(
                "DATABASE_IAM_AUTH=True but no IAM database username could "
                "be resolved. Set DATABASE_IAM_AUTH_USER and "
                "DATABASE_IAM_AUTH_MIGRATE_USER explicitly, or put the user "
                "in DATABASE_URL (e.g. mysql+asyncmy://rebuild_app@host/db)."
            )
        return self


settings = Settings()
