"""MEM.1 + IQ.1 hermetic tests."""

from __future__ import annotations

from atlas.investment.learning_intelligence import (
    build_revision_calibration,
    format_calibration_section,
)
from atlas.investment.memory_distill import (
    collect_episodic,
    format_memory_distill_section,
    load_distill,
    run_memory_distill,
    structure_layers,
)
from atlas.investment.reports import format_evening_report
from atlas.investment.world_state import append_revision, empty_wso, save_wso


def _rev_wso(symbol: str, lab: str, statuses: list[str]):
    w = empty_wso(symbol=symbol, laboratory_id=lab)
    for st in statuses:
        append_revision(w, status=st, reason=f"{st} for {symbol}", llm=True)
    return w


def test_mem1_structure_and_persist(tmp_path):
    lab = "india_equity_learner"
    w1 = _rev_wso("EICHERMOT.NS", lab, ["strengthened", "weakened"])
    w2 = _rev_wso("TCS.NS", lab, ["falsified"])
    save_wso(tmp_path, w1)
    save_wso(tmp_path, w2)
    doc = run_memory_distill(
        tmp_path, laboratory_id=lab, allow_llm=False
    )
    assert doc["episodic_n"] >= 3
    assert doc["advice_only"] is True
    assert any(p.get("rule_stub") for p in doc.get("procedures") or [])
    loaded = load_distill(tmp_path, laboratory_id=lab)
    assert loaded is not None
    lines = format_memory_distill_section(doc)
    assert any("MEM.1" in x for x in lines)


def test_mem1_empty_honest(tmp_path):
    doc = run_memory_distill(tmp_path, laboratory_id="empty", wsos=[], allow_llm=False)
    assert doc["status"] == "empty"
    assert "empty" in (doc.get("skip_reason") or "").lower()


def test_iq1_revision_calibration_flip():
    lab = "lab"
    wsos = [
        _rev_wso("A.NS", lab, ["strengthened", "weakened"]),
        _rev_wso("B.NS", lab, ["strengthened"]),
        _rev_wso("C.NS", lab, ["falsified"]),
        _rev_wso("D.NS", lab, ["weakened"]),
        _rev_wso("E.NS", lab, ["strengthened"]),
    ]
    cal = build_revision_calibration(wsos, min_n=5)
    assert cal["visible"] is True
    assert cal["n"] >= 5
    assert cal["flip_events"] >= 1
    assert cal["flip_rate"] is not None


def test_iq1_hidden_below_sample():
    cal = build_revision_calibration(
        [_rev_wso("X.NS", "lab", ["strengthened"])], min_n=5
    )
    assert cal["visible"] is False
    assert cal["flip_rate"] is None


def test_iq1_format_and_evening():
    curve = {
        "visible": False,
        "sample_note": "Confidence calibration hidden until ≥30 scored exits (have 0).",
    }
    rev = build_revision_calibration(
        [
            _rev_wso("A.NS", "lab", ["strengthened"]),
            _rev_wso("B.NS", "lab", ["weakened"]),
            _rev_wso("C.NS", "lab", ["falsified"]),
            _rev_wso("D.NS", "lab", ["strengthened"]),
            _rev_wso("E.NS", "lab", ["weakened"]),
        ],
        min_n=5,
    )
    lines = format_calibration_section(
        confidence_curve=curve, revision_calibration=rev
    )
    assert any("IQ.1" in x for x in lines)
    assert any("flip_rate" in x for x in lines)

    subject, body = format_evening_report(
        plan={"as_of": "2026-08-10", "phase": "review", "summary": "t"},
        portfolio={
            "portfolio_key": "lab",
            "revision_calibration": rev,
            "memory_distill": {
                "episodic_n": 2,
                "concepts": [{"label": "weakened", "count": 2, "statement": None}],
                "procedures": [
                    {"rule_stub": "Re-check falsifiers", "tip": None}
                ],
                "advice_only": True,
                "status": "done",
            },
            "atlas_iq": {"confidence_calibration": curve, "axes": {}},
        },
        laboratory_id="lab",
    )
    assert "Calibration (IQ.1)" in body
    assert "Memory distill (MEM.1)" in body


def test_collect_episodic_filters():
    w = empty_wso(symbol="Z.NS", laboratory_id="lab")
    append_revision(w, status="unchanged", reason="noop", llm=False)
    append_revision(w, status="strengthened", reason="ok", llm=True)
    rows = collect_episodic(wsos=[w], experiences=[])
    assert len(rows) == 1
    layers = structure_layers(rows)
    assert layers["episodic_n"] == 1
