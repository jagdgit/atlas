"""Notification subsystem (Phase 0 · ATLAS_OS_ROADMAP §2.5, A1).

Live operator delivery over two channels — **web/SSE first, email second** — fed by the
event bus. Durability lives upstream (the dispatcher persists to ``audit.events``); this
package is purely live fan-out (`EventBroker`) + best-effort email (`EmailSender`), tied
together by the `Notifier` service.
"""

from __future__ import annotations

from atlas.notify.broker import EventBroker, sse_stream
from atlas.notify.email import EmailSender
from atlas.notify.service import Notifier

__all__ = ["Notifier", "EventBroker", "EmailSender", "sse_stream"]
