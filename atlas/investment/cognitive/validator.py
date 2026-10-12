"""Cognitive Loop C6 — route an experiment result into the learning ladder.

The ladder already exists and already refuses to skip levels: L3 → L4 candidate with
an OPEN subsequent test → VALIDATED / FALSIFIED / INCONCLUSIVE. This module only
decides which rung a result earns, and the answer is usually "none yet".

The rules, which nothing here may bypass:

* **SUPPORTED is not validated.** One pass becomes an L4 candidate carrying an OPEN
  test. Validation needs the pre-declared independent sample to pass too.
* **REJECTED is kept.** A falsified claim is knowledge; deleting it would be the only
  way to lose it.
* **INCONCLUSIVE and NOT_EVALUABLE write no belief at all.**
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from atlas.investment.cognitive.experiment_bridge import (
    REPLICATION_PASSES,
    RESULT_INCONCLUSIVE,
    RESULT_NOT_EVALUABLE,
    RESULT_REJECTED,
    RESULT_SUPPORTED,
)

VERSION = "cognitive.validator.v1"
KIND = "LEARNING_CANDIDATE"
STORE_REL = Path("investment") / "cognitive" / "learnings"

OUTCOME_CANDIDATE = "L4_CANDIDATE_OPEN_TEST"
OUTCOME_FALSIFIED = "FALSIFIED"
OUTCOME_NO_WRITE = "NO_BELIEF_WRITE"

_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.cognitive.validator")


def _ladder_outcome(result: str) -> tuple[str, str]:
    if result == RESULT_SUPPORTED:
        return OUTCOME_CANDIDATE, (
            "One supported pass. Recorded as an L4 belief candidate with an OPEN "
            f"subsequent test; {REPLICATION_PASSES} independent passes are required "
            "before anything may be called validated."
        )
    if result == RESULT_REJECTED:
        return OUTCOME_FALSIFIED, (
            "Falsified, and kept. A rejected claim is a real result — the control "
            "does not have the edge this question proposed."
        )
    if result == RESULT_INCONCLUSIVE:
        return OUTCOME_NO_WRITE, (
            "Inconclusive. The question stays open and no belief is written; the "
            "effect was smaller than the pre-declared minimum, which is not support."
        )
    return OUTCOME_NO_WRITE, (
        "Not evaluable. No verdict, no belief write — the data could not separate the "
        "groups and no proxy was substituted."
    )


def build_learning_candidate(
    experiment_result: dict[str, Any] | None,
    *,
    hypothesis: dict[str, Any] | None = None,
    laboratory_id: str,
) -> dict[str, Any] | None:
    """A learning *candidate* — never a learning, never a lesson."""
    res = experiment_result if isinstance(experiment_result, dict) else {}
    if not res.get("hypothesis_id"):
        return None
    result = str(res.get("result") or RESULT_NOT_EVALUABLE)
    outcome, honesty = _ladder_outcome(result)
    hypo = hypothesis if isinstance(hypothesis, dict) else {}
    confounded = list((hypo.get("source_pattern") or {}).get("confounded_with") or [])

    return {
        "version": VERSION,
        "kind": KIND,
        "laboratory_id": str(laboratory_id or ""),
        "as_of_ist": datetime.now(_IST).strftime("%Y-%m-%d"),
        "hypothesis_id": res.get("hypothesis_id"),
        "experiment_id": res.get("experiment_id"),
        "dimension": res.get("dimension"),
        "statement": hypo.get("statement"),
        "falsifier": hypo.get("falsifier"),
        "experiment_result": result,
        "experiment_reason": res.get("reason"),
        "gap": res.get("gap"),
        "min_effect": res.get("min_effect"),
        "baseline": res.get("baseline"),
        "group_rates": res.get("group_rates"),
        "ladder_outcome": outcome,
        "level": "L4" if outcome == OUTCOME_CANDIDATE else "L3",
        "validated": False,
        "writes_belief": outcome == OUTCOME_CANDIDATE,
        "passes_done": 1 if result in {RESULT_SUPPORTED, RESULT_REJECTED} else 0,
        "passes_required": REPLICATION_PASSES,
        "confounded_with": confounded,
        "untested_claims": [
            spec.get("claim_scope")
            for spec in (hypo.get("experiment_specs") or [])
            if isinstance(spec, dict) and not spec.get("evaluable")
        ],
        "mutates_strategy": False,
        "promotion": None,
        "honesty": honesty
        + (
            f" Still indistinguishable from {', '.join(confounded)} — this sample does "
            "not separate them."
            if confounded
            else ""
        ),
    }


def apply_to_ladder(
    data_dir: str | Path | None,
    candidate: dict[str, Any] | None,
    *,
    laboratory_id: str,
) -> dict[str, Any]:
    """Create the L4 belief candidate with an OPEN test — only when earned."""
    cand = candidate if isinstance(candidate, dict) else {}
    if not cand:
        return {"ok": False, "reason": "missing_candidate"}
    if not cand.get("writes_belief"):
        return {
            "ok": True,
            "promoted": False,
            "reason": cand.get("experiment_result"),
            "detail": "no belief candidate: result did not earn one",
        }
    try:
        from atlas.investment.l5_validation import promote_l3_to_candidate

        rec = {
            "id": f"CL-{str(cand.get('hypothesis_id') or '')[:12]}",
            "experience_id": cand.get("hypothesis_id"),
            "symbol": str(cand.get("dimension") or "").upper(),
            "chain_complete": True,
            "level": "L3",
            "update": cand.get("statement"),
            "lesson": cand.get("statement"),
            "prediction": {"status": "computed"},
            "attribution": {"status": "evidence_backed", "satisfied": True},
        }
        out = promote_l3_to_candidate(
            rec, laboratory_id=laboratory_id, data_dir=data_dir
        )
        return {
            "ok": bool(out.get("ok", True)),
            "promoted": True,
            "candidate_id": (out.get("candidate") or {}).get("id"),
            "subsequent_test_status": (
                (out.get("candidate") or {}).get("subsequent_test") or {}
            ).get("status"),
            "detail": "L4 candidate with OPEN subsequent test; never L5 here",
        }
    except Exception as exc:  # noqa: BLE001
        _log.debug("ladder promotion failed", exc_info=True)
        return {"ok": False, "reason": type(exc).__name__}


def persist_candidate(
    data_dir: str | Path | None, candidate: dict[str, Any] | None
) -> dict[str, Any]:
    if not data_dir or not isinstance(candidate, dict):
        return {"ok": False, "reason": "missing_args"}
    try:
        path = (
            Path(data_dir)
            / STORE_REL
            / str(candidate.get("laboratory_id") or "")
            / f"{candidate.get('hypothesis_id')}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"ok": True, "path": str(path)}
    except Exception as exc:  # noqa: BLE001
        _log.debug("learning candidate persist failed", exc_info=True)
        return {"ok": False, "reason": type(exc).__name__}


def load_candidates(
    data_dir: str | Path | None, *, laboratory_id: str
) -> list[dict[str, Any]]:
    if not data_dir:
        return []
    root = Path(data_dir) / STORE_REL / str(laboratory_id)
    if not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(doc, dict):
            rows.append(doc)
    return rows


def ladder_counts(data_dir: str | Path | None, *, laboratory_id: str) -> dict[str, Any]:
    """The honest hierarchy — questions asked is not learnings validated."""
    rows = load_candidates(data_dir, laboratory_id=laboratory_id)
    return {
        "version": VERSION,
        "candidates": len(rows),
        "supported": sum(1 for r in rows if r.get("experiment_result") == RESULT_SUPPORTED),
        "rejected": sum(1 for r in rows if r.get("experiment_result") == RESULT_REJECTED),
        "inconclusive": sum(
            1 for r in rows if r.get("experiment_result") == RESULT_INCONCLUSIVE
        ),
        "not_evaluable": sum(
            1 for r in rows if r.get("experiment_result") == RESULT_NOT_EVALUABLE
        ),
        "validated": sum(1 for r in rows if r.get("validated")),
        "belief_writes": sum(1 for r in rows if r.get("writes_belief")),
        "honesty": (
            "Candidates are questions that got an answer. validated counts only "
            "claims that passed a pre-declared independent test."
        ),
    }
