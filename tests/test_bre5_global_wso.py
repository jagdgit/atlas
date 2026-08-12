"""BRE.5 — global WSO + mentor digest from revision history."""

from __future__ import annotations

from atlas.investment.global_mind import (
    build_mentor_digest,
    collect_revision_patterns,
    distill_global_mind,
    format_global_mind_section,
    mentor_lesson_from_digest,
)
from atlas.investment.reports import format_evening_report
from atlas.investment.world_state import (
    append_revision,
    empty_wso,
    load_global_wso,
    save_wso,
)
from atlas.workers.base import TickContext
from atlas.workers.investment_mentor import InvestmentMentorWorker


def _wso_with_revision(symbol: str, lab: str, *, status: str, reason: str):
    w = empty_wso(symbol=symbol, laboratory_id=lab)
    append_revision(w, status=status, reason=reason, llm=True)
    return w


def test_collect_and_digest_patterns():
    lab = "lab"
    wsos = [
        _wso_with_revision("EICHERMOT.NS", lab, status="strengthened", reason="RS held"),
        _wso_with_revision("TCS.NS", lab, status="weakened", reason="FCF still missing"),
    ]
    patterns = collect_revision_patterns(wsos)
    assert len(patterns) >= 2
    digest = build_mentor_digest(patterns)
    assert digest["advice_only"] is True
    assert digest["enable_soft_bias"] is False
    assert digest["pattern_count"] >= 2
    assert any("strengthened" in b for b in digest["bullets"])


def test_distill_writes_global_wso(tmp_path):
    lab = "india_equity_learner"
    w1 = _wso_with_revision(
        "EICHERMOT.NS", lab, status="strengthened", reason="thesis intact"
    )
    w2 = _wso_with_revision(
        "APOLLOHOSP.NS", lab, status="falsified", reason="occupancy miss"
    )
    save_wso(tmp_path, w1)
    save_wso(tmp_path, w2)

    doc = distill_global_mind(
        tmp_path,
        laboratory_id=lab,
        allow_llm_narrative=False,
    )
    assert doc.get("kind") == "global"
    assert doc.get("mentor_digest", {}).get("pattern_count", 0) >= 2
    loaded = load_global_wso(tmp_path, lab)
    assert loaded is not None
    assert loaded.get("symbol") == "_GLOBAL"


def test_format_global_mind_in_evening():
    gw = {
        "kind": "global",
        "thesis_text": "",
        "mentor_digest": {
            "pattern_count": 2,
            "linked_symbols": ["EICHERMOT.NS", "TCS.NS"],
            "bullets": ["1 belief(s) strengthened — e.g. EICHERMOT.NS: RS held"],
            "recommendations": ["Re-check falsifiers before adding size"],
            "advice_only": True,
        },
        "patterns": [],
    }
    lines = format_global_mind_section(gw)
    assert any("BRE.5" in x for x in lines)
    assert any("advice_only" in x for x in lines)

    subject, body = format_evening_report(
        plan={"as_of": "2026-08-10", "phase": "review", "summary": "t"},
        portfolio={"global_wso": gw, "portfolio_key": "lab"},
        laboratory_id="lab",
    )
    assert "Global mind (BRE.5)" in body


def test_mentor_lesson_advice_only_and_worker(tmp_path):
    lab = "india_equity_learner"
    w = _wso_with_revision(
        "EICHERMOT.NS", lab, status="weakened", reason="news contradicted"
    )
    save_wso(tmp_path, w)
    distill_global_mind(tmp_path, laboratory_id=lab)
    gw = load_global_wso(tmp_path, lab)
    payload = mentor_lesson_from_digest(gw)
    assert payload is not None
    assert payload["enable_soft_bias"] is False
    assert "bre5" in payload["tags"]

    bias_calls: list[str] = []

    class _Learning:
        def list_experiences(self, *, limit=40):
            return []

        def enable_bias(self, eid, *, enabled=True):
            bias_calls.append(eid)

        def remember_experience(self, **kwargs):
            return {"ref_id": "exp-bre5"}

    worker = InvestmentMentorWorker(
        learning=_Learning(), data_dir=str(tmp_path)
    )
    result = worker.do_tick(
        TickContext(
            worker_id="im-1",
            mission_id="m-im",
            config={
                "portfolio_key": lab,
                "data_dir": str(tmp_path),
                "force": True,
            },
            config_version=1,
            state={},
        )
    )
    assert "bre5" in (result.note or "")
    assert result.state.get("bre5_advice_only") is True
    assert bias_calls == []  # A7 — no soft-bias


def test_empty_revisions_honest(tmp_path):
    doc = distill_global_mind(
        tmp_path, laboratory_id="empty_lab", wsos=[], allow_llm_narrative=False
    )
    assert doc["status"] == "insufficient_evidence"
    assert mentor_lesson_from_digest(doc) is None
