import asyncio
from typing import Callable, Awaitable, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


class SingleFlight:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._futures: dict[str, asyncio.Future] = {}
        self._global_lock: asyncio.Lock = asyncio.Lock()

    async def run(
            self,
            key: str,
            coro_factory: Callable[P, Awaitable[R]],
            *args: P.args,
            **kwargs: P.kwargs,
    ) -> R:
        loop = asyncio.get_running_loop()

        async with self._global_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
                self._futures[key] = loop.create_future()

            lock = self._locks[key]
            future = self._futures[key]

            if lock.locked() and not future.done():
                return await future

        async with lock:
            if future.done():
                return future.result()

            try:
                result = await coro_factory(*args, **kwargs)
                future.set_result(result)
                return result
            except Exception as e:
                future.set_exception(e)
                raise
            finally:
                async with self._global_lock:
                    self._locks.pop(key, None)
                    await self._futures.pop(key, None)
