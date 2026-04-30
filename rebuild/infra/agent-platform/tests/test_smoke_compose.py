"""End-to-end smoke test against the running compose stack.

Skipped by default. Two gates have to be satisfied for this test to run:

1. The :mod:`compose` pytest marker (declared in
   ``rebuild/infra/agent-platform/pyproject.toml``) is selected — i.e.
   pytest is invoked with ``-m compose`` or ``-m "compose or ..."``.
   The platform's standard suite uses ``-m "not compose"`` and skips
   this file entirely.
2. The ``COMPOSE_E2E=1`` environment variable is set, so an unguarded
   ``pytest`` invocation against a quiescent dev box doesn't try to
   curl localhost:8080 and report a confusing connection-refused.

The test exercises the rebuild's HTTP surface, **not** the platform's
own ``/v1/models`` — the goal is to verify the end-to-end path the
acceptance criteria call out (rebuild app → MODEL_GATEWAY_BASE_URL →
agent-platform → ollama). The streaming chat half is deferred to a
follow-up: creating a chat through the rebuild requires folder
plumbing that is heavyweight to wire from a smoke test, and the
``/api/models`` curl is the minimum viable signal called out in the
plan's § Acceptance criteria first bullet.

Plan reference: ``rebuild/docs/plans/feature-llm-models.md`` § Tests
→ Unit tests (``test_smoke_compose.py``) and § Acceptance criteria.
"""

from __future__ import annotations

import os

import httpx
import pytest

# Marker keeps the test out of the default suite; env var keeps it from
# firing under ``-m compose`` when no stack is up.
pytestmark = [
    pytest.mark.compose,
    pytest.mark.skipif(
        os.environ.get("COMPOSE_E2E") != "1",
        reason="set COMPOSE_E2E=1 (with the docker stack up) to enable",
    ),
]


def test_rebuild_app_lists_dev_model_through_agent_platform() -> None:
    """Compose is up: the rebuild's ``/api/models`` includes ``dev``.

    Identity is established via the trusted-proxy header
    ``X-Forwarded-Email`` per the rebuild's ``get_user`` dependency.
    """
    response = httpx.get(
        "http://localhost:8080/api/models",
        headers={"X-Forwarded-Email": "smoke@canva.com"},
        timeout=30.0,
    )
    assert response.status_code == 200
    items = response.json()["items"]
    ids = {item["id"] for item in items}
    assert "dev" in ids, f"expected 'dev' in {ids!r}"

    # TODO(smoke): exercise streaming POST against /api/chats/{id}/messages
    # once the smoke harness has folder + chat creation helpers wired up.
    # The plan's first acceptance check (this assertion) is the minimum
    # viable signal that the whole chain (rebuild app → agent-platform →
    # ollama) is healthy.
