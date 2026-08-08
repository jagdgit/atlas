"""LI.3b — opportunity tracker, company/macro obs helpers, revisit obs awareness."""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.investment.decision_packets import DecisionPacketStore, build_packet
from atlas.investment.decision_timeline import DecisionTimelineStore, what_changed
from atlas.investment.laboratory import (
    DEFAULT_INTRADAY_LAB,
    DEFAULT_SWING_LAB,
    LaboratoryContaminationError,
)
from atlas.investment.observations import DecisionObservationStore
from atlas.investment.opportunity_tracker import (
    list_opportunities,
    opportunity_counts,
    record_opportunity,
    record_plan_avoid,
    resolve_material_move,
)
from atlas.workers.base import TickContext
from atlas.workers.decision_evolution import DecisionEvolutionWorker


def test_company_and_macro_observation_helpers(tmp_path: Path):
    timeline = DecisionTimelineStore(data_dir=tmp_path)
    obs = DecisionObservationStore(data_dir=tmp_path, timeline=timeline)
    mgmt = obs.record_mgmt_event(symbol="INFY.NS", title="CEO guidance raised")
    assert mgmt["observation"]["kind"] == "mgmt_event"
    op = obs.record_operating_metric(
        symbol="INFY.NS", metric="attrition_pct", value=12.5, unit="pct"
    )
    assert op["observation"]["kind"] == "operating_metric"
    fil = obs.record_filing_event(
        symbol="INFY.NS", filing_type="quarterly", title="Q1 results"
    )
    assert fil["observation"]["kind"] == "filing_event"
    mac = obs.record_macro_event(
        title="RBI rate hold", regime_tags=["rate_hold", "sideways"]
    )
    assert mac["observation"]["kind"] == "macro_event"
    assert mac["observation"]["symbol"] is None
    macro_tl = timeline.list_symbol(symbol="__MACRO__", kind="observation")
    assert len(macro_tl) >= 1


def test_opportunity_tracker_lab_hermetic(tmp_path: Path):
    a = record_opportunity(
        tmp_path,
        laboratory_id=DEFAULT_SWING_LAB,
        symbol="CIPLA.NS",
        kind="deferred",
        reason="weak MoS",
        mark=100.0,
    )
    record_opportunity(
        tmp_path,
        laboratory_id=DEFAULT_INTRADAY_LAB,
        symbol="CIPLA.NS",
        kind="ignored",
        reason="no intraday setup",
        mark=100.0,
    )
    swing = list_opportunities(tmp_path, laboratory_id=DEFAULT_SWING_LAB)
    intra = list_opportunities(tmp_path, laboratory_id=DEFAULT_INTRADAY_LAB)
    assert len(swing) == 1 and swing[0]["kind"] == "deferred"
    assert len(intra) == 1 and intra[0]["kind"] == "ignored"
    assert opportunity_counts(tmp_path, laboratory_id=DEFAULT_SWING_LAB)["n"] == 1
    assert opportunity_counts(tmp_path, laboratory_id=DEFAULT_INTRADAY_LAB)["n"] == 1

    resolved = resolve_material_move(
        tmp_path,
        laboratory_id=DEFAULT_SWING_LAB,
        opportunity_id=a["opportunity"]["id"],
        mark_now=88.0,
        note="dropped after defer",
    )
    assert resolved is not None
    assert resolved["status"] == "materialized_adverse"
    assert resolved["outcome"]["is_trade_pnl"] is False

    with pytest.raises(LaboratoryContaminationError):
        resolve_material_move(
            tmp_path,
            laboratory_id=DEFAULT_INTRADAY_LAB,
            opportunity_id=a["opportunity"]["id"],
            mark_now=90.0,
        )


def test_plan_avoid_helper(tmp_path: Path):
    out = record_plan_avoid(
        tmp_path,
        laboratory_id=DEFAULT_SWING_LAB,
        symbol="ITC.NS",
        reason="rank too low",
        mark=420.0,
    )
    assert out["opportunity"]["source"] == "morning_plan"
    assert out["opportunity"]["kind"] == "deferred"


def test_what_changed_sees_new_observations():
    pkt = build_packet(
        action="buy",
        symbol="TCS.NS",
        portfolio_key=DEFAULT_SWING_LAB,
        strategy_tag="sma_cross_rsi",
        observation_ids=["obs-old"],
        prices={"mark": 100.0, "fill_price": 100.0},
        reasons_for=["signal"],
    )
    diff = what_changed(
        pkt,
        current_mark=105.0,
        recent_observations=[
            {"id": "obs-old", "kind": "market_event"},
            {
                "id": "obs-new",
                "kind": "mgmt_event",
                "payload": {"title": "buyback announced"},
            },
        ],
    )
    assert diff["new_observations"] is True
    assert diff["new_observation_count"] == 1
    assert "mgmt_event" in diff["new_observation_kinds"]
    assert diff["management_note"] and "buyback" in diff["management_note"]
    assert any("new_observations=1" in d for d in diff["deltas"])


def test_revisit_steady_state_with_observations(tmp_path: Path):
    timeline = DecisionTimelineStore(data_dir=tmp_path)
    packets = DecisionPacketStore(data_dir=tmp_path, timeline=timeline)
    timeline._packets = packets
    obs = DecisionObservationStore(data_dir=tmp_path, timeline=timeline)

    out = packets.record(
        action="buy",
        symbol="REVISIT.NS",
        portfolio_key=DEFAULT_SWING_LAB,
        strategy_tag="sma_cross_rsi",
        ts_ist="2026-08-05",
        prices={"mark": 100.0, "fill_price": 100.0, "filled_qty": 1},
        reasons_for=["signal"],
        observation_ids=[],
    )
    did = out["packet"]["decision_id"]
    obs.record_mgmt_event(symbol="REVISIT.NS", title="capacity expansion")

    result = timeline.run_due_revisits(
        as_of_ist="2026-08-06",
        portfolio_key=DEFAULT_SWING_LAB,
        limit=10,
        mark_fn=lambda _s: 103.0,
        observations_fn=lambda s: obs.list_symbol(symbol=s, limit=10, since_hours=720),
    )
    assert result["completed"] >= 1
    item = next(i for i in result["items"] if i.get("decision_id") == did)
    assert item["what_changed"]["new_observations"] is True
    counts = timeline.learning_counts(portfolio_key=DEFAULT_SWING_LAB)
    assert counts["done_revisits"] >= 1


def test_decision_evolution_worker_wires_observations(tmp_path: Path):
    timeline = DecisionTimelineStore(data_dir=tmp_path)
    packets = DecisionPacketStore(data_dir=tmp_path, timeline=timeline)
    timeline._packets = packets
    obs = DecisionObservationStore(data_dir=tmp_path, timeline=timeline)
    packets.record(
        action="buy",
        symbol="EVO.NS",
        portfolio_key=DEFAULT_SWING_LAB,
        strategy_tag="sma_cross_rsi",
        ts_ist="2026-08-05",
        prices={"mark": 50.0, "fill_price": 50.0, "filled_qty": 2},
        reasons_for=["signal"],
    )
    obs.record_filing_event(symbol="EVO.NS", filing_type="annual", title="AR FY26")

    class _Reader:
        def bars_for(self, symbol, **kwargs):
            return {"bars": [{"close": 55.0}], "count": 1}

    worker = DecisionEvolutionWorker(
        timeline=timeline,
        decision_packets=packets,
        market_reader=_Reader(),
        observations=obs,
    )
    assert worker.VERSION >= 2
    result = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={"portfolio_key": DEFAULT_SWING_LAB, "max_revisits": 5},
            config_version=1,
            state={},
        )
    )
    assert "evolution:" in result.note
    assert worker._observations is obs
