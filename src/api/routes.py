from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from .schemas import (
    AirStatus,
    DeviceInfo,
    PowerRequest,
    ReadRequest,
    WriteRequest,
)
from .service import DaikinService

router = APIRouter(prefix="/api")


def get_service(request: Request) -> DaikinService:
    return request.app.state.daikin


@router.get("/health", tags=["system"])
async def health(service: DaikinService = Depends(get_service)) -> dict[str, Any]:
    return {"status": "ok", "host": service.client.host}


@router.get("/info", response_model=DeviceInfo, tags=["status"])
async def info(service: DaikinService = Depends(get_service)) -> DeviceInfo:
    raw = await service.run(service.client.device_info)
    return DeviceInfo.model_validate(raw)


@router.get("/status", response_model=AirStatus, tags=["status"])
async def status(service: DaikinService = Depends(get_service)) -> AirStatus:
    raw = await service.run(service.client.air_status)
    return AirStatus.model_validate(raw)


@router.get("/tree", tags=["status"])
async def tree(service: DaikinService = Depends(get_service)) -> dict[str, Any]:
    return await service.run(service.client.status_tree)


@router.post("/read", tags=["raw"])
async def read(
    body: ReadRequest,
    service: DaikinService = Depends(get_service),
) -> dict[str, Any]:
    return await service.run(service.client.read, body.targets)


@router.post("/write", tags=["raw"])
async def write(
    body: WriteRequest,
    service: DaikinService = Depends(get_service),
) -> dict[str, Any]:
    if not body.confirm:
        raise HTTPException(
            status_code=400, detail="Set confirm=true to write to the unit"
        )
    result = await service.run(service.client.write, body.to, body.entity_path, body.pv)
    return {
        "written": {"to": body.to, "entity_path": body.entity_path, "pv": body.pv},
        "result": result,
    }


@router.post("/power", tags=["control"])
async def power(
    body: PowerRequest,
    service: DaikinService = Depends(get_service),
) -> dict[str, Any]:
    await service.run(service.client.set_power, body.on)
    return {"power": body.on}
