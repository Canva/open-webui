"""Application-level error type + FastAPI exception handler registration.

Kept intentionally tiny in M0; M2+ raise ``AppError`` subclasses for domain
errors that should not be exposed as raw stack traces.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


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
