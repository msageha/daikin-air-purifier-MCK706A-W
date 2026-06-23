import asyncio
from collections.abc import Callable
from typing import Any, TypeVar

from config import Settings
from daikin import DaikinClient

T = TypeVar("T")


class DaikinService:
    def __init__(self, settings: Settings) -> None:
        self.client = DaikinClient(settings.daikin_host, timeout=settings.timeout)
        self._lock = asyncio.Lock()

    async def run(self, fn: Callable[..., T], *args: Any) -> T:
        async with self._lock:
            return await asyncio.to_thread(fn, *args)
