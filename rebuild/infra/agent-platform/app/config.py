from __future__ import annotations

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelDef(BaseModel):
    """A surfaced model. ``id`` is the stable alias the rebuild sees;
    ``ollama_tag`` is what the platform pulls + asks Ollama to run.
    """

    id: str
    label: str
    ollama_tag: str
    owned_by: str = "agent-platform"


class Settings(BaseSettings):
    # PEP 8 attribute names with case_sensitive=False so the canonical
    # UPPER_SNAKE env-var keys (OLLAMA_BASE_URL, MODELS, ...) keep
    # populating the lowercase Python attribute. See
    # rebuild/docs/plans/m0-foundations.md § Settings(BaseSettings)
    # "Casing convention (locked)".
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    ollama_base_url: str = "http://ollama:11434"
    host: str = "0.0.0.0"
    port: int = 8081
    log_level: str = "INFO"

    # Default catalog. Override at compose-time via the MODELS env var
    # holding a JSON list of ModelDef shapes.
    models: list[ModelDef] = [
        ModelDef(id="dev", label="Dev (Qwen 2.5, 0.5B)", ollama_tag="qwen2.5:0.5b"),
    ]


settings = Settings()
