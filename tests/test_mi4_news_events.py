"""Interesting events + News / Event Research workers (MI.4)."""

from __future__ import annotations

import pytest

from atlas.trading.interesting_events import (
    score_observation,
    score_price_move,
    score_volume_spike,
    volume_ratio_from_bars,
)
from atlas.workers.base import TickContext
from atlas.workers.event_research import EventResearchWorker
from atlas.workers.news_intelligence import NewsIntelligenceWorker


def test_score_price_move_below_threshold():
    assert score_price_move("X", 3.0, alert_pct=5.0) is None


def test_score_price_move_and_objective():
    ev = score_price_move("RELIANCE", 12.0, alert_pct=5.0)
    assert ev is not None
    assert ev.score >= 0.5
    assert "RELIANCE" in ev.research_objective()
    assert "verify" in ev.research_objective().lower()


def test_volume_ratio_and_spike():
    bars = [{"volume": 100}] * 10 + [{"volume": 400}]
    ratio = volume_ratio_from_bars(bars)
    assert ratio == pytest.approx(4.0)
    ev = score_volume_spike("X", ratio, min_ratio=2.5)
    assert ev is not None
    assert ev.kind == "volume_spike"


def test_score_observation_composite():
    bars = [{"close": 100, "volume": 10}] * 5 + [{"close": 120, "volume": 50}]
    ev = score_observation(
        "DEMO",
        pct_move=20.0,
        bars=bars,
        alert_pct=5.0,
        volume_min_ratio=2.5,
    )
    assert ev is not None
    assert ev.score >= 0.5


def test_news_intelligence_emits_candidates():
    emitted: list[dict] = []

    class _Candidates:
        def emit(self, payload):
            emitted.append(payload)
            return {"id": f"c{len(emitted)}"}

        def consume_pending(self, *, limit=100):
            return [{"finding_id": "f1"}]

    worker = NewsIntelligenceWorker(candidates=_Candidates())
    result = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={
                "headlines": [
                    "Inflation reduces purchasing power for the middle class this quarter."
                ]
            },
            config_version=1,
            state={},
        )
    )
    assert "emitted" in result.note
    assert emitted
    # Second tick skips same headline
    result2 = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={
                "headlines": [
                    "Inflation reduces purchasing power for the middle class this quarter."
                ]
            },
            config_version=1,
            state=result.state,
        )
    )
    assert "skipped" in result2.note


def test_event_research_spawns_from_pending():
    created: list[str] = []

    class _Jobs:
        def create_job(self, objective, **kwargs):
            created.append(objective)

            class J:
                id = f"job-{len(created)}"

            return {"job": J()}

    worker = EventResearchWorker(jobs=_Jobs())
    result = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={
                "spawn_research": True,
                "score_threshold": 0.6,
                "pending_events": [
                    {
                        "symbol": "TATA",
                        "pct_move": 9.5,
                        "score": 0.8,
                        "kind": "price_move",
                        "detail": "TATA jumped 9.5%",
                    }
                ],
            },
            config_version=1,
            state={},
        )
    )
    assert result.state["last_spawned"] == 1
    assert created and "TATA" in created[0]
    # Dedupe on second tick
    result2 = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={
                "spawn_research": True,
                "score_threshold": 0.6,
                "pending_events": [
                    {
                        "symbol": "TATA",
                        "pct_move": 9.5,
                        "score": 0.8,
                        "kind": "price_move",
                        "detail": "TATA jumped 9.5%",
                    }
                ],
            },
            config_version=1,
            state=result.state,
        )
    )
    assert result2.state["last_spawned"] == 0
