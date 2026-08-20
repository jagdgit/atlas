"""OI-LINT0 Phase 5 — research intelligence gates."""

from __future__ import annotations

from atlas.investment.curiosity import drain_queue_work, load_queue
from atlas.investment.research_intelligence import (
    curiosity_affects_allocation,
    drain_news_curiosity,
    filter_curiosity_candidates,
    gate_belief_revision_output,
    verify_extract,
)


class _FakeResearch:
    def start(self, symbol, **kwargs):  # noqa: ANN001
        return {"ok": True, "symbol": symbol}


def test_curiosity_only_when_allocation_sensitive():
    assert curiosity_affects_allocation(
        "fcf", symbol="CIPLA.NS", is_open=True
    )
    assert not curiosity_affects_allocation(
        "occupancy", symbol="CLOSED.NS", is_open=False
    )
    assert curiosity_affects_allocation(
        "fcf",
        symbol="CIPLA.NS",
        allocation_blockers=[{"symbol": "CIPLA.NS", "unknown": "fcf"}],
        is_open=False,
    )


def test_filter_drops_non_allocation_curiosity():
    cands = [
        {"symbol": "CLOSED.NS", "unknown": "occupancy", "status": "queued"},
        {"symbol": "CIPLA.NS", "unknown": "fcf", "status": "queued"},
    ]
    kept, skipped = filter_curiosity_candidates(
        cands, open_symbols={"CIPLA.NS"}
    )
    assert skipped == 1
    assert len(kept) == 1
    assert kept[0]["symbol"] == "CIPLA.NS"


def test_verify_extract_tier3_cannot_write_belief():
    v = verify_extract("fcf", 100.0, source_tier=3, evidence_level="G")
    assert v["may_write_belief"] is False
    assert v["status"] == "research_question"


def test_verify_extract_primary_can_write():
    v = verify_extract("fcf", 100.0, source_tier=1, evidence_level="A")
    assert v["may_write_belief"] is True


def test_gate_belief_strips_unverified_fcf_claim():
    parsed = {
        "status": "strengthened",
        "thesis_text": "FCF is strong at 500cr",
        "claims": [{"text": "FCF is 500cr", "evidence_ids": ["obs-1"]}],
    }
    gated = gate_belief_revision_output(
        parsed, {"obs-1"}, fundamentals={"pe": 30.0}
    )
    assert gated["parsed"]["status"] == "insufficient_evidence"
    assert gated["parsed"]["thesis_text"] == ""


def test_news_drain_explicit_unknown_without_evidence(tmp_path):
    qdoc = {
        "items": [
            {
                "symbol": "CIPLA.NS",
                "unknown": "news",
                "status": "queued",
            }
        ]
    }
    out = drain_news_curiosity(qdoc, tmp_path, laboratory_id="india_equity_learner")
    assert out["items"][0]["status"] == "unknown_explicit"
    assert out["news_drain"]["unknown_explicit"] == 1


def test_news_drain_resolved_with_evidence(tmp_path):
    from atlas.investment.observations import DecisionObservationStore

    obs = DecisionObservationStore(data_dir=tmp_path)
    obs.record_news_event(
        text="Cipla receives FDA approval for new drug formulation today",
        symbol="CIPLA.NS",
        source="rss:pib_press",
        extra={
            "feed_id": "pib_press",
            "source_tier": 1,
            "evidence_class": "evidence_candidate",
        },
    )
    qdoc = {"items": [{"symbol": "CIPLA.NS", "unknown": "news", "status": "queued"}]}
    out = drain_news_curiosity(qdoc, tmp_path)
    assert out["items"][0]["status"] == "resolved"
    assert out["news_drain"]["resolved"] == 1


def test_drain_queue_applies_news_drain(tmp_path):
    q = drain_queue_work(
        tmp_path,
        laboratory_id="india_equity_learner",
        research=_FakeResearch(),
        wsos=[{"symbol": "CIPLA.NS", "unknowns": ["news", "fcf"]}],
        open_symbols={"CIPLA.NS"},
        max_starts=1,
        ist_date="2026-08-20",
    )
    assert "news_drain" in q
    loaded = load_queue(tmp_path, "2026-08-20")
    news = [i for i in loaded.get("items") or [] if i.get("unknown") == "news"]
    assert news and news[0]["status"] in {"unknown_explicit", "resolved"}
