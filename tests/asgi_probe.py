"""
e2e テストで起動する API サーバーの ASGI アプリ。`main:app` をそのまま包み、テストのために 2 つだけ足す。

- HTTP の要求がアプリに届くたびに、stderr に `ENTRY_PREFIX <method> <path>` を書く。要求が API サーバーに
  届いたことを、テストが外から待てるようにするため。
- stdin が閉じたら SIGTERM で終了する。テストのプロセスが後始末をせずに落ちても (xdist の worker の
  SIGKILL 等)、サーバーを残さないため。
"""

import os
import signal
import sys
import threading

from starlette.types import Receive, Scope, Send

from main import app as _app
from tests.harness import ENTRY_PREFIX


def _terminate_when_stdin_closes() -> None:
    sys.stdin.buffer.read()
    os.kill(os.getpid(), signal.SIGTERM)


threading.Thread(target=_terminate_when_stdin_closes, daemon=True).start()


async def app(scope: Scope, receive: Receive, send: Send) -> None:  # noqa: PLR0917 - ASGI の呼び出し規約
    if scope["type"] == "http":
        sys.stderr.write(f"{ENTRY_PREFIX} {scope['method']} {scope['path']}\n")
        sys.stderr.flush()
    await _app(scope, receive, send)
