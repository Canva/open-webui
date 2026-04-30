"""Project-wide dependency type aliases.

Route signatures use these directly (``user: CurrentUser``, ``db: DbSession``)
rather than ``user: User = Depends(get_user)``. The first form silently
becomes a query-parameter declaration if the ``Depends()`` wrapper is
forgotten; the alias form is impossible to typo. Enforced by the AST gate in
``backend/tests/test_no_bare_depends.py`` (scoped to ``app/routers/``).

M2 adds ``Provider`` (the single :class:`OpenAICompatibleProvider`
instance constructed in ``lifespan``), ``ModelsCacheDep`` (the
in-process 5-minute model-list cache), ``RedisDep`` (the per-worker
``redis.asyncio.Redis`` connection pool shared with M4 socket.io and
M6 rate limits), and ``StreamRegistryDep`` (the cancellation registry
that fans cancel signals across pods via Redis pub/sub). All are wired
through ``app.state`` so tests can swap them via
``app.dependency_overrides`` without touching module-level state.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_user
from app.core.db import get_session
from app.models.user import User
from app.providers.openai import OpenAICompatibleProvider
from app.services.models_cache import ModelsCache
from app.services.stream_registry import StreamRegistry

CurrentUser = Annotated[User, Depends(get_user)]
DbSession = Annotated[AsyncSession, Depends(get_session)]


def get_provider(request: Request) -> OpenAICompatibleProvider:
    provider: OpenAICompatibleProvider = request.app.state.provider
    return provider


def get_models_cache(request: Request) -> ModelsCache:
    cache: ModelsCache = request.app.state.models_cache
    return cache


def get_redis(request: Request) -> Redis:
    redis: Redis = request.app.state.redis
    return redis


def get_stream_registry(request: Request) -> StreamRegistry:
    registry: StreamRegistry = request.app.state.stream_registry
    return registry


Provider = Annotated[OpenAICompatibleProvider, Depends(get_provider)]
ModelsCacheDep = Annotated[ModelsCache, Depends(get_models_cache)]
RedisDep = Annotated[Redis, Depends(get_redis)]
StreamRegistryDep = Annotated[StreamRegistry, Depends(get_stream_registry)]
