"""Durable event bus + Notifier tests (Phase 0 · ATLAS_OS_ROADMAP §2.5, A1).

Hermetic: no live Postgres, no real SMTP. Covers (1) the dispatcher's best-effort
persist-before-dispatch, (2) the SSE fan-out broker, (3) best-effort email availability
+ delivery, and (4) the Notifier's web-first/email-second routing.
"""

from __future__ import annotations

import queue
from itertools import islice
from typing import Any

from atlas.events.dispatcher import EventDispatcher
from atlas.events.event import Event
from atlas.events.handlers import WILDCARD
from atlas.notify import EmailSender, EventBroker, Notifier
from atlas.notify.broker import sse_stream


# --- durable dispatcher --------------------------------------------------

class FakeStore:
    def __init__(self, *, boom: bool = False) -> None:
        self.persisted: list[Event] = []
        self._boom = boom

    def persist(self, event: Event) -> None:
        if self._boom:
            raise RuntimeError("db down")
        self.persisted.append(event)


def test_dispatcher_persists_before_handlers():
    store = FakeStore()
    seen: list[str] = []
    bus = EventDispatcher(store=store)
    bus.subscribe(WILDCARD, lambda e: seen.append(e.type))
    bus.emit("job.completed", {"id": "1"})
    assert [e.type for e in store.persisted] == ["job.completed"]
    assert seen == ["job.completed"]


def test_dispatcher_persists_even_if_handler_fails():
    store = FakeStore()

    def bad(_e: Event) -> None:
        raise ValueError("handler boom")

    bus = EventDispatcher(store=store)
    bus.subscribe(WILDCARD, bad)
    bus.emit("x.failed")
    # The event is durably recorded even though the handler blew up.
    assert len(store.persisted) == 1


def test_dispatcher_store_failure_is_isolated():
    store = FakeStore(boom=True)
    seen: list[str] = []
    bus = EventDispatcher(store=store)
    bus.subscribe(WILDCARD, lambda e: seen.append(e.type))
    # A store outage must not break in-process dispatch.
    bus.emit("job.started")
    assert seen == ["job.started"]


def test_dispatcher_without_store_still_works():
    seen: list[str] = []
    bus = EventDispatcher()
    bus.subscribe(WILDCARD, lambda e: seen.append(e.type))
    bus.emit("noop")
    assert seen == ["noop"]


# --- SSE broker ----------------------------------------------------------

def test_broker_fans_out_to_all_subscribers():
    broker = EventBroker()
    q1 = broker.subscribe()
    q2 = broker.subscribe()
    delivered = broker.publish({"type": "t", "payload": {}})
    assert delivered == 2
    assert q1.get_nowait()["type"] == "t"
    assert q2.get_nowait()["type"] == "t"


def test_broker_drops_oldest_when_full():
    broker = EventBroker(max_queue=2)
    q = broker.subscribe()
    for i in range(5):
        broker.publish({"type": "t", "payload": {"n": i}})
    # Only the two most recent survived; oldest were dropped.
    remaining = [q.get_nowait()["payload"]["n"] for _ in range(q.qsize())]
    assert remaining == [3, 4]


def test_broker_unsubscribe_stops_delivery():
    broker = EventBroker()
    q = broker.subscribe()
    broker.unsubscribe(q)
    assert broker.publish({"type": "t"}) == 0
    assert broker.subscriber_count() == 0


def test_sse_stream_formats_frame_and_unsubscribes():
    broker = EventBroker()
    q = broker.subscribe()
    broker.publish({"type": "job.done", "payload": {"id": 7}})
    gen = sse_stream(q, broker=broker, heartbeat_seconds=0.05)
    frame = next(gen)
    assert frame.startswith("event: job.done\n")
    assert '"id": 7' in frame
    gen.close()  # simulates client disconnect
    assert broker.subscriber_count() == 0


def test_sse_stream_emits_heartbeat_when_idle():
    q: queue.Queue = queue.Queue()
    gen = sse_stream(q, heartbeat_seconds=0.01)
    assert next(gen).startswith(": keep-alive")
    gen.close()


# --- email sender --------------------------------------------------------

def test_email_unavailable_when_unconfigured():
    assert EmailSender().available() is False
    assert EmailSender(host="smtp.x").available() is False  # no from/to
    assert EmailSender().send("s", "b") is False


def test_email_available_when_configured():
    sender = EmailSender(host="smtp.x", from_addr="a@x", to_addrs=["b@y"])
    assert sender.available() is True


def test_email_send_uses_smtp(monkeypatch):
    sent: list[Any] = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            self.host = host

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            sent.append("starttls")

        def login(self, u, p):
            sent.append(("login", u))

        def send_message(self, msg):
            sent.append(("msg", msg["Subject"]))

    monkeypatch.setattr("atlas.notify.email.smtplib.SMTP", FakeSMTP)
    sender = EmailSender(
        host="smtp.x", username="u", password="p",
        from_addr="a@x", to_addrs=["b@y"], use_tls=True,
    )
    assert sender.send("[Atlas] job.failed", "body") is True
    assert "starttls" in sent
    assert ("login", "u") in sent
    assert ("msg", "[Atlas] job.failed") in sent


# --- notifier ------------------------------------------------------------

class RecordingEmail:
    def __init__(self, available: bool = True) -> None:
        self._available = available
        self.sent: list[tuple[str, str]] = []

    def available(self) -> bool:
        return self._available

    def send(self, subject: str, body: str) -> bool:
        self.sent.append((subject, body))
        return True


def test_notifier_pushes_every_event_to_web():
    broker = EventBroker()
    q = broker.subscribe()
    notifier = Notifier(broker, None, channels=["web"])
    notifier(Event.create("anything.happened", {"a": 1}))
    assert q.get_nowait()["type"] == "anything.happened"


def test_notifier_emails_notable_events_only():
    broker = EventBroker()
    email = RecordingEmail()
    notifier = Notifier(broker, email, channels=["web", "email"])
    notifier(Event.create("job.progress"))       # not notable
    notifier(Event.create("job.completed"))       # notable (suffix)
    notifier(Event.create("backup.failed"))       # notable (suffix)
    subjects = [s for s, _ in email.sent]
    assert subjects == ["[Atlas] job.completed", "[Atlas] backup.failed"]


def test_notifier_honours_explicit_notable_types():
    broker = EventBroker()
    email = RecordingEmail()
    notifier = Notifier(broker, email, notable_types=["mission.milestone"])
    notifier(Event.create("mission.milestone"))
    assert [s for s, _ in email.sent] == ["[Atlas] mission.milestone"]


def test_notifier_skips_email_when_unavailable():
    broker = EventBroker()
    email = RecordingEmail(available=False)
    notifier = Notifier(broker, email)
    notifier(Event.create("job.failed"))
    assert email.sent == []


def test_notifier_disabled_does_nothing():
    broker = EventBroker()
    q = broker.subscribe()
    email = RecordingEmail()
    notifier = Notifier(broker, email, enabled=False)
    notifier(Event.create("job.failed"))
    assert q.empty()
    assert email.sent == []


def test_notifier_health_reports_channels():
    broker = EventBroker()
    notifier = Notifier(broker, RecordingEmail(available=True))
    health = notifier.health_check()
    assert health.healthy is True
    assert "web" in health.data["channels"]
    assert health.data["email"] is True
