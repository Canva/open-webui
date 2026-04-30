"""``build_agents(settings)`` registry tests.

Locks the alias→tag mapping that the platform's ``GET /v1/models``
exposes and ``POST /v1/chat/completions`` dispatches against. The
registry is the only place that knows about the underlying Ollama
tag (``qwen2.5:0.5b``) — every other surface deals in stable aliases
(``dev``).

Plan reference: ``rebuild/docs/plans/feature-llm-models.md`` § Tests
→ Unit tests (``test_agents.py``) and ``app/agents.py``.
"""

from __future__ import annotations

from pydantic_ai import Agent

from app.agents import build_agents
from app.config import ModelDef, Settings


def test_build_agents_default_catalog_returns_single_dev_entry() -> None:
    settings = Settings(
        MODELS=[
            ModelDef(id="dev", label="Dev (Qwen 2.5, 0.5B)", ollama_tag="qwen2.5:0.5b"),
        ]
    )

    agents = build_agents(settings)

    assert len(agents) == 1
    assert "dev" in agents

    entry = agents["dev"]
    assert entry.definition.id == "dev"
    assert entry.definition.label == "Dev (Qwen 2.5, 0.5B)"
    assert entry.definition.ollama_tag == "qwen2.5:0.5b"
    assert entry.definition.owned_by == "agent-platform"
    assert isinstance(entry.agent, Agent)


def test_build_agents_multi_model_catalog_keeps_each_alias() -> None:
    settings = Settings(
        MODELS=[
            ModelDef(id="a", label="A", ollama_tag="t1"),
            ModelDef(id="b", label="B", ollama_tag="t2"),
        ]
    )

    agents = build_agents(settings)

    assert len(agents) == 2
    assert set(agents.keys()) == {"a", "b"}
    assert agents["a"].definition.ollama_tag == "t1"
    assert agents["b"].definition.ollama_tag == "t2"


def test_build_agents_unknown_alias_returns_none() -> None:
    """The registry is a plain ``dict``; ``.get`` returns ``None``
    for unknown aliases so the router's 404 branch can fire cleanly.
    """
    settings = Settings(
        MODELS=[
            ModelDef(id="dev", label="Dev", ollama_tag="qwen2.5:0.5b"),
        ]
    )
    agents = build_agents(settings)

    assert agents.get("does-not-exist") is None
