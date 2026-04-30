"""Folder CRUD — list / create / patch / delete with recursive-CTE cycle
and descendant computation per ``rebuild/docs/plans/m2-conversations.md``
§ Folder CRUD and § Cycle detection and descendant computation.

Layering:

* This router is intentionally thin. The two recursive-CTE shapes live
  in :mod:`app.services.folders` so the router does not inline raw SQL
  (``rebuild/docs/best-practises/FastAPI-best-practises.md`` § A.5).
* All ``Folder.user_id == user.id`` filters are issued explicitly on
  every read and write — defence in depth even with the FK
  (``database-best-practises.md`` § A.5 / § C "404 not 403"). Foreign or
  missing rows produce ``404`` and never leak existence.

DELETE uses the descendant CTE to populate the response payload only;
the actual cascade still runs through the DB-level
``ON DELETE CASCADE`` (``folder.parent_id``) and ``ON DELETE SET NULL``
(``chat.folder_id``) — see plan lines 612–613.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, select, update

from app.core.deps import CurrentUser, DbSession
from app.core.ids import new_id
from app.core.time import now_ms
from app.models.chat import Chat
from app.models.folder import Folder
from app.schemas.folder import FolderCreate, FolderDeleteResult, FolderPatch, FolderRead
from app.services.folders import assert_no_cycle, collect_descendants

router = APIRouter(prefix="/api", tags=["folders"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_owned_folder(db: DbSession, *, folder_id: str, user_id: str) -> Folder:
    """Load a folder by id + user, or raise ``404``.

    Centralised so every PATCH / DELETE path uses the same shape; the
    user filter is the single most important invariant on this router
    and reading it once makes the call sites unambiguous.
    """
    folder = await db.scalar(
        select(Folder).where(Folder.id == folder_id, Folder.user_id == user_id)
    )
    if folder is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="folder not found")
    return folder


def _to_read(folder: Folder) -> FolderRead:
    return FolderRead(
        id=folder.id,
        parent_id=folder.parent_id,
        name=folder.name,
        expanded=folder.expanded,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/folders", response_model=list[FolderRead])
async def list_folders(user: CurrentUser, db: DbSession) -> list[FolderRead]:
    """Flat list of the user's folders, oldest first.

    The UI builds the parent/child tree client-side from this flat shape
    (plan line 555). Sorting on ``created_at`` keeps top-level folders in
    creation order; the sidebar's tree renderer is the place where
    parent-child grouping happens.
    """
    rows = await db.scalars(
        select(Folder).where(Folder.user_id == user.id).order_by(Folder.created_at.asc())
    )
    return [_to_read(f) for f in rows.all()]


@router.post("/folders", response_model=FolderRead, status_code=status.HTTP_201_CREATED)
async def create_folder(body: FolderCreate, user: CurrentUser, db: DbSession) -> FolderRead:
    """Create a folder, optionally under ``parent_id``.

    A non-null ``parent_id`` triggers
    :func:`app.services.folders.assert_no_cycle`, which validates the
    parent exists and belongs to the user (404 otherwise). The cycle
    branch can never fire on create — a brand-new folder has no
    descendants — but the parent-existence check is the same code path.
    """
    if body.parent_id is not None:
        await assert_no_cycle(
            db,
            candidate_parent_id=body.parent_id,
            folder_being_moved=None,
            user_id=user.id,
        )

    now = now_ms()
    folder = Folder(
        id=new_id(),
        user_id=user.id,
        parent_id=body.parent_id,
        name=body.name,
        expanded=False,
        created_at=now,
        updated_at=now,
    )
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return _to_read(folder)


@router.patch("/folders/{folder_id}", response_model=FolderRead)
async def patch_folder(
    folder_id: str, body: FolderPatch, user: CurrentUser, db: DbSession
) -> FolderRead:
    """Rename / move / toggle ``expanded``. All fields optional.

    A ``parent_id`` change triggers the cycle CTE — moving a folder into
    one of its own descendants raises ``409``. A ``parent_id`` that does
    not exist (or belongs to another user) raises ``404`` from the same
    CTE (the empty-anchor branch in :func:`assert_no_cycle`).
    """
    folder = await _load_owned_folder(db, folder_id=folder_id, user_id=user.id)
    patch = body.model_dump(exclude_unset=True)

    if "parent_id" in patch and patch["parent_id"] != folder.parent_id:
        new_parent = patch["parent_id"]
        if new_parent is not None:
            await assert_no_cycle(
                db,
                candidate_parent_id=new_parent,
                folder_being_moved=folder.id,
                user_id=user.id,
            )

    for field, value in patch.items():
        setattr(folder, field, value)
    folder.updated_at = now_ms()
    await db.commit()
    await db.refresh(folder)
    return _to_read(folder)


@router.delete("/folders/{folder_id}", response_model=FolderDeleteResult)
async def delete_folder(folder_id: str, user: CurrentUser, db: DbSession) -> FolderDeleteResult:
    """Delete a folder + every descendant; detach (don't delete) chats.

    Steps (all inside one transaction so a partial failure rolls back
    cleanly — plan line 620):

    1. ``collect_descendants`` returns ``[folder_id, ...descendant_ids]``;
       an empty list means the target does not exist or does not belong
       to the user — map to ``404`` to leak nothing.
    2. ``UPDATE chat SET folder_id = NULL WHERE folder_id IN (...)``,
       capturing the affected ids for ``detached_chat_ids``.
    3. ``DELETE FROM folder WHERE id IN (...)`` for the response.

    The DB-level ``ON DELETE CASCADE`` on ``folder.parent_id`` and
    ``ON DELETE SET NULL`` on ``chat.folder_id`` remain in place as
    belt-and-braces; the CTE exists to populate the response payload,
    not to do the cascade itself (plan lines 612–613).
    """
    deleted_ids = await collect_descendants(db, folder_id=folder_id, user_id=user.id)
    if not deleted_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="folder not found")

    detached_rows = await db.scalars(
        select(Chat.id).where(
            Chat.user_id == user.id,
            Chat.folder_id.in_(deleted_ids),
        )
    )
    detached_chat_ids = list(detached_rows.all())

    if detached_chat_ids:
        await db.execute(
            update(Chat)
            .where(Chat.user_id == user.id, Chat.folder_id.in_(deleted_ids))
            .values(folder_id=None, updated_at=now_ms())
        )

    await db.execute(delete(Folder).where(Folder.user_id == user.id, Folder.id.in_(deleted_ids)))
    await db.commit()

    return FolderDeleteResult(
        deleted_folder_ids=deleted_ids,
        detached_chat_ids=detached_chat_ids,
    )
