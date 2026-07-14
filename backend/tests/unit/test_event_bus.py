import asyncio

from app.application.event_bus import MissionEventBus


def test_event_bus_adds_ordering_and_timestamp_metadata() -> None:
    async def scenario() -> None:
        bus = MissionEventBus()
        stream = bus.subscribe()
        pending = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        await bus.publish({"type": "decision_completed"})
        first = await pending
        second_pending = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        await bus.publish({"type": "decision_completed"})
        second = await second_pending
        assert first["event_id"] == 1
        assert second["event_id"] == 2
        assert first["emitted_at"]
        await stream.aclose()

    asyncio.run(scenario())
