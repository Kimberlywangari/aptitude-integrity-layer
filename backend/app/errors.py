from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """An expected failure with a stable machine-readable `code` the frontend switches on."""

    def __init__(self, status_code: int, code: str, **extra: Any) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.extra = extra


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse({"code": exc.code, **exc.extra}, status_code=exc.status_code)
