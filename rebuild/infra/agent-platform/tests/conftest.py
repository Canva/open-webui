"""Test fixtures for the agent-platform unit suite.

The platform's tests mount the OAI router on a **bare** ``FastAPI()`` —
no ``lifespan`` attached, so the Ollama health probe never fires. The
production ``app/main.py`` lifespan is what wires ``app.state.agents``;
here, every fixture that needs the agents map populates it directly
on the freshly-built app. This is the same shape as the rebuild
backend's test seam (``app.dependency_overrides`` for swapping
collaborators) — see
``rebuild/docs/best-practises/FastAPI-best-practises.md`` § A.11.

Two seams are exposed:

* :func:`agents_dict` — the production ``build_agents(settings)``
  result. The agents are pointed at a phantom Ollama URL but are
  never invoked by the routes that consume this fixture (only
  ``GET /v1/models`` reads ``definition`` fields).
* :func:`make_client` — a factory that takes any ``agents`` mapping
  and returns a fresh :class:`fastapi.testclient.TestClient`. Tests
  that need to actually run an agent (chat completions stream /
  non-stream) build a ``TestModel``-backed agent in-test and pass it
  in — see :mod:`test_oai_router_chat` and
  :mod:`test_oai_router_nonstream`.

The seam choice for the chat tests is ``pydantic_ai.models.test.TestModel``
(in-process, deterministic, zero HTTP). ``respx`` mocking against the
SDK's outbound HTTP would also work but is brittle: pydantic-ai's
``OpenAIModel`` makes the OpenAI SDK do its own HTTP and matching the
exact request shape (model id, body, headers) is fragile. ``TestModel``
plugs in at the model-driver layer ``Agent`` already abstracts.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents import AgentEntry, build_agents
from app.config import AgentDef, Settings
from app.oai_router import router as oai_router


@pytest.fixture
def app_settings() -> Settings:
    """A :class:`Settings` instance with the platform default catalogue.

    Constructed explicitly (rather than relying on the module-level
    ``settings = Settings()`` import side-effect in ``app/config.py``)
    so a future test can pass a different ``agents=[...]`` list without
    fighting environment leakage from a previous test.
    """
    return Settings(
        agents=[
            AgentDef(id="dev", label="Dev (Qwen 2.5, 0.5B)", ollama_tag="qwen2.5:0.5b"),
        ]
    )


@pytest.fixture
def agents_dict(app_settings: Settings) -> dict[str, AgentEntry]:
    """The production ``build_agents(settings)`` map.

    The OpenAI provider inside each entry is bound to a phantom
    ``http://ollama:11434`` URL — never reached because the routes
    using this fixture (``GET /v1/models``, error paths on
    ``POST /v1/chat/completions``) only read ``entry.definition`` and
    never invoke ``entry.agent``.
    """
    return build_agents(app_settings)


@pytest.fixture
def make_client() -> Callable[[Mapping[str, AgentEntry]], TestClient]:
    """Factory that mounts the OAI router on a bare app and returns a TestClient.

    No ``lifespan`` is attached, so the Ollama health probe in
    :func:`app.main.lifespan` never fires — the platform tests don't
    need to exercise that path (the lifespan is its own seam, and the
    plan's § Tests block deliberately scopes the unit suite to the
    router + helpers + agents factory).
    """

    def _make(agents: Mapping[str, AgentEntry]) -> TestClient:
        app = FastAPI()
        app.include_router(oai_router)
        app.state.agents = dict(agents)
        return TestClient(app)

    return _make


@pytest.fixture
def client(
    make_client: Callable[[Mapping[str, AgentEntry]], TestClient],
    agents_dict: dict[str, AgentEntry],
) -> TestClient:
    """A TestClient bound to the production ``build_agents`` output.

    Used by :mod:`test_oai_router_models` and any other test that only
    reads ``entry.definition`` without invoking ``entry.agent``.
    """
    return make_client(agents_dict)
