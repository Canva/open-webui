from __future__ import annotations

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentDef(BaseModel):
    """A surfaced agent. ``id`` is the stable alias the rebuild sees;
    ``ollama_tag`` is the underlying model the platform pulls + asks
    Ollama to run.

    The rebuild's product domain calls each surfaced entry an "agent"
    (each agent has a preselected underlying model). The OpenAI-
    compatible wire format keeps the legacy field name "model" on the
    response objects and on the ``/v1/models`` path — see
    :mod:`app.oai_models` — so downstream OpenAI SDK clients still
    deserialise it cleanly.
    """

    id: str
    label: str
    ollama_tag: str
    owned_by: str = "agent-platform"


class Settings(BaseSettings):
    # PEP 8 attribute names with case_sensitive=False so the canonical
    # UPPER_SNAKE env-var keys (OLLAMA_BASE_URL, AGENTS, ...) keep
    # populating the lowercase Python attribute. See
    # rebuild/docs/plans/m0-foundations.md § Settings(BaseSettings)
    # "Casing convention (locked)".
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    ollama_base_url: str = "http://ollama:11434"
    host: str = "0.0.0.0"
    port: int = 8081
    log_level: str = "INFO"

    # Default catalogue. Override at compose-time via the AGENTS env
    # var holding a JSON list of AgentDef shapes.
    agents: list[AgentDef] = [
        AgentDef(id="dev", label="Dev (Qwen 2.5, 0.5B)", ollama_tag="qwen2.5:0.5b"),
    ]


settings = Settings()
