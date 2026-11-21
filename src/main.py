import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api import DaikinService, router
from daikin import (
    DaikinClient,
    DaikinConnectionError,
    DaikinError,
    DaikinUnsupportedError,
)
from settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    service = DaikinService(
        DaikinClient(str(settings.daikin_host), timeout=settings.timeout)
    )
    app.state.daikin = service
    try:
        yield
    finally:
        await service.run(service.client.close)


app = FastAPI(
    title="Daikin MCK706A API",
    version="0.1.0",
    description=(
        "Daikin MCK706A 空気清浄機のローカル dsiot API をラップした監視・操作 API。"
    ),
    lifespan=lifespan,
)
app.include_router(router)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    errors: list[dict[str, Any]] = jsonable_encoder(exc.errors())
    return JSONResponse(
        status_code=422, content={"detail": [_json_safe(e) for e in errors]}
    )


def _json_safe(error: dict[str, Any]) -> dict[str, Any]:
    """
    既定の 422 の応答と同じ形のエラー。入力値を JSON にできない (NaN や孤立した surrogate) ときだけ input を除く。

    除かないと、応答を JSON にできずに 500 になる。
    """
    try:
        # JSONResponse と同じ設定で直列化する。孤立した surrogate は UTF-8 への encode で UnicodeEncodeError
        # (ValueError の派生) になる。
        json.dumps(error, ensure_ascii=False, allow_nan=False).encode()
    except ValueError:
        return {key: value for key, value in error.items() if key != "input"}
    return error


@app.exception_handler(DaikinConnectionError)
async def connection_error_handler(
    _: Request, exc: DaikinConnectionError
) -> JSONResponse:
    return JSONResponse(status_code=504, content={"detail": str(exc)})


@app.exception_handler(DaikinUnsupportedError)
async def unsupported_error_handler(
    _: Request, exc: DaikinUnsupportedError
) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(DaikinError)
async def daikin_error_handler(_: Request, exc: DaikinError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc), "rsc": exc.rsc})


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"name": "daikin-mck706a-api", "docs": "/docs"}
