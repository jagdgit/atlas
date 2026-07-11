"""Subscription registry: maps event types to handlers.

Supports exact-type subscriptions and a wildcard ("*") that receives every event.
"""

from __future__ import annotations

from collections import defaultdict

from atlas.events.handlers import WILDCARD, HandlerFunc


class SubscriptionRegistry:
    def __init__(self) -> None:
        self._subs: dict[str, list[HandlerFunc]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: HandlerFunc) -> None:
        if handler not in self._subs[event_type]:
            self._subs[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: HandlerFunc) -> None:
        if handler in self._subs.get(event_type, []):
            self._subs[event_type].remove(handler)

    def handlers_for(self, event_type: str) -> list[HandlerFunc]:
        """Return exact-type handlers followed by wildcard handlers."""
        return list(self._subs.get(event_type, [])) + list(self._subs.get(WILDCARD, []))

    def types(self) -> list[str]:
        return [t for t, hs in self._subs.items() if hs]
