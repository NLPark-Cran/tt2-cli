"""统一错误格式：{"error": {"code", "message", "details"}}。"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def err(status: int, code: str, message: str, details: dict | None = None) -> HTTPException:
    """构造统一错误格式的 HTTPException。"""
    return HTTPException(
        status, detail={"error": {"code": code, "message": message, "details": details or {}}}
    )


def _payload(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        # 业务错误直接抛 HTTPException(detail={"error": {...}}) 时透传
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(exc.detail, status_code=exc.status_code)
        return JSONResponse(_payload("http_error", str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            _payload("validation_error", "请求参数不合法", {"errors": exc.errors()[:5]}),
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(_payload("internal_error", "服务器内部错误"), status_code=500)
