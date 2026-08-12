"""Judgment Month J4 — curiosity unknowns → real research work."""

from __future__ import annotations

from atlas.investment.cognitive_work import remaining, run_cws_pass
from atlas.investment.curiosity import (
    drain_queue_work,
    is_data_gap_unknown,
    load_queue,
    normalize_unknown,
)


class _FakeResearch:
    def __init__(self) -> None:
        self.starts: list[str] = []

    def start(self, symbol, **kwargs):  # noqa: ANN001
        self.starts.append(str(symbol))
        return {"ok": True, "symbol": symbol, "mode": kwargs.get("mode")}


def test_normalize_unknown_j2_shapes():
    assert normalize_unknown("fundamentals.fcf") == "fcf"
    assert normalize_unknown("fcf_missing") == "fcf"
    assert normalize_unknown("debt_to_equity") == "debt_to_equity"
    assert is_data_gap_unknown("fundamentals.fcf")
    assert is_data_gap_unknown("promoter_holding")
    assert not is_data_gap_unknown("news")


def test_drain_starts_ira_and_persists(tmp_path):
    research = _FakeResearch()
    q = drain_queue_work(
        tmp_path,
        laboratory_id="india_equity_learner",
        research=research,
        wsos=[
            {
                "symbol": "CIPLA.NS",
                "unknowns": ["fundamentals.fcf", "news", "roic"],
            }
        ],
        open_symbols={"CIPLA.NS"},
        max_starts=2,
        ist_date="2026-08-11",
    )
    assert q["work_started_n"] >= 1
    assert research.starts
    assert "CIPLA.NS" in research.starts
    loaded = load_queue(tmp_path, "2026-08-11")
    statuses = {i.get("status") for i in (loaded.get("items") or []) if isinstance(i, dict)}
    assert "ira_started" in statuses
    # news stays queued (no fake completion)
    news = [
        i
        for i in (loaded.get("items") or [])
        if isinstance(i, dict) and str(i.get("unknown") or "").lower() == "news"
    ]
    if news:
        assert news[0].get("status") == "queued"


def test_cws_research_quota_only_after_real_work(tmp_path):
    lab = "india_equity_learner"
    # No research service → unknowns enqueue but research_task stays 0
    doc = run_cws_pass(
        tmp_path,
        laboratory_id=lab,
        wsos=[{"symbol": "EICHERMOT.NS", "unknowns": ["fcf", "pb"]}],
        open_symbols=["EICHERMOT.NS"],
        research=None,
    )
    assert int((doc.get("completed") or {}).get("research_task") or 0) == 0
    # belief_review still structural
    assert int((doc.get("completed") or {}).get("belief_review") or 0) >= 1

    research = _FakeResearch()
    doc2 = run_cws_pass(
        tmp_path,
        laboratory_id=lab,
        wsos=[{"symbol": "EICHERMOT.NS", "unknowns": ["fcf", "pb"]}],
        open_symbols=["EICHERMOT.NS"],
        research=research,
    )
    assert research.starts
    assert int((doc2.get("completed") or {}).get("research_task") or 0) >= 1
    rem = remaining(doc2)
    assert rem["research_task"] < 3
