"""
e2e テストの実行環境: dsiot の multireq を話す fake の空気清浄機と、それに接続した API サーバー。

fake は README の「仕組み」の形 (`POST /dsiot/multireq` の `requests` 配列、op=2 の読み取り・op=3 の書き込み、
`rsc` の結果コード) で応答し、書き込みを自分のプロパティツリーに反映する。実機と同じく `md.mx` の範囲外の値も
拒否せずに保存する。
"""

import copy
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Generator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, NamedTuple, override

import requests

from tests.dsiot import mck706a_containers

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_MULTIREQ = "/dsiot/multireq"
_OP_READ = 2
_OP_WRITE = 3
_RSC_READ_OK = 2000
# MCK706A は書き込みの成功に 2004 を返す。
_RSC_WRITE_OK = 2004
_RSC_BAD_PARAMETER = 4000
_RSC_NOT_FOUND = 4041
_PT_CONTAINER = 1
_PT_LEAVES = {2, 3}


class HttpReply(NamedTuple):
    """本体が返す HTTP 応答そのもの。"""

    status: int
    content_type: str
    body: bytes

    @classmethod
    def json(cls, value: object, *, status: int = 200) -> HttpReply:
        return cls(status, "application/json", json.dumps(value).encode())


@dataclass(frozen=True)
class Write:
    """本体が受けた書き込み。path はコンテナ直下からリーフまでのプロパティ名を / で繋いだもの。"""

    to: str
    path: str
    pv: str


class FakeUnit:
    """
    1 台の MCK706A を模した HTTP サーバー。

    `containers` (アドレス → プロパティツリー) を読み取りに返し、書き込みをそのツリーのリーフに反映する。
    `read_rsc` に登録したアドレスの読み取りと、`write_rsc` を設定したときの書き込みはその rsc を返す。
    `reply` を設定すると、すべての multireq に、要求を解釈せずその HTTP 応答を返す。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._released = threading.Event()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_class())
        self._server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self._server.server_port}"
        self.containers: dict[str, dict[str, Any]] = {}
        self.read_rsc: dict[str, object] = {}
        self.write_rsc: object = None
        self.reply: HttpReply | None = None
        self.reachable = True
        self._reads: list[str] = []
        self._writes: list[Write] = []
        self._received = 0
        self._in_flight = 0
        self._max_in_flight = 0
        self.reset()

    @classmethod
    @contextmanager
    def serve(cls) -> Generator[FakeUnit]:
        unit = cls()
        thread = threading.Thread(target=unit._server.serve_forever, daemon=True)
        thread.start()
        try:
            yield unit
        finally:
            unit._released.set()
            unit._server.shutdown()
            unit._server.server_close()

    def reset(self) -> None:
        """状態 (プロパティツリー・登録した応答・記録) を初期状態の MCK706A に戻す。"""
        with self._lock:
            self.containers = mck706a_containers()
            self.read_rsc = {}
            self.write_rsc = None
            self.reply = None
            self.reachable = True
            self._reads = []
            self._writes = []
            self._received = 0
            self._max_in_flight = 0
        self._released.set()

    @contextmanager
    def hold(self) -> Generator[None]:
        """抜けるまで、届いた multireq に応答しない (通信中の状態を作る)。"""
        self._released.clear()
        try:
            yield
        finally:
            self._released.set()

    def wait_for_requests(self, count: int) -> None:
        """multireq が count 件届くまで待つ。"""
        deadline = time.monotonic() + 10
        while self.received < count:
            if time.monotonic() > deadline:
                raise TimeoutError(f"unit received {self.received} of {count} requests")
            time.sleep(0.01)

    @property
    def reads(self) -> list[str]:
        """読み取り (op=2) を受けたアドレス (到着順)。"""
        with self._lock:
            return list(self._reads)

    @property
    def writes(self) -> list[Write]:
        """受けた書き込み (op=3) (到着順)。"""
        with self._lock:
            return list(self._writes)

    @property
    def received(self) -> int:
        """届いた HTTP リクエストの数。"""
        with self._lock:
            return self._received

    @property
    def max_in_flight(self) -> int:
        """同時に処理していた HTTP リクエストの数の最大。"""
        with self._lock:
            return self._max_in_flight

    def _read(self, to: str) -> dict[str, Any]:
        if (rsc := self.read_rsc.get(to)) is not None:
            return {"fr": to, "rsc": rsc}
        if (pc := self.containers.get(to)) is None:
            return {"fr": to, "rsc": _RSC_NOT_FOUND}
        return {"fr": to, "pc": copy.deepcopy(pc), "rsc": _RSC_READ_OK}

    def _write(self, to: str, *, pc: object) -> dict[str, Any]:
        target = _write_target(pc, container=to.rsplit(".", 1)[-1])
        if target is None:
            return {"fr": to, "rsc": _RSC_BAD_PARAMETER}
        names, pv = target
        self._writes.append(Write(to, "/".join(names), pv))
        if self.write_rsc is not None:
            return {"fr": to, "rsc": self.write_rsc}
        if (root := self.containers.get(to)) is None:
            return {"fr": to, "rsc": _RSC_NOT_FOUND}
        if (leaf := _find(root, names=names)) is None:
            return {"fr": to, "rsc": _RSC_BAD_PARAMETER}
        leaf["pv"] = pv
        return {"fr": to, "rsc": _RSC_WRITE_OK}

    def _multireq(self, raw_body: bytes) -> dict[str, Any]:
        body: Any = json.loads(raw_body)
        responses: list[dict[str, Any]] = []
        with self._lock:
            for request in body["requests"]:
                to = request["to"]
                if request["op"] == _OP_READ:
                    self._reads.append(to)
                    responses.append(self._read(to))
                elif request["op"] == _OP_WRITE:
                    responses.append(self._write(to, pc=request.get("pc")))
                else:
                    responses.append({"fr": to, "rsc": _RSC_BAD_PARAMETER})
        return {"responses": responses}

    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        unit = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw_body = self.rfile.read(length)
                with unit._lock:
                    unit._received += 1
                    unit._in_flight += 1
                    unit._max_in_flight = max(unit._max_in_flight, unit._in_flight)
                try:
                    unit._released.wait()
                    reply = self._build_reply(raw_body)
                finally:
                    # 応答を送る前に減らす。送った後だと、応答を受けた API サーバーが始めた次の通信と重ねて数えうる。
                    with unit._lock:
                        unit._in_flight -= 1
                if reply is None:
                    # 応答を返さずに切断し、到達できない本体を模す。
                    self.close_connection = True
                    return
                # 応答を待たずに切断したクライアント (タイムアウトした API サーバー) への書き込みは失敗する。
                with suppress(BrokenPipeError, ConnectionResetError):
                    self._reply(reply)

            def _build_reply(self, raw_body: bytes) -> HttpReply | None:
                """本体の応答。到達できない本体を模すときは None。"""
                if not unit.reachable:
                    return None
                if self.path != _MULTIREQ:
                    return HttpReply(404, "text/plain", b"not found")
                if (reply := unit.reply) is not None:
                    return reply
                return HttpReply.json(unit._multireq(raw_body))

            def _reply(self, reply: HttpReply) -> None:
                self.send_response(reply.status)
                self.send_header("Content-Type", reply.content_type)
                self.send_header("Content-Length", str(len(reply.body)))
                self.end_headers()
                self.wfile.write(reply.body)

            @override
            def log_message(self, format: str, *args: Any) -> None:
                pass

        return Handler


def _write_target(pc: object, *, container: str) -> tuple[list[str], str] | None:
    """
    書き込み本文の pc から、書き込むリーフのパスと pv を取り出す。

    pc は根の名前がコンテナ名で、各階層の子が 1 つだけの鎖でなければならない。ノードの型 (pt) は
    コンテナが 1、リーフが 2 か 3 (README「仕組み」)。形が違えば None。
    """
    names: list[str] = []
    node: Any = pc
    try:
        if node["pn"] != container:
            return None
        while "pch" in node:
            children: Any = node["pch"]
            if (
                not _is_node_type(node["pt"], types={_PT_CONTAINER})
                or len(children) != 1
            ):
                return None
            node = children[0]
            names.append(node["pn"])
        pv: Any = node["pv"]
        leaf_type: Any = node["pt"]
    except KeyError, TypeError:
        return None
    valid = names and _is_node_type(leaf_type, types=_PT_LEAVES) and isinstance(pv, str)
    return (names, pv) if valid else None


def _is_node_type(value: object, *, types: set[int]) -> bool:
    # bool は int の派生なので、true を 1 とみなさないよう型を先に確かめる。
    return type(value) is int and value in types


def _find(root: dict[str, Any], *, names: list[str]) -> dict[str, Any] | None:
    node = root
    for name in names:
        for child in node.get("pch", []):
            if child.get("pn") == name:
                node = child
                break
        else:
            return None
    return None if "pch" in node else node


class Api:
    """起動した API サーバーへの HTTP クライアント。"""

    def __init__(self, base_url: str, *, log_path: Path) -> None:
        self.base_url = base_url
        self._log_path = log_path

    def entries(self) -> int:
        """これまでに API サーバーのアプリに届いた HTTP の要求の数。"""
        log = self._log_path.read_text(encoding="utf-8")
        return sum(line.startswith(ENTRY_PREFIX) for line in log.splitlines())

    def wait_for_entries(self, count: int) -> None:
        """API サーバーのアプリに届いた HTTP の要求が count 件になるまで待つ。"""
        deadline = time.monotonic() + 10
        while self.entries() < count:
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"API server received {self.entries()} of {count} requests"
                )
            time.sleep(0.01)

    def request(
        self, method: str, *, path: str, json: object = None
    ) -> requests.Response:
        """json を JSON の本文にして送る。None なら本文を付けない。"""
        body = None if json is None else _to_json(json)
        return self._send(method, path=path, body=body)

    def get(self, path: str) -> requests.Response:
        return self.request("GET", path=path)

    def post(self, path: str, *, json: object = None) -> requests.Response:
        return self.request("POST", path=path, json=json)

    def post_bytes(self, path: str, *, body: bytes) -> requests.Response:
        """本文をそのまま JSON として送る (JSON でない本文や、JSON の値でない NaN を含む本文)。"""
        return self._send("POST", path=path, body=body)

    def _send(self, method: str, *, path: str, body: bytes | None) -> requests.Response:
        # 並行に呼ばれるので Session を共有しない。実行環境の HTTP_PROXY などを使わず、loopback へ直接つなぐ。
        with requests.Session() as session:
            session.trust_env = False
            headers = {} if body is None else {"Content-Type": "application/json"}
            return session.request(
                method,
                f"{self.base_url}{path}",
                data=body,
                headers=headers,
                timeout=30,
            )


def _to_json(value: object) -> bytes:
    return json.dumps(value).encode()


def as_json(value: object) -> str:
    """
    JSON の値として比べるための表現。

    Python の == は True と 1、False と 0 を等しいとみなし、JSON の型の違いを見逃す。
    """
    return json.dumps(value, sort_keys=True)


@dataclass(frozen=True)
class Stack:
    """fake の空気清浄機と、それに接続した API サーバー。"""

    unit: FakeUnit
    api: Api


# tests/asgi_probe.py が、HTTP の要求がアプリに届くたびに stderr に書く行の接頭辞。
ENTRY_PREFIX = "asgi-probe: entered"
_STARTED_RE = re.compile(r"Uvicorn running on (http://\S+)")


@contextmanager
def run_api(*, env: Mapping[str, str], log_path: Path) -> Generator[Api]:
    """
    `main:app` を包んだ `tests.asgi_probe:app` を、本番と同じく uvicorn と環境変数の設定で subprocess として起動する。

    実行環境の変数は coverage の計測に使うものだけを引き継ぎ、ほかは env だけを渡す。settings は名前の大小文字を
    区別せずに読むので、手元の `daikin_host` などが残ると実機に接続しうるため。proxy も同じ理由で渡さない。
    """
    child_env = {k: v for k, v in os.environ.items() if k.startswith("COVERAGE_")}
    child_env |= env
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "tests.asgi_probe:app",
        "--app-dir",
        "src",
        "--host",
        "127.0.0.1",
        "--port",
        "0",
        "--no-access-log",
    ]
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(  # noqa: S603 - 引数は固定値と sys.executable だけ
            command,
            cwd=_PROJECT_ROOT,
            env=child_env,
            # このプロセスが終わると閉じ、サーバーが後を追って終了する (tests/asgi_probe.py)。
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=log,
        )
    # 抜けるときに stdin のパイプを閉じる。
    with process:
        try:
            url = _wait_until_started(process, log_path=log_path)
        except BaseException:
            # 起動の失敗に加え、待機中の中断 (Ctrl-C 等) でもサーバーを残さない。
            process.kill()
            process.wait()
            raise
        try:
            yield Api(url, log_path=log_path)
        finally:
            _stop(process, log_path=log_path)


def _stop(process: subprocess.Popen[bytes], *, log_path: Path) -> None:
    """SIGTERM で終了させ、lifespan の終了処理と coverage の保存を通す。途中で落ちていたら失敗にする。"""
    if process.poll() is not None:
        raise RuntimeError(
            f"API server exited during the tests:\n{log_path.read_text(encoding='utf-8')}"
        )
    process.terminate()
    try:
        returncode = process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        returncode = None
    # uvicorn は終了処理の後に SIGTERM を投げ直して終わる。
    if returncode not in {0, -signal.SIGTERM}:
        raise RuntimeError(
            f"API server did not stop cleanly ({returncode}):\n"
            f"{log_path.read_text(encoding='utf-8')}"
        )


def _wait_until_started(process: subprocess.Popen[bytes], *, log_path: Path) -> str:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        output = log_path.read_text(encoding="utf-8")
        if match := _STARTED_RE.search(output):
            return str(match.group(1))
        if process.poll() is not None:
            raise RuntimeError(f"API server exited during startup:\n{output}")
        time.sleep(0.05)
    raise RuntimeError(
        f"API server did not start in time:\n{log_path.read_text(encoding='utf-8')}"
    )
