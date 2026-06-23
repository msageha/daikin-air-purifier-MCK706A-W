from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api import router
from api.service import DaikinService
from config import get_settings
from daikin import DaikinConnectionError, DaikinError


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.daikin = DaikinService(settings)
    yield


app = FastAPI(
    title="Daikin MCK706A API",
    version="0.1.0",
    description="Local monitoring/control API for the Daikin MCK706A air purifier.",
    lifespan=lifespan,
)
app.include_router(router)


@app.exception_handler(DaikinConnectionError)
async def _conn_handler(_: Request, exc: DaikinConnectionError) -> JSONResponse:
    return JSONResponse(status_code=504, content={"detail": exc.message})


@app.exception_handler(DaikinError)
async def _daikin_handler(_: Request, exc: DaikinError) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={"detail": exc.message, "rsc": exc.rsc},
    )


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"name": "daikin-mck706a-api", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
