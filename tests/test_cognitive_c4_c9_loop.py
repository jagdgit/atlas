"""Cognitive Loop C4–C9 — admission, experiment, validation, belief, next question.

The milestone under test: from closed episodes alone, Atlas identifies a pattern,
frames a testable hypothesis, decides whether it is worth compute, runs it through the
existing FEL runner on persisted data, records SUPPORTED / REJECTED / INCONCLUSIVE /
NOT_EVALUABLE, and produces a learning candidate — without live trading behaviour
changing and without the hypothesis being named by the operator.

The negative assertions matter most here: one supported pass must not become a
validated learning, and no result may change strategy or sizing.
"""

from __future__ import annotations

import json
from pathlib import Path

from atlas.investment.cognitive.admission import (
    ADMITTED,
    REASON_BARS_NOT_REPLAYABLE,
    REASON_DUPLICATE,
    REASON_INSUFFICIENT_SAMPLE,
    REASON_NO_FALSIFIER,
    REFUSED,
    admit_hypothesis,
)
from atlas.investment.cognitive.beliefs import (
    STATUS_ACCEPTED,
    STATUS_PROPOSED,
    accept_revision,
    behavioural_delta,
    belief_context_for_decision,
    belief_id_for,
    propose_revision,
)
from atlas.investment.cognitive.experiment_bridge import (
    RESULT_INCONCLUSIVE,
    RESULT_NOT_EVALUABLE,
    RESULT_REJECTED,
    RESULT_SUPPORTED,
    enqueue_hypothesis_test,
    evaluate_hypothesis,
)
from atlas.investment.cognitive.hypothesis_engine import build_hypothesis
from atlas.investment.cognitive.loop import format_cognitive_loop_section, run_cycle
from atlas.investment.cognitive.pattern_detector import detect_patterns
from atlas.investment.cognitive.validator import (
    OUTCOME_CANDIDATE,
    OUTCOME_FALSIFIED,
    OUTCOME_NO_WRITE,
    apply_to_ladder,
    build_learning_candidate,
    ladder_counts,
    persist_candidate,
)

_LAB = "india_fno_learner"
_DAY = "2026-10-05"
_SYMS = ["AAA", "BBB", "CCC", "DDD"]


def _bars(tmp_path: Path, symbol: str, *, close_above_open: bool) -> None:
    """Minimal durable daily OHLCV that passes the P2 replayability gate."""
    root = tmp_path / "market" / "bars"
    root.mkdir(parents=True, exist_ok=True)
    bars = []
    for i in range(1, 29):
        day = f"2026-09-{i:02d}" if i <= 30 else None
        o = 100.0
        c = 101.0 if close_above_open else 99.0
        bars.append(
            {"date": day, "open": o, "high": 102.0, "low": 98.0, "close": c, "volume": 1000}
        )
    bars.append(
        {
            "date": "2026-10-05",
            "open": 100.0,
            "high": 102.0,
            "low": 98.0,
            "close": 101.0 if close_above_open else 99.0,
            "volume": 1000,
        }
    )
    (root / f"{symbol}.NS.json").write_text(json.dumps({"bars": bars}), encoding="utf-8")


def _episode(
    eid: str,
    *,
    underlying: str,
    option_type: str,
    matched: bool,
    underlier_up: bool,
    day: str = _DAY,
) -> dict:
    return {
        "experience_id": eid,
        "symbol": f"{underlying}26OCT100{option_type}",
        "underlying": underlying,
        "option_type": option_type,
        "prediction": {"expected_direction": "up", "er_model": "control.v1"},
        "features": {
            "option_type": option_type,
            "sma_margin": 0.02 if option_type == "CE" else -0.02,
            "underlying_type": "stock",
        },
        "prediction_error": {
            "status": "computed",
            "direction_match": "matched" if matched else "missed",
        },
        "underlier_movement": {
            "price_change_pct": 0.5 if underlier_up else -0.5,
            "session": {
                "open": 100.0,
                "close": 101.0 if underlier_up else 99.0,
            },
        },
        "fill": {
            "entry_at": f"{day}T05:48:00+00:00",
            "exit_at": f"{day}T10:11:00+00:00",
        },
    }


def _episodes() -> list[dict]:
    """CE 3/4 matched on premium, PE 0/4 — and underliers that make the restated
    claim land cleanly (every CE underlier up, every PE underlier up too, so the
    put's directional call was wrong every time)."""
    rows = []
    for i, sym in enumerate(_SYMS):
        rows.append(
            _episode(
                f"ce-{i}",
                underlying=sym,
                option_type="CE",
                matched=i < 3,
                underlier_up=True,
                day=("2026-10-02", _DAY)[i % 2],
            )
        )
    for i, sym in enumerate(_SYMS):
        rows.append(
            _episode(
                f"pe-{i}",
                underlying=sym,
                option_type="PE",
                matched=False,
                underlier_up=True,
                day=("2026-10-02", _DAY)[i % 2],
            )
        )
    return rows


_LATER = "2026-10-06"


def _fresh_episodes(n_each: int = 5) -> list[dict]:
    """Closed after the question was asked — the only sample allowed to answer it."""
    rows = []
    for i in range(n_each):
        sym = _SYMS[i % len(_SYMS)]
        for right in ("CE", "PE"):
            day = (_LATER, "2026-10-07")[i % 2]
            row = _episode(f"fresh-{right}-{i}", underlying=sym, option_type=right,
                           matched=right == "CE", underlier_up=True, day=day)
            row["as_of_ist"] = day
            rows.append(row)
    return rows


def _hypothesis(rows=None):
    patterns = detect_patterns(rows or _episodes(), laboratory_id=_LAB, as_of_ist=_DAY)
    opt = {p["dimension"]: p for p in patterns}["option_type"]
    return build_hypothesis(opt, laboratory_id=_LAB)


def _with_bars(tmp_path: Path) -> Path:
    for sym in _SYMS:
        _bars(tmp_path, sym, close_above_open=True)
    return tmp_path


# --- C4 admission ---------------------------------------------------------


def test_admission_requires_a_falsifier():
    hypo = _hypothesis()
    hypo.pop("falsifier")
    decision = admit_hypothesis(hypo, laboratory_id=_LAB)
    assert decision["status"] == REFUSED
    assert decision["reason"] == REASON_NO_FALSIFIER


def test_admission_refuses_when_bars_are_not_replayable(tmp_path: Path):
    decision = admit_hypothesis(
        _hypothesis(), data_dir=tmp_path, laboratory_id=_LAB, underlying_symbols=_SYMS
    )
    assert decision["status"] == REFUSED
    assert decision["reason"] == REASON_BARS_NOT_REPLAYABLE


def test_admission_refuses_a_thin_sample():
    rows = _episodes()[:5]  # 4 CE + 1 PE
    decision = admit_hypothesis(_hypothesis(rows), laboratory_id=_LAB)
    assert decision["status"] == REFUSED
    assert decision["reason"] == REASON_INSUFFICIENT_SAMPLE


def test_admission_admits_a_testable_question_with_replayable_bars(tmp_path: Path):
    _with_bars(tmp_path)
    decision = admit_hypothesis(
        _hypothesis(), data_dir=tmp_path, laboratory_id=_LAB, underlying_symbols=_SYMS
    )
    assert decision["status"] == ADMITTED
    assert decision["experiment_spec"]["evaluable"] is True
    # Confounds travel with the admission — the question is admitted, not the cause.
    assert "sma_margin_sign" in decision["confounded_with"]


def test_admission_refuses_an_already_asked_question(tmp_path: Path):
    from atlas.investment.cognitive.hypothesis_engine import persist_hypothesis

    _with_bars(tmp_path)
    hypo = _hypothesis()
    persist_hypothesis(tmp_path, hypo, laboratory_id=_LAB)
    decision = admit_hypothesis(
        hypo, data_dir=tmp_path, laboratory_id=_LAB, underlying_symbols=_SYMS
    )
    assert decision["status"] == REFUSED
    assert decision["reason"] == REASON_DUPLICATE


def test_kernel_task_is_p3_and_cannot_outrank_operational_work():
    """P3 is the contract: _select drops P3 whenever any P0/P1/P2 work is due."""
    from atlas.agent_kernel.kernel import AgentKernel

    source = Path("atlas/agent_kernel/kernel.py").read_text(encoding="utf-8")
    assert "_cognitive_payloads" in source
    block = source.split("def _cognitive_payloads")[1].split("def _upsert")[0]
    assert '"priority_class": "P3"' in block
    assert '"domain": "cognitive"' in block
    assert AgentKernel is not None


# --- C5 experiment --------------------------------------------------------


def test_enqueue_refuses_a_spec_without_a_baseline(tmp_path: Path):
    spec = {"evaluable": True, "baseline_required": False}
    out = enqueue_hypothesis_test(
        tmp_path, laboratory_id=_LAB, hypothesis_id="h1", experiment_spec=spec
    )
    assert out["ok"] is False
    assert out["reason"] == "baseline_not_declared"


def test_enqueue_refuses_a_not_evaluable_spec(tmp_path: Path):
    spec = {"evaluable": False, "not_evaluable_reason": "no_option_intraday_history"}
    out = enqueue_hypothesis_test(
        tmp_path, laboratory_id=_LAB, hypothesis_id="h1", experiment_spec=spec
    )
    assert out["ok"] is False
    assert out["result"] == RESULT_NOT_EVALUABLE


def test_experiment_refuses_to_score_without_replayable_bars(tmp_path: Path):
    spec = [s for s in _hypothesis()["experiment_specs"] if s.get("evaluable")][0]
    res = evaluate_hypothesis(
        tmp_path,
        laboratory_id=_LAB,
        hypothesis_id="h1",
        experiment_spec=spec,
        episodes=_episodes() + _fresh_episodes(),
    )
    assert res["result"] == RESULT_NOT_EVALUABLE
    assert res["reason"] == "bars_not_replayable"


def test_experiment_never_answers_a_question_with_its_own_discovery_sample(tmp_path: Path):
    _with_bars(tmp_path)
    spec = [s for s in _hypothesis()["experiment_specs"] if s.get("evaluable")][0]
    res = evaluate_hypothesis(
        tmp_path, laboratory_id=_LAB, hypothesis_id="h1", experiment_spec=spec, episodes=_episodes()
    )
    assert res["result"] == RESULT_NOT_EVALUABLE
    assert res["reason"] == "awaiting_fresh_sample"


def test_thin_fresh_sample_waits_instead_of_judging(tmp_path: Path):
    _with_bars(tmp_path)
    spec = [s for s in _hypothesis()["experiment_specs"] if s.get("evaluable")][0]
    res = evaluate_hypothesis(
        tmp_path, laboratory_id=_LAB, hypothesis_id="h1", experiment_spec=spec,
        episodes=_episodes() + _fresh_episodes(n_each=3),
    )
    assert res["reason"] == "awaiting_fresh_sample"
    assert "CE=3" in res["detail"]


def test_fresh_reversal_rejects(tmp_path: Path):
    _with_bars(tmp_path)
    spec = [s for s in _hypothesis()["experiment_specs"] if s.get("evaluable")][0]
    fresh = _fresh_episodes()
    for row in fresh:
        row["underlier_movement"]["session"]["close"] = 99.0  # every underlier fell: puts right
    res = evaluate_hypothesis(
        tmp_path, laboratory_id=_LAB, hypothesis_id="h1", experiment_spec=spec,
        episodes=_episodes() + fresh,
    )
    assert res["result"] == RESULT_REJECTED
    assert res["gap"] < 0


def test_post_hoc_spec_is_closed_not_retried(tmp_path: Path):
    _with_bars(tmp_path)
    spec = {"evaluable": True, "dimension": "underlier_direction", "groups": ["up", "down"],
            "baseline_required": True}
    res = evaluate_hypothesis(
        tmp_path, laboratory_id=_LAB, hypothesis_id="h1", experiment_spec=spec,
        episodes=_episodes() + _fresh_episodes(),
    )
    assert res["reason"] == "post_hoc_dimension"


def test_experiment_translates_premium_direction_into_underlier_direction(tmp_path: Path):
    """A put's premium rises when the underlier falls — contract mechanics.

    Every underlier here closed up, so each call's directional call landed and each
    put's did not. That must come out as a clean gap, not a coin flip.
    """
    _with_bars(tmp_path)
    spec = [s for s in _hypothesis()["experiment_specs"] if s.get("evaluable")][0]
    res = evaluate_hypothesis(
        tmp_path,
        laboratory_id=_LAB,
        hypothesis_id="h1",
        experiment_spec=spec,
        episodes=_episodes() + _fresh_episodes(),
    )
    assert res["group_rates"]["CE"] == 1.0
    assert res["group_rates"]["PE"] == 0.0
    assert res["result"] == RESULT_SUPPORTED
    assert res["p_value"] < 0.05
    assert res["baseline"]["n"] == 10  # only the fresh episodes
    assert res["mutates_strategy"] is False
    assert res["promotion"] is None
    assert res["live_orders"] is False
    assert res["replication"]["validated"] is False


# --- C6 validation ladder -------------------------------------------------


def test_one_supported_pass_is_a_candidate_not_a_validated_learning(tmp_path: Path):
    hypo = _hypothesis()
    result = {
        "hypothesis_id": "h1",
        "experiment_id": "HYP-h1",
        "result": RESULT_SUPPORTED,
        "dimension": "option_type",
        "gap": 1.0,
        "min_effect": 0.5,
    }
    cand = build_learning_candidate(result, hypothesis=hypo, laboratory_id=_LAB)
    assert cand["ladder_outcome"] == OUTCOME_CANDIDATE
    assert cand["level"] == "L4"
    assert cand["validated"] is False
    assert cand["passes_done"] == 1
    assert cand["passes_required"] == 2

    out = apply_to_ladder(tmp_path, cand, laboratory_id=_LAB)
    assert out["promoted"] is True
    assert out["subsequent_test_status"] == "OPEN"


def test_rejected_result_is_kept_as_knowledge():
    cand = build_learning_candidate(
        {
            "hypothesis_id": "h1",
            "experiment_id": "HYP-h1",
            "result": RESULT_REJECTED,
            "dimension": "option_type",
        },
        hypothesis=_hypothesis(),
        laboratory_id=_LAB,
    )
    assert cand["ladder_outcome"] == OUTCOME_FALSIFIED
    assert cand["writes_belief"] is False
    assert "kept" in cand["honesty"]
    assert "real result" in cand["honesty"]


def test_inconclusive_and_not_evaluable_write_no_belief(tmp_path: Path):
    for result in (RESULT_INCONCLUSIVE, RESULT_NOT_EVALUABLE):
        cand = build_learning_candidate(
            {
                "hypothesis_id": f"h-{result}",
                "experiment_id": "HYP-x",
                "result": result,
                "dimension": "option_type",
            },
            hypothesis=_hypothesis(),
            laboratory_id=_LAB,
        )
        assert cand["ladder_outcome"] == OUTCOME_NO_WRITE
        assert cand["writes_belief"] is False
        assert apply_to_ladder(tmp_path, cand, laboratory_id=_LAB)["promoted"] is False
        assert propose_revision(tmp_path, cand, laboratory_id=_LAB)["proposed"] is False


def test_untested_claims_are_named_on_the_candidate():
    cand = build_learning_candidate(
        {
            "hypothesis_id": "h1",
            "experiment_id": "HYP-h1",
            "result": RESULT_SUPPORTED,
            "dimension": "option_type",
        },
        hypothesis=_hypothesis(),
        laboratory_id=_LAB,
    )
    assert "option_premium" in cand["untested_claims"]
    assert "sma_margin_sign" in cand["confounded_with"]


def test_ladder_counts_separate_questions_from_validated_learnings(tmp_path: Path):
    for result in (RESULT_SUPPORTED, RESULT_INCONCLUSIVE, RESULT_REJECTED):
        cand = build_learning_candidate(
            {
                "hypothesis_id": f"h-{result}",
                "experiment_id": "HYP-x",
                "result": result,
                "dimension": "option_type",
            },
            hypothesis=_hypothesis(),
            laboratory_id=_LAB,
        )
        persist_candidate(tmp_path, cand)
    counts = ladder_counts(tmp_path, laboratory_id=_LAB)
    assert counts["candidates"] == 3
    assert counts["supported"] == 1
    assert counts["rejected"] == 1
    assert counts["inconclusive"] == 1
    assert counts["validated"] == 0
    assert counts["belief_writes"] == 1


# --- C7 / C8 belief + behavioural proof -----------------------------------


def test_belief_revision_is_versioned_and_proposed_not_accepted(tmp_path: Path):
    cand = build_learning_candidate(
        {
            "hypothesis_id": "h1",
            "experiment_id": "HYP-h1",
            "result": RESULT_SUPPORTED,
            "dimension": "option_type",
            "gap": 1.0,
        },
        hypothesis=_hypothesis(),
        laboratory_id=_LAB,
    )
    out = propose_revision(tmp_path, cand, laboratory_id=_LAB)
    belief = out["belief"]
    assert out["proposed"] is True
    assert belief["status"] == STATUS_PROPOSED
    assert belief["version_n"] == 1
    assert belief["previous_version"] is None
    assert belief["evidence"]["experiment_ids"] == ["HYP-h1"]
    assert belief["affects"] == "decision_context_only"
    for forbidden in ("order_authority", "position_sizing", "capital_allocation"):
        assert forbidden in belief["does_not_affect"]

    # Second proposal chains a version rather than overwriting the first.
    again = propose_revision(tmp_path, cand, laboratory_id=_LAB)
    assert again["belief"]["version_n"] == 2
    assert again["belief"]["previous_version"] == 1
    assert again["belief"]["status"] == STATUS_PROPOSED


def test_belief_cannot_be_accepted_without_a_validated_learning(tmp_path: Path):
    cand = build_learning_candidate(
        {
            "hypothesis_id": "h1",
            "experiment_id": "HYP-h1",
            "result": RESULT_SUPPORTED,
            "dimension": "option_type",
        },
        hypothesis=_hypothesis(),
        laboratory_id=_LAB,
    )
    propose_revision(tmp_path, cand, laboratory_id=_LAB)
    bid = belief_id_for(_LAB, "option_type")

    refused = accept_revision(
        tmp_path, laboratory_id=_LAB, belief_id=bid, validated_learning_id=None
    )
    assert refused["ok"] is False
    assert refused["reason"] == "no_validated_learning"

    accepted = accept_revision(
        tmp_path, laboratory_id=_LAB, belief_id=bid, validated_learning_id="VL-1"
    )
    assert accepted["ok"] is True
    assert accepted["belief"]["status"] == STATUS_ACCEPTED


def test_decision_context_is_empty_until_something_is_accepted(tmp_path: Path):
    ctx = belief_context_for_decision(tmp_path, laboratory_id=_LAB)
    assert ctx["n_accepted"] == 0
    assert ctx["affects"] == "decision_context_only"

    cand = build_learning_candidate(
        {
            "hypothesis_id": "h1",
            "experiment_id": "HYP-h1",
            "result": RESULT_SUPPORTED,
            "dimension": "option_type",
        },
        hypothesis=_hypothesis(),
        laboratory_id=_LAB,
    )
    propose_revision(tmp_path, cand, laboratory_id=_LAB)
    # Proposed is not accepted — context must stay empty.
    assert belief_context_for_decision(tmp_path, laboratory_id=_LAB)["n_accepted"] == 0

    accept_revision(
        tmp_path,
        laboratory_id=_LAB,
        belief_id=belief_id_for(_LAB, "option_type"),
        validated_learning_id="VL-1",
    )
    after = belief_context_for_decision(tmp_path, laboratory_id=_LAB)
    assert after["n_accepted"] == 1
    assert after["beliefs"][0]["version_n"] == 1

    delta = behavioural_delta(ctx, after)
    assert delta["changed"] is True
    assert delta["paper_only"] is True
    assert delta["added"]


def test_no_behavioural_claim_when_nothing_changed(tmp_path: Path):
    ctx = belief_context_for_decision(tmp_path, laboratory_id=_LAB)
    assert behavioural_delta(ctx, ctx)["changed"] is False


# --- C9 full cycle --------------------------------------------------------


def test_cycle_with_no_episodes_is_an_empty_day_not_a_failure(tmp_path: Path):
    cycle = run_cycle(tmp_path, laboratory_id=_LAB, as_of_ist=_DAY)
    assert cycle["episodes"] == 0
    assert cycle["hypotheses_created"] == 0
    assert "empty day" in cycle["honesty"]


def test_cycle_asks_a_question_then_answers_it_then_asks_the_next(tmp_path: Path):
    from atlas.investment.cognitive.experiment_bridge import persist_result
    from atlas.investment.fno_closed_loop_dataset import STORE_REL as CL_STORE

    _with_bars(tmp_path)
    day_file = tmp_path / CL_STORE / _LAB / f"{_DAY}.jsonl"
    day_file.parent.mkdir(parents=True, exist_ok=True)
    day_file.write_text(
        "\n".join(json.dumps(r) for r in _episodes()) + "\n", encoding="utf-8"
    )

    first = run_cycle(tmp_path, laboratory_id=_LAB, as_of_ist=_DAY)
    assert first["episodes"] == 8
    assert first["patterns"] >= 1
    assert first["hypotheses_created"] == 1
    assert first["learning_candidates"] == 0
    assert first["validated"] == 0
    hid = first["hypotheses"][0]["hypothesis_id"]
    assert first["open_questions"]

    # Run the experiment the way the FEL worker would.
    from atlas.investment.cognitive.queue import next_admitted_hypothesis
    from atlas.investment.fel.experiments.dispatch import process_one

    # Nothing closed after the question yet: the cycle waits instead of judging.
    assert first["awaiting"][0]["reason"] == "awaiting_fresh_sample"
    later = tmp_path / CL_STORE / _LAB / f"{_LATER}.jsonl"
    later.write_text("\n".join(json.dumps(r) for r in _fresh_episodes()) + "\n", encoding="utf-8")

    row = next_admitted_hypothesis(tmp_path, laboratory_id=_LAB)
    assert row["hypothesis_id"] == hid
    enqueue_hypothesis_test(
        tmp_path,
        laboratory_id=_LAB,
        hypothesis_id=hid,
        experiment_spec=row["experiment_spec"],
    )
    ran = process_one(str(tmp_path))
    assert ran["status"] == "COMPLETED"

    second = run_cycle(tmp_path, laboratory_id=_LAB, as_of_ist=_DAY)
    assert second["learning_candidates"] == 1
    assert second["results"][0]["result"] in {
        RESULT_SUPPORTED,
        RESULT_INCONCLUSIVE,
        RESULT_REJECTED,
    }
    # The same question is not asked twice.
    assert any(r["reason"] == REASON_DUPLICATE for r in second["refused"])
    # A supported pass still does not validate anything.
    assert second["validated"] == 0
    assert second["mutates_strategy"] is False
    assert second["live_orders"] is False

    lines = format_cognitive_loop_section(second)
    assert any("validated=0" in ln for ln in lines)
    assert persist_result is not None


def test_cycle_section_states_when_nothing_has_run():
    lines = format_cognitive_loop_section(None)
    assert any("no questions asked" in ln for ln in lines)
