"""
同時に来たリクエストの扱い。

本体への通信は 1 件ずつ順に行う。GET /api/info・/api/status・/api/tree は、同じ endpoint への読み取りが通信待ちか
通信中なら、それに相乗りして同じ結果を返す。書き込みの応答を受け取ってから読めば、書き込み後の状態が返る。

各テストは本体の応答を止めて同時の状態を作り、すべての要求が API サーバーのアプリに届いたのを待ってから再開する。
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from tests import dsiot
from tests.harness import Stack


def test_unit_receives_one_request_at_a_time(stack: Stack) -> None:
    stack.unit.reset()
    entered = stack.api.entries()
    calls = [
        ("GET", "/api/status", None),
        ("GET", "/api/info", None),
        ("GET", "/api/tree", None),
        ("POST", "/api/read", {"targets": [dsiot.STATUS]}),
        ("POST", "/api/power", {"on": True}),
        ("POST", "/api/fan-speed", {"fan_speed": "low"}),
    ]

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        with stack.unit.hold():
            futures = [
                pool.submit(stack.api.request, m, path=p, json=b) for m, p, b in calls
            ]
            stack.unit.wait_for_requests(1)
            stack.api.wait_for_entries(entered + len(calls))
        responses = [f.result() for f in futures]

    assert [r.status_code for r in responses] == [200] * len(calls)
    assert stack.unit.max_in_flight == 1


@pytest.mark.parametrize("path", ["/api/status", "/api/info", "/api/tree"])
def test_simultaneous_reads_of_one_endpoint_share_one_unit_request(
    *, stack: Stack, path: str
) -> None:
    stack.unit.reset()
    entered = stack.api.entries()

    with ThreadPoolExecutor(max_workers=5) as pool:
        with stack.unit.hold():
            first = pool.submit(stack.api.request, "GET", path=path)
            stack.unit.wait_for_requests(1)
            rest = [pool.submit(stack.api.request, "GET", path=path) for _ in range(4)]
            stack.api.wait_for_entries(entered + 5)
        responses = [f.result() for f in (first, *rest)]

    assert [r.status_code for r in responses] == [200] * 5
    assert all(r.json() == responses[0].json() for r in responses)
    assert stack.unit.received == 1


def test_reads_waiting_behind_another_request_share_one_unit_request(
    stack: Stack,
) -> None:
    """本体が別の操作と通信している間に待っている同じ読み取りも、1 回の通信にまとまる。"""
    stack.unit.reset()
    entered = stack.api.entries()

    with ThreadPoolExecutor(max_workers=5) as pool:
        with stack.unit.hold():
            write = pool.submit(
                stack.api.request,
                "POST",
                path="/api/power",
                json={"on": False},
            )
            stack.unit.wait_for_requests(1)
            reads = [
                pool.submit(stack.api.request, "GET", path="/api/status")
                for _ in range(4)
            ]
            stack.api.wait_for_entries(entered + 5)
        responses = [f.result() for f in (write, *reads)]

    assert [r.status_code for r in responses] == [200] * 5
    assert all(r.json() == responses[1].json() for r in responses[1:])
    assert stack.unit.reads == [dsiot.STATUS]


def test_simultaneous_writes_are_each_sent(stack: Stack) -> None:
    """相乗りするのは読み取りだけで、同時に来た同じ書き込みはどれも本体に届く。"""
    stack.unit.reset()
    entered = stack.api.entries()

    with ThreadPoolExecutor(max_workers=2) as pool:
        with stack.unit.hold():
            futures = [
                pool.submit(
                    stack.api.request,
                    "POST",
                    path="/api/power",
                    json={"on": False},
                )
                for _ in range(2)
            ]
            stack.unit.wait_for_requests(1)
            stack.api.wait_for_entries(entered + 2)
        responses = [f.result() for f in futures]

    assert [r.status_code for r in responses] == [200, 200]
    assert len(stack.unit.writes) == 2


def test_read_after_a_write_response_sees_the_write(stack: Stack) -> None:
    """書き込みより前に始まった読み取りが通信中でも、書き込みの応答の後の読み取りは書き込み後の状態を返す。"""
    stack.unit.reset()
    entered = stack.api.entries()

    with ThreadPoolExecutor(max_workers=2) as pool:
        with stack.unit.hold():
            before = pool.submit(stack.api.request, "GET", path="/api/status")
            stack.unit.wait_for_requests(1)
            write = pool.submit(
                stack.api.request,
                "POST",
                path="/api/power",
                json={"on": False},
            )
            stack.api.wait_for_entries(entered + 2)
        assert before.result().json()["power"] is True
        assert write.result().status_code == 200

    after = stack.api.get("/api/status")

    assert after.json()["power"] is False
