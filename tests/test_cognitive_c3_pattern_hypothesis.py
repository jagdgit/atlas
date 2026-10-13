"""Cognitive Loop C3 — Atlas must find the question itself.

The operator's requirement is explicit: the CE-vs-PE asymmetry must not be hard-coded.
These tests pin that the detector is dimension-agnostic (relabel the data and the same
pattern surfaces under the new name), that thin groups can never produce a verdict, and
that claims needing option history we do not store come back NOT_EVALUABLE rather than
being tested against a proxy.
"""

from __future__ import annotations

from pathlib import Path

from atlas.investment.cognitive.hypothesis_engine import (
    EVALUABLE,
    NOT_EVALUABLE,
    SCOPE_OPTION_PREMIUM,
    SCOPE_UNDERLIER_DIRECTION,
    build_hypothesis,
    duplicate_of,
    persist_hypothesis,
)
from atlas.investment.cognitive.pattern_detector import (
    STATUS_CANDIDATE,
    STATUS_INSUFFICIENT,
    detect_patterns,
    load_patterns,
    persist_patterns,
)

_LAB = "india_fno_learner"
_DAY = "2026-10-05"
# Two sessions: a group drawn from one day is that day's market, not the feature.
_SESSIONS = ("2026-10-05", "2026-10-06")


def _episode(
    eid: str,
    *,
    option_type: str,
    matched: bool,
    sma_margin: float,
    underlier_pct: float,
    day: str = "2026-10-05",
) -> dict:
    return {
        "experience_id": eid,
        "symbol": f"X26OCT100{option_type}",
        "option_type": option_type,
        "prediction": {
            "expected_direction": "up",
            "er_model": "fno_lab_v1_control_signal.v1",
            "prediction_horizon": "session_flat",
        },
        "features": {
            "sma_margin": sma_margin,
            "underlying_type": "stock",
            "control_action": "buy",
            "signal": "sma_cross_rsi.v1",
        },
        "prediction_error": {
            "status": "computed",
            "direction_match": "matched" if matched else "missed",
        },
        "underlier_movement": {"price_change_pct": underlier_pct},
        "fill": {
            "entry_at": f"{day}T05:48:00+00:00",
            "exit_at": f"{day}T10:11:00+00:00",
        },
    }


def _day_like_today() -> list[dict]:
    """CE 3/4 matched, PE 0/4 matched — the shape of 2026-10-05."""
    rows = []
    for i in range(4):
        rows.append(
            _episode(
                f"ce-{i}",
                option_type="CE",
                matched=i < 3,
                sma_margin=0.02,
                underlier_pct=0.4,
                day=_SESSIONS[i % 2],
            )
        )
    for i in range(4):
        rows.append(
            _episode(
                f"pe-{i}",
                option_type="PE",
                matched=False,
                sma_margin=-0.02,
                underlier_pct=0.3 if i < 1 else -0.5,
                day=_SESSIONS[i % 2],
            )
        )
    return rows


def test_detector_finds_the_split_without_being_told_which_dimension_matters():
    patterns = detect_patterns(
        _day_like_today(), laboratory_id=_LAB, as_of_ist=_DAY
    )
    by_dim = {p["dimension"]: p for p in patterns}
    assert "option_type" in by_dim
    opt = by_dim["option_type"]
    assert opt["status"] == STATUS_CANDIDATE
    assert opt["groups"]["CE"] == {"n": 4, "hits": 3, "hit_rate": 0.75}
    assert opt["groups"]["PE"] == {"n": 4, "hits": 0, "hit_rate": 0.0}


def test_detector_is_blind_to_the_dimension_name():
    """Rename the values and the same structure must still surface.

    If the module contained any CE/PE knowledge, relabelling would hide the pattern.
    """
    rows = _day_like_today()
    for row in rows:
        row["option_type"] = {"CE": "ALPHA", "PE": "BETA"}[row["option_type"]]
    patterns = detect_patterns(rows, laboratory_id=_LAB, as_of_ist=_DAY)
    opt = {p["dimension"]: p for p in patterns}["option_type"]
    assert opt["high_group"] == "ALPHA"
    assert opt["low_group"] == "BETA"
    assert opt["split_delta"] == 0.75


def test_a_separable_split_outranks_an_equally_strong_confounded_one():
    """The one question per cycle should be one this sample can actually separate."""
    rows = _day_like_today()
    early = {"ce-0", "ce-1", "ce-2", "pe-0"}
    for row in rows:
        day = row["fill"]["entry_at"][:10]
        start, end = ("04", "06") if row["experience_id"] in early else ("08", "10")
        row["fill"]["entry_at"] = f"{day}T{start}:00:00+00:00"
        row["fill"]["exit_at"] = f"{day}T{end}:00:00+00:00"  # same holding time
    patterns = detect_patterns(rows, laboratory_id=_LAB, as_of_ist=_DAY)
    candidates = [p for p in patterns if p["status"] == STATUS_CANDIDATE]
    first = candidates[0]
    assert first["dimension"] == "entry_time_bucket"
    assert not first["confounded_with"]
    opt = {p["dimension"]: p for p in patterns}["option_type"]
    assert opt["p_value"] == first["p_value"]
    assert opt["confounded_with"]
    assert patterns.index(first) < patterns.index(opt)


def test_post_hoc_dimensions_are_never_candidates():
    from atlas.investment.cognitive.pattern_detector import STATUS_POST_HOC

    patterns = detect_patterns(_day_like_today(), laboratory_id=_LAB, as_of_ist=_DAY)
    under = {p["dimension"]: p for p in patterns}.get("underlier_direction")
    assert under is not None and under["status"] == STATUS_POST_HOC
    hypo = build_hypothesis(under, laboratory_id=_LAB)
    assert hypo["evaluable"] is False


def test_noise_split_does_not_pass_the_screen():
    rows = _day_like_today()
    # CE 2/4 vs PE 1/4: chance alone does this often.
    for row, matched in zip(rows, [True, True, False, False, True, False, False, False]):
        row["prediction_error"]["direction_match"] = "matched" if matched else "missed"
    patterns = detect_patterns(rows, laboratory_id=_LAB, as_of_ist=_DAY)
    assert "option_type" not in {p["dimension"] for p in patterns if p["status"] == STATUS_CANDIDATE}


def test_perfectly_correlated_dimensions_are_reported_as_confounded():
    patterns = detect_patterns(_day_like_today(), laboratory_id=_LAB, as_of_ist=_DAY)
    opt = {p["dimension"]: p for p in patterns}["option_type"]
    # CE is always bought on a positive control margin in this sample.
    assert "sma_margin_sign" in opt["confounded_with"]
    assert "Indistinguishable from" in opt["honesty"]


def test_thin_groups_record_the_question_but_block_a_verdict():
    rows = _day_like_today()[:3]  # 2 CE matched + 1 CE missed → PE absent
    rows.append(
        _episode("pe-0", option_type="PE", matched=False, sma_margin=-0.02, underlier_pct=-0.5)
    )
    patterns = detect_patterns(rows, laboratory_id=_LAB, as_of_ist=_DAY)
    opt = {p["dimension"]: p for p in patterns}["option_type"]
    assert opt["status"] == STATUS_INSUFFICIENT
    assert "PE" in opt["thin_groups"]

    hypo = build_hypothesis(opt, laboratory_id=_LAB)
    specs = {s["claim_scope"]: s for s in hypo["experiment_specs"]}
    assert specs[SCOPE_UNDERLIER_DIRECTION]["status"] == NOT_EVALUABLE
    assert specs[SCOPE_UNDERLIER_DIRECTION]["not_evaluable_reason"] == "insufficient_sample"
    assert hypo["evaluable"] is False


def test_single_group_is_not_a_contrast():
    rows = _day_like_today()
    for row in rows:
        row["option_type"] = "CE"
    patterns = detect_patterns(rows, laboratory_id=_LAB, as_of_ist=_DAY)
    assert "option_type" not in {p["dimension"] for p in patterns}


def test_option_premium_claim_is_not_evaluable_and_gets_no_proxy():
    patterns = detect_patterns(_day_like_today(), laboratory_id=_LAB, as_of_ist=_DAY)
    opt = {p["dimension"]: p for p in patterns}["option_type"]
    hypo = build_hypothesis(opt, laboratory_id=_LAB)
    specs = {s["claim_scope"]: s for s in hypo["experiment_specs"]}

    premium = specs[SCOPE_OPTION_PREMIUM]
    assert premium["status"] == NOT_EVALUABLE
    assert premium["not_evaluable_reason"] == "no_option_intraday_history"

    # The narrower, honestly testable restatement is separate and evaluable.
    restated = specs[SCOPE_UNDERLIER_DIRECTION]
    assert restated["status"] == EVALUABLE
    assert restated["data_requirement"] == "daily_underlier_bars"
    assert restated["baseline_required"] is True
    assert restated["mutates_strategy"] is False
    assert restated["promotion"] is None


def test_hypothesis_is_a_question_with_a_falsifier_not_a_lesson():
    patterns = detect_patterns(_day_like_today(), laboratory_id=_LAB, as_of_ist=_DAY)
    hypo = build_hypothesis(patterns[0], laboratory_id=_LAB)
    assert hypo["falsifier"]
    assert "Rejected if" in hypo["falsifier"]
    assert hypo["confidence"] == "very_low"
    assert hypo["pattern_status"] == STATUS_CANDIDATE
    # Never asserts a finding.
    assert "LESSON" not in str(hypo)
    assert "may be" in hypo["statement"] or "may be" in hypo["deterministic_statement"]


def test_absent_llm_still_produces_a_statement():
    patterns = detect_patterns(_day_like_today(), laboratory_id=_LAB, as_of_ist=_DAY)
    hypo = build_hypothesis(patterns[0], laboratory_id=_LAB, llm=None)
    assert hypo["statement_source"] == "deterministic"
    assert hypo["statement"] == hypo["deterministic_statement"]


def test_silent_llm_does_not_block_the_pipeline():
    class Broken:
        def complete(self, prompt):
            raise RuntimeError("lane busy")

    patterns = detect_patterns(_day_like_today(), laboratory_id=_LAB, as_of_ist=_DAY)
    hypo = build_hypothesis(patterns[0], laboratory_id=_LAB, llm=Broken())
    assert hypo["statement_source"] == "deterministic"


def test_persist_round_trip_and_duplicate_detection(tmp_path: Path):
    patterns = detect_patterns(_day_like_today(), laboratory_id=_LAB, as_of_ist=_DAY)
    assert persist_patterns(
        tmp_path, patterns, laboratory_id=_LAB, as_of_ist=_DAY
    )["ok"]
    assert len(load_patterns(tmp_path, laboratory_id=_LAB, as_of_ist=_DAY)) == len(patterns)

    opt = {p["dimension"]: p for p in patterns}["option_type"]
    assert duplicate_of(tmp_path, laboratory_id=_LAB, dimension="option_type") is None

    hypo = build_hypothesis(opt, laboratory_id=_LAB)
    out = persist_hypothesis(tmp_path, hypo, laboratory_id=_LAB)
    assert out["ok"] and out["hypothesis_id"]
    assert out["hypothesis"]["status"] == "open"
    # Asking the same question twice is not a new question.
    assert duplicate_of(tmp_path, laboratory_id=_LAB, dimension="option_type") == out[
        "hypothesis_id"
    ]


def test_a_group_from_one_session_is_that_day_not_the_feature():
    rows = _day_like_today()
    for row in rows:
        if row["option_type"] == "PE":
            row["fill"]["entry_at"] = "2026-10-06T05:48:00+00:00"
    opt = {p["dimension"]: p for p in detect_patterns(rows, laboratory_id=_LAB, as_of_ist=_DAY)}["option_type"]
    assert opt["status"] == STATUS_INSUFFICIENT
    assert opt["single_session_groups"] == ["PE"]
