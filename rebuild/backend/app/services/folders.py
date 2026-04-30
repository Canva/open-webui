"""Folder-tree CTE helpers used by ``app/routers/folders.py``.

The folder router stays thin by delegating the two recursive-CTE shapes
locked in ``rebuild/docs/plans/m2-conversations.md`` § Cycle detection
and descendant computation to this module:

* :func:`assert_no_cycle` — upward "ancestors of candidate parent" CTE.
  Used by ``POST /api/folders`` (validates the parent exists + belongs
  to the user) and by ``PATCH /api/folders/{id}`` when ``parent_id``
  changes (the additional check that the folder being moved does not
  appear in its own ancestor chain).
* :func:`collect_descendants` — downward "all descendants of target"
  CTE. Used by ``DELETE /api/folders/{id}`` to populate the response
  payload's ``deleted_folder_ids`` and to drive the chat-detach
  ``UPDATE``. The DB-level ``ON DELETE CASCADE`` (``folder.parent_id``)
  and ``ON DELETE SET NULL`` (``chat.folder_id``) remain in place as a
  belt-and-braces guarantee — the CTE exists to populate the *response*,
  not to do the cascade itself (plan lines 612–613).

Why a dedicated service module rather than inline SQL in the router:

* Avoids the "raw SQL inside a router file" anti-pattern that the
  router half of ``rebuild/docs/best-practises/FastAPI-best-practises.md``
  § A.5 calls out.
* Lets the M2 ``test_folders_*`` integration tests exercise the CTEs in
  isolation (one fixture, no FastAPI client).
* Keeps the per-statement ``SET SESSION cte_max_recursion_depth = 256``
  preamble visible at exactly one call site per CTE, which the plan
  (line 584) requires.

The constant :data:`FOLDER_CTE_MAX_DEPTH` lives here — *not* in
``app/core/constants.py`` — because it is intrinsic to this query rather
than a project-wide tunable (plan line 584).
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

FOLDER_CTE_MAX_DEPTH: int = 256
"""Hard cap on recursion depth for both folder-tree CTEs.

The session variable ``cte_max_recursion_depth`` is set to this value
per-statement (never per-connection) so every other query in the
codebase keeps MySQL's 1000 default. Setting it on the SQLAlchemy
``engine.connect`` event would silently lower the cap globally and
surface as confusing "max recursion" errors anywhere a future migration
adds a deeper CTE — see plan line 584 for the locked rationale.
"""


_ANCESTORS_CTE = text(
    """
    WITH RECURSIVE ancestors AS (
        SELECT id, parent_id, 0 AS depth
        FROM folder
        WHERE id = :candidate_parent_id AND user_id = :user_id
        UNION ALL
        SELECT f.id, f.parent_id, a.depth + 1
        FROM folder f
        JOIN ancestors a ON f.id = a.parent_id
        WHERE f.user_id = :user_id AND a.depth < :max_depth
    )
    SELECT id FROM ancestors
    """
)

_DESCENDANTS_CTE = text(
    """
    WITH RECURSIVE descendants AS (
        SELECT id, parent_id, 0 AS depth
        FROM folder
        WHERE id = :folder_id AND user_id = :user_id
        UNION ALL
        SELECT f.id, f.parent_id, d.depth + 1
        FROM folder f
        JOIN descendants d ON f.parent_id = d.id
        WHERE f.user_id = :user_id AND d.depth < :max_depth
    )
    SELECT id FROM descendants
    """
)

_SET_CTE_DEPTH = text(f"SET SESSION cte_max_recursion_depth = {FOLDER_CTE_MAX_DEPTH}")


async def assert_no_cycle(
    session: AsyncSession,
    *,
    candidate_parent_id: str,
    folder_being_moved: str | None,
    user_id: str,
) -> None:
    """Validate that setting ``parent_id = candidate_parent_id`` would not
    create a cycle in the user's folder tree.

    Two call shapes:

    * **Create** (``folder_being_moved is None``): the candidate parent
      simply has to exist and belong to the user; a cycle is impossible
      because the new folder has no descendants yet. A missing parent
      raises ``404``.
    * **Move** (``folder_being_moved`` is the id being moved): walks the
      ancestor chain upward from ``candidate_parent_id``; if
      ``folder_being_moved`` appears, the move would put the folder
      inside one of its own descendants and we raise ``409``.

    The user-id filter on every iteration is intentional defence in
    depth — the FK already enforces it, but a buggy future revision must
    not be able to walk into another user's folder tree (plan line 602).
    """
    await session.execute(_SET_CTE_DEPTH)
    result = await session.execute(
        _ANCESTORS_CTE,
        {
            "candidate_parent_id": candidate_parent_id,
            "user_id": user_id,
            "max_depth": FOLDER_CTE_MAX_DEPTH,
        },
    )
    ancestor_ids = {row[0] for row in result.all()}

    if not ancestor_ids:
        # The recursive CTE's anchor row is the candidate parent itself,
        # filtered by ``user_id``. An empty result means the candidate
        # parent either does not exist or belongs to another user; in
        # both cases we leak nothing about other users' rows by returning
        # 404 (plan/best-practices: "404, not 403, for missing/foreign
        # rows" — FastAPI-best-practises § A.9).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="parent folder not found",
        )

    if folder_being_moved is not None and folder_being_moved in ancestor_ids:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="cycle")


async def collect_descendants(
    session: AsyncSession,
    *,
    folder_id: str,
    user_id: str,
) -> list[str]:
    """Return ``[folder_id, ...all_descendant_ids]`` ordered breadth-first.

    Used by ``DELETE /api/folders/{id}`` to:

    1. Populate the ``deleted_folder_ids`` response field.
    2. Drive the ``UPDATE chat SET folder_id = NULL WHERE folder_id IN (...)``
       that produces ``detached_chat_ids``.
    3. Drive the final ``DELETE FROM folder WHERE id IN (...)``.

    Returns an empty list if the target folder does not exist or does
    not belong to the user — the router maps that to ``404``.
    """
    await session.execute(_SET_CTE_DEPTH)
    result = await session.execute(
        _DESCENDANTS_CTE,
        {
            "folder_id": folder_id,
            "user_id": user_id,
            "max_depth": FOLDER_CTE_MAX_DEPTH,
        },
    )
    return [row[0] for row in result.all()]
