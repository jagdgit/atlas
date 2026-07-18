"""In-memory SSE fan-out broker (Phase 0 · ATLAS_OS_ROADMAP §2.5).

The **web/SSE channel** of the Notifier. Each connected client gets its own bounded
thread-safe queue; publishing fans an event out to every queue. If a slow client's
queue is full, its **oldest** event is dropped (live status beats perfect history —
the durable log in ``audit.events`` remains the source of truth for replay).

Deliberately dependency-free (stdlib ``queue``/``threading``) so it works under the
sync, threaded server without pulling in an async broker.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from typing import Any, Iterator


class EventBroker:
    def __init__(self, *, max_queue: int = 1000, logger: logging.Logger | None = None) -> None:
        self._subs: set[queue.Queue] = set()
        self._lock = threading.Lock()
        self._max = max(1, int(max_queue))
        self._logger = logger or logging.getLogger("atlas.notify.broker")

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=self._max)
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subs.discard(q)

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)

    def publish(self, item: dict[str, Any]) -> int:
        """Fan ``item`` out to every subscriber. Returns the number delivered to."""
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            self._offer(q, item)
        return len(subs)

    def _offer(self, q: queue.Queue, item: dict[str, Any]) -> None:
        try:
            q.put_nowait(item)
        except queue.Full:
            # Drop the oldest to make room — live status must not block on slow clients.
            try:
                q.get_nowait()
            except queue.Empty:
                pass
            try:
                q.put_nowait(item)
            except queue.Full:  # pragma: no cover - racing producers
                pass


def sse_stream(
    q: queue.Queue,
    *,
    broker: EventBroker | None = None,
    heartbeat_seconds: float = 15.0,
) -> Iterator[str]:
    """Yield ``text/event-stream`` frames from a subscriber queue.

    Emits a heartbeat comment when idle so proxies keep the connection open, and
    unsubscribes the queue from ``broker`` when the client disconnects (GeneratorExit).
    """
    try:
        while True:
            try:
                item = q.get(timeout=heartbeat_seconds)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            event_type = str(item.get("type", "message"))
            data = json.dumps(item, default=str)
            yield f"event: {event_type}\ndata: {data}\n\n"
    finally:
        if broker is not None:
            broker.unsubscribe(q)
