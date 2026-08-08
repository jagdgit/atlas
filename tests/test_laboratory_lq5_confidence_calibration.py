"""LQ.5 — stated confidence vs outcome calibration curves (hide below sample)."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.laboratory import DEFAULT_INTRADAY_LAB, DEFAULT_SWING_LAB
from atlas.investment.learning_intelligence import (
    CALIB_MIN_CURVE_N,
    build_atlas_iq_proxies,
    build_confidence_calibration_curve,
    format_atlas_iq_section,
)


def _pkt(did: str, overall: float, lab: str = DEFAULT_SWING_LAB) -> dict:
    return {
        "decision_id": did,
        "laboratory_id": lab,
        "portfolio_key": lab,
        "confidence_breakdown": {"overall": overall},
        "action": "buy",
    }


def _attr(did: str, thesis: str, lab: str = DEFAULT_SWING_LAB) -> dict:
    return {
        "decision_id": did,
        "trigger": "exit",
        "laboratory_id": lab,
        "portfolio_key": lab,
        "grades": {"thesis_correct": thesis, "pnl": 1.0 if thesis == "yes" else -1.0},
        "payload": {},
    }


def test_curve_hidden_below_sample():
    packets = [_pkt(f"d{i}", 0.7) for i in range(10)]
    attrs = [_attr(f"d{i}", "yes" if i % 2 == 0 else "no") for i in range(10)]
    curve = build_confidence_calibration_curve(packets, attrs, min_curve_n=30)
    assert curve["visible"] is False
    assert curve["n"] == 10
    assert curve["bins"] == []
    assert "hidden until" in (curve.get("sample_note") or "").lower()


def test_curve_bins_and_ece():
    packets = []
    attrs = []
    # Low confidence mostly misses; high confidence mostly hits
    for i in range(20):
        packets.append(_pkt(f"lo{i}", 0.15))
        attrs.append(_attr(f"lo{i}", "no" if i < 16 else "yes"))
    for i in range(20):
        packets.append(_pkt(f"hi{i}", 0.85))
        attrs.append(_attr(f"hi{i}", "yes" if i < 16 else "no"))
    curve = build_confidence_calibration_curve(
        packets, attrs, min_curve_n=30, min_bin_n=5
    )
    assert curve["visible"] is True
    assert curve["n"] == 40
    assert curve["ece"] is not None
    visible = [b for b in curve["bins"] if b.get("visible")]
    assert len(visible) >= 2
    lo = next(b for b in curve["bins"] if b["band"].startswith("0.0"))
    hi = next(b for b in curve["bins"] if b["band"].startswith("0.8"))
    assert lo["hit_rate"] is not None and lo["hit_rate"] < 0.5
    assert hi["hit_rate"] is not None and hi["hit_rate"] > 0.5


def test_partial_unknown_excluded_and_confidence_immutable():
    packets = [_pkt(f"d{i}", 0.55) for i in range(35)]
    attrs = [_attr(f"d{i}", "partial") for i in range(20)]
    attrs += [_attr(f"d{i}", "yes") for i in range(20, 35)]
    curve = build_confidence_calibration_curve(packets, attrs, min_curve_n=10)
    # only 15 yes/no scored (20-34)
    assert curve["n"] == 15
    # packet freeze unchanged
    assert packets[0]["confidence_breakdown"]["overall"] == 0.55


def test_lab_isolation_no_pool():
    packets = [_pkt(f"s{i}", 0.7, DEFAULT_SWING_LAB) for i in range(35)]
    packets += [_pkt(f"i{i}", 0.7, DEFAULT_INTRADAY_LAB) for i in range(35)]
    attrs = [_attr(f"s{i}", "yes", DEFAULT_SWING_LAB) for i in range(35)]
    attrs += [_attr(f"i{i}", "no", DEFAULT_INTRADAY_LAB) for i in range(35)]
    # Caller scopes lists per lab (hermeticity) — curve must not mix if only swing passed
    swing = build_confidence_calibration_curve(
        [p for p in packets if p["laboratory_id"] == DEFAULT_SWING_LAB],
        [a for a in attrs if a["laboratory_id"] == DEFAULT_SWING_LAB],
        min_curve_n=30,
    )
    assert swing["visible"] is True
    assert swing["n"] == 35
    # all yes → high hit rate in mid/high bands
    vis = [b for b in swing["bins"] if b.get("visible")]
    assert all((b.get("hit_rate") or 0) == 1.0 for b in vis)


def test_iq_snapshot_includes_curve(tmp_path: Path):
    packets = [_pkt(f"d{i}", 0.75) for i in range(CALIB_MIN_CURVE_N)]
    attrs = [
        _attr(f"d{i}", "yes" if i < 25 else "no") for i in range(CALIB_MIN_CURVE_N)
    ]
    snap = build_atlas_iq_proxies(
        tmp_path,
        laboratory_id=DEFAULT_SWING_LAB,
        packets=packets,
        attributions=attrs,
        process_score=7.0,
        done_revisits=5,
        observation_count=8,
    )
    calib = snap.get("confidence_calibration") or {}
    assert calib.get("visible") is True
    assert calib.get("ece") is not None
    text = "\n".join(format_atlas_iq_section(snap))
    assert "Confidence calibration (LQ.5)" in text
    assert "ECE=" in text

    thin = build_atlas_iq_proxies(
        tmp_path,
        laboratory_id=DEFAULT_SWING_LAB,
        packets=packets[:5],
        attributions=attrs[:5],
        process_score=7.0,
    )
    assert thin["confidence_calibration"]["visible"] is False
    thin_text = "\n".join(format_atlas_iq_section(thin))
    assert "hidden until" in thin_text.lower() or "calibration" in thin_text.lower()
