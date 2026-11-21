"""サーバーの起動設定と GET /api/health: 本体に触れずにサーバーの状態と接続先を返す。"""

import time
from pathlib import Path

import pytest

from tests.harness import FakeUnit, Stack, run_api


def test_health_reports_the_unit_url_without_contacting_the_unit(
    stack: Stack,
) -> None:
    stack.unit.reset()

    response = stack.api.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "host": stack.unit.url}
    assert stack.unit.received == 0


def test_health_answers_while_the_unit_is_unreachable(stack: Stack) -> None:
    stack.unit.reset()
    stack.unit.reachable = False

    assert stack.api.get("/api/health").status_code == 200


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"DAIKIN_HOST": "not a url"},
        {"DAIKIN_HOST": "http://127.0.0.1", "TIMEOUT": "0"},
    ],
    ids=["missing-host", "host-not-url", "non-positive-timeout"],
)
def test_server_refuses_to_start_with_invalid_settings(
    *, env: dict[str, str], tmp_path: Path
) -> None:
    with (
        pytest.raises(RuntimeError, match="exited during startup"),
        run_api(env=env, log_path=tmp_path / "uvicorn.log"),
    ):
        pass


def test_unit_slower_than_timeout_is_504(tmp_path: Path) -> None:
    """TIMEOUT 秒以内に応答しない本体は、到達できない本体と同じ 504 になる。"""
    with (
        FakeUnit.serve() as unit,
        run_api(
            env={"DAIKIN_HOST": unit.url, "TIMEOUT": "1"},
            log_path=tmp_path / "uvicorn.log",
        ) as api,
        unit.hold(),
    ):
        started = time.monotonic()
        response = api.get("/api/status")
        elapsed = time.monotonic() - started

    assert response.status_code == 504
    # 既定の TIMEOUT (10 秒) ではなく、指定した 1 秒で打ち切る。
    assert elapsed < 5
