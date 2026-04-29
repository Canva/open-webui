"""``GET /api/me`` — round-trip endpoint that proves the trusted-header path.

The handler is a one-liner: ``CurrentUser`` triggers
``get_user`` → ``upsert_user_from_headers``, and the row is mapped to the
project ``UserRead`` schema for the response.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import CurrentUser
from app.schemas.user import UserRead

router = APIRouter()


@router.get("/api/me", response_model=UserRead)
async def me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user, from_attributes=True)
