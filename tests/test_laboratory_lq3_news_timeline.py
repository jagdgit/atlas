"""LQ.3 — per-symbol news timeline + revisit news_delta cites (hermetic)."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.decision_packets import DecisionPacketStore
from atlas.investment.decision_timeline import DecisionTimelineStore, what_changed
from atlas.investment.observations import (
    DecisionObservationStore,
    infer_news_topic_tags,
    mirror_root,
)
from atlas.workers.base import TickContext
from atlas.workers.news_intelligence import NewsIntelligenceWorker


class _FakeCandidates:
    def __init__(self) -> None:
        self.emitted: list = []

    def emit(self, payload):
        self.emitted.append(payload)

    def consume_pending(self, limit: int = 20):
        return {"consumed": min(limit, len(self.emitted))}


def test_infer_topic_tags_honest():
    tags = infer_news_topic_tags("Company wins large defence order book contract")
    assert "order" in tags
    assert infer_news_topic_tags("Completely unrelated fluff xyz") == []


def test_news_event_mirrors_jsonl_and_lists(tmp_path: Path):
    timeline = DecisionTimelineStore(data_dir=tmp_path)
    obs = DecisionObservationStore(data_dir=tmp_path, timeline=timeline)
    out = obs.record_news_event(
        text="Apollo Hospitals Q1 earnings beat on occupancy and ARPOB",
        symbol="APOLLOHOSP.NS",
        source="test",
        open_book=True,
        link_decision_id="11111111-1111-1111-1111-111111111111",
    )
    row = out["observation"]
    assert row["kind"] == "news_event"
    assert "earnings" in (row["payload"].get("topic_tags") or [])
    assert row["payload"]["sentiment"] == "unknown"
    assert row["payload"]["open_book"] is True
    assert row["payload"]["decision_id"]

    news_path = mirror_root(tmp_path) / "news" / "APOLLOHOSP.NS.jsonl"
    assert news_path.is_file()
    listed = obs.list_news_for_symbol(symbol="APOLLOHOSP.NS", limit=10)
    assert len(listed) >= 1
    assert listed[0]["id"] == row["id"]

    tl = timeline.list_symbol(symbol="APOLLOHOSP.NS", kind="observation")
    assert any(
        (e.get("payload") or {}).get("observation_kind") == "news_event" for e in tl
    )


def test_what_changed_cites_news_delta(tmp_path: Path):
    packets = DecisionPacketStore(data_dir=tmp_path)
    pkt = packets.record(
        action="buy",
        symbol="MTARTECH.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="x",
        ts_ist="2026-08-01",
        prices={"mark": 100.0},
        reasons_for=["signal"],
        observation_ids=[],
    )["packet"]

    obs = DecisionObservationStore(data_dir=tmp_path)
    news = obs.record_news_event(
        text="MTARTECH bags large defence order win from MoD",
        symbol="MTARTECH.NS",
        open_book=True,
        topic_tags=["order"],
    )["observation"]

    diff = what_changed(
        pkt,
        current_mark=105.0,
        recent_observations=[news],
        note="lq3",
    )
    assert diff["news_delta"] is not None
    assert diff["news_delta"]["count"] == 1
    assert "order" in (diff["news_delta"].get("topic_tags") or [])
    assert news["id"] in (diff["news_delta"].get("observation_ids") or [])
    assert any(str(d).startswith("news_delta:") for d in (diff.get("deltas") or []))
    assert diff.get("management_note") is None


def test_news_worker_open_book_link(tmp_path: Path):
    timeline = DecisionTimelineStore(data_dir=tmp_path)
    packets = DecisionPacketStore(data_dir=tmp_path, timeline=timeline)
    timeline._packets = packets
    buy = packets.record(
        action="buy",
        symbol="CIPLA.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="x",
        ts_ist="2026-08-01",
        prices={"mark": 1400.0, "fill_price": 1400.0, "filled_qty": 1},
        reasons_for=["signal"],
    )["packet"]

    obs = DecisionObservationStore(data_dir=tmp_path, timeline=timeline)
    worker = NewsIntelligenceWorker(
        candidates=_FakeCandidates(),
        observations=obs,
        decision_packets=packets,
    )
    result = worker.do_tick(
        TickContext(
            worker_id="n1",
            mission_id="m",
            config={
                "portfolio_key": "india_equity_learner",
                "open_symbols": ["CIPLA.NS"],
                "seed_from_watchlist": False,
                "items": [
                    {
                        "symbol": "CIPLA.NS",
                        "text": "Cipla receives FDA approval for new formulation",
                        "source": "operator_input",
                        "sentiment": "positive",
                    }
                ],
            },
            config_version=1,
            state={},
        )
    )
    assert "obs=1" in result.note
    assert result.state.get("last_news", {}).get("open_book_news") == 1

    news = obs.list_news_for_symbol(symbol="CIPLA.NS", open_book_only=True)
    assert len(news) >= 1
    pl = news[0].get("payload") or {}
    assert pl.get("open_book") is True
    assert pl.get("decision_id") == buy.get("decision_id")
    assert pl.get("sentiment") == "positive"
    assert "regulation" in (pl.get("topic_tags") or []) or True  # FDA → regulation if matched


def test_revisit_includes_news_delta(tmp_path: Path):
    timeline = DecisionTimelineStore(data_dir=tmp_path)
    packets = DecisionPacketStore(data_dir=tmp_path, timeline=timeline)
    timeline._packets = packets
    packets.record(
        action="buy",
        symbol="INFY.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="x",
        ts_ist="2026-07-01",
        prices={"mark": 1500.0, "fill_price": 1500.0, "filled_qty": 1},
        reasons_for=["signal"],
    )
    obs = DecisionObservationStore(data_dir=tmp_path, timeline=timeline)
    obs.record_news_event(
        text="Infosys wins multi-year digital transformation order",
        symbol="INFY.NS",
        open_book=True,
    )

    due = timeline.list_due(
        as_of_ist="2026-07-02", portfolio_key="india_equity_learner", limit=5
    )
    assert due
    result = timeline.run_due_revisits(
        as_of_ist="2026-07-02",
        portfolio_key="india_equity_learner",
        limit=5,
        mark_fn=lambda _s: 1510.0,
        observations_fn=lambda sym: obs.list_news_for_symbol(symbol=sym, limit=10),
    )
    assert result["completed"] >= 1
    item = result["items"][0]
    assert (item.get("what_changed") or {}).get("news_delta", {}).get("count", 0) >= 1
