"""OI-CLC0 CLC.5 — hermetic Day-2: retrieve → cite → bounded L2 → persist.

Does not replace Step 11 RAG canary. Does not require Ollama.
L5 stays 0: this is loop_closed_cite, not subsequent validation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from atlas.decision.contracts import DecisionRequest
from atlas.decision.engine import DecisionEngine
from atlas.decision.rules import DecisionRuleRegistry
from atlas.investment.decision_packets import build_packet, feature_contributions_v1
from atlas.investment.fel import default_fel
from atlas.investment.fel.features.store import is_decision_eligible, is_lesson_eligible
from atlas.investment.lesson_influence import (
    E001_LESSON_ID,
    E001_STATEMENT,
    INFLUENCE_BOUNDED,
    LAYER_AUTHOR_CLAIM,
    OPTION_SCORE_CAP,
    RANKING_CAP,
    SETUP_X_FINDING_ID,
    action_after_l0,
    canonical_e001_lesson,
    canonical_setup_x_lesson,
    catalog_lessons,
    experience_bias_map,
    experience_ref_ids,
    l2_totals,
    loop_closed_cite,
    match_lessons,
)
from atlas.investment.ranking import PHASE_ACTIVE, score_universe
from atlas.knowledge.restart_canary import CANARY_TOKEN, STATEMENT as SETUP_X_CANARY
from atlas.reasoning.decision_consult import consult_unique_decision
from atlas.trading.strategy import StrategyDecisionRule
from tests.test_loop0_l2_decision_consult import _rs


QUERY_E001 = "Does volume acceleration help buy_name?"


class _FakeDecisionRepo:
    def __init__(self) -> None:
        self.rows: list = []

    def record(self, decision):
        self.rows.append(decision)
        return {"id": str(uuid.uuid4()), "created_at": datetime.now(timezone.utc)}


def _day2_candidate() -> dict:
    return {
        "decision_type": "buy_name",
        "action": "buy",
        "strategy_tag": "setup_x",
        "setup_tag": "X",
        "regime": "Y",
        "regime_tags": ["Y"],
        "features": ["volume_acceleration_20d"],
        "query": QUERY_E001,
        "symbol": "DAY2.NS",
    }


def _retrieved() -> list[dict]:
    setup = canonical_setup_x_lesson()
    setup["statement"] = SETUP_X_CANARY
    return [setup, canonical_e001_lesson()]


def _bars(n: int = 25) -> list[dict]:
    return [
        {
            "t": f"2026-01-{i + 1:02d}",
            "open": 100.0 + i,
            "high": 101.0 + i,
            "low": 99.0 + i,
            "close": 100.0 + i,
            "volume": 1_000_000.0,
        }
        for i in range(n)
    ]


def test_day2_retrieve_cite_e001_and_setup_x():
    lessons = match_lessons(
        candidate=_day2_candidate(),
        retrieved=_retrieved(),
        query=QUERY_E001,
    )
    ids = experience_ref_ids(lessons)
    assert SETUP_X_FINDING_ID in ids
    assert E001_LESSON_ID in ids
    assert any(E001_STATEMENT[:40] in str(r.get("statement") or "") for r in lessons)
    assert any("Setup X performed poorly" in str(r.get("statement") or "") for r in lessons)
    totals = l2_totals(lessons)
    assert totals["option"] == -OPTION_SCORE_CAP
    assert totals["ranking"] == -RANKING_CAP


def test_day2_packet_experience_refs_and_score_moves():
    lessons = match_lessons(
        candidate=_day2_candidate(),
        retrieved=_retrieved(),
        query=QUERY_E001,
    )
    blank = build_packet(
        action="buy",
        symbol="DAY2.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="setup_x",
        ts_ist="2026-09-21",
        indicators={"rsi": 55.0, "sma_fast": 110.0, "sma_slow": 100.0},
    )
    cited = build_packet(
        action="buy",
        symbol="DAY2.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="setup_x",
        ts_ist="2026-09-21",
        indicators={"rsi": 55.0, "sma_fast": 110.0, "sma_slow": 100.0},
        lesson_refs=lessons,
        experience_refs=experience_ref_ids(lessons),
        belief_context={
            "influence": INFLUENCE_BOUNDED,
            "lesson_refs": lessons,
            "experience_refs": experience_ref_ids(lessons),
        },
    )
    assert cited["experience_refs"]
    assert SETUP_X_FINDING_ID in cited["experience_refs"]
    assert E001_LESSON_ID in cited["experience_refs"]
    assert cited["lesson_refs"]
    assert cited["feature_contributions"]["experience"] != blank["feature_contributions"]["experience"]
    assert cited["feature_contributions"]["experience"] < 0
    assert loop_closed_cite(cited) is True
    assert loop_closed_cite(blank) is False


def test_day2_buy_option_score_moves_and_engine_persists_refs():
    lessons = match_lessons(
        candidate=_day2_candidate(),
        retrieved=_retrieved(),
        query=QUERY_E001,
    )
    rule = StrategyDecisionRule()
    base = {
        "symbol": "DAY2.NS",
        "price": 100.0,
        "position_qty": 0.0,
        "equity": 100_000.0,
        "cash": 100_000.0,
        "trade_fraction": 0.1,
        "allow_min_lot": True,
        "indicators": {
            "sma_fast": 110.0,
            "sma_slow": 100.0,
            "rsi": 40.0,
            "params": {"sma_fast": 10, "sma_slow": 30},
            "bars": 40,
        },
    }
    plain = next(
        o
        for o in rule.score(
            DecisionRequest(mission_id="m", mission_type="paper_trading", context=dict(base)),
            None,
        )
        if o.key.startswith("buy:")
    )
    cited_opts = rule.score(
        DecisionRequest(
            mission_id="m",
            mission_type="paper_trading",
            context={**base, "lesson_refs": lessons},
        ),
        None,
    )
    cited = next(o for o in cited_opts if o.key.startswith("buy:"))
    assert cited.score < plain.score
    assert abs((plain.score - cited.score) - OPTION_SCORE_CAP) < 1e-9
    assert E001_LESSON_ID in cited.experience_refs
    assert SETUP_X_FINDING_ID in cited.experience_refs

    repo = _FakeDecisionRepo()
    reg = DecisionRuleRegistry()
    reg.register(rule)
    engine = DecisionEngine(repo, rules=reg)
    decision = engine.decide(
        DecisionRequest(
            mission_id="m",
            mission_type="paper_trading",
            context={**base, "lesson_refs": lessons},
        )
    )
    assert decision.experience_refs
    assert E001_LESSON_ID in decision.experience_refs
    assert repo.rows
    assert repo.rows[0].experience_refs == decision.experience_refs


def test_day2_ranking_experience_component_moves():
    lessons = match_lessons(
        candidate=_day2_candidate(),
        retrieved=_retrieved(),
        query=QUERY_E001,
    )
    members = [{"symbol": "DAY2.NS", "name": "Day2", "sector": "X"}]
    bars = {"DAY2.NS": _bars()}
    plain = score_universe(members, bars_by_symbol=bars, cold_start_coverage=0.25)
    biased = score_universe(
        members,
        bars_by_symbol=bars,
        experience_bias_by_symbol=experience_bias_map(["DAY2.NS"], lessons),
        cold_start_coverage=0.25,
    )
    assert plain[0]["phase"] == PHASE_ACTIVE
    assert biased[0]["components"]["experience"] != plain[0]["components"]["experience"]
    assert biased[0]["components"]["experience"] < plain[0]["components"]["experience"]


def test_day2_plc_a_still_blocks_incomplete_fundamentals():
    lessons = match_lessons(
        candidate=_day2_candidate(),
        retrieved=_retrieved(),
        query=QUERY_E001,
    )
    assert l2_totals(lessons)["option"] < 0
    gated = action_after_l0(
        "buy",
        research_gate={"allowed": False, "reason": "plc_a_hold", "code": "fundamentals_incomplete"},
        fundamentals={"pe": None, "fcf": None, "block_if_incomplete": True},
    )
    assert gated == "hold"
    pkt = build_packet(
        action="hold",
        symbol="DAY2.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="plc_a_hold",
        ts_ist="2026-09-21",
        lesson_refs=lessons,
        experience_refs=experience_ref_ids(lessons),
        research_gate={"allowed": False, "reason": "plc_a_hold"},
        fundamentals={},
    )
    assert pkt["action"] == "hold"
    assert pkt["gates"]["research"]["allowed"] is False
    assert pkt["experience_refs"]


def test_author_claim_is_cite_only_never_l2():
    claim = {
        "id": "F-book-vol-accel",
        "kind": "finding",
        "statement": "Author claims volume acceleration may improve momentum.",
        "layer": LAYER_AUTHOR_CLAIM,
        "sign": 1,
    }
    lessons = match_lessons(
        candidate=_day2_candidate(),
        retrieved=[claim],
        query=QUERY_E001,
    )
    assert lessons
    assert all(r["layer"] == LAYER_AUTHOR_CLAIM for r in lessons)
    assert l2_totals(lessons)["option"] == 0.0
    assert l2_totals(lessons)["ranking"] == 0.0


def test_e001_feature_lesson_eligible_not_live_control():
    fel = default_fel()
    vol = fel.features.get("volume_acceleration_20d")
    assert vol is not None
    assert is_decision_eligible(vol) is False
    assert is_lesson_eligible(vol) is True
    gene = vol
    extra = getattr(gene, "extra", {}) or {}
    assert extra.get("lesson_eligible") in {True, None}


def test_consult_stamps_cited_bounded_without_llm():
    rs = _rs()
    ctx = consult_unique_decision(
        rs,
        symbol="DAY2.NS",
        laboratory_id="india_equity_learner",
        action_kind="buy",
        strategy_tag="setup_x",
        ist_day="2026-09-21",
        cache={"states": {}},
        persist=False,
        candidate=_day2_candidate(),
        retrieved_lessons=_retrieved(),
        regime="Y",
    )
    assert ctx["influence"] == INFLUENCE_BOUNDED
    assert "no size/side change" not in str(ctx.get("note") or "")
    ids = ctx.get("experience_refs") or []
    assert SETUP_X_FINDING_ID in ids
    assert E001_LESSON_ID in ids
    assert ctx.get("no_match") is False
    assert CANARY_TOKEN in SETUP_X_CANARY


def test_feature_contributions_experience_from_lessons_not_risk_axis():
    lessons = match_lessons(
        candidate=_day2_candidate(),
        retrieved=_retrieved(),
        query=QUERY_E001,
    )
    from_lessons = feature_contributions_v1(
        action="buy",
        investment_score={"axes": {"risk": 0.9}},
        experience_signed=l2_totals(lessons)["ranking"],
    )
    from_risk = feature_contributions_v1(
        action="buy",
        investment_score={"axes": {"risk": 0.9}},
    )
    assert from_lessons["experience"] != from_risk["experience"]
    assert from_lessons["experience"] < 0


def test_catalog_includes_e001_without_disk():
    rows = catalog_lessons()
    assert any(r["id"] == E001_LESSON_ID for r in rows)
    assert all(r.get("decision_eligible") is False for r in rows if r["id"] == E001_LESSON_ID)


def test_clc6_forced_replay_packet_stamps_no_match_or_refs(tmp_path, monkeypatch):
    """CLC.6 — worker decide path writes packets; empty refs are honest no_match."""
    from atlas.investment.decision_packets import DecisionPacketStore
    from atlas.investment.experience_integrity import ist_day
    from tests.test_paper_trading_worker import (
        _CFG,
        _UPDOWN,
        _bars as _pt_bars,
        _engine,
        _worker,
        _ctx,
        _FakeEvents,
    )

    class _Cfg:
        class paths:
            data = tmp_path

    monkeypatch.setattr("atlas.config.get_config", lambda reload=False: _Cfg())
    store = DecisionPacketStore(data_dir=tmp_path)
    events = _FakeEvents()
    engine = _engine()
    worker = _worker(
        {"acme": _pt_bars(_UPDOWN)},
        engine=engine,
        events=events,
    )
    worker._decision_packets = store
    cfg = {**_CFG, "portfolio_key": "india_equity_learner"}
    result = worker.do_tick(_ctx(cfg))
    assert result.done is True
    packets = store.list_day(
        portfolio_key="india_equity_learner",
        ts_ist=ist_day(),
        limit=50,
    )
    assert packets, "CLC.6 failed: worker recorded no decision packet"
    for pkt in packets:
        refs = list(pkt.get("experience_refs") or [])
        lessons = list(pkt.get("lesson_refs") or [])
        bc = pkt.get("belief_context") or {}
        if refs or lessons:
            assert pkt.get("no_match") is not True
            continue
        assert pkt.get("no_match") is True or bc.get("no_match") is True


def test_clc6_worker_consult_with_vol_accel_cites_e001(tmp_path, monkeypatch):
    """CLC.6 — when the candidate is buy_name/vol-accel, E001 sits on the worker consult."""
    from tests.test_paper_trading_worker import _worker, _engine, _UPDOWN, _bars as _pt_bars

    class _Cfg:
        class paths:
            data = tmp_path

    monkeypatch.setattr("atlas.config.get_config", lambda reload=False: _Cfg())
    worker = _worker({"acme": _pt_bars(_UPDOWN)}, engine=_engine())
    ctx = worker._belief_context_for_packet(
        action="buy",
        symbol="ACME",
        strategy_tag="sma_cross_rsi",
        portfolio_key="india_equity_learner",
        thesis_trigger=None,
        plan_link=None,
        expected_doc=None,
        research_gate=None,
        portfolio_gate=None,
        indicators={
            "features": ["volume_acceleration_20d"],
            "decision_type": "buy_name",
            "setup_tag": "X",
            "regime_tags": ["Y"],
        },
        fundamentals=None,
        sector=None,
        ist_day="2026-09-22",
    )
    ids = list(ctx.get("experience_refs") or [])
    assert E001_LESSON_ID in ids
    assert ctx.get("no_match") is False
    assert ctx.get("influence") == INFLUENCE_BOUNDED
