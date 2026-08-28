from collections.abc import Callable
from typing import Protocol

from app.domain.events import DomainEvent, EventType

EventHandler = Callable[[DomainEvent], None]


class EventBus(Protocol):
    def publish(self, event: DomainEvent) -> None:
        """Publish an event to interested subscribers."""

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Subscribe a handler to an event type."""


class InMemoryEventBus(EventBus):
    def __init__(self) -> None:
        self._handlers: dict[EventType, list[EventHandler]] = {}
        self.published_events: list[DomainEvent] = []

    def publish(self, event: DomainEvent) -> None:
        self.published_events.append(event)
        for handler in self._handlers.get(event.event_type, []):
            handler(event)

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)
