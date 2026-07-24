"""Hermetic tests for KnowledgeVerificationWatcher (KV.7)."""

from __future__ import annotations

import uuid
from typing import Any

from atlas.workers.base import TickContext
from atlas.workers.knowledge_verification import KnowledgeVerificationWatcher


class _FakeEvents:
    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict]] = []

    def emit(self, event_type, payload, *, source=None):
        self.emitted.append((event_type, payload))


class _FakeVerification:
    def __init__(self, pending: list[dict[str, Any]] | None = None) -> None:
        self._pending = list(pending or [])
        self.batch_calls: list[dict[str, Any]] = []

    def list_pending(self, **kw):
        return list(self._pending)

    def verify_batch(self, **kw):
        self.batch_calls.append(kw)
        rows = list(self._pending)
        before_after = [
            {
                "finding_id": r.get("id"),
                "statement": r.get("statement"),
                "confidence": "UNVERIFIED",
                "after_confidence": "MEDIUM",
                "gather_added": 0,
            }
            for r in rows
        ]
        self._pending = []
        return {
            "status": "done",
            "selected": len(rows),
            "promoted_or_scored": len(rows),
            "still_unverified": 0,
            "before_after": before_after,
            "gather_requested": bool(kw.get("gather")),
            "verification": "executed",
            "version": "kv.4",
        }


def _ctx(config, state=None, *, version=1, inputs=None):
    return TickContext(
        worker_id="w-kv",
        mission_id=str(uuid.uuid4()),
        config=config,
        config_version=version,
        state=state or {},
        inputs=inputs or [],
    )


def test_idle_when_no_pending():
    events = _FakeEvents()
    worker = KnowledgeVerificationWatcher(
        verification=_FakeVerification([]), events=events
    )
    result = worker.do_tick(
        _ctx({"batch_limit": 5}, state={"config_version": 1}, version=1)
    )
    assert result.note == ""
    assert result.state["last_pending"] == 0
    assert events.emitted == []


def test_tick_verifies_batch_and_notifies():
    pending = [
        {"id": "f1", "statement": "The rich buy assets.", "claim_type": "claim"},
        {"id": "f2", "statement": "Inflation reduces purchasing power.", "claim_type": "claim"},
    ]
    fake = _FakeVerification(pending)
    events = _FakeEvents()
    worker = KnowledgeVerificationWatcher(verification=fake, events=events)
    result = worker.do_tick(
        _ctx(
            {
                "batch_limit": 10,
                "gather": False,
                "claim_types": ["claim"],
                "alert_on_promoted": True,
            }
        )
    )
    assert fake.batch_calls
    assert fake.batch_calls[0]["limit"] == 10
    assert fake.batch_calls[0]["gather"] is False
    assert "2 selected" in result.note
    assert result.state["total_verified"] == 2
    types = [t for t, _ in events.emitted]
    assert "VerificationProgress" in types
    assert "KnowledgeVerified" in types


def test_gather_flag_passed_through():
    fake = _FakeVerification([{"id": "f1", "statement": "x", "claim_type": "claim"}])
    worker = KnowledgeVerificationWatcher(verification=fake)
    worker.do_tick(_ctx({"batch_limit": 3, "gather": True, "max_gather_iterations": 2}))
    assert fake.batch_calls[0]["gather"] is True
    assert fake.batch_calls[0]["max_gather_iterations"] == 2
