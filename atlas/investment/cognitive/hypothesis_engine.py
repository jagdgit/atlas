"""Cognitive Loop C3b — turn a candidate pattern into a testable hypothesis.

Deterministic code owns everything that decides anything: which episodes count as
evidence, how the sample is defined, where the experiment's boundaries are, what would
falsify the claim, and the status. An LLM, when one is available, may only rewrite the
prose. A silent or busy LLM costs nothing — the deterministic statement stands.

Two claims come out of one pattern, and they are not the same claim:

* the **option-premium** claim, which needs intraday option history we do not store,
  so it is recorded ``NOT_EVALUABLE`` rather than tested against a proxy; and
* the **underlier-direction** restatement, which asks whether the control signal's
  directional call was better in one group than another. That one is testable against
  durable daily OHLCV we already have.

Writes hypotheses. Does not place orders, size positions, or change strategy.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.investment.cognitive.pattern_detector import (
    DECIDE_TIME_DIMENSIONS,
    MIN_EFFECT,
    STATUS_CANDIDATE,
)

VERSION = "cognitive.hypothesis.v2"

# Verdict rules for the fresh-sample test (experiment_bridge applies them).
CONFIRM_ALPHA = 0.05
MIN_FRESH_N = 5

SCOPE_OPTION_PREMIUM = "option_premium"
SCOPE_UNDERLIER_DIRECTION = "underlier_direction"

REQUIREMENT_OPTION_HISTORY = "option_intraday_history"
REQUIREMENT_DAILY_BARS = "daily_underlier_bars"

NOT_EVALUABLE = "NOT_EVALUABLE"
EVALUABLE = "EVALUABLE"

# Dimensions whose split can be honestly restated as a claim about the control
# signal's directional accuracy, which durable daily underlier bars can test.
# A dimension absent here is option-specific and stays NOT_EVALUABLE.
_UNDERLIER_RESTATEMENT: dict[str, str] = {
    "option_type": "control_direction_bias",
    "underlying_type": "instrument_class",
    "control_action": "control_action",
    "signal": "control_signal",
    "expected_direction": "control_direction_bias",
    "er_model": "model",
    "sma_margin_sign": "control_margin_sign",
}

_log = logging.getLogger("atlas.investment.cognitive.hypothesis_engine")


def _statement(pattern: dict[str, Any]) -> str:
    dim = pattern.get("dimension")
    high = pattern.get("high_group")
    low = pattern.get("low_group")
    groups = pattern.get("groups") or {}
    hi = groups.get(str(high)) or {}
    lo = groups.get(str(low)) or {}
    if pattern.get("source") == "llm_proposed":
        return (
            f"Proposed question on {dim}: do episodes with {dim}={high} match their stated "
            f"direction more often than {dim}={low}? So far {high} is {hi.get('hits')}/{hi.get('n')} "
            f"and {low} is {lo.get('hits')}/{lo.get('n')}; only trades closed after this "
            f"question will answer it."
        )
    return (
        f"On dimension {dim}, episodes with {dim}={high} matched their stated direction "
        f"more often ({hi.get('hits')}/{hi.get('n')}) than {dim}={low} "
        f"({lo.get('hits')}/{lo.get('n')}). This may be a real difference in how well "
        f"the control signal calls direction for those groups, or it may be noise."
    )


def _falsifier(pattern: dict[str, Any]) -> str:
    dim = pattern.get("dimension")
    return (
        f"Tested only on episodes closed after this question was asked. Rejected if the "
        f"direction-match gap between {dim}={pattern.get('high_group')} and "
        f"{dim}={pattern.get('low_group')} is zero or reverses sign. Supported only if "
        f"the gap is positive with a one-sided exact-test p <= {CONFIRM_ALPHA}; a "
        f"same-sign gap short of that is INCONCLUSIVE, not support."
    )


def _llm_prose(llm: Any, deterministic: str, pattern: dict[str, Any]) -> tuple[str, str]:
    """Optional rewording. Returns (statement, source). Never blocks the pipeline."""
    if llm is None:
        return deterministic, "deterministic"
    try:
        prompt = (
            "Rewrite this observation as one neutral, falsifiable sentence. Do not add "
            "numbers, causes, or recommendations that are not present.\n\n"
            f"Observation: {pattern.get('observation')}\n"
            f"Draft: {deterministic}"
        )
        out = llm.complete(prompt) if hasattr(llm, "complete") else None
        text = str((out or {}).get("text") if isinstance(out, dict) else out or "").strip()
        if text and len(text) < 480:
            return text, "llm_phrasing"
    except Exception:  # noqa: BLE001
        _log.debug("hypothesis LLM phrasing skipped", exc_info=True)
    return deterministic, "deterministic"


def _experiment_specs(pattern: dict[str, Any]) -> list[dict[str, Any]]:
    dim = str(pattern.get("dimension") or "")
    high = pattern.get("high_group")
    low = pattern.get("low_group")
    thin = bool(pattern.get("thin_groups"))

    specs: list[dict[str, Any]] = [
        {
            "claim_scope": SCOPE_OPTION_PREMIUM,
            "data_requirement": REQUIREMENT_OPTION_HISTORY,
            "evaluable": False,
            "not_evaluable_reason": "no_option_intraday_history",
            "status": NOT_EVALUABLE,
            "honesty": (
                "Testing how premiums behaved needs stored intraday option history, "
                "which does not exist. Daily underlier bars are not a substitute and "
                "no proxy premium will be invented."
            ),
        }
    ]

    restated = _UNDERLIER_RESTATEMENT.get(dim) or (
        f"control_accuracy_by_{dim}" if dim in DECIDE_TIME_DIMENSIONS else None
    )
    if not restated:
        return specs

    evaluable = not thin
    specs.append(
        {
            "claim_scope": SCOPE_UNDERLIER_DIRECTION,
            "restated_as": restated,
            "data_requirement": REQUIREMENT_DAILY_BARS,
            "evaluable": evaluable,
            "not_evaluable_reason": None if evaluable else "insufficient_sample",
            "status": EVALUABLE if evaluable else NOT_EVALUABLE,
            "dimension": dim,
            "groups": [str(high), str(low)],
            "metric": "direction_match_rate",
            "min_effect": MIN_EFFECT,
            "alpha": CONFIRM_ALPHA,
            "min_fresh_n": MIN_FRESH_N,
            "holdout": "episodes_closed_after_question",
            "exclude_experience_ids": sorted(
                str(x) for x in (pattern.get("source_experience_ids") or []) if x
            ),
            "asked_as_of": pattern.get("as_of_ist"),
            "baseline_required": True,
            "evaluator": "walk_forward",
            "mutates_strategy": False,
            "promotion": None,
            "honesty": (
                "Restated as a claim about the control signal's directional accuracy, "
                "which durable daily OHLCV can test. This is a narrower claim than the "
                "premium one — supporting it does not support the premium claim."
            ),
        }
    )
    return specs


def build_hypothesis(
    pattern: dict[str, Any] | None,
    *,
    laboratory_id: str,
    llm: Any | None = None,
) -> dict[str, Any] | None:
    """Structured, falsifiable hypothesis from one candidate pattern."""
    if not isinstance(pattern, dict) or not pattern.get("dimension"):
        return None

    deterministic = _statement(pattern)
    statement, source = _llm_prose(llm, deterministic, pattern)
    specs = _experiment_specs(pattern)
    evaluable = [s for s in specs if s.get("evaluable")]

    return {
        "version": VERSION,
        "laboratory_id": str(laboratory_id or ""),
        "as_of_ist": pattern.get("as_of_ist"),
        "dimension": pattern.get("dimension"),
        "observation": pattern.get("observation"),
        "statement": statement,
        "statement_source": source,
        "deterministic_statement": deterministic,
        "prediction": (
            f"If real, the gap on {pattern.get('dimension')} keeps its sign on episodes "
            f"closed after this question, at one-sided p <= {CONFIRM_ALPHA}."
        ),
        "source": pattern.get("source") or "pattern_detector",
        "mechanism": pattern.get("mechanism"),
        "falsifier": _falsifier(pattern),
        "experiment_specs": specs,
        "evaluable": bool(evaluable),
        "pattern_status": pattern.get("status"),
        "source_pattern": {
            "dimension": pattern.get("dimension"),
            "groups": pattern.get("groups"),
            "split_delta": pattern.get("split_delta"),
            "thin_groups": pattern.get("thin_groups"),
            "confounded_with": list(pattern.get("confounded_with") or []),
        },
        "source_experience_ids": list(pattern.get("source_experience_ids") or []),
        "confidence": "very_low",
        "honesty": (
            "Question, not a finding. One day of episodes cannot support a verdict. "
            + (
                "The LLM proposed which split to ask about; "
                if pattern.get("source") == "llm_proposed"
                else ""
            )
            + "deterministic code counted the evidence and set the sample, boundaries "
            f"and falsifier; the statement wording came from {source}."
        ),
    }


def persist_hypothesis(
    data_dir: Any,
    hypothesis: dict[str, Any] | None,
    *,
    laboratory_id: str,
) -> dict[str, Any]:
    """Store through the existing hypothesis ledger — no parallel store."""
    if not isinstance(hypothesis, dict) or not hypothesis.get("statement"):
        return {"ok": False, "reason": "missing_hypothesis"}
    try:
        from atlas.investment.hypothesis_learning import create_hypothesis

        out = create_hypothesis(
            data_dir,
            statement=str(hypothesis["statement"]),
            domain_tags=["cognitive_loop", str(hypothesis.get("dimension") or "")],
            laboratory_id=laboratory_id,
            # Lab-scoped: a claim about this control in this lab is not a world claim.
            transfer_class="strategy",
            linked_decision_ids=list(hypothesis.get("source_experience_ids") or []),
            extra={
                "cognitive_loop": VERSION,
                "dimension": hypothesis.get("dimension"),
                "observation": hypothesis.get("observation"),
                "prediction": hypothesis.get("prediction"),
                "falsifier": hypothesis.get("falsifier"),
                "experiment_specs": hypothesis.get("experiment_specs"),
                "evaluable": hypothesis.get("evaluable"),
                "pattern_status": hypothesis.get("pattern_status"),
                "source_pattern": hypothesis.get("source_pattern"),
                "statement_source": hypothesis.get("statement_source"),
                "deterministic_statement": hypothesis.get("deterministic_statement"),
                "source": hypothesis.get("source"),
                "mechanism": hypothesis.get("mechanism"),
                "honesty": hypothesis.get("honesty"),
            },
        )
        row = (out or {}).get("hypothesis") or {}
        return {"ok": True, "hypothesis_id": row.get("hypothesis_id"), "hypothesis": row}
    except Exception as exc:  # noqa: BLE001
        _log.debug("hypothesis persist failed", exc_info=True)
        return {"ok": False, "reason": type(exc).__name__}


def duplicate_of(
    data_dir: Any, *, laboratory_id: str, dimension: str
) -> str | None:
    """Already-asked questions are not new questions."""
    try:
        from atlas.investment.hypothesis_learning import list_hypotheses

        for row in list_hypotheses(
            data_dir, laboratory_id=laboratory_id, include_world=False, limit=100
        ):
            extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
            if str(extra.get("dimension") or "") == str(dimension):
                return str(row.get("hypothesis_id") or "") or None
    except Exception:  # noqa: BLE001
        _log.debug("duplicate hypothesis scan skipped", exc_info=True)
    return None
