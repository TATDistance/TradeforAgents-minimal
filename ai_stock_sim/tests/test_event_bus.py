from __future__ import annotations

from app.event_bus import EventBus


def test_event_bus_publish_and_drain() -> None:
    bus = EventBus()
    seen = []

    def handle(event) -> None:
        seen.append((event.event_type, event.payload.get("symbol")))

    bus.subscribe("PRICE_UPDATED", handle)
    bus.publish("PRICE_UPDATED", {"symbol": "300750"})
    drained = bus.drain_events()

    assert len(drained) == 1
    assert seen == [("PRICE_UPDATED", "300750")]
