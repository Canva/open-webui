"""Project-wide dependency type aliases.

Route signatures use these directly (``user: CurrentUser``, ``db: DbSession``)
rather than ``user: User = Depends(get_user)``. The first form silently
becomes a query-parameter declaration if the ``Depends()`` wrapper is
forgotten; the alias form is impossible to typo. Enforced by the AST gate in
``backend/tests/test_no_bare_depends.py`` (scoped to ``app/routers/``).

M1 adds ``Provider``; M0 ships ``CurrentUser`` + ``DbSession`` only.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_user
from app.core.db import get_session
from app.models.user import User

CurrentUser = Annotated[User, Depends(get_user)]
DbSession = Annotated[AsyncSession, Depends(get_session)]
