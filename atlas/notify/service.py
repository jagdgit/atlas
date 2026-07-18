"""Notifier (Phase 0 · ATLAS_OS_ROADMAP §2.5, A1).

A single wildcard subscriber on the event bus that fans events out to the operator over
two channels, **web/SSE first, email second** (A1):

  * **web** — every event is pushed to the in-memory :class:`EventBroker`, which the
    Operations Dashboard / web console consumes over SSE (live, no polling).
  * **email** — *notable* events (failures + completions by default) are emailed when
    SMTP is configured; otherwise email is silently skipped.

Durability is handled upstream (the dispatcher persists to ``audit.events`` before this
runs), so the Notifier is purely a live-delivery concern and is best-effort throughout.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.events.event import Event
    from atlas.notify.broker import EventBroker
    from atlas.notify.email import EmailSender

# Events worth an email by default: anything that failed or completed. Extendable via
# config (notable_types); prefix/suffix matching keeps it robust as new types appear.
_DEFAULT_NOTABLE_SUFFIXES = (".failed", ".completed", ".error")


class Notifier:
    name = "notifier"
    VERSION = "1"

    def __init__(
        self,
        broker: "EventBroker",
        email: "EmailSender | None" = None,
        *,
        enabled: bool = True,
        channels: list[str] | None = None,
        notable_types: list[str] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._broker = broker
        self._email = email
        self._enabled = enabled
        self._channels = list(channels or ["web", "email"])
        self._notable = set(notable_types or [])
        self._logger = logger or logging.getLogger("atlas.notify")

    # --- event handler (subscribed as WILDCARD) ------------------------

    def __call__(self, event: "Event") -> None:
        if not self._enabled:
            return
        item = self._serialize(event)
        if "web" in self._channels:
            try:
                self._broker.publish(item)
            except Exception:  # noqa: BLE001 - a broker hiccup must not break dispatch
                self._logger.exception("SSE fan-out failed for %s", event.type)
        if (
            "email" in self._channels
            and self._email is not None
            and self._email.available()
            and self._is_notable(event.type)
        ):
            self._email.send(f"[Atlas] {event.type}", self._email_body(item))

    # --- SSE plumbing ---------------------------------------------------

    def subscribe(self):
        """Register a new SSE subscriber; returns its queue."""
        return self._broker.subscribe()

    def unsubscribe(self, q) -> None:
        self._broker.unsubscribe(q)

    @property
    def broker(self) -> "EventBroker":
        return self._broker

    # --- helpers --------------------------------------------------------

    def _is_notable(self, event_type: str) -> bool:
        if event_type in self._notable:
            return True
        return any(event_type.endswith(suffix) for suffix in _DEFAULT_NOTABLE_SUFFIXES)

    @staticmethod
    def _serialize(event: "Event") -> dict[str, Any]:
        return {
            "id": str(event.id),
            "type": event.type,
            "source": event.source,
            "payload": event.payload,
            "created_at": event.created_at.isoformat() if event.created_at else None,
        }

    @staticmethod
    def _email_body(item: dict[str, Any]) -> str:
        lines = [
            f"Event: {item['type']}",
            f"Source: {item.get('source') or '-'}",
            f"Time:  {item.get('created_at') or '-'}",
            "",
            "Payload:",
        ]
        payload = item.get("payload") or {}
        if payload:
            lines += [f"  {k}: {v}" for k, v in payload.items()]
        else:
            lines.append("  (none)")
        return "\n".join(lines)

    # --- lifecycle ------------------------------------------------------

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def health_check(self) -> HealthStatus:
        email_ready = bool(self._email and self._email.available())
        channels = [c for c in self._channels if c != "email" or email_ready]
        return HealthStatus.ok(
            "notifier ready",
            enabled=self._enabled,
            channels=channels,
            email=email_ready,
            sse_subscribers=self._broker.subscriber_count(),
        )
