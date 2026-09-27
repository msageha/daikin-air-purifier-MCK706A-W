from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api import DaikinService, router
from daikin import DaikinClient, DaikinConnectionError, DaikinError
from settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    service = DaikinService(
        DaikinClient(settings.daikin_host, timeout=settings.timeout)
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


@app.exception_handler(DaikinConnectionError)
async def connection_error_handler(
    _: Request, exc: DaikinConnectionError
) -> JSONResponse:
    return JSONResponse(status_code=504, content={"detail": str(exc)})


@app.exception_handler(DaikinError)
async def daikin_error_handler(_: Request, exc: DaikinError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc), "rsc": exc.rsc})


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"name": "daikin-mck706a-api", "docs": "/docs"}
