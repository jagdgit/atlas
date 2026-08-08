"""LI.5b — skill-axis reports, hypotheses, narratives, readiness gauge."""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.investment.decision_attribution import format_attribution_section
from atlas.investment.decision_packets import build_packet
from atlas.investment.hypothesis_learning import (
    VERDICT_MIN_LINKS,
    create_hypothesis,
    list_hypotheses,
    record_verdict,
)
from atlas.investment.laboratory import (
    DEFAULT_INTRADAY_LAB,
    DEFAULT_SWING_LAB,
    LaboratoryContaminationError,
)
from atlas.investment.learning_intelligence import (
    VERSION,
    build_atlas_iq_proxies,
    build_learning_intelligence_report,
    failure_cause_histogram,
    format_atlas_iq_section,
    format_evolution_narrative,
)
from atlas.investment.ml_export import build_export_quality_report
from atlas.investment.reports import format_learned_today_section


def test_skill_axis_report_and_histogram(tmp_path: Path):
    attrs = [
        {"payload": {"failure_cause": "evidence_failure"}},
        {"payload": {"extra": {"failure_cause": "evidence_failure"}}},
        {"payload": {"failure_cause": "execution_failure"}},
    ]
    snap = build_atlas_iq_proxies(
        tmp_path,
        laboratory_id=DEFAULT_SWING_LAB,
        packets=[{"unknowns": []}] * 6,
        attributions=attrs,
        process_score=7.0,
        done_revisits=2,
        observation_count=5,
    )
    assert snap["version"] == VERSION
    assert "axis_report" in snap
    assert snap["axis_report"]["research"]["note"]
    hist = failure_cause_histogram(attrs)
    assert hist["evidence_failure"] == 2
    assert hist["execution_failure"] == 1
    assert snap["failure_cause_histogram"]["evidence_failure"] == 2
    text = "\n".join(format_atlas_iq_section(snap))
    assert "LI.5b" in text
    assert "Failure causes:" in text


def test_evolution_narrative():
    lines = format_evolution_narrative(
        [
            {
                "at": "2026-08-08T01:00:00Z",
                "axis": "learning",
                "from": 10,
                "to": 40,
                "reason": "more revisits",
            }
        ]
    )
    assert any("learning" in ln and "10→40" in ln for ln in lines)


def test_hypothesis_verdict_gated(tmp_path: Path):
    out = create_hypothesis(
        tmp_path,
        statement="Lower PE stocks outperform during rate cuts",
        domain_tags=["valuation", "macro"],
        laboratory_id=DEFAULT_SWING_LAB,
        transfer_class="world",
    )
    hid = out["hypothesis"]["hypothesis_id"]
    # Thin evidence → inconclusive
    v = record_verdict(
        tmp_path,
        hypothesis_id=hid,
        verdict="supported",
        laboratory_id=DEFAULT_SWING_LAB,
    )
    assert v["hypothesis"]["status"] == "inconclusive"
    assert v["hypothesis"]["verdict"]["requested"] == "supported"

    # Enough links → accepted
    linked = create_hypothesis(
        tmp_path,
        statement="High ROE compounds better in sideways regimes",
        laboratory_id=DEFAULT_SWING_LAB,
        linked_decision_ids=[f"d{i}" for i in range(VERDICT_MIN_LINKS)],
    )
    v2 = record_verdict(
        tmp_path,
        hypothesis_id=linked["hypothesis"]["hypothesis_id"],
        verdict="partially_supported",
        laboratory_id=DEFAULT_SWING_LAB,
    )
    assert v2["hypothesis"]["status"] == "partially_supported"

    swing = list_hypotheses(tmp_path, laboratory_id=DEFAULT_SWING_LAB)
    assert len(swing) >= 2

    # Strategy hyp cannot be world-scoped
    with pytest.raises(ValueError):
        create_hypothesis(
            tmp_path,
            statement="Intraday SMA only",
            transfer_class="strategy",
            laboratory_id=None,
        )


def test_hypothesis_lab_hermetic_verdict(tmp_path: Path):
    out = create_hypothesis(
        tmp_path,
        statement="Swing lab only belief",
        laboratory_id=DEFAULT_SWING_LAB,
        transfer_class="strategy",
        linked_decision_ids=["a", "b", "c"],
    )
    with pytest.raises(LaboratoryContaminationError):
        record_verdict(
            tmp_path,
            hypothesis_id=out["hypothesis"]["hypothesis_id"],
            verdict="supported",
            laboratory_id=DEFAULT_INTRADAY_LAB,
        )


def test_readiness_gauge_and_report(tmp_path: Path):
    pkts = [
        build_packet(
            action="buy",
            symbol="X.NS",
            portfolio_key=DEFAULT_SWING_LAB,
            strategy_tag="sma_cross_rsi",
            evidence_refs=["e1"],
            market_snapshot={"regime_tags": ["sideways"]},
            hypothesis_id="hyp-1",
            reasons_for=["x"],
        )
    ]
    attrs = [
        {
            "decision_id": pkts[0]["decision_id"],
            "trigger": "exit",
            "portfolio_key": DEFAULT_SWING_LAB,
            "laboratory_id": DEFAULT_SWING_LAB,
            "payload": {"failure_cause": "evidence_failure", "pnl": -1},
            "grades": {"pnl": -1},
        }
    ]
    q = build_export_quality_report(
        packets=pkts, attributions=attrs, laboratory_id=DEFAULT_SWING_LAB
    )
    assert "readiness" in q
    assert q["readiness"]["live_nn_trading"] is False
    assert q["li_hypothesis_ids_present"] == 1
    # Single closed exit → not trusted sample → blocking closed_sample
    assert "closed_sample" in q["readiness"]["blocking"]

    report = build_learning_intelligence_report(
        tmp_path,
        laboratory_id=DEFAULT_SWING_LAB,
        packets=pkts,
        attributions=attrs,
        quality=q,
    )
    assert report["version"].startswith("li.5b")
    assert report["readiness"]["live_nn_trading"] is False
    assert report["evolution_narrative"]


def test_mail_polish_root_cause_and_iq():
    lines = format_attribution_section(
        [
            {
                "symbol": "CIPLA.NS",
                "trigger": "exit",
                "grades": {
                    "decision_quality": "B",
                    "market_quality": "C",
                    "may_update_priors": True,
                },
                "payload": {"failure_cause": "evidence_failure"},
            }
        ]
    )
    assert any("Root cause: evidence_failure" in ln for ln in lines)

    evening = format_learned_today_section(
        plan={"phase": "learning"},
        portfolio={
            "atlas_iq": {
                "laboratory_id": DEFAULT_SWING_LAB,
                "overall": 55,
                "axes": {"research": 40, "learning": 50},
                "axis_report": {
                    "research": {"score": 40, "note": "Fundamentals", "visible": True}
                },
                "failure_cause_histogram": {"evidence_failure": 2},
                "counts": {"packets": 3, "attributions": 2, "observations": 1, "revisits_done": 1},
            },
            "evolution_narrative": ["2026-08-08: learning 10→40 — more revisits"],
            "readiness": {"ready": False, "blocking": ["closed_sample"], "live_nn_trading": False},
        },
    )
    text = "\n".join(evening)
    assert "Atlas IQ skill axes" in text
    assert "Evolution memory" in text
    assert "Dataset readiness: NOT READY" in text
    assert "live_nn=False" in text
