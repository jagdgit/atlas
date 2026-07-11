"""In-process event dispatcher (the "event bus").

Synchronous, in-process publish/subscribe (ADR-0012). A misbehaving handler is
logged and isolated so it cannot break other handlers or the publisher.

DB-backed persistence is intentionally NOT here yet; the package layout is ready
for it when distributed processing is actually needed (ADR-0025).
"""

from __future__ import annotations

import logging

from atlas.events.event import Event
from atlas.events.handlers import HandlerFunc
from atlas.events.subscriptions import SubscriptionRegistry


class EventDispatcher:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._subs = SubscriptionRegistry()
        self._logger = logger or logging.getLogger("atlas.events")

    def subscribe(self, event_type: str, handler: HandlerFunc) -> None:
        self._subs.subscribe(event_type, handler)

    def unsubscribe(self, event_type: str, handler: HandlerFunc) -> None:
        self._subs.unsubscribe(event_type, handler)

    def publish(self, event: Event) -> int:
        """Dispatch an event to all subscribers. Returns number of handlers run."""
        handlers = self._subs.handlers_for(event.type)
        for handler in handlers:
            try:
                handler(event)
            except Exception:  # noqa: BLE001 - isolate handler failures
                self._logger.exception(
                    "event handler failed for %s (event id=%s)", event.type, event.id
                )
        return len(handlers)

    def emit(
        self,
        event_type: str,
        payload: dict | None = None,
        source: str | None = None,
    ) -> int:
        """Convenience: build and publish an event in one call."""
        return self.publish(Event.create(event_type, payload, source))

    def subscribed_types(self) -> list[str]:
        return self._subs.types()
