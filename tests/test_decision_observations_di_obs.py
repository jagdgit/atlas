"""DI.Obs Observation Layer — hermetic."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.decision_packets import DecisionPacketStore
from atlas.investment.decision_timeline import DecisionTimelineStore
from atlas.investment.observations import DecisionObservationStore, format_observations_section
from atlas.investment.reports import format_evening_report
from atlas.investment.research.service import InvestmentResearchService


def test_record_market_and_timeline_fanout(tmp_path: Path):
    timeline = DecisionTimelineStore(data_dir=tmp_path)
    obs = DecisionObservationStore(data_dir=tmp_path, timeline=timeline)
    out = obs.record_market_event(
        symbol="EICHERMOT.NS",
        event={"pct_move": 6.2, "score": 0.8, "kind": "price_spike", "reason": "gap up"},
    )
    row = out["observation"]
    assert row["kind"] == "market_event"
    assert row["symbol"] == "EICHERMOT.NS"
    assert Path(out["mirror_path"]).is_file()

    loaded = obs.get(row["id"])
    assert loaded is not None
    assert loaded["id"] == row["id"]

    events = timeline.list_symbol(symbol="EICHERMOT.NS", kind="observation")
    assert len(events) >= 1
    assert events[0]["payload"]["observation_id"] == row["id"]


def test_packet_cites_observation_ids(tmp_path: Path):
    timeline = DecisionTimelineStore(data_dir=tmp_path)
    obs = DecisionObservationStore(data_dir=tmp_path, timeline=timeline)
    o1 = obs.record_news_event(
        text="Company announces strong order book growth for FY",
        symbol="TCS.NS",
    )["observation"]
    packets = DecisionPacketStore(data_dir=tmp_path, timeline=timeline)
    ids = obs.ids_for_symbol("TCS.NS", limit=5, since_hours=72)
    assert o1["id"] in ids
    out = packets.record(
        action="watch",
        symbol="TCS.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="plan_watch",
        ts_ist="2026-08-05",
        reasons_for=["plan"],
        observation_ids=ids,
    )
    assert o1["id"] in out["packet"]["observation_ids"]


def test_research_awareness_includes_observations(tmp_path: Path):
    obs = DecisionObservationStore(data_dir=tmp_path)
    obs.record_market_event(
        symbol="INFY.NS",
        event={"pct_move": -5.5, "score": 0.75, "kind": "price_drop"},
    )
    research = InvestmentResearchService(data_dir=str(tmp_path))
    research.bind_observations(obs)
    aw = research.awareness("INFY.NS")
    assert aw.get("recent_observations")
    assert aw["recent_observations"][0]["kind"] == "market_event"


def test_list_since_and_policy_macro(tmp_path: Path):
    timeline = DecisionTimelineStore(data_dir=tmp_path)
    obs = DecisionObservationStore(data_dir=tmp_path, timeline=timeline)
    obs.record_policy_event(
        title="PLI electronics extension",
        sectors=["Consumer Durables", "IT"],
    )
    recent = obs.list_since(since_hours=24, limit=10)
    assert any(r.get("kind") == "policy_event" for r in recent)
    macro = timeline.list_symbol(symbol="__MACRO__", kind="observation")
    assert len(macro) >= 1


def test_evening_observations_section():
    _subj, body = format_evening_report(
        plan={"as_of": "2026-08-05", "summary": "x", "phase": "learning", "confidence": "low"},
        portfolio={
            "cash": 1,
            "observations": [
                {
                    "id": "abc",
                    "kind": "market_event",
                    "symbol": "EICHERMOT.NS",
                    "source": "market_observer",
                    "payload": {"pct_move": 5.0},
                }
            ],
        },
    )
    assert "Observations (DI.Obs)" in body
    assert "market_event" in body
    lines = format_observations_section([])
    assert any("none recorded" in ln for ln in lines)
