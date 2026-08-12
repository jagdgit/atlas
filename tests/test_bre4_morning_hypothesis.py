"""BRE.4 — morning hypothesis / evidence-needed BATCH hermetic tests."""

from __future__ import annotations

from atlas.investment.morning_hypothesis import (
    collect_morning_targets,
    format_morning_hypothesis_section,
    load_batch,
    run_morning_hypothesis_batch,
)
from atlas.investment.reports import format_morning_report
from atlas.investment.world_state import empty_wso


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


_JSON = (
    '{"hypotheses":['
    '{"symbol":"EICHERMOT.NS","kind":"open_book",'
    '"statement":"Hold while FCF remains unknown; thesis intact if RS holds.",'
    '"falsifiers":["FCF stays missing after Screener import","RS breaks vs NIFTY"]},'
    '{"symbol":"APOLLOHOSP.NS","kind":"candidate",'
    '"statement":"Candidate needs PE/FCF before size-up.",'
    '"falsifiers":["valuation gap widens"]}],'
    '"evidence_needed":['
    '{"symbol":"EICHERMOT.NS","unknown":"fcf","asks":["screener FCF","cashflow statement"]},'
    '{"symbol":"APOLLOHOSP.NS","unknown":"coverage","asks":["confirm PE/FCF"]}],'
    '"notes":"Focus open books first"}'
)


def test_collect_open_and_candidates():
    w = empty_wso(symbol="EICHERMOT.NS", laboratory_id="lab")
    w["unknowns"] = ["fcf", "news"]
    plan = {
        "candidates": [
            {"symbol": "EICHERMOT.NS", "rank": 1, "why": "top"},
            {"symbol": "APOLLOHOSP.NS", "rank": 2, "why": "next"},
        ]
    }
    targets = collect_morning_targets(
        wsos=[w],
        plan=plan,
        open_symbols={"EICHERMOT.NS"},
        max_candidates=5,
    )
    syms = {t["symbol"].upper() for t in targets}
    assert "EICHERMOT.NS" in syms
    assert "APOLLOHOSP.NS" in syms
    open_row = next(t for t in targets if t["symbol"].upper() == "EICHERMOT.NS")
    assert open_row["kind"] == "open_book"
    assert "fcf" in open_row["unknowns"]


def test_batch_no_llm_deterministic(tmp_path):
    w = empty_wso(symbol="EICHERMOT.NS", laboratory_id="lab")
    w["unknowns"] = ["fcf"]
    doc = run_morning_hypothesis_batch(
        tmp_path,
        laboratory_id="lab",
        llm=None,
        wsos=[w],
        plan={"candidates": [{"symbol": "TCS.NS", "rank": 1}]},
        open_symbols={"EICHERMOT.NS"},
        ist_date="2026-08-10",
    )
    assert doc["llm"] is False
    assert "no LLM" in (doc.get("skip_reason") or "")
    assert any(e.get("unknown") == "fcf" for e in doc.get("evidence_needed") or [])
    loaded = load_batch(tmp_path, laboratory_id="lab", ist_date="2026-08-10")
    assert loaded is not None


def test_batch_llm_done(tmp_path):
    w = empty_wso(symbol="EICHERMOT.NS", laboratory_id="lab")
    w["unknowns"] = ["fcf", "news"]
    llm = _FakeLLM(_JSON)
    doc = run_morning_hypothesis_batch(
        tmp_path,
        laboratory_id="lab",
        llm=llm,
        wsos=[w],
        plan={"candidates": [{"symbol": "APOLLOHOSP.NS", "rank": 1, "why": "alt"}]},
        open_symbols={"EICHERMOT.NS"},
        ist_date="2026-08-10",
        max_passes=3,
    )
    assert doc["status"] == "done"
    assert llm.calls >= 1
    assert any(h.get("statement") for h in doc.get("hypotheses") or [])
    assert any(e.get("asks") for e in doc.get("evidence_needed") or [])


def test_batch_lane_busy(tmp_path):
    w = empty_wso(symbol="EICHERMOT.NS", laboratory_id="lab")
    w["unknowns"] = ["fcf"]
    llm = _FakeLLM(_JSON, busy=True)
    doc = run_morning_hypothesis_batch(
        tmp_path,
        laboratory_id="lab",
        llm=llm,
        wsos=[w],
        open_symbols={"EICHERMOT.NS"},
        ist_date="2026-08-10",
    )
    assert doc["status"] == "deferred_lane_busy"
    assert llm.calls == 0


def test_empty_targets(tmp_path):
    doc = run_morning_hypothesis_batch(
        tmp_path,
        laboratory_id="lab",
        llm=_FakeLLM(_JSON),
        wsos=[],
        plan={"candidates": []},
        ist_date="2026-08-10",
    )
    assert doc["status"] == "empty"


def test_format_section_and_morning_report():
    doc = {
        "status": "done",
        "hypotheses": [
            {
                "symbol": "EICHERMOT.NS",
                "kind": "open_book",
                "statement": "Hold while FCF unknown.",
                "falsifiers": ["FCF stays missing"],
            }
        ],
        "evidence_needed": [
            {
                "symbol": "EICHERMOT.NS",
                "unknown": "fcf",
                "asks": ["screener FCF"],
            }
        ],
    }
    lines = format_morning_hypothesis_section(doc)
    assert any("BRE.4" in x for x in lines)
    assert any("EICHERMOT" in x for x in lines)
    assert any("Evidence needed" in x for x in lines)

    subject, body = format_morning_report(
        plan={
            "as_of": "2026-08-10",
            "phase": "deploy",
            "confidence": "medium",
            "capital": 50000,
            "deploy_fraction": 0.2,
            "summary": "test",
            "candidates": [{"symbol": "EICHERMOT.NS", "rank": 1, "suggested_notional": 1000}],
        },
        morning_hypothesis=doc,
        laboratory_id="lab",
    )
    assert "BRE.4" in body
    assert "EICHERMOT" in body
    assert "Morning investment plan" in subject
