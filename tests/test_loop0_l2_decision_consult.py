"""LOOP0 L2 — unique-state decision consult (hermetic)."""

from __future__ import annotations

from atlas.investment.decision_packets import build_packet
from atlas.reasoning import (
    InMemoryBeliefRepository,
    ReasoningService,
    consult_unique_decision,
    should_consult,
)
from atlas.reasoning.decision_consult import (
    INFLUENCE,
    decision_state_key,
    evidence_fingerprint,
    ranking_bucket,
    regime_bucket,
)


def _rs() -> ReasoningService:
    repo = InMemoryBeliefRepository()
    svc = ReasoningService(repo, llm=None, goals=None)
    svc.ensure_seeded()
    return svc


def test_should_consult_skips_clock_noise():
    assert should_consult(action="hold", strategy_tag="sma_cross_rsi") is True
    assert should_consult(action="hold", strategy_tag="mark_only") is False
    assert should_consult(action="hold", strategy_tag="session_closed") is False
    assert should_consult(action="buy", strategy_tag="sma_cross_rsi") is True


def test_same_state_reuses_and_counts_once():
    rs = _rs()
    cache: dict = {"states": {}}
    kwargs = dict(
        symbol="CIPLA.NS",
        laboratory_id="india_equity_learner",
        action_kind="hold",
        strategy_tag="switch_blocked_missing_er",
        ist_day="2026-08-17",
        cache=cache,
        persist=False,
        book_fp="CIPLA.NS,EICHERMOT.NS|c3",
        evidence_fp=evidence_fingerprint(pe_present=True, er_completeness=0.3),
        regime=regime_bucket({"rsi14": 55, "above_sma20": True}),
    )
    first = consult_unique_decision(rs, **kwargs)
    mid = rs.consultation_metrics()["total"]
    second = consult_unique_decision(rs, **kwargs)
    assert first["reused"] is False
    assert second["reused"] is True
    assert second["state_key"] == first["state_key"]
    assert first["influence"] == INFLUENCE
    assert first["beliefs_found"] >= 1
    assert first["note"] != "No relevant belief found."
    assert rs.consultation_metrics()["total"] == mid  # no second metric row


def test_regime_change_is_new_state():
    rs = _rs()
    cache: dict = {"states": {}}
    base = dict(
        symbol="CIPLA.NS",
        laboratory_id="india_equity_learner",
        action_kind="hold",
        strategy_tag="engine_hold",
        ist_day="2026-08-17",
        cache=cache,
        persist=False,
    )
    a = consult_unique_decision(rs, **base, regime="sma_above_rsi_mid|")
    n1 = rs.consultation_metrics()["total"]
    b = consult_unique_decision(rs, **base, regime="sma_below_rsi_os|")
    assert a["state_key"] != b["state_key"]
    assert b["reused"] is False
    assert rs.consultation_metrics()["total"] == n1 + 1


def test_empty_worldview_still_records_none_found():
    repo = InMemoryBeliefRepository()
    rs = ReasoningService(repo, llm=None, goals=None)
    out = consult_unique_decision(
        rs,
        symbol="CIPLA.NS",
        laboratory_id="india_equity_learner",
        action_kind="hold",
        strategy_tag="plc_a_hold",
        ist_day="2026-08-17",
        cache={"states": {}},
        persist=False,
    )
    assert out["beliefs_found"] == 0
    assert out["note"] == "No relevant belief found."
    assert rs.consultation_metrics()["total"] == 1
    assert out["influence"] == "advice_only"


def test_mark_only_does_not_consult():
    rs = _rs()
    before = rs.consultation_metrics()["total"]
    out = consult_unique_decision(
        rs,
        symbol="CIPLA.NS",
        laboratory_id="india_equity_learner",
        action_kind="hold",
        strategy_tag="mark_only",
        ist_day="2026-08-17",
        cache={"states": {}},
        persist=False,
    )
    assert out.get("skip_reason") == "not_decision_state"
    assert rs.consultation_metrics()["total"] == before


def test_consult_record_mode_once_vs_per_belief():
    rs = _rs()
    per = rs.consult(domain="market", limit=8, purpose="consult")
    n_per = rs.consultation_metrics()["total"]
    once = rs.consult(domain="market", limit=8, purpose="decide", record_mode="once")
    n_once = rs.consultation_metrics()["total"]
    assert per["count"] >= 1
    assert once["count"] >= 1
    assert once["record_mode"] == "once"
    assert n_once == n_per + 1


def test_packet_carries_belief_context():
    rs = _rs()
    ctx = consult_unique_decision(
        rs,
        symbol="EICHERMOT.NS",
        laboratory_id="india_equity_learner",
        action_kind="hold",
        strategy_tag="engine_hold",
        ist_day="2026-08-17",
        cache={"states": {}},
        persist=False,
    )
    pkt = build_packet(
        action="hold",
        symbol="EICHERMOT.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="engine_hold",
        ts_ist="2026-08-17",
        belief_context=ctx,
    )
    assert pkt["belief_context"]["influence"] == "advice_only"
    assert pkt["belief_context"]["beliefs_found"] >= 1
    assert pkt["belief_context"]["state_key"]


def test_state_key_stable_and_rank_bucket():
    a = decision_state_key(
        laboratory_id="india_equity_learner",
        symbol="cipla.ns",
        ist_day="2026-08-17",
        action_kind="hold",
        strategy_tag="engine_hold",
        ranking_bucket_s=ranking_bucket(3),
        book_fp="A,B|c2",
        evidence_fp="x",
        regime="sma_above_rsi_mid|",
    )
    b = decision_state_key(
        laboratory_id="india_equity_learner",
        symbol="CIPLA.NS",
        ist_day="2026-08-17",
        action_kind="hold",
        strategy_tag="engine_hold",
        ranking_bucket_s="top5",
        book_fp="A,B|c2",
        evidence_fp="x",
        regime="sma_above_rsi_mid|",
    )
    assert a == b
    assert ranking_bucket(12) == "mid"
