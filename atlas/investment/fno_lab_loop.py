"""F&O-LAB — isolated paper/research cognitive loop. Live orders never.

Opening this laboratory means: ingest, hypothesize, paper/synthetic
experiments, retrieve → reason → outcome → lesson. It does **not** mean
enable real F&O execution, share equity capital, mutate SMA/RSI, or
declare that Atlas has learned.

Synthetic cycle (deterministic, no live capital):

    hypothesis (Condition X → positive return)
        → retrieve known lesson (E001)
        → paper decision (never_orders)
        → synthetic outcome (Condition X → negative return)
        → prediction error → experience → lesson
        → next F&O decision retrieves that lesson
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from atlas.investment.hypothesis_learning import create_hypothesis
from atlas.investment.laboratory import DEFAULT_FNO_LAB
from atlas.investment.lesson_influence import (
    E001_LESSON_ID,
    LAYER_VALIDATED,
    canonical_e001_lesson,
    match_lessons,
)

VERSION = "fno.lab.clc.v1"
LABORATORY_ID = "fno_paper_clc"
PRODUCTION_FNO_LAB = DEFAULT_FNO_LAB
FNO_LESSON_ID = "L-FNO-SYNTH-COND-X"
HYPOTHESIS = (
    "Condition X: NIFTY ATM CE entered after underlier volume acceleration "
    "should produce positive return after costs."
)
SYNTHETIC_OUTCOME = (
    "Condition X produced negative return after costs. Prediction error."
)
FNO_LESSON_STATEMENT = (
    "F&O synthetic: Condition X (ATM CE after underlier volume acceleration) "
    "did not produce positive return. Do not treat vol-accel as a reason to "
    "buy index options. Bounded caution only. Not a live-trading license."
)
STORE_REL = Path("investment") / "fel" / "lessons"
CYCLE_REL = Path("investment") / "fno" / "lab_cycles"


def lab_policy() -> dict[str, Any]:
    return {
        "version": VERSION,
        "kind": "FNO_LAB",
        "laboratory_id": LABORATORY_ID,
        "isolated_from": PRODUCTION_FNO_LAB,
        "live_orders": False,
        "live_execution": False,
        "capital_isolated": True,
        "never_orders": True,
        "sma_rsi_untouched": True,
        "plc_a_untouched": True,
        "allows": (
            "research",
            "hypothesis",
            "paper_synthetic_experiments",
            "data_ingestion",
            "retrieve_reason_outcome_lesson",
        ),
        "forbids": (
            "live_fno_execution",
            "cash_equity_alts",
            "shared_capital_with_equity",
            "sma_rsi_mutation",
        ),
        "honesty": (
            "F&O-LAB proves the cognitive loop can run off the equity swing "
            "machinery. It does not prove R1-LIVE or authorize live F&O."
        ),
    }


def fno_lesson() -> dict[str, Any]:
    return {
        "id": FNO_LESSON_ID,
        "kind": "fel_result",
        "statement": FNO_LESSON_STATEMENT,
        "layer": LAYER_VALIDATED,
        "sign": -1,
        "lesson_eligible": True,
        "decision_eligible": False,
        "match_tokens": ("condition x", "atm ce", "volume acceleration"),
        "synthetic": True,
        "never_orders": True,
        "live_orders": False,
    }


def persist_fno_lesson(data_dir: str | Path) -> Path:
    root = Path(data_dir) / STORE_REL
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{FNO_LESSON_ID}.json"
    payload = {"store_version": VERSION, **fno_lesson(), "live_control": False}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def retrieve_for_decision(
    *,
    query: str,
    extra: list[dict[str, Any]] | None = None,
    symbol: str = "NIFTY26SEPFUT",
) -> list[dict[str, Any]]:
    retrieved = [canonical_e001_lesson(), *(extra or [])]
    matched = match_lessons(
        candidate={
            "decision_type": "buy_name",
            "action": "buy",
            "symbol": symbol,
            "features": ["volume_acceleration_20d"],
            "query": query,
        },
        retrieved=retrieved,
        query=query,
    )
    seen = {str(x.get("id") or "") for x in matched if isinstance(x, dict)}
    blob = " ".join(str(query or "").lower().replace("_", " ").split())
    for item in extra or []:
        if not isinstance(item, dict):
            continue
        iid = str(item.get("id") or "")
        if not iid or iid in seen:
            continue
        tokens = [str(t).lower() for t in (item.get("match_tokens") or ()) if t]
        if iid.lower() in blob or any(tok in blob for tok in tokens if len(tok) > 3):
            matched.append(
                {
                    "id": iid,
                    "kind": item.get("kind"),
                    "statement": str(item.get("statement") or "")[:400],
                    "match": "fno_lab_token",
                    "layer": item.get("layer"),
                    "sign": item.get("sign"),
                    "l2_option": 0.0,
                    "l2_ranking": 0.0,
                }
            )
            seen.add(iid)
    return matched


def run_synthetic_cycle(data_dir: str | Path) -> dict[str, Any]:
    """One closed paper loop. Never places orders. Never touches live F&O capital."""
    policy = lab_policy()
    created = create_hypothesis(
        data_dir,
        statement=HYPOTHESIS,
        domain_tags=["fno", "synthetic", "volume_acceleration"],
        laboratory_id=LABORATORY_ID,
        transfer_class="strategy",
        extra={"prediction": "positive_return", "live_orders": False},
    )
    hyp = created.get("hypothesis") if isinstance(created, dict) else {}
    if not isinstance(hyp, dict):
        hyp = created if isinstance(created, dict) else {}
    first_query = (
        "F&O paper: Condition X ATM CE after volume acceleration. "
        "Should E001 change ranking/caution?"
    )
    first_cite = retrieve_for_decision(query=first_query)
    first_ids = [str(x.get("id") or "") for x in first_cite if isinstance(x, dict)]
    paper_decision = {
        "decision_id": f"fno-synth-{uuid4().hex[:10]}",
        "symbol": "NIFTY26SEPFUT",
        "action": "buy",
        "synthetic": True,
        "never_orders": True,
        "live_orders": False,
        "paper": True,
        "prediction": "positive_return",
        "condition": "X",
        "lesson_refs": first_ids,
        "laboratory_id": LABORATORY_ID,
    }
    outcome = {
        "realized": "negative_return",
        "prediction_error": True,
        "attribution": "vol_accel_condition_x_failed",
        "statement": SYNTHETIC_OUTCOME,
    }
    lesson_path = persist_fno_lesson(data_dir)
    experience = {
        "id": f"exp-fno-synth-{uuid4().hex[:10]}",
        "laboratory_id": LABORATORY_ID,
        "hypothesis_id": hyp.get("hypothesis_id"),
        "decision_id": paper_decision["decision_id"],
        "prediction": "positive_return",
        "outcome": "negative_return",
        "prediction_error": True,
        "lesson_id": FNO_LESSON_ID,
        "never_orders": True,
        "live_orders": False,
    }
    next_query = (
        f"F&O paper next decision: Condition X ATM CE after volume acceleration. "
        f"Retrieve prior lesson {FNO_LESSON_ID}."
    )
    next_cite = retrieve_for_decision(
        query=next_query,
        extra=[fno_lesson()],
        symbol="NIFTY26OCTFUT",
    )
    next_ids = [str(x.get("id") or "") for x in next_cite if isinstance(x, dict)]
    report = {
        "version": VERSION,
        "kind": "FNO_LAB_SYNTHETIC_CYCLE",
        **policy,
        "hypothesis_id": hyp.get("hypothesis_id"),
        "first_decision": paper_decision,
        "first_cited_e001": E001_LESSON_ID in first_ids,
        "outcome": outcome,
        "experience": experience,
        "lesson_path": str(lesson_path),
        "next_decision_lesson_refs": next_ids,
        "next_retrieved_fno_lesson": FNO_LESSON_ID in next_ids,
        "loop_closed": bool(
            E001_LESSON_ID in first_ids and FNO_LESSON_ID in next_ids
        ),
        "r1_live": False,
        "atlas_has_learned": False,
    }
    _persist_cycle(data_dir, report)
    return report


def _persist_cycle(data_dir: str | Path, report: dict[str, Any]) -> None:
    root = Path(data_dir) / CYCLE_REL
    root.mkdir(parents=True, exist_ok=True)
    hid = str(report.get("hypothesis_id") or uuid4().hex[:10])
    path = root / f"{hid}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)
