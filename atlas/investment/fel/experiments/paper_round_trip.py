"""LAB-LOOP0 Step 7 — paper round-trip experiences → FEL (no RL).

Turns rewarded JSONL closes into a lab-hermetic PIT-shaped dataset and a
cash-baseline experiment queued like E001. Promotion never ``live_control``.
Does not mix F&O into equity. Does not mutate SMA/RSI. Thin samples stay
inconclusive; a losing book is a durable rejected hypothesis.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas.investment.fel.datasets.builder import persist_pit_dataset
from atlas.investment.fel.experiments.store import persist_experiment
from atlas.investment.fel.promotion import LIVE_CONTROL, promotion_for
from atlas.investment.hypothesis_learning import (
    create_hypothesis,
    get_hypothesis,
    record_verdict,
    store_dir as hypothesis_store_dir,
)
from atlas.investment.laboratory import (
    DEFAULT_SWING_LAB,
    LaboratoryContaminationError,
    MAIL_SNAPSHOT_LABS,
    normalize_laboratory_id,
)
from atlas.investment.learning_objects import load_learning_events, store_dir as learning_store_dir

_log = logging.getLogger("atlas.investment.fel.paper_round_trip")

KIND = "paper_round_trip"
VERSION = "fel.paper_round_trip.v1"
MIN_SAMPLE = 3
FINDINGS_REL = Path("investment") / "fel" / "findings"
HYPOTHESIS_STATEMENT = (
    "Paper SMA/RSI round-trips in this laboratory earn more than cash "
    "after recorded costs."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in (s or ""))[:80]


def experiment_id_for(laboratory_id: str) -> str:
    return f"E-paper-round-trip-{_safe(normalize_laboratory_id(laboratory_id=laboratory_id))}"


def hypothesis_id_for(laboratory_id: str) -> str:
    return f"H-paper-round-trip-{_safe(normalize_laboratory_id(laboratory_id=laboratory_id))}"


def _is_fno_experience(exp: dict[str, Any]) -> bool:
    lab = str(exp.get("laboratory_id") or "").lower()
    if "fno" in lab:
        return True
    fields = exp.get("lab_fields") if isinstance(exp.get("lab_fields"), dict) else {}
    inst = exp.get("instrument") if isinstance(exp.get("instrument"), dict) else {}
    return bool(fields.get("fno_contract") or inst.get("nfo_tradingsymbol"))


def _is_rewarded_round_trip(exp: dict[str, Any]) -> bool:
    if not isinstance(exp, dict):
        return False
    if exp.get("not_a_trade") or str(exp.get("experience_type") or "") == "blocked_buy":
        return False
    if str(exp.get("event_kind") or "") == "blocked_buy":
        return False
    if str(exp.get("experience_type") or "") != "round_trip":
        return False
    reward = exp.get("reward") if isinstance(exp.get("reward"), dict) else {}
    return reward.get("status") == "computed" and reward.get("value") is not None


def load_round_trip_experiences(
    data_dir: str | Path | None,
    laboratory_id: str,
    *,
    limit_per_day: int = 400,
) -> list[dict[str, Any]]:
    """All rewarded round-trips for one lab. Does not pool laboratories."""
    lab = normalize_laboratory_id(laboratory_id=laboratory_id)
    root = learning_store_dir(data_dir, lab)
    if root is None or not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    want_fno = "fno" in lab.lower()
    for path in sorted(root.glob("*.jsonl")):
        day = path.stem
        for exp in load_learning_events(data_dir, lab, as_of_ist=day, limit=limit_per_day):
            if not _is_rewarded_round_trip(exp):
                continue
            row_lab = str(exp.get("laboratory_id") or lab)
            if normalize_laboratory_id(laboratory_id=row_lab) != lab:
                raise LaboratoryContaminationError(
                    f"experience laboratory {row_lab} != dataset {lab}"
                )
            if _is_fno_experience(exp) != want_fno:
                continue
            out.append(exp)
    return out


def experiences_to_dataset(
    experiences: list[dict[str, Any]],
    *,
    laboratory_id: str,
) -> dict[str, Any]:
    """PIT-shaped rows from paper closes. Target = recorded reward, not a new P&L."""
    lab = normalize_laboratory_id(laboratory_id=laboratory_id)
    want_fno = "fno" in lab.lower()
    rows: list[dict[str, Any]] = []
    for exp in experiences:
        if not isinstance(exp, dict):
            continue
        row_lab = str(exp.get("laboratory_id") or lab)
        if normalize_laboratory_id(laboratory_id=row_lab) != lab:
            raise LaboratoryContaminationError(
                f"experience laboratory {row_lab} != dataset {lab}"
            )
        if _is_fno_experience(exp) != want_fno:
            raise LaboratoryContaminationError(
                "refusing to mix F&O contract rows into a cash-equity FEL dataset"
                if not want_fno
                else "refusing to mix cash-equity rows into an F&O FEL dataset"
            )
        reward = exp.get("reward") if isinstance(exp.get("reward"), dict) else {}
        feats = exp.get("features") if isinstance(exp.get("features"), dict) else {}
        inst = exp.get("instrument") if isinstance(exp.get("instrument"), dict) else {}
        symbol = str(inst.get("symbol") or exp.get("symbol") or "")
        ret = reward.get("return_pct")
        value = ret if ret is not None else reward.get("value")
        rows.append(
            {
                "as_of": exp.get("as_of_ist"),
                "symbol": symbol,
                "laboratory_id": lab,
                "features": {
                    "rsi": feats.get("rsi"),
                    "sma_fast": feats.get("sma_fast"),
                    "sma_slow": feats.get("sma_slow"),
                },
                "target": {
                    "target_id": "paper_round_trip_reward",
                    "horizon": "round_trip",
                    "value": value,
                    "reward_inr": reward.get("value"),
                },
                "experience_id": exp.get("experience_id"),
                "fingerprint": exp.get("fingerprint"),
            }
        )
    return {
        "dataset_id": f"DS-{experiment_id_for(lab)}",
        "version": VERSION,
        "laboratory_id": lab,
        "decision_type": "buy_name",
        "feature_ids": ["rsi", "sma_fast", "sma_slow"],
        "target_id": "paper_round_trip_reward",
        "n_rows": len(rows),
        "source": "paper_round_trip_experiences",
        "built_at": _now(),
        "rows": rows,
        "honesty": (
            "Rows are closed paper experiences with a computed book reward. "
            "Not Yahoo PIT. Not F&O mixed into equity. Not RL."
        ),
    }


def evaluate_vs_cash(dataset: dict[str, Any]) -> dict[str, Any]:
    """Cash baseline = 0. Candidate = mean recorded reward. Not walk-forward, not RL."""
    vals: list[float] = []
    for row in dataset.get("rows") or []:
        tgt = row.get("target") if isinstance(row.get("target"), dict) else {}
        raw = tgt.get("value")
        if raw is None:
            continue
        try:
            vals.append(float(raw))
        except (TypeError, ValueError):
            continue
    n = len(vals)
    mean = round(sum(vals) / n, 6) if n else None
    wins = sum(1 for v in vals if v > 1e-9)
    baseline = 0.0
    if n < MIN_SAMPLE:
        result = "invalid"
        reason = f"insufficient_sample (n={n} < {MIN_SAMPLE})"
    elif mean is not None and mean < -1e-9:
        result = "worse"
        reason = "paper round-trips did not beat cash after costs"
    elif mean is not None and mean > 1e-9:
        result = "no_significant"
        reason = "mean reward above cash but sample too small to promote SMA/RSI"
    else:
        result = "no_significant"
        reason = "flat vs cash after costs"
    promo = promotion_for(result=result)
    if promo == LIVE_CONTROL:
        raise ValueError("FEL must not promote to live_control")
    return {
        "evaluator_id": "paper_vs_cash",
        "version": VERSION,
        "result": result,
        "reason": reason,
        "n": n,
        "n_wins": wins,
        "baseline_economic": baseline,
        "candidate_economic": mean,
        "delta_economic": None if mean is None else round(mean - baseline, 6),
        "promotion": promo,
        "mutates_strategy": False,
        "honesty": (
            "Cash baseline is zero (the trade was optional). "
            "A single close does not change SMA/RSI. Not RL."
        ),
    }


def _verdict_for(result: str) -> str:
    return {
        "improve": "supported",
        "conditional": "partially_supported",
        "no_significant": "inconclusive",
        "worse": "rejected",
        "invalid": "inconclusive",
        "blocked_unavailable": "inconclusive",
    }.get(result, "inconclusive")


def _ensure_hypothesis(data_dir: str, laboratory_id: str) -> dict[str, Any]:
    hid = hypothesis_id_for(laboratory_id)
    existing = get_hypothesis(data_dir, hid, laboratory_id=laboratory_id)
    if existing:
        return existing
    created = create_hypothesis(
        data_dir,
        statement=HYPOTHESIS_STATEMENT,
        domain_tags=["paper", "round_trip", "sma_cross_rsi", "fel"],
        laboratory_id=laboratory_id,
        transfer_class="strategy",
        linked_experiment_ids=[],
        extra={"canonical_id": hid, "fel_kind": KIND},
    )
    row = dict(created.get("hypothesis") or {})
    if row and data_dir:
        row["hypothesis_id"] = hid
        root = hypothesis_store_dir(data_dir, laboratory_id=laboratory_id)
        path = root / "by_id" / f"{hid}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
        old = root / "by_id" / f"{(created.get('hypothesis') or {}).get('hypothesis_id')}.json"
        if old != path and old.is_file():
            try:
                old.unlink()
            except OSError:
                pass
    return get_hypothesis(data_dir, hid, laboratory_id=laboratory_id) or row


def persist_finding(data_dir: str | Path | None, doc: dict[str, Any]) -> Path | None:
    """Durable 'this hypothesis did not survive' record. Not pgvector."""
    if not data_dir or not isinstance(doc, dict):
        return None
    lab = normalize_laboratory_id(
        laboratory_id=doc.get("laboratory_id") or DEFAULT_SWING_LAB
    )
    root = Path(data_dir) / FINDINGS_REL / _safe(lab)
    root.mkdir(parents=True, exist_ok=True)
    eid = _safe(str(doc.get("experiment_id") or "paper"))
    path = root / f"{eid}.json"
    finding = {
        "kind": "FEL_FINDING",
        "version": VERSION,
        "experiment_id": doc.get("experiment_id"),
        "hypothesis_id": doc.get("hypothesis_id"),
        "laboratory_id": lab,
        "statement": HYPOTHESIS_STATEMENT,
        "result": doc.get("result"),
        "reason": doc.get("reason"),
        "belief": (doc.get("belief") or {}).get("note") or doc.get("reason"),
        "status": (doc.get("hypothesis") or {}).get("status")
        or (doc.get("belief") or {}).get("status"),
        "promotion": doc.get("promotion"),
        "n_experiences": (doc.get("evaluation") or {}).get("n"),
        "did_not_survive": str(doc.get("result") or "") == "worse",
        "not_live_control": True,
        "not_vector_memory": True,
        "not_rl": True,
        "recorded_at": _now(),
    }
    path.write_text(json.dumps(finding, indent=2) + "\n", encoding="utf-8")
    return path


def run_paper_round_trip(
    data_dir: str | Path | None,
    *,
    laboratory_id: str | None = None,
) -> dict[str, Any]:
    """Build dataset from paper experiences, evaluate vs cash, persist belief."""
    if not data_dir:
        return {
            "experiment_id": experiment_id_for(DEFAULT_SWING_LAB),
            "result": "invalid",
            "reason": "no_data_dir",
            "promotion": "never",
        }
    lab = normalize_laboratory_id(laboratory_id=laboratory_id or DEFAULT_SWING_LAB)
    eid = experiment_id_for(lab)
    hid = hypothesis_id_for(lab)
    exps = load_round_trip_experiences(data_dir, lab)
    dataset = experiences_to_dataset(exps, laboratory_id=lab)
    persist_pit_dataset(data_dir, dataset)
    evaluation = evaluate_vs_cash(dataset)
    result = str(evaluation.get("result") or "invalid")
    reason = str(evaluation.get("reason") or "")
    promo = str(evaluation.get("promotion") or "never")
    if promo == LIVE_CONTROL:
        raise ValueError("FEL must not promote to live_control")
    survived = result not in {"worse", "invalid"}
    belief_note = (
        "this hypothesis did not survive"
        if result == "worse"
        else reason
    )
    doc: dict[str, Any] = {
        "experiment_id": eid,
        "version": VERSION,
        "kind": KIND,
        "hypothesis_id": hid,
        "laboratory_id": lab,
        "dataset_id": dataset.get("dataset_id"),
        "n_experiences": len(exps),
        "evaluation": evaluation,
        "result": result,
        "reason": reason,
        "promotion": promo,
        "mutates_strategy": False,
        "belief": {
            "statement": HYPOTHESIS_STATEMENT,
            "status": result,
            "note": belief_note,
            "survived": survived,
            "not_a_live_control_change": True,
            "not_rl": True,
        },
        "created_at": _now(),
        "honesty": (
            "Paper experiences became a FEL dataset and a cash-baseline belief. "
            "SMA/RSI V1 is unchanged. Not vector memory."
        ),
    }
    hyp = _ensure_hypothesis(str(data_dir), lab)
    ids = list(hyp.get("linked_experiment_ids") or [])
    if eid not in ids:
        ids.append(eid)
    hyp["linked_experiment_ids"] = ids[-20:]
    try:
        root = hypothesis_store_dir(data_dir, laboratory_id=lab)
        path = root / "by_id" / f"{hid}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(hyp, indent=2) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        _log.debug("hypothesis link persist failed", exc_info=True)
    try:
        evidence_n = int(evaluation.get("n") or 0)
        verdict = record_verdict(
            data_dir,
            hypothesis_id=hid,
            verdict=_verdict_for(result),
            laboratory_id=lab,
            evidence_n=evidence_n,
            note=belief_note,
            force=evidence_n >= MIN_SAMPLE,
        )
    except Exception as exc:  # noqa: BLE001
        _log.warning("paper hypothesis verdict failed: %s", exc)
        verdict = {"error": str(exc)}
    doc["hypothesis"] = {
        "hypothesis_id": hid,
        "status": (verdict.get("hypothesis") or hyp or {}).get("status"),
        "verdict": (verdict.get("hypothesis") or {}).get("verdict"),
    }
    persist_experiment(data_dir, doc)
    persist_finding(data_dir, doc)
    return doc


def enqueue_if_sample_grew(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
) -> dict[str, Any]:
    """Queue one paper experiment per lab when rewarded n is new or grew."""
    from atlas.investment.fel.queue import enqueue, get_item

    if not data_dir:
        return {"ok": False, "reason": "no_data_dir"}
    lab = normalize_laboratory_id(laboratory_id=laboratory_id)
    eid = experiment_id_for(lab)
    n = len(load_round_trip_experiences(data_dir, lab))
    if n == 0:
        return {"ok": True, "skipped": True, "reason": "no_rewarded_round_trips", "n": 0}
    existing = get_item(data_dir, eid)
    prev_n = None
    if existing and isinstance(existing.get("params"), dict):
        try:
            prev_n = int(existing["params"].get("n_experiences"))
        except (TypeError, ValueError):
            prev_n = None
    grew = existing is not None and str(existing.get("status") or "") == "COMPLETED" and prev_n != n
    row = enqueue(
        data_dir,
        kind=KIND,
        experiment_id=eid,
        laboratory_id=lab,
        params={"n_experiences": n, "laboratory_id": lab},
        skip_if_complete=not grew,
    )
    return {"ok": True, "skipped": not grew and str(row.get("status") or "") == "COMPLETED", "item": row, "n": n}


def enqueue_mail_labs(data_dir: str | Path | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for lab in MAIL_SNAPSHOT_LABS:
        try:
            out.append(enqueue_if_sample_grew(data_dir, laboratory_id=lab))
        except Exception:  # noqa: BLE001
            _log.debug("paper FEL enqueue skipped for %s", lab, exc_info=True)
    return out
