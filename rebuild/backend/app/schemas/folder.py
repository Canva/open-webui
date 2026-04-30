"""Request / response schemas for the M2 folder surface.

Router handlers live in ``app/routers/folders.py`` (Phase 2b dispatch); this
module owns only the wire shapes. Every schema inherits from
:class:`StrictModel` so unknown fields are rejected at validation time.

Locked references:

* ``rebuild/docs/plans/m2-conversations.md`` § Folder CRUD.
* The DELETE response shape (:class:`FolderDeleteResult`) is consumed by
  the frontend ``folders`` and ``chats`` stores to update in place;
  without it the sidebar would have to refetch both lists after every
  folder deletion.
"""

from __future__ import annotations

from pydantic import Field

from app.schemas._base import StrictModel


class FolderRead(StrictModel):
    id: str
    parent_id: str | None
    name: str
    expanded: bool
    created_at: int
    updated_at: int


class FolderCreate(StrictModel):
    """Body for ``POST /api/folders``. ``name`` rejects empty / whitespace-only
    via :class:`StrictModel`'s ``str_strip_whitespace=True`` plus
    ``min_length=1``."""

    name: str = Field(min_length=1)
    parent_id: str | None = None


class FolderPatch(StrictModel):
    """Body for ``PATCH /api/folders/{id}``. Every field is optional so a
    rename, a move, and an expand toggle are all the same endpoint with
    different fields populated.

    A non-``None`` ``parent_id`` triggers the recursive-CTE cycle check in
    the folder router (a folder may not be moved into one of its own
    descendants); the schema does not enforce that — it's a server-side
    check against the live folder tree.
    """

    name: str | None = Field(default=None, min_length=1)
    parent_id: str | None = None
    expanded: bool | None = None


class FolderDeleteResult(StrictModel):
    """Response for ``DELETE /api/folders/{id}``.

    ``deleted_folder_ids`` includes the target folder + every descendant
    (computed via the recursive descendant CTE in the folder router).
    ``detached_chat_ids`` is the set of chats whose ``folder_id`` was set
    to ``NULL`` because they lived inside a deleted folder — folder
    deletion never destroys conversations.
    """

    deleted_folder_ids: list[str]
    detached_chat_ids: list[str]
