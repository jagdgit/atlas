"""Cognitive Loop C4 — is this hypothesis worth compute?

The Agent Kernel already decides what operational work to do next. A hypothesis is
work too, so it goes through an explicit, inspectable rubric rather than being run
because it exists. Every refusal is a durable, named reason: a question Atlas declined
to test is information, and silently dropping it would be the dishonest option.

Admission is advisory. Nothing here places orders, changes priority classes, or
promotes anything.
"""

from __future__ import annotations

import logging
from typing import Any

VERSION = "cognitive.admission.v1"

ADMITTED = "ADMITTED"
REFUSED = "REFUSED"

# Refusal reasons. Each one is a fact about the question or the data, never "later".
REASON_INSUFFICIENT_SAMPLE = "insufficient_sample"
REASON_NOT_EVALUABLE = "not_evaluable"
REASON_DUPLICATE = "duplicate_hypothesis"
REASON_ALREADY_TESTED = "already_tested"
REASON_BARS_NOT_REPLAYABLE = "bars_not_replayable"
REASON_NO_FALSIFIER = "no_falsifier"
REASON_CONFOUNDED_ONLY = "confounded_without_separating_sample"

_log = logging.getLogger("atlas.investment.cognitive.admission")


def _evaluable_spec(hypothesis: dict[str, Any]) -> dict[str, Any] | None:
    for spec in hypothesis.get("experiment_specs") or []:
        if isinstance(spec, dict) and spec.get("evaluable"):
            return spec
    return None


def _bars_replayable(data_dir: Any, symbols: list[str]) -> tuple[bool, list[str]]:
    """Reuse the P2 bars-health gate — no separate notion of 'enough data'."""
    if not symbols:
        return False, []
    try:
        from atlas.investment.market_bars_health import assess_symbols

        doc = assess_symbols(data_dir, symbols)
        bad = [
            str(r.get("symbol"))
            for r in (doc.get("symbols") or [])
            if not r.get("replayable")
        ]
        return bool(doc.get("all_replayable")), bad
    except Exception:  # noqa: BLE001
        _log.debug("bars health gate unavailable", exc_info=True)
        return False, list(symbols)


def admit_hypothesis(
    hypothesis: dict[str, Any] | None,
    *,
    data_dir: Any = None,
    laboratory_id: str,
    underlying_symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Decide, with a named reason either way."""
    hypo = hypothesis if isinstance(hypothesis, dict) else {}
    decision: dict[str, Any] = {
        "version": VERSION,
        "laboratory_id": str(laboratory_id or ""),
        "dimension": hypo.get("dimension"),
        "status": REFUSED,
        "reason": None,
        "detail": None,
        "experiment_spec": None,
    }

    if not hypo.get("falsifier"):
        decision["reason"] = REASON_NO_FALSIFIER
        decision["detail"] = "a claim with no falsifier is not testable"
        return decision

    spec = _evaluable_spec(hypo)
    if spec is None:
        reasons = sorted(
            {
                str(s.get("not_evaluable_reason"))
                for s in (hypo.get("experiment_specs") or [])
                if isinstance(s, dict) and s.get("not_evaluable_reason")
            }
        )
        decision["reason"] = (
            REASON_INSUFFICIENT_SAMPLE
            if "insufficient_sample" in reasons
            else REASON_NOT_EVALUABLE
        )
        decision["detail"] = ", ".join(reasons) or "no evaluable experiment spec"
        return decision

    dim = str(hypo.get("dimension") or "")
    if data_dir and dim:
        try:
            from atlas.investment.cognitive.hypothesis_engine import duplicate_of

            dup = duplicate_of(data_dir, laboratory_id=laboratory_id, dimension=dim)
            if dup:
                decision["reason"] = REASON_DUPLICATE
                decision["detail"] = f"already asked as {dup}"
                decision["duplicate_of"] = dup
                return decision
        except Exception:  # noqa: BLE001
            _log.debug("duplicate check skipped", exc_info=True)

    symbols = [str(s).upper() for s in (underlying_symbols or []) if s]
    ok, bad = _bars_replayable(data_dir, symbols) if data_dir else (False, symbols)
    if not ok:
        decision["reason"] = REASON_BARS_NOT_REPLAYABLE
        decision["detail"] = (
            f"durable daily bars not replayable for {', '.join(bad[:6]) or 'the universe'}"
        )
        decision["unreplayable_symbols"] = bad
        return decision

    decision["status"] = ADMITTED
    decision["reason"] = "interesting_testable_evidenced_and_not_yet_tested"
    decision["experiment_spec"] = spec
    decision["detail"] = (
        f"{dim}: {spec.get('metric')} gap >= {spec.get('min_effect')} on "
        f"{spec.get('data_requirement')}"
    )
    decision["confounded_with"] = list(
        (hypo.get("source_pattern") or {}).get("confounded_with") or []
    )
    return decision
