"""Domain exceptions and their HTTP mapping."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class TranslateBookError(Exception):
    """Base class for everything this application raises deliberately."""

    status_code = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(TranslateBookError):
    status_code = 404


class ValidationError(TranslateBookError):
    status_code = 422


class ConflictError(TranslateBookError):
    """The resource exists but is in a state that forbids this operation."""

    status_code = 409


class ExtractionError(TranslateBookError):
    status_code = 422


class ProviderError(TranslateBookError):
    """An LLM provider is misconfigured or unreachable."""

    status_code = 503


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(TranslateBookError)
    async def _handle(_: Request, exc: TranslateBookError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": type(exc).__name__, "detail": exc.message},
        )
