"""FastAPI application factory + ``lifespan``.

The factory pattern keeps tests isolated — each fixture can build a fresh
``FastAPI`` instance without import-time side effects beyond constructing
``settings`` and the engine.

Routers are mounted by the factory; no router knows about the others.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.routers import health, me


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.LOG_LEVEL)
    yield
    # No teardown needed in M0; the engine is process-scoped and uvicorn
    # tears the worker down. M1+ add SSE registry / socket.io shutdown here.


def create_app() -> FastAPI:
    app = FastAPI(title="open-webui rebuild", version="0.0.0", lifespan=lifespan)
    if settings.CORS_ALLOW_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ALLOW_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(me.router)
    return app


app = create_app()
