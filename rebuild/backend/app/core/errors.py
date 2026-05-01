"""Application-level error type + FastAPI exception handler registration.

Kept intentionally tiny in M0; M2+ raise ``AppError`` subclasses (and
narrow domain exceptions like
:class:`app.services.chat_writer.HistoryTooLargeError`) for domain
errors that should not be exposed as raw stack traces.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.providers.openai import ProviderError
from app.services.chat_writer import HistoryTooLargeError


class AppError(Exception):
    """Base class for application-level errors with an HTTP shape."""

    status_code: int = 500
    detail: str = "internal error"

    def __init__(self, detail: str | None = None, *, status_code: int | None = None) -> None:
        if detail is not None:
            self.detail = detail
        if status_code is not None:
            self.status_code = status_code
        super().__init__(self.detail)


def register_exception_handlers(app: FastAPI) -> None:
    """Attach project-wide exception handlers to ``app``."""

    @app.exception_handler(AppError)
    async def _app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {"detail": "validation error", "errors": exc.errors()},
            status_code=422,
        )

    @app.exception_handler(HistoryTooLargeError)
    async def _history_too_large_handler(
        _request: Request, _exc: HistoryTooLargeError
    ) -> JSONResponse:
        # Request-side path (e.g. a client posts a too-large chat or a
        # PATCH that would overflow). The streaming generator (Phase 2c)
        # catches the same exception inside its persist loop and emits a
        # terminal SSE ``error`` frame instead — that path never reaches
        # this handler because headers have already been sent.
        return JSONResponse(
            {"detail": "chat history exceeds 1 MiB cap"},
            status_code=413,
        )

    @app.exception_handler(ProviderError)
    async def _provider_error_handler(_request: Request, exc: ProviderError) -> JSONResponse:
        # Non-streaming surfaces — ``GET /api/agents``, ``POST /api/chats/{id}/title``
        # — let :class:`app.providers.openai.ProviderError` bubble out so the
        # status code (502 / 504 / 429) is owned in one place. The streaming
        # generator (Phase 2c) catches it inside the SSE loop and emits a
        # terminal ``error`` frame instead, never reaching this handler.
        return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)
