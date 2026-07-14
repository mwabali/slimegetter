import asyncio
from datetime import UTC, datetime
from itertools import count
from typing import Any


class MissionEventBus:
    """Development fan-out. Replace with Redis/RabbitMQ consumer in multi-worker deployment."""
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._event_ids = count(1)

    async def publish(self, event: dict[str, Any]) -> None:
        envelope = {
            **event,
            "event_id": next(self._event_ids),
            "emitted_at": datetime.now(UTC).isoformat(),
        }
        for queue in tuple(self._subscribers):
            if queue.full():
                # A slow browser should reconcile from the journal rather than
                # cause unbounded server memory growth.
                queue.get_nowait()
            queue.put_nowait(envelope)

    async def subscribe(self):
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100); self._subscribers.add(queue)
        try:
            while True: yield await queue.get()
        finally: self._subscribers.discard(queue)


mission_events = MissionEventBus()
