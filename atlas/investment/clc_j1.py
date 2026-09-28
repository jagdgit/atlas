"""CLC.J1 — one supervised planner job (E001 investigation).

Starts only after a ``bre3_decide_rationale`` REVIEWED path exists
(R1-SYNTHETIC is enough to *start*; R1-LIVE remains a separate proof).

Does not mutate SMA/RSI. Does not place BUY/SELL. Not AGENT-1.

Saturday densify: conclude from durable FEL disk (experiment + lesson), not
from empty research-web rounds — the prior live J1 job completed with 0 B
evidence because it searched the objective text instead of reading E001.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas.investment.lesson_influence import E001_EXPERIMENT_ID, E001_STATEMENT

VERSION = "clc.j1.v1"
KIND = "CLC_J1"
CONCLUSION_REL = Path("investment") / "clc" / "j1_conclusion.json"

J1_OBJECTIVE = (
    "CLC.J1 — Investigate why volume acceleration failed to improve the "
    "momentum + RS baseline (E001-buy_name-vol-accel). Determine whether "
    "there is evidence for a regime where it could still be useful. "
    "Conclude with a bounded lesson or an explicit 'no further test.' "
    "Do not mutate SMA/RSI. Do not place BUY/SELL orders. Advice-only. "
    "Never change PLC.A, live_control, or capital."
)

_log = logging.getLogger("atlas.investment.clc_j1")


def j1_constraints() -> dict[str, Any]:
    return {
        "version": VERSION,
        "kind": KIND,
        "experiment_id": E001_EXPERIMENT_ID,
        "e001_statement": E001_STATEMENT,
        "sma_rsi_untouched": True,
        "never_orders": True,
        "live_execution": False,
        "plc_a_untouched": True,
        "allowed_conclusions": ("bounded_lesson", "no_further_test"),
        "honesty": (
            "J1 is a real job.jobs investigation. Completing it does not "
            "prove R1-LIVE or that Atlas has learned at L5."
        ),
    }


def _f(v: Any) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def load_e001_experiment(data_dir: str | Path | None) -> dict[str, Any] | None:
    if not data_dir:
        return None
    path = (
        Path(data_dir)
        / "investment"
        / "fel"
        / "experiments"
        / "india_equity_learner"
        / f"{E001_EXPERIMENT_ID}.json"
    )
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def load_e001_lesson(data_dir: str | Path | None) -> dict[str, Any] | None:
    if not data_dir:
        return None
    path = Path(data_dir) / "investment" / "fel" / "lessons" / "L-E001-buy_name-vol-accel.json"
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def conclude_j1_from_fel_disk(
    data_dir: str | Path | None,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    """Bounded J1 conclusion from durable E001 FEL artifacts (no web, no SMA mutate).

    Regime read of E001:
      • overall = worse (promotion never)
      • high_momentum = no_significant (not better / not promotion-worthy)
      • low_momentum = worse
    → conclusion = no_further_test (no leftover regime justifies more vol-accel tests).
    """
    exp = load_e001_experiment(data_dir)
    lesson = load_e001_lesson(data_dir)
    if not exp:
        return {
            "ok": False,
            "reason": "e001_experiment_missing",
            "conclusion": None,
            "sma_rsi_untouched": True,
            "never_orders": True,
            "not_l5": True,
        }
    evaluation = exp.get("evaluation") if isinstance(exp.get("evaluation"), dict) else {}
    regimes = exp.get("regimes") if isinstance(exp.get("regimes"), dict) else {}
    overall = str(exp.get("result") or evaluation.get("result") or "").strip().lower()
    delta = _f(evaluation.get("delta_economic"))
    n_folds = evaluation.get("n_folds") or exp.get("n_folds")
    high = regimes.get("high_momentum") if isinstance(regimes.get("high_momentum"), dict) else {}
    low = regimes.get("low_momentum") if isinstance(regimes.get("low_momentum"), dict) else {}
    high_ev = high.get("evaluation") if isinstance(high.get("evaluation"), dict) else {}
    low_ev = low.get("evaluation") if isinstance(low.get("evaluation"), dict) else {}
    high_res = str(high_ev.get("result") or "").strip().lower()
    low_res = str(low_ev.get("result") or "").strip().lower()

    # Any regime that is strictly better after costs would keep a bounded_lesson path.
    regime_better = [
        name
        for name, block in (("high_momentum", high_ev), ("low_momentum", low_ev))
        if str(block.get("result") or "").strip().lower() == "better"
    ]
    if regime_better:
        conclusion = "bounded_lesson"
        narrative = (
            f"E001 overall={overall} (delta_economic={delta}, folds={n_folds}). "
            f"Leftover regime(s) marked better: {', '.join(regime_better)}. "
            "Hold a bounded regime-conditioned lesson — do not promote to live_control."
        )
    else:
        conclusion = "no_further_test"
        narrative = (
            f"E001 overall={overall} after 15 bps costs (delta_economic={delta}, "
            f"folds={n_folds}). high_momentum={high_res or 'n/a'}; "
            f"low_momentum={low_res or 'n/a'}. No regime shows better-after-costs. "
            "No further vol-accel buy_name test. Do not treat vol-accel as a reason to buy. "
            "SMA/RSI untouched. Not L5."
        )

    doc = {
        "version": VERSION,
        "kind": "CLC_J1_CONCLUSION",
        "ok": True,
        "conclusion": conclusion,
        "narrative": narrative,
        "experiment_id": E001_EXPERIMENT_ID,
        "hypothesis_id": exp.get("hypothesis_id") or "H-buy_name-vol-accel",
        "lesson_id": (lesson or {}).get("id") or "L-E001-buy_name-vol-accel",
        "lesson_statement": (lesson or {}).get("statement") or E001_STATEMENT,
        "evidence": {
            "overall_result": overall,
            "delta_economic": delta,
            "n_folds": n_folds,
            "promotion": exp.get("promotion"),
            "high_momentum": high_res or None,
            "low_momentum": low_res or None,
            "source_path": (
                "investment/fel/experiments/india_equity_learner/"
                f"{E001_EXPERIMENT_ID}.json"
            ),
        },
        "allowed_conclusions": list(j1_constraints()["allowed_conclusions"]),
        "sma_rsi_untouched": True,
        "never_orders": True,
        "live_execution": False,
        "plc_a_untouched": True,
        "not_l5": True,
        "not_r1_live": True,
        "prior_live_job": {
            "note": (
                "job e498ebb2… completed with 0 B research evidence — "
                "this disk conclusion supersedes that empty answer for J1."
            )
        },
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "honesty": (
            "Disk-backed J1 conclusion from FEL E001. Advice-only. "
            "Does not mutate SMA/RSI, PLC.A, or live_control. Not an L5 claim."
        ),
    }
    if persist and data_dir:
        path = Path(data_dir) / CONCLUSION_REL
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
            doc["path"] = str(path)
        except OSError as exc:
            _log.debug("j1 conclusion persist failed: %s", exc, exc_info=True)
            doc["persist_ok"] = False
    return doc


def start_j1(*, jobs: Any | None = None, session_id: str | None = None) -> dict[str, Any]:
    """Create the J1 job via JobService (planner decompose, not a new worker)."""
    svc = jobs
    if svc is None:
        from atlas.kernel.bootstrap import build_application

        owned_app = build_application()
        svc = owned_app.container.resolve("jobs")
    detail = svc.create_job(J1_OBJECTIVE, session_id=session_id)
    job = detail.get("job") if isinstance(detail, dict) else None
    jid = getattr(job, "id", None)
    if jid is None and isinstance(job, dict):
        jid = job.get("id")
    constraints = j1_constraints()
    if jid and hasattr(svc, "_repo") and hasattr(svc._repo, "merge_job_metadata"):
        try:
            svc._repo.merge_job_metadata(
                str(jid),
                {
                    "clc_j1": True,
                    "kind": KIND,
                    "sma_rsi_untouched": True,
                    "never_orders": True,
                    "live_execution": False,
                },
            )
        except Exception:  # noqa: BLE001
            pass
    return {
        "started": True,
        "job_id": str(jid) if jid else None,
        "objective": J1_OBJECTIVE,
        **constraints,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="CLC.J1 — start job or conclude from FEL disk")
    parser.add_argument(
        "--conclude-from-disk",
        action="store_true",
        help="Write J1 conclusion from durable E001 FEL artifacts (no web research)",
    )
    args = parser.parse_args(argv)
    if args.conclude_from_disk:
        from atlas.config import get_config

        out = conclude_j1_from_fel_disk(str(get_config().paths.data), persist=True)
        print(json.dumps(out, indent=2, default=str))
        return 0 if out.get("ok") else 1
    out = start_j1()
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("started") and out.get("job_id") else 1


if __name__ == "__main__":
    raise SystemExit(main())
