from __future__ import annotations

from dataclasses import dataclass

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.config import ModelDef, Settings


@dataclass(slots=True)
class AgentEntry:
    definition: ModelDef
    agent: Agent[None, str]


def build_agents(settings: Settings) -> dict[str, AgentEntry]:
    """Construct one Agent per configured model. Called once from
    ``lifespan``; the result is cached on ``app.state.agents``.

    A single ``OpenAIProvider`` is reused across every agent — pointed at
    the local Ollama daemon's OpenAI-compatible ``/v1`` surface. No
    ``system_prompt`` is set on the Agent: the rebuild's provider
    already prepends ``params.system`` into ``messages[0]`` before the
    HTTP call, so baking one in here would double-stack. See the plan's
    ``app/agents.py`` section for the locked rationale.
    """
    provider = OpenAIProvider(base_url=f"{settings.ollama_base_url}/v1", api_key="ollama")
    out: dict[str, AgentEntry] = {}
    for defn in settings.models:
        model = OpenAIModel(defn.ollama_tag, provider=provider)
        out[defn.id] = AgentEntry(
            definition=defn,
            agent=Agent(model=model, output_type=str),
        )
    return out
