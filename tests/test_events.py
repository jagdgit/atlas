"""Tests for the in-process event system."""

from __future__ import annotations

from atlas.events import Event, EventDispatcher


def test_event_create_defaults():
    ev = Event.create("Thing", {"a": 1}, source="test")
    assert ev.type == "Thing"
    assert ev.payload == {"a": 1}
    assert ev.source == "test"
    assert ev.id is not None
    assert ev.created_at is not None


def test_subscribe_and_publish():
    bus = EventDispatcher()
    received = []
    bus.subscribe("Ping", lambda e: received.append(e.payload["n"]))
    count = bus.emit("Ping", {"n": 42})
    assert count == 1
    assert received == [42]


def test_wildcard_receives_all():
    bus = EventDispatcher()
    seen = []
    bus.subscribe("*", lambda e: seen.append(e.type))
    bus.emit("A")
    bus.emit("B")
    assert seen == ["A", "B"]


def test_unsubscribe():
    bus = EventDispatcher()
    calls = []
    handler = lambda e: calls.append(e.type)  # noqa: E731
    bus.subscribe("X", handler)
    bus.emit("X")
    bus.unsubscribe("X", handler)
    bus.emit("X")
    assert calls == ["X"]


def test_handler_failure_is_isolated():
    bus = EventDispatcher()
    good = []

    def boom(_e):
        raise RuntimeError("handler boom")

    bus.subscribe("E", boom)
    bus.subscribe("E", lambda e: good.append(True))
    count = bus.emit("E")
    assert count == 2
    assert good == [True]  # good handler still ran despite boom
