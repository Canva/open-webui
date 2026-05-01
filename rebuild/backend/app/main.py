"""FastAPI application factory + ``lifespan``.

The factory pattern keeps tests isolated — each fixture can build a fresh
``FastAPI`` instance without import-time side effects beyond constructing
``settings`` and the engine.

Routers are mounted by the factory; no router knows about the others.

M2 hosts every long-lived singleton on ``app.state`` so routes resolve
them through the ``Provider`` / ``ModelsCacheDep`` / ``RedisDep`` /
``StreamRegistryDep`` dependency aliases rather than via module-level
singletons (single-instance-per-worker; fork-safe; testable via
``app.dependency_overrides`` — see
``rebuild/docs/best-practises/FastAPI-best-practises.md`` § A.5 / § B.4).

Construction order matters: the Redis connection pool is built first so
the :class:`StreamRegistry` (which holds it) can be constructed next,
before the provider/cache. Shutdown reverses the order: registry, then
Redis, then provider — so the registry can drain its in-flight pubsub
subscriptions while the connection pool is still alive.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.providers.openai import OpenAICompatibleProvider
from app.routers import chats, folders, health, me, models, shares
from app.services.models_cache import ModelsCache
from app.services.stream_registry import StreamRegistry


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.log_level)
    # Redis pool first — the StreamRegistry below holds a reference to it
    # for pubsub subscribe/publish. ``decode_responses=False`` keeps the
    # bytes payloads we publish on cancel (``b"1"``) untouched; the
    # registry never inspects the value.
    redis = Redis.from_url(
        settings.redis_url,
        decode_responses=False,
        max_connections=10,
    )
    app.state.redis = redis
    app.state.stream_registry = StreamRegistry(redis=redis)
    provider = OpenAICompatibleProvider()
    app.state.provider = provider
    app.state.models_cache = ModelsCache(provider)
    try:
        yield
    finally:
        # Tear down in reverse construction order. The registry needs
        # the Redis pool alive while it cancels its outstanding pubsub
        # subscriptions; closing Redis first would leave the listen
        # tasks raising on a dead connection.
        await app.state.stream_registry.aclose()
        await redis.aclose()
        await provider.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="open-webui rebuild", version="0.0.0", lifespan=lifespan)
    if settings.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allow_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(me.router)
    app.include_router(models.router)
    app.include_router(folders.router)
    app.include_router(chats.router)
    # M3 sharing endpoints (POST/DELETE /api/chats/{id}/share, GET /api/shared/{token}).
    app.include_router(shares.router)
    return app


app = create_app()
