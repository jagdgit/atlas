"""OI-F2 Temporal Knowledge helpers + MCA / consolidate wiring."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from atlas.knowledge.consolidation import InMemoryFindingStore, KnowledgeLifecycleService
from atlas.knowledge.temporal import (
    TRUTH_CURRENT,
    TRUTH_HISTORICAL,
    TRUTH_PREDICTED,
    annotate_finding_item,
    is_operative_fact,
    partition_by_truth,
    stamp_prediction,
    stamp_validity,
    truth_kind,
)
from atlas.missions.context import MissionContextService


def test_truth_kind_classification():
    now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    assert (
        truth_kind(
            {"provenance": {"truth_kind": "predicted"}, "status": "active"},
            now=now,
        )
        == TRUTH_PREDICTED
    )
    assert truth_kind({"status": "superseded"}, now=now) == TRUTH_HISTORICAL
    assert (
        truth_kind(
            {
                "status": "active",
                "valid_until": (now - timedelta(days=1)).isoformat(),
            },
            now=now,
        )
        == TRUTH_HISTORICAL
    )
    assert (
        truth_kind(
            {
                "status": "active",
                "valid_from": (now + timedelta(days=1)).isoformat(),
            },
            now=now,
        )
        == TRUTH_PREDICTED
    )
    assert truth_kind({"status": "active", "freshness": "aging"}, now=now) == TRUTH_CURRENT
    assert is_operative_fact({"status": "active"}, now=now) is True
    assert is_operative_fact({"claim_type": "forecast"}, now=now) is False


def test_stamp_prediction_and_partition():
    now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    forecast = stamp_prediction(
        {"statement": "AAPL may gap up after earnings"},
        horizon_until=(now + timedelta(days=7)).isoformat(),
        valid_from=now.isoformat(),
    )
    assert forecast["claim_type"] == "forecast"
    assert forecast["provenance"]["truth_kind"] == TRUTH_PREDICTED
    assert truth_kind(forecast, now=now) == TRUTH_PREDICTED

    fact = stamp_validity(
        {"statement": "NSE closes 15:30", "status": "active"},
        valid_from=(now - timedelta(days=30)).isoformat(),
        truth_kind_value=TRUTH_CURRENT,
    )
    historical = {"statement": "old rule", "status": "superseded"}
    parts = partition_by_truth([forecast, fact, historical], now=now)
    assert len(parts[TRUTH_PREDICTED]) == 1
    assert len(parts[TRUTH_CURRENT]) == 1
    assert len(parts[TRUTH_HISTORICAL]) == 1


def test_consolidate_preserves_validity_window():
    now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    store = InMemoryFindingStore()
    svc = KnowledgeLifecycleService(store)
    stamped = stamp_prediction(
        {
            "statement": "DEMO equity may rally into Friday",
            "domain": "markets",
            "supporting_sources": [{"url": "https://example.test/a"}],
        },
        horizon_until=(now + timedelta(days=3)).isoformat(),
        valid_from=now.isoformat(),
    )
    row = svc.consolidate(stamped)
    assert row.get("valid_from")
    assert row.get("valid_until")
    assert (row.get("provenance") or {}).get("truth_kind") == TRUTH_PREDICTED
    assert truth_kind(row, now=now) == TRUTH_PREDICTED


def test_mca_finding_items_include_truth_kind():
    now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)

    class _Knowledge:
        def retrieve(self, *a, **k):
            return []

        def list_findings(self, *, limit=50, domain=None, include_archive=False):
            return [
                {
                    "id": "f-cur",
                    "statement": "NSE equity session closes at 15:30",
                    "claim_type": "fact",
                    "domain": "markets",
                    "status": "active",
                    "freshness": "current",
                    "quality": {"trust": "medium"},
                },
                {
                    "id": "f-pred",
                    "statement": "NSE settlement volume may spike tomorrow",
                    "claim_type": "forecast",
                    "domain": "markets",
                    "status": "active",
                    "freshness": "current",
                    "provenance": {"truth_kind": "predicted"},
                    "valid_until": (now + timedelta(days=1)).isoformat(),
                    "quality": {"trust": "low"},
                },
            ]

    svc = MissionContextService(knowledge=_Knowledge())
    out = svc.gather("NSE", program_id="market", limit=12)
    assert out["version"] == "mca.1.1"
    findings = [i for i in out["items"] if i.get("item_kind") == "finding"]
    assert findings
    kinds = {i["id"]: i.get("truth_kind") for i in findings}
    assert kinds.get("f-cur") == TRUTH_CURRENT
    assert kinds.get("f-pred") == TRUTH_PREDICTED
    assert "freshness" in findings[0]


def test_annotate_finding_item_shape():
    ann = annotate_finding_item(
        {
            "status": "active",
            "freshness": "aging",
            "valid_from": "2026-01-01T00:00:00+00:00",
            "valid_until": None,
        }
    )
    assert ann["truth_kind"] == TRUTH_CURRENT
    assert ann["freshness"] == "aging"
    assert ann["valid_from"]


def test_paper_trading_partitions_findings_into_context():
    """DecisionRequest context separates predicted findings from operative facts."""
    from atlas.workers.paper_trading import PaperTradingWorker

    class FakeCtx:
        def gather(self, topic, *, program_id=None, limit=8):
            return {
                "summary": "mixed",
                "citations": ["finding:f1"],
                "items": [
                    {
                        "item_kind": "finding",
                        "id": "f1",
                        "statement": "price is 100",
                        "truth_kind": "current",
                        "status": "active",
                        "freshness": "current",
                    },
                    {
                        "item_kind": "finding",
                        "id": "f2",
                        "statement": "may rally",
                        "truth_kind": "predicted",
                        "claim_type": "forecast",
                        "status": "active",
                    },
                    {
                        "item_kind": "experience_advice",
                        "advice": "re-check risk",
                    },
                ],
            }

    captured: dict = {}

    class FakeEngine:
        def decide(self, request):
            captured["context"] = dict(request.context)
            from atlas.decision.contracts import Decision

            return Decision(
                mission_id=request.mission_id,
                mission_type=request.mission_type,
                action_kind="hold",
                action={"kind": "hold"},
                why="noop",
                id="d1",
            )

    class FakePortfolio:
        def position(self, *a, **k):
            return {"quantity": 0.0}

        def snapshot(self, *a, **k):
            return {"equity": 10_000.0, "cash": 10_000.0}

    worker = PaperTradingWorker(
        assets=None,
        market_data=None,
        decision_engine=FakeEngine(),
        portfolio=FakePortfolio(),
        mission_context=FakeCtx(),
    )
    bars = [{"close": 100.0 + i} for i in range(40)]
    worker._decide_bar(
        symbol="DEMO",
        bars=bars,
        cursor=39,
        cfg={},
        strategy={"sma_fast": 5, "sma_slow": 10, "trade_fraction": 0.1},
        allowed=["DEMO"],
        blocked=[],
        portfolio_id="p1",
        mission_id="m1",
        config_version=1,
        totals={"decisions": 0, "holds": 0, "gaps": 0},
        marks={},
    )
    ctx = captured["context"]
    assert len(ctx["fact_findings"]) == 1
    assert ctx["fact_findings"][0]["id"] == "f1"
    assert len(ctx["predicted_findings"]) == 1
    assert ctx["predicted_findings"][0]["id"] == "f2"
    assert "re-check risk" in ctx["mentor_advice"]
