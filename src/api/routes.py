from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from daikin import AirStatus, DecodedLeaf, DeviceInfo

from .schemas import PowerRequest, ReadRequest, WriteRequest
from .service import DaikinService

router = APIRouter(prefix="/api")


def _get_service(request: Request) -> DaikinService:
    return request.app.state.daikin


Service = Annotated[DaikinService, Depends(_get_service)]


@router.get("/health", tags=["system"])
async def health(service: Service) -> dict[str, str]:
    """本体に触れずに、サーバー状態と接続先を返す。"""
    return {"status": "ok", "host": service.client.host}


@router.get("/info", tags=["status"])
async def info(service: Service) -> DeviceInfo:
    return await service.run(service.client.device_info)


@router.get("/status", tags=["status"])
async def status(service: Service) -> AirStatus:
    return await service.run(service.client.air_status)


@router.get("/tree", tags=["status"])
async def tree(service: Service) -> dict[str, DecodedLeaf]:
    """dgc_status の全リーフの復号済みツリー。未マップのセンサーを探すときに使う。"""
    return await service.run(service.client.status_tree)


@router.post("/read", tags=["raw"])
async def read(body: ReadRequest, service: Service) -> dict[str, Any]:
    """任意アドレスの生読み取り。応答元アドレスをキーにした dict を返す。"""
    return await service.run(service.client.read, body.targets)


@router.post("/write", tags=["raw"])
async def write(body: WriteRequest, service: Service) -> dict[str, Any]:
    """任意プロパティへの生書き込み。confirm=true が必須。"""
    result = await service.run(service.client.write, body.to, body.entity_path, body.pv)
    return {
        "written": {"to": body.to, "entity_path": body.entity_path, "pv": body.pv},
        "result": result,
    }


@router.post("/power", tags=["control"])
async def power(body: PowerRequest, service: Service) -> dict[str, bool]:
    await service.run(service.client.set_power, body.on)
    return {"power": body.on}
