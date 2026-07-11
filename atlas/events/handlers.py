"""Event handler protocol and a couple of built-in handlers."""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from atlas.events.event import Event

# A handler is any callable taking an Event.
HandlerFunc = Callable[[Event], None]

WILDCARD = "*"


@runtime_checkable
class Handler(Protocol):
    def __call__(self, event: Event) -> None: ...


class LoggingHandler:
    """Handler that logs every event it receives (useful for observability)."""

    def __init__(self, logger) -> None:
        self._logger = logger

    def __call__(self, event: Event) -> None:
        self._logger.info(
            "event %s from %s (id=%s)", event.type, event.source or "?", event.id
        )
