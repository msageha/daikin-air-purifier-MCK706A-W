import json
import math
from collections.abc import Callable, Coroutine
from typing import Annotated, Any, cast, override

from fastapi import APIRouter, Depends, Request, Response
from fastapi.routing import APIRoute

from api.schemas import (
    CourseRequest,
    FanSpeedRequest,
    HumidifyRequest,
    HumiditySettingRequest,
    PowerRequest,
    ReadRequest,
    WriteRequest,
)
from api.service import DaikinService
from daikin import AirStatus, DecodedLeaf, DeviceInfo


def _parse_finite_float(text: str) -> float:
    """JSON の数値と NaN・Infinity の literal を float にし、有限でない値 (1e999 を含む) は JSONDecodeError にする。"""
    if not math.isfinite(value := float(text)):
        raise json.JSONDecodeError("non-finite number", text, 0)
    return value


class _StrictJsonRequest(Request):
    # json.loads は JSON の値でない NaN・Infinity と、UTF-8 で表せない孤立した surrogate も受け付ける。そうした値は
    # 本体へ送れず、422 の応答の input に載ると直列化できずに 500 になるので、FastAPI が JSON の構文の誤りと同じ
    # 422 (json_invalid) にする JSONDecodeError で拒否する。非有限数は、同名のキーで上書きされる値も拒否できるよう
    # 復号の途中で拒否する。
    @override
    async def json(self) -> Any:
        body = await self.body()
        value = json.loads(
            body, parse_float=_parse_finite_float, parse_constant=_parse_finite_float
        )
        try:
            json.dumps(value, ensure_ascii=False).encode()
        except UnicodeEncodeError as err:
            raise json.JSONDecodeError(
                "unpaired surrogate", body.decode(errors="replace"), 0
            ) from err
        return value


class _StrictJsonRoute(APIRoute):
    @override
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def strict_json_handler(request: Request) -> Response:
            return await handler(_StrictJsonRequest(request.scope, request.receive))

        return strict_json_handler


router = APIRouter(prefix="/api", route_class=_StrictJsonRoute)


async def _get_service(request: Request) -> DaikinService:
    # FastAPI は同期関数の依存を threadpool で実行するので、await しなくても async にする。
    # app.state は型を持たない入れ物で、main.py の lifespan が DaikinService を入れる。
    return cast("DaikinService", request.app.state.daikin)


type Service = Annotated[DaikinService, Depends(_get_service)]


@router.get("/health", tags=["system"])
async def health(service: Service) -> dict[str, str]:
    """本体に触れずに、サーバー状態と接続先を返す。"""
    return {"status": "ok", "host": service.client.host}


@router.get("/info", tags=["status"])
async def info(service: Service) -> DeviceInfo:
    return await service.read(service.client.device_info)


@router.get("/status", tags=["status"])
async def status(service: Service) -> AirStatus:
    return await service.read(service.client.air_status)


@router.get("/tree", tags=["status"])
async def tree(service: Service) -> dict[str, DecodedLeaf]:
    """dgc_status の全リーフの復号済みツリー。未マップのセンサーを探すときに使う。"""
    return await service.read(service.client.status_tree)


@router.post("/read", tags=["raw"])
async def read(body: ReadRequest, *, service: Service) -> dict[str, Any]:
    """任意アドレスの生読み取り。応答元アドレスをキーにした dict を返す。"""
    return await service.run(service.client.read, body.targets)


@router.post("/write", tags=["raw"])
async def write(body: WriteRequest, *, service: Service) -> dict[str, Any]:
    """任意プロパティへの生書き込み。confirm=true が必須。"""
    result = await service.run(
        service.client.write, body.to, entity_path=body.entity_path, pv=body.pv
    )
    return {
        "written": {"to": body.to, "entity_path": body.entity_path, "pv": body.pv},
        "result": result,
    }


@router.post("/power", tags=["control"])
async def power(body: PowerRequest, *, service: Service) -> dict[str, bool]:
    await service.run(service.client.set_power, on=body.on)
    return {"power": body.on}


@router.post("/humidify", tags=["control"])
async def humidify(body: HumidifyRequest, *, service: Service) -> dict[str, bool]:
    """運転切替。加湿 + 空気清浄と、空気清浄のみを切り替える。"""
    await service.run(service.client.set_humidify, on=body.on)
    return {"humidify": body.on}


@router.post("/course", tags=["control"])
async def course(body: CourseRequest, *, service: Service) -> dict[str, str]:
    """現在の運転切替側のコースを変える。選べないコースは 409。"""
    await service.run(service.client.set_course, body.course)
    return {"course": body.course}


@router.post("/fan-speed", tags=["control"])
async def fan_speed(body: FanSpeedRequest, *, service: Service) -> dict[str, str]:
    """手動コースの風量を変える。コースが manual でないと運転には反映されない。"""
    await service.run(service.client.set_fan_speed, body.fan_speed)
    return {"fan_speed": body.fan_speed}


@router.post("/humidity-setting", tags=["control"])
async def humidity_setting(
    body: HumiditySettingRequest, *, service: Service
) -> dict[str, str]:
    """加湿側のコースに対する湿度設定を変える。そのコースの湿度が自動のときは 409。"""
    await service.run(service.client.set_humidity_setting, body.humidity_setting)
    return {"humidity_setting": body.humidity_setting}
