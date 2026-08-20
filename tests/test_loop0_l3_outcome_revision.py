"""LOOP0 L3 — outcome_check + genealogical belief candidates (hermetic)."""

from __future__ import annotations

from atlas.investment.decision_packets import DecisionPacketStore
from atlas.investment.decision_timeline import DecisionTimelineStore, what_changed
from atlas.investment.laboratory import DEFAULT_SWING_LAB
from atlas.reasoning import (
    InMemoryBeliefRepository,
    ReasoningService,
    build_outcome_check,
    record_belief_candidate,
)


def _buy_packet(**extra):
    pkt = {
        "decision_id": "dec-cipla-1",
        "symbol": "CIPLA.NS",
        "action": "buy",
        "prices": {"mark": 1464.0, "fill_price": 1464.0},
        "expected": {
            "expected_return": 0.04,
            "er_model": "prototype_v1",
            "er_basis": "prototype",
            "falsifiers": ["price breaks 8% against entry"],
        },
        "confidence_breakdown": {"overall": 0.35},
        "observation_ids": ["obs-1"],
    }
    pkt.update(extra)
    return pkt


def test_matched_up_move_no_candidate():
    pkt = _buy_packet()
    what = what_changed(pkt, current_mark=1510.0, checkpoint="week1")
    oc = build_outcome_check(pkt, what, checkpoint="week1")
    assert oc["expected_direction"] == "up"
    assert oc["observed_direction"] == "up"
    assert oc["direction_match"] == "matched"
    assert oc["thesis_change"] == "strengthen"
    assert oc["write_candidate"] is False
    assert "no candidate" in (oc["skip_candidate"] or "").lower()
    assert oc["outcome_horizon"] == "7d"
    assert record_belief_candidate(None, oc)["wrote"] is False


def test_missed_down_move_writes_genealogy():
    pkt = _buy_packet()
    what = what_changed(pkt, current_mark=1350.0, checkpoint="week1")
    oc = build_outcome_check(pkt, what, checkpoint="week1")
    assert oc["observed_direction"] == "down"
    assert oc["direction_match"] == "missed"
    assert oc["thesis_change"] == "weaken"
    assert oc["write_candidate"] is True
    assert oc["source_decision_id"] == "dec-cipla-1"
    assert oc["falsifier_status"] in {"triggered", "open"}
    repo = InMemoryBeliefRepository()
    rs = ReasoningService(repo, llm=None, goals=None)
    out = record_belief_candidate(rs, oc)
    assert out["wrote"] is True
    cand = out["belief_candidate"]
    assert cand["source_decision_id"] == "dec-cipla-1"
    assert cand["expected_direction"] == "up"
    assert cand["observed_direction"] == "down"
    assert cand["outcome_horizon"] == "7d"
    assert cand["confidence_before"] == 0.35
    assert cand["confidence_after_candidate"] < cand["confidence_before"]
    assert cand["status"] == "candidate"
    stored = repo.get_belief(cand["belief_id"])
    assert stored["status"] == "candidate"
    assert stored["metadata"]["genealogy"]["source_decision_id"] == "dec-cipla-1"
    assert stored["status"] != "active"


def test_thin_evidence_explicit_skip():
    pkt = {
        "decision_id": "dec-thin",
        "symbol": "EICHERMOT.NS",
        "action": "hold",
        "prices": {},
        "expected": {},
    }
    what = what_changed(pkt, current_mark=None, checkpoint="day1")
    oc = build_outcome_check(pkt, what, checkpoint="day1")
    assert oc["thin_evidence"] is True
    assert oc["write_candidate"] is False
    assert oc["skip_candidate"] == "no candidate: evidence too thin"
    recorded = record_belief_candidate(None, oc)
    assert recorded["wrote"] is False
    assert recorded["skip_reason"] == "no candidate: evidence too thin"


def test_revisit_attaches_outcome_check(tmp_path):
    timeline = DecisionTimelineStore(data_dir=tmp_path)
    packets = DecisionPacketStore(data_dir=tmp_path, timeline=timeline)
    timeline._packets = packets
    out = packets.record(
        action="buy",
        symbol="CIPLA.NS",
        portfolio_key=DEFAULT_SWING_LAB,
        strategy_tag="sma_cross_rsi",
        ts_ist="2026-08-05",
        prices={"mark": 100.0, "fill_price": 100.0, "filled_qty": 1},
        expected={"expected_return": 0.05, "er_model": "prototype_v1"},
        reasons_for=["signal"],
    )
    did = out["packet"]["decision_id"]
    result = timeline.run_due_revisits(
        as_of_ist="2026-08-06",
        portfolio_key=DEFAULT_SWING_LAB,
        limit=10,
        mark_fn=lambda _s: 92.0,
    )
    assert result["completed"] >= 1
    item = next(i for i in result["items"] if i.get("decision_id") == did)
    oc = item["outcome_check"]
    assert oc["source_decision_id"] == did
    assert oc["expected_direction"] == "up"
    assert oc["observed_direction"] == "down"
    assert oc["write_candidate"] is True
    assert oc["hypothesis"]
    assert oc["reason"]


def test_open_book_outcome_once_per_ist_day(tmp_path):
    timeline = DecisionTimelineStore(data_dir=tmp_path)
    packets = DecisionPacketStore(data_dir=tmp_path, timeline=timeline)
    timeline._packets = packets
    packets.record(
        action="buy",
        symbol="CIPLA.NS",
        portfolio_key=DEFAULT_SWING_LAB,
        strategy_tag="sma_cross_rsi",
        ts_ist="2026-08-10",
        prices={"mark": 1464.0, "fill_price": 1464.0, "filled_qty": 13},
        expected={"expected_return": 0.04, "er_model": "prototype_v1"},
        reasons_for=["signal"],
    )
    first = timeline.record_open_book_outcomes(
        portfolio_key=DEFAULT_SWING_LAB,
        open_symbols=["CIPLA.NS"],
        as_of_ist="2026-08-18",
        mark_fn=lambda _s: 1431.1,
    )
    assert first["wrote"] == 1
    oc = first["items"][0]["outcome_check"]
    assert oc["source_decision_id"]
    assert oc["outcome_horizon"] == "session"
    second = timeline.record_open_book_outcomes(
        portfolio_key=DEFAULT_SWING_LAB,
        open_symbols=["CIPLA.NS"],
        as_of_ist="2026-08-18",
        mark_fn=lambda _s: 1431.1,
    )
    assert second["wrote"] == 0
    assert second["skipped"] >= 1


def test_paper_tick_writes_open_book_l3_without_evolution_wait(tmp_path):
    from atlas.workers.paper_trading import PaperTradingWorker

    timeline = DecisionTimelineStore(data_dir=tmp_path)
    packets = DecisionPacketStore(data_dir=tmp_path, timeline=timeline)
    timeline._packets = packets
    packets.record(
        action="buy",
        symbol="CIPLA.NS",
        portfolio_key=DEFAULT_SWING_LAB,
        strategy_tag="sma_cross_rsi",
        ts_ist="2026-08-10",
        prices={"mark": 1464.0, "fill_price": 1464.0, "filled_qty": 13},
        expected={"expected_return": 0.04, "er_model": "prototype_v1"},
        reasons_for=["signal"],
    )
    worker = PaperTradingWorker(
        assets=None,
        market_data=None,
        decision_engine=None,
        portfolio=None,
        decision_packets=packets,
        reasoning=None,
    )
    out = worker._maybe_open_book_l3(
        portfolio_key=DEFAULT_SWING_LAB,
        snapshot={"positions": [{"symbol": "CIPLA.NS", "qty": 13}]},
        marks={"CIPLA.NS": 1431.1},
        ist_date="2026-08-18",
    )
    assert out["wrote"] == 1
    oc = out["items"][0]["outcome_check"]
    assert oc["observed_direction"] == "down"
    assert oc["skip_candidate"] or oc["write_candidate"]
