"""``GET /v1/models`` returns the configured catalog in the OpenAI shape.

The rebuild's :class:`app.providers.openai.OpenAICompatibleProvider`
reads ``data[*].id``, ``data[*].owned_by``, and (after this feature's
one-line shim) ``data[*].label``. This test locks every field the
rebuild looks at — including the non-OpenAI ``label`` extension that
makes the friendly dropdown text round-trip end-to-end.

Plan reference: ``rebuild/docs/plans/feature-llm-models.md`` § API
surface (agent platform) → ``GET /v1/models`` and § Tests → Unit
tests (``test_oai_router_models.py``).
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_get_models_returns_configured_catalog(client: TestClient) -> None:
    response = client.get("/v1/models")

    assert response.status_code == 200
    body = response.json()

    assert body["object"] == "list"
    assert len(body["data"]) == 1

    entry = body["data"][0]
    assert entry["id"] == "dev"
    assert entry["label"] == "Dev (Qwen 2.5, 0.5B)"
    assert entry["owned_by"] == "agent-platform"
    assert entry["object"] == "model"
    # ``created`` is a ``time.time()`` snapshot — we only lock the type
    # so a future swap to ``time.time_ns() // 1_000_000`` would break
    # the test loudly. Pinning the exact value would be flaky.
    assert isinstance(entry["created"], int)
