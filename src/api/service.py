import asyncio
from collections.abc import Callable

from daikin import DaikinClient


class DaikinService:
    """同期の DaikinClient を event loop から使うためのラッパー。

    DaikinClient は requests.Session を共有していて並行利用できないので、
    呼び出しを lock で直列化して worker thread で実行する。
    """

    def __init__(self, client: DaikinClient) -> None:
        self.client = client
        self._lock = asyncio.Lock()

    async def run[**P, T](
        self, fn: Callable[P, T], *args: P.args, **kwargs: P.kwargs
    ) -> T:
        async with self._lock:
            return await asyncio.to_thread(fn, *args, **kwargs)
