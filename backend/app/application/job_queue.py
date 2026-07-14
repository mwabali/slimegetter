import asyncio
from collections.abc import Awaitable, Callable


Job = Callable[[], Awaitable[None]]


class DevelopmentJobQueue:
    """Single-process queue for development; production replaces it with a durable worker."""
    def __init__(self) -> None: self._queue: asyncio.Queue[Job] = asyncio.Queue()
    async def enqueue(self, job: Job) -> None: await self._queue.put(job)
    async def run_once(self) -> None: await (await self._queue.get())()
