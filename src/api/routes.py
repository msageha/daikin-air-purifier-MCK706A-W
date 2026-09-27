from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from daikin import AirStatus, DecodedLeaf, DeviceInfo

from .schemas import (
    CourseRequest,
    FanSpeedRequest,
    HumidifyRequest,
    HumiditySettingRequest,
    PowerRequest,
    ReadRequest,
    WriteRequest,
)
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


@router.post("/humidify", tags=["control"])
async def humidify(body: HumidifyRequest, service: Service) -> dict[str, bool]:
    """運転切替。加湿 + 空気清浄と、空気清浄のみを切り替える。"""
    await service.run(service.client.set_humidify, body.on)
    return {"humidify": body.on}


@router.post("/course", tags=["control"])
async def course(body: CourseRequest, service: Service) -> dict[str, str]:
    """現在の運転切替側のコースを変える。選べないコースは 409。"""
    await service.run(service.client.set_course, body.course)
    return {"course": body.course}


@router.post("/fan-speed", tags=["control"])
async def fan_speed(body: FanSpeedRequest, service: Service) -> dict[str, str]:
    """手動コースの風量を変える。コースが manual でないと運転には反映されない。"""
    await service.run(service.client.set_fan_speed, body.fan_speed)
    return {"fan_speed": body.fan_speed}


@router.post("/humidity-setting", tags=["control"])
async def humidity_setting(
    body: HumiditySettingRequest, service: Service
) -> dict[str, str]:
    """加湿側のコースに対する湿度設定を変える。そのコースの湿度が自動のときは 409。"""
    await service.run(service.client.set_humidity_setting, body.humidity_setting)
    return {"humidity_setting": body.humidity_setting}
