"""OI-C5 — scheduled candidate drain/prune on CandidateConsumer."""

from __future__ import annotations

from atlas.knowledge.candidate_consumer import CandidateConsumer, InMemoryCandidateStore


class _StubConsolidator:
    def consolidate(self, incoming):
        return {"id": "f1", "_transition": "created"}


def test_drain_and_prune_tasks_reschedule():
    store = InMemoryCandidateStore()

    def prune_consumed(*, older_than_days=30):
        return 2

    store.prune_consumed = prune_consumed  # type: ignore[method-assign]

    enqueued: list[tuple] = []

    def enqueue(task_type, payload, delay_seconds=0):
        enqueued.append((task_type, delay_seconds))

    consumer = CandidateConsumer(
        store,
        _StubConsolidator(),
        enqueue=enqueue,
        count_pending=lambda _t: 0,
        drain_interval=10,
        prune_interval=20,
        prune_older_than_days=7,
    )
    store.create("Atlas uses PostgreSQL", claim_type="prose", domain="personal")
    out = consumer.drain_task({"limit": 5})
    assert out["drained"] == 1
    assert any(t == "candidates_drain" for t, _ in enqueued)

    enqueued.clear()
    pout = consumer.prune_task({})
    assert pout["pruned"] == 2
    assert any(t == "candidates_prune" for t, _ in enqueued)


def test_start_seeds_both_chains():
    store = InMemoryCandidateStore()
    enqueued: list[str] = []

    def enqueue(task_type, payload, delay_seconds=0):
        enqueued.append(task_type)

    consumer = CandidateConsumer(
        store,
        _StubConsolidator(),
        enqueue=enqueue,
        count_pending=lambda _t: 0,
        drain_interval=5,
        prune_interval=5,
    )
    consumer.start()
    assert "candidates_drain" in enqueued
    assert "candidates_prune" in enqueued
