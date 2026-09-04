"""Error responses, RFC 9457 `application/problem+json`.

Every error body carries a stable machine `code`. The frontend switches on
that code and never on the message text, so wording can improve without
breaking a client.

The money layer's `MoneyError` codes surface here unchanged, which is what
makes the import rejection report and the API speak the same language.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from ledgergraph_domain.money import MoneyError
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_JSON = "application/problem+json"


class ApiError(Exception):
    """A failure with a stable code, raised by services and routers."""

    def __init__(
        self,
        code: str,
        detail: str,
        *,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.detail = detail
        self.status_code = status_code
        self.extra = extra or {}
        super().__init__(detail)


def _problem(
    status_code: int,
    code: str,
    title: str,
    detail: str,
    instance: str,
    **extra: Any,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"https://tallyproof.dev/errors/{code.lower()}",
        "title": title,
        "status": status_code,
        "code": code,
        "detail": detail,
        "instance": instance,
    }
    body.update(extra)
    return JSONResponse(status_code=status_code, content=body, media_type=PROBLEM_JSON)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return _problem(
            exc.status_code,
            exc.code,
            exc.code.replace("_", " ").title(),
            exc.detail,
            str(request.url.path),
            **exc.extra,
        )

    @app.exception_handler(MoneyError)
    async def _money_error(request: Request, exc: MoneyError) -> JSONResponse:
        # A bad amount is a client data problem, and the offending value is
        # echoed back so the caller can find the row without guessing.
        return _problem(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            exc.code,
            "Invalid amount",
            str(exc),
            str(request.url.path),
            offendingValue=None if exc.value is None else str(exc.value)[:120],
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _problem(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "VALIDATION_FAILED",
            "Validation failed",
            "One or more fields did not pass validation.",
            str(request.url.path),
            errors=[
                {
                    "field": ".".join(str(p) for p in e["loc"][1:]),
                    "message": e["msg"],
                    "type": e["type"],
                }
                for e in exc.errors()
            ],
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {
            401: "UNAUTHENTICATED",
            403: "INSUFFICIENT_ROLE",
            404: "NOT_FOUND",
            409: "CONFLICT",
            429: "RATE_LIMITED",
        }
        return _problem(
            exc.status_code,
            codes.get(exc.status_code, "HTTP_ERROR"),
            "Request failed",
            str(exc.detail),
            str(request.url.path),
        )
