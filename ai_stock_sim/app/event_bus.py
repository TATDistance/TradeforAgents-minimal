from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Deque, Dict, List, MutableMapping


EventHandler = Callable[["RuntimeEvent"], None]


@dataclass
class RuntimeEvent:
    event_type: str
    payload: Dict[str, object] = field(default_factory=dict)
    ts: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


class EventBus:
    def __init__(self) -> None:
        self._handlers: MutableMapping[str, List[EventHandler]] = defaultdict(list)
        self._queue: Deque[RuntimeEvent] = deque()

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._handlers[event_type].append(handler)

    def publish(self, event_type: str, payload: Dict[str, object] | None = None) -> RuntimeEvent:
        event = RuntimeEvent(event_type=event_type, payload=dict(payload or {}))
        self._queue.append(event)
        return event

    def drain_events(self) -> List[RuntimeEvent]:
        drained: List[RuntimeEvent] = []
        while self._queue:
            event = self._queue.popleft()
            drained.append(event)
            for handler in self._handlers.get(event.event_type, []):
                handler(event)
        return drained
