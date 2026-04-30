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
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    OLLAMA_BASE_URL: str = "http://ollama:11434"
    HOST: str = "0.0.0.0"
    PORT: int = 8081
    LOG_LEVEL: str = "INFO"

    # Default catalog. Override at compose-time via the MODELS env var
    # holding a JSON list of ModelDef shapes.
    MODELS: list[ModelDef] = [
        ModelDef(id="dev", label="Dev (Qwen 2.5, 0.5B)", ollama_tag="qwen2.5:0.5b"),
    ]


settings = Settings()
