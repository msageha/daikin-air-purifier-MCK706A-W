import asyncio
from collections.abc import Callable
from typing import Any

from daikin import DaikinClient


class DaikinService:
    """
    同期の DaikinClient を event loop から使うためのラッパー。

    DaikinClient は requests.Session を共有していて並行利用できないので、
    呼び出しを lock で直列化して worker thread で実行する。
    """

    def __init__(self, client: DaikinClient) -> None:
        self.client = client
        self._lock = asyncio.Lock()
        self._pending_reads: dict[Callable[[], object], asyncio.Task[Any]] = {}

    async def run[**P, T](
        self, fn: Callable[P, T], *args: P.args, **kwargs: P.kwargs
    ) -> T:
        async with self._lock:
            return await asyncio.to_thread(fn, *args, **kwargs)

    async def read[T](self, fn: Callable[[], T]) -> T:
        """
        本体の状態を読むだけの fn を実行し、同じ fn が lock 待ちか実行中なら、その結果を共有する。

        共有するのは、呼び出しより後に lock を取る読み取りか、呼び出し時に実行中の読み取りだけ。
        実行中の読み取りは、この service を通した直前の書き込みが終わってから lock を取っているので、
        書き込みの完了後に呼べば、その書き込みより前の状態は返らない。fn は本体の状態を変えないこと。

        fn は == で比べるので、`client.air_status` のような bound method を渡す
        (呼び出しごとに作る lambda は共有されない)。
        """
        if (task := self._pending_reads.get(fn)) is None:
            task = asyncio.create_task(self._read_once(fn))
            self._pending_reads[fn] = task
        # 呼び出し元の 1 つが cancel されても、結果を待つほかの呼び出し元の読み取りは止めない。
        return await asyncio.shield(task)

    async def _read_once[T](self, fn: Callable[[], T]) -> T:
        try:
            return await self.run(fn)
        finally:
            del self._pending_reads[fn]
