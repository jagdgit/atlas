"""CUR.1 + BRE.2 hermetic tests."""

from __future__ import annotations

from atlas.investment.belief_revision import revise_beliefs_budgeted, revise_one_wso
from atlas.investment.cognitive_budget import budget_for_wso, pick_budgeted, score_dimensions
from atlas.investment.curiosity import enqueue_from_wsos, load_queue
from atlas.investment.world_state import empty_wso, evidence_delta_counts


class _FakeResp:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeRole:
    def __init__(self, text: str) -> None:
        self._text = text

    def chat(self, messages, **kwargs):  # noqa: ANN001
        return _FakeResp(self._text)


class _FakeLLM:
    def __init__(self, text: str, *, busy: bool = False) -> None:
        self._text = text
        self._busy = busy
        self.calls = 0

    def lane_busy(self) -> bool:
        return self._busy

    def for_role(self, role: str) -> _FakeRole:
        self.calls += 1
        return _FakeRole(self._text)


def test_cognitive_budget_high_vs_low():
    hi = score_dimensions(importance="high", novelty="high", uncertainty="high")
    lo = score_dimensions(importance="low", novelty="low", uncertainty="low")
    assert hi["llm_budget"] == 3
    assert lo["llm_budget"] == 0


def test_curiosity_enqueue_from_unknowns(tmp_path):
    w = empty_wso(symbol="APOLLOHOSP.NS", laboratory_id="india_equity_learner")
    w["unknowns"] = ["fcf", "occupancy"]
    w["uncertainty"] = {"data": "high", "model": "unknown", "execution": "low", "macro": "medium", "governance": "unknown"}
    doc = enqueue_from_wsos(
        tmp_path,
        "india_equity_learner",
        [w],
        max_n=3,
        open_symbols={"APOLLOHOSP.NS"},
        ist_date="2026-08-10",
    )
    assert doc["enqueued_tonight"] >= 1
    items = doc["items"]
    assert any(i.get("unknown") == "fcf" for i in items)
    loaded = load_queue(tmp_path, "2026-08-10")
    assert len(loaded.get("items") or []) >= 1
    # Idempotent second call same night
    doc2 = enqueue_from_wsos(
        tmp_path,
        "india_equity_learner",
        [w],
        max_n=3,
        open_symbols={"APOLLOHOSP.NS"},
        ist_date="2026-08-10",
    )
    assert doc2["enqueued_tonight"] == 0


def test_bre2_skips_without_material_delta(tmp_path):
    w = empty_wso(symbol="EICHERMOT.NS", laboratory_id="lab")
    llm = _FakeLLM('{"status":"strengthened","thesis_text":"should not apply"}')
    out = revise_beliefs_budgeted(
        [w],
        evidence_delta=evidence_delta_counts(),
        llm=llm,
        data_dir=str(tmp_path),
    )
    assert llm.calls == 0
    assert out[0]["status"] == "unchanged"
    assert "no material evidence delta" in (out[0]["revision_history"][-1]["reason"])


def test_bre2_llm_applies_with_citations(tmp_path):
    w = empty_wso(symbol="EICHERMOT.NS", laboratory_id="lab")
    w["evidence_ids"] = ["ev1"]
    payload = {
        "status": "weakened",
        "thesis_text": "Demand slowing vs prior belief",
        "thesis_strength": 5.0,
        "beliefs": {
            "demand_resilience": {
                "confidence": 0.4,
                "note": "exports soft",
                "evidence_ids": ["ev1"],
            }
        },
        "falsifiers": ["export recovery"],
        "unknowns": ["inventory"],
        "reason": "exports soft in evidence",
        "claims": [{"text": "exports soft", "evidence_ids": ["ev1"]}],
    }
    import json

    llm = _FakeLLM(json.dumps(payload))
    out = revise_one_wso(
        w,
        llm=llm,
        evidence_delta=evidence_delta_counts(news_n=1),
        extra_evidence_ids=["ev1"],
        data_dir=str(tmp_path),
    )
    assert out["status"] == "weakened"
    assert "Demand slowing" in out["thesis_text"]
    assert out["beliefs"]["demand_resilience"]["confidence"] == 0.4
    assert out["revision_history"][-1]["llm"] is True


def test_bre2_rejects_uncited_belief_notes(tmp_path):
    w = empty_wso(symbol="EICHERMOT.NS", laboratory_id="lab")
    w["evidence_ids"] = ["ev1"]
    import json

    payload = {
        "status": "strengthened",
        "thesis_text": "ok",
        "beliefs": {
            "moat": {
                "confidence": 0.9,
                "note": "invented",
                "evidence_ids": ["NOT_REAL"],
            }
        },
        "reason": "x",
        "claims": [],
    }
    llm = _FakeLLM(json.dumps(payload))
    out = revise_one_wso(
        w,
        llm=llm,
        evidence_delta=evidence_delta_counts(research_n=1),
        data_dir=str(tmp_path),
    )
    assert "moat" not in (out.get("beliefs") or {})
    assert "dropped" in out["revision_history"][-1]["reason"]


def test_pick_budgeted_respects_cap():
    items = [
        {"symbol": "A", "llm_budget": 3},
        {"symbol": "B", "llm_budget": 1},
        {"symbol": "C", "llm_budget": 1},
    ]
    picked = pick_budgeted(items, max_passes=3)
    assert len(picked) == 1
    assert picked[0]["symbol"] == "A"


def test_budget_for_open_book_with_gaps():
    w = empty_wso(symbol="X.NS", laboratory_id="lab")
    w["unknowns"] = ["fcf", "debt_equity", "pe"]
    w["uncertainty"] = {"data": "high"}
    b = budget_for_wso(w, is_open_position=True, has_material_delta=True)
    assert b["llm_budget"] >= 1
