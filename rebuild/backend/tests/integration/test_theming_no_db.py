"""M1 theming "no DB persistence" integration test.

Pinned by ``rebuild/docs/plans/m1-theming.md`` § Tests § Backend
integration (``test_theming_no_db.py``) AND § Acceptance criteria
("the picker round-trip touches NO database tables outside the M0
``user`` upsert").

Plain English contract:

  The M1 theme picker is a pure client-side concern. The cookie + the
  ``localStorage["theme"]`` mirror are both written from JavaScript;
  the SvelteKit ``hooks.server.ts`` reads the cookie on every render
  and emits ``<html data-theme="X">``, but does NOT call any backend
  endpoint to persist it. The only HTTP request the picker page makes
  to the FastAPI service is the M0-baseline ``GET /api/me`` (which
  the trusted-header dep upserts the ``user`` row from). Anything else
  — a sneaky ``POST /api/users/me/theme``, a side-effecting load that
  writes a ``user_settings`` row — would be a regression and a
  database-best-practises § 1 violation: M1 is supposed to ship with
  zero schema additions.

Two complementary assertions:

  1. **Wire-shaped**: Attach a SQLAlchemy ``before_cursor_execute``
     event on the per-test async engine (capturing every SQL statement
     issued during a single ``GET /api/me`` round-trip with a trusted-
     header email). The captured statement set must contain only the
     ``user`` table — exactly the M0 upsert/select shape.
  2. **Static**: Walk ``app.routes`` and assert NO route's path or
     handler-function name matches the regex ``r"theme"`` (case-
     insensitive). This guards against a future router that *would*
     touch the DB on the picker's behalf even before that router is
     wired into the picker.

Why not drive the actual Playwright leg from inside pytest:
  Cross-process (pytest → vite dev server → playwright) plumbing is
  fragile; the M0 deterministic E2E stack lives in two separate
  pipelines (``make test-unit`` and ``make test-e2e-smoke``). The
  picker only ever talks to ``/api/me`` from the page lifecycle (the
  store mutates JS state and rewrites the cookie/localStorage; SSR on
  reload picks the cookie back up). Replicating "the only HTTP request
  the picker triggers backend-side is /api/me" via a single httpx GET
  here is equivalent to running the full UI flow for the purposes of
  this assertion. The Playwright-based ``theme-explicit-persists
  .spec.ts`` covers the UI-side persistence contract end-to-end.

If a future milestone (M2+) adds a real backend endpoint that touches
user data adjacent to themes (e.g. accessibility prefs in user_settings,
or the M3 share path emitting per-share theme choices), extend this
test by:

  - Adding the new permitted table(s) to ``ALLOWED_TABLES_BY_ROUTE``.
  - Updating the regex check to account for whatever neighbour
    namespace the new route lives under.

Do NOT relax the regex to "anything goes" — the locked decision is "M1
ships no theme route", and M2+ should re-evaluate the locked decision
deliberately rather than slip the constraint silently.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

# Tables the M0 ``GET /api/me`` round-trip is allowed to touch.
# Anything else surfacing in the captured statement set is a
# regression — surface it in the failure message so the orchestrator
# knows which router to suspect.
ALLOWED_TABLES = frozenset({"user"})


# Regex for the static route-walk assertion. Case-insensitive, matches
# anywhere in the path or handler-function name.
THEME_ROUTE_REGEX = re.compile(r"theme", re.IGNORECASE)


def _capture_sql_statements(sync_engine: Engine, sink: list[str]) -> None:
    """Wire a ``before_cursor_execute`` event onto a sync engine.

    SQLAlchemy events fire on the synchronous Engine layer that sits
    underneath the async wrapper. ``AsyncEngine.sync_engine`` is the
    correct attachment point.

    The dispatch's database-best-practises § 6 (event-listener
    diagnostics) explicitly authorises this pattern for cross-cutting
    invariants — it's load-bearing for the M1 "no DB persistence"
    decision lock.
    """

    @sa.event.listens_for(sync_engine, "before_cursor_execute")
    def _record(  # type: ignore[unused-ignore]
        conn: Connection,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        sink.append(statement)


def _extract_table_names(statement: str) -> set[str]:
    """Extract bare table identifiers from a captured SQL statement.

    Heuristic — sufficient for the M0 single-table surface, NOT a
    full SQL parser. Picks up table identifiers after explicit table-
    referencing keywords:

      - ``FROM <table>``       (SELECT ... FROM, DELETE FROM)
      - ``INSERT INTO <table>`` (UPDATE-style INSERT statements)
      - ``UPDATE <table> SET`` (statement-leading UPDATE only — the
        ``ON DUPLICATE KEY UPDATE col = ...`` MySQL-upsert clause uses
        the same keyword but for column-level updates, NOT a table
        reference, so anchoring on ``^UPDATE`` avoids that false
        positive)
      - ``JOIN <table>``       (any join variant)

    Quoted identifiers (with backticks) are stripped.

    For any future expansion (M2+ surfaces query joins, CTEs, or
    sub-SELECTs that the heuristic mis-handles), swap this to a real
    SQL parser like ``sqlglot``; the heuristic is fine while M1's
    only path is the user upsert.
    """
    tables: set[str] = set()
    # Statement-leading UPDATE — the ``^`` anchors past leading whitespace,
    # which prevents matching the trailing ``ON DUPLICATE KEY UPDATE col =
    # ...`` clause MySQL emits for upserts. Only ``UPDATE <table> SET ...``
    # at statement head should count as a table reference.
    leading_update = re.match(r"\s*UPDATE\s+`?(\w+)`?\s+SET\b", statement, re.IGNORECASE)
    if leading_update:
        tables.add(leading_update.group(1).lower())

    # FROM / INTO / JOIN are unambiguous: they always introduce a table
    # identifier as their next non-whitespace token.
    pattern = re.compile(
        r"\b(?:FROM|INTO|JOIN)\s+`?(\w+)`?",
        re.IGNORECASE,
    )
    for match in pattern.finditer(statement):
        tables.add(match.group(1).lower())
    return tables


@pytest.mark.asyncio
async def test_picker_round_trip_touches_only_the_user_table(
    client: Any,
    engine: Any,
) -> None:
    """The picker's only backend round-trip is GET /api/me; SQL must
    only touch the ``user`` table.

    See module docstring for the full contract reasoning. If a future
    author adds a backend endpoint adjacent to themes that *should*
    touch user data, extend ``ALLOWED_TABLES`` rather than weakening
    this assertion.
    """
    captured: list[str] = []
    _capture_sql_statements(engine.sync_engine, captured)

    response = await client.get(
        "/api/me",
        headers={
            "X-Forwarded-Email": "alice@canva.com",
            "X-Forwarded-Name": "Alice Example",
        },
    )
    assert response.status_code == 200, (
        "expected /api/me to round-trip cleanly with the M0 trusted-header path; "
        f"got {response.status_code} {response.text}"
    )

    # Aggregate the table set across every captured statement and
    # assert it is exactly the allow-list — surface the actual
    # captured SQL on failure so a regression is debuggable from the
    # CI log alone.
    touched: set[str] = set()
    for statement in captured:
        touched |= _extract_table_names(statement)

    forbidden = touched - ALLOWED_TABLES
    assert not forbidden, (
        "the M1 picker round-trip touched a non-permitted table; this is a "
        "regression of the locked 'no DB persistence' decision in m1-theming.md "
        "§ Acceptance criteria.\n"
        f"  forbidden tables:        {sorted(forbidden)}\n"
        f"  permitted tables (M0):   {sorted(ALLOWED_TABLES)}\n"
        f"  full captured statement set ({len(captured)} statements):\n    "
        + "\n    ".join(captured)
    )


def test_no_fastapi_route_references_theme() -> None:
    """No FastAPI route exists whose path or handler name mentions ``theme``.

    Static counterpart to the wire-shaped check above: even if no client
    currently calls a hypothetical ``/api/users/me/theme`` endpoint,
    *registering* one would be a quiet violation of the locked decision
    — the next svelte-engineer who adds a fetch in the picker would
    then unknowingly opt-in to backend persistence.
    """
    from app.main import app

    offending: list[tuple[str, str]] = []
    for route in app.routes:
        path = getattr(route, "path", "") or ""
        endpoint = getattr(route, "endpoint", None)
        endpoint_name = getattr(endpoint, "__name__", "") if endpoint else ""
        if THEME_ROUTE_REGEX.search(path) or THEME_ROUTE_REGEX.search(endpoint_name):
            offending.append((path, endpoint_name))

    assert not offending, (
        "found a FastAPI route whose path or handler name references 'theme'; "
        "this is a regression of the M1 'no theme route' decision lock.\n"
        f"  offending routes: {offending}\n"
        "If you intentionally added a theme endpoint in M2+, update "
        "ALLOWED_TABLES + the regex above and document the new contract."
    )
