"""In-process event dispatcher (the "event bus").

Synchronous, in-process publish/subscribe (ADR-0012). A misbehaving handler is
logged and isolated so it cannot break other handlers or the publisher.

Durable persistence (Phase 0 · ATLAS_OS_ROADMAP §2.5, P1): an optional ``store`` is
persisted **before** handlers run, so the event survives a crash even if a handler
later fails. Persistence is best-effort — a store failure is logged and never blocks
dispatch (the in-process bus must keep working even if Postgres is briefly down).
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from atlas.events.event import Event
from atlas.events.handlers import HandlerFunc
from atlas.events.subscriptions import SubscriptionRegistry


@runtime_checkable
class EventStore(Protocol):
    def persist(self, event: Event) -> None: ...


class EventDispatcher:
    def __init__(
        self,
        logger: logging.Logger | None = None,
        *,
        store: "EventStore | None" = None,
    ) -> None:
        self._subs = SubscriptionRegistry()
        self._logger = logger or logging.getLogger("atlas.events")
        self._store = store

    def subscribe(self, event_type: str, handler: HandlerFunc) -> None:
        self._subs.subscribe(event_type, handler)

    def unsubscribe(self, event_type: str, handler: HandlerFunc) -> None:
        self._subs.unsubscribe(event_type, handler)

    def publish(self, event: Event) -> int:
        """Dispatch an event to all subscribers. Returns number of handlers run.

        The event is first persisted to the durable store (if configured) so it is
        replayable after a restart; a store failure is isolated like a handler failure.
        """
        if self._store is not None:
            try:
                self._store.persist(event)
            except Exception:  # noqa: BLE001 - durability is best-effort, never blocks
                self._logger.exception(
                    "event persistence failed for %s (id=%s)", event.type, event.id
                )
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
