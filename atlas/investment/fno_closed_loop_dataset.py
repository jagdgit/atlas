"""Canonical F&O closed-loop learning dataset — join, don't invent.

One row per closed Lab v1 round-trip:

    prediction → fill → exit → underlier move → option move
        → prediction error → attribution → experience / learning story

Built from durable stores already written on the close path. Does not mutate
SMA/RSI, PLC.A, capital allocation, or order authority. Belief stays
``unchanged`` unless an existing gate says otherwise.

A day is *pipeline-complete* when every session_flat close has:
  stated prediction, computed prediction_error, attribution status
  (evidence_backed | partial | unknown_explicit), EXPERIENCE + LEARNING_STORY.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "fno.closed_loop.dataset.v1"
STORE_REL = Path("investment") / "fno" / "closed_loop"
LABORATORY_ID = "india_fno_learner"

_ATTR_OK = frozenset({"evidence_backed", "partial", "unknown_explicit"})
_log = logging.getLogger("atlas.investment.fno_closed_loop_dataset")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_sym(symbol: str | None) -> str:
    return str(symbol or "").strip().replace("/", "_").replace(" ", "")


def day_dir(data_dir: str | Path | None, laboratory_id: str = LABORATORY_ID) -> Path | None:
    if not data_dir:
        return None
    return Path(data_dir) / STORE_REL / str(laboratory_id or LABORATORY_ID)


def day_jsonl_path(
    data_dir: str | Path | None,
    *,
    as_of_ist: str,
    laboratory_id: str = LABORATORY_ID,
) -> Path | None:
    root = day_dir(data_dir, laboratory_id)
    if root is None or not as_of_ist:
        return None
    return root / f"{as_of_ist}.jsonl"


def day_summary_path(
    data_dir: str | Path | None,
    *,
    as_of_ist: str,
    laboratory_id: str = LABORATORY_ID,
) -> Path | None:
    root = day_dir(data_dir, laboratory_id)
    if root is None or not as_of_ist:
        return None
    return root / f"{as_of_ist}.summary.json"


def _load_prediction(data_dir: str | Path, symbol: str) -> dict[str, Any] | None:
    try:
        from atlas.investment import fno_lab_v1 as lab_v1

        return lab_v1.load_entry_prediction(data_dir, option_symbol=symbol)
    except Exception:  # noqa: BLE001
        return None


def _underlier_move(attr: dict[str, Any] | None) -> dict[str, Any] | None:
    causal = (attr or {}).get("causal_factors") if isinstance(attr, dict) else None
    if not isinstance(causal, dict):
        return None
    ev = causal.get("fno_rt_evidence") if isinstance(causal.get("fno_rt_evidence"), dict) else {}
    obs = ev.get("observables") if isinstance(ev.get("observables"), dict) else {}
    sess = obs.get("underlying_session") if isinstance(obs.get("underlying_session"), dict) else None
    factors = causal.get("factors") if isinstance(causal.get("factors"), list) else []
    und_factor = next(
        (f for f in factors if isinstance(f, dict) and f.get("factor") == "underlying_move"),
        None,
    )
    return {
        "session": sess,
        "role": (und_factor or {}).get("role"),
        "evidence": (und_factor or {}).get("evidence"),
        "price_change_pct": causal.get("price_change_pct"),
    }


def _decide_time_features(
    exp: dict[str, Any], pred_file: dict[str, Any] | None
) -> dict[str, Any]:
    """What was known at entry. Absent inputs stay absent, never defaulted to 0."""
    out: dict[str, Any] = {}
    stored = exp.get("features") if isinstance(exp.get("features"), dict) else {}
    out.update({k: v for k, v in stored.items() if v is not None})
    pred = pred_file if isinstance(pred_file, dict) else {}
    for key in (
        "sma_margin",
        "rsi",
        "sma_fast",
        "sma_slow",
        "control_action",
        "option_type",
        "underlying_type",
        "direction",
        "er_model",
    ):
        if out.get(key) is None and pred.get(key) is not None:
            out[key] = pred[key]
    for ev in pred.get("key_evidence") or []:
        text = str(ev)
        if text.startswith("control=") and not out.get("signal"):
            out["signal"] = text.split("=", 1)[1].split(" ", 1)[0]
    return out


def _option_move(attr: dict[str, Any] | None, entry: dict[str, Any], exit_: dict[str, Any]) -> dict[str, Any]:
    causal = (attr or {}).get("causal_factors") if isinstance(attr, dict) else None
    factors = (causal or {}).get("factors") if isinstance(causal, dict) else []
    prem = next(
        (
            f
            for f in (factors or [])
            if isinstance(f, dict) and f.get("factor") == "option_premium_path"
        ),
        None,
    )
    entry_px = entry.get("price") if isinstance(entry, dict) else None
    exit_px = exit_.get("price") if isinstance(exit_, dict) else None
    ret = None
    try:
        if entry_px is not None and exit_px is not None and float(entry_px) > 0:
            ret = 100.0 * (float(exit_px) - float(entry_px)) / float(entry_px)
    except (TypeError, ValueError):
        ret = None
    return {
        "entry_premium": entry_px,
        "exit_premium": exit_px,
        "premium_return_pct": ret,
        "role": (prem or {}).get("role"),
        "evidence": (prem or {}).get("evidence"),
    }


def _chain_complete(row: dict[str, Any]) -> bool:
    pred = row.get("prediction") if isinstance(row.get("prediction"), dict) else {}
    err = row.get("prediction_error") if isinstance(row.get("prediction_error"), dict) else {}
    attr = row.get("attribution") if isinstance(row.get("attribution"), dict) else {}
    status = str(attr.get("status") or "").strip().lower()
    return bool(
        pred.get("prediction_status") in {"stated", "resolved", "consumed"}
        and err.get("status") == "computed"
        and status in _ATTR_OK
        and row.get("experience_id")
        and row.get("learning_story_id")
        and row.get("exit")
        and row.get("entry")
    )


def assemble_closed_loop_rows(
    data_dir: str | Path | None,
    *,
    as_of_ist: str,
    laboratory_id: str = LABORATORY_ID,
    limit: int = 500,
) -> dict[str, Any]:
    """Join day's EXPERIENCE + LEARNING_STORY (+ entry predictions) into canonical rows."""
    if not data_dir or not as_of_ist:
        return {
            "version": VERSION,
            "ok": False,
            "reason": "missing_data_dir_or_day",
            "rows": [],
            "n_rows": 0,
        }
    from atlas.investment.learning_objects import load_learning_events

    events = load_learning_events(
        data_dir, laboratory_id, as_of_ist=as_of_ist, limit=limit
    )
    experiences = [e for e in events if e.get("kind") == "EXPERIENCE"]
    stories = {
        str(e.get("experience_id") or ""): e
        for e in events
        if e.get("kind") == "LEARNING_STORY" and e.get("experience_id")
    }

    from atlas.investment.learning_quarantine import is_learning_eligible, quarantined_ids

    held = quarantined_ids(data_dir, laboratory_id)
    rows: list[dict[str, Any]] = []
    for exp in experiences:
        if not isinstance(exp, dict):
            continue
        symbol = str(exp.get("symbol") or "").strip()
        if not symbol:
            continue
        eid = str(exp.get("experience_id") or "")
        story = stories.get(eid) if eid else None
        pred_file = _load_prediction(data_dir, symbol)
        predicted = exp.get("predicted") if isinstance(exp.get("predicted"), dict) else {}
        if not predicted and isinstance(pred_file, dict):
            predicted = {
                "expected_return": pred_file.get("expected_return"),
                "expected_direction": pred_file.get("expected_direction"),
                "confidence": pred_file.get("predicted_probability")
                or pred_file.get("opportunity_confidence"),
                "prediction_status": pred_file.get("prediction_status") or "stated",
                "prediction_horizon": pred_file.get("prediction_horizon"),
                "er_model": pred_file.get("er_model"),
                "decision_id": pred_file.get("decision_id"),
                "experiment_id": pred_file.get("experiment_id")
                or pred_file.get("experiment_family"),
                "thesis": pred_file.get("thesis"),
            }
        entry = exp.get("entry") if isinstance(exp.get("entry"), dict) else {}
        exit_ = exp.get("exit") if isinstance(exp.get("exit"), dict) else {}
        attr = exp.get("attribution") if isinstance(exp.get("attribution"), dict) else {}
        err = (
            exp.get("prediction_error")
            if isinstance(exp.get("prediction_error"), dict)
            else {}
        )
        # Prefer story error / outcome when EXPERIENCE is thinner.
        if not err and isinstance(story, dict) and isinstance(story.get("error"), dict):
            err = story["error"]
        underlier = _underlier_move(attr)
        option = _option_move(attr, entry, exit_)
        causal = attr.get("causal_factors") if isinstance(attr.get("causal_factors"), dict) else {}
        ev_pack = (
            causal.get("fno_rt_evidence")
            if isinstance(causal.get("fno_rt_evidence"), dict)
            else {}
        )
        obs = (
            ev_pack.get("observables")
            if isinstance(ev_pack.get("observables"), dict)
            else {}
        )
        row = {
            "version": VERSION,
            "kind": "FNO_CLOSED_LOOP_ROW",
            "laboratory_id": laboratory_id,
            "as_of_ist": as_of_ist,
            "symbol": symbol,
            "underlying": obs.get("underlying") or (pred_file or {}).get("underlying"),
            "option_type": obs.get("option_right") or (pred_file or {}).get("option_type"),
            "experience_id": eid or None,
            "learning_eligible": is_learning_eligible(exp, quarantined=held),
            "learning_story_id": (story or {}).get("story_id"),
            "decision_id": predicted.get("decision_id")
            or (pred_file or {}).get("decision_id"),
            "experiment_id": predicted.get("experiment_id")
            or (pred_file or {}).get("experiment_id")
            or (pred_file or {}).get("experiment_family"),
            "prediction": predicted,
            # Decide-time features so the cognitive loop can group episodes on what
            # was known at entry, not on what the outcome turned out to be.
            "features": _decide_time_features(exp, pred_file),
            "entry": entry,
            "exit": exit_,
            "fill": {
                "entry_trade_id": entry.get("trade_id") or (pred_file or {}).get("trade_id"),
                "exit_trade_id": exit_.get("trade_id"),
                "entry_premium": entry.get("price"),
                "exit_premium": exit_.get("price"),
                "entry_at": entry.get("at") or (pred_file or {}).get("entry_time"),
                "exit_at": exit_.get("at"),
            },
            "underlier_movement": underlier,
            "option_movement": option,
            "prediction_error": err,
            "attribution": {
                "status": attr.get("status"),
                "required": attr.get("required"),
                "satisfied": attr.get("satisfied"),
                "helped": causal.get("helped"),
                "hurt": causal.get("hurt"),
                "unknown": causal.get("unknown"),
                "missing_evidence": causal.get("missing_evidence"),
                "narrative": causal.get("narrative"),
            },
            "outcome": {
                "realized_pnl": exp.get("pnl"),
                "realized_return_pct": err.get("realized_return_pct"),
                "direction_match": err.get("direction_match"),
            },
            "belief_update": exp.get("belief_update")
            or (story or {}).get("belief_update")
            or "unchanged",
            "lessons": list(exp.get("lessons") or (story or {}).get("lessons") or []),
            "sources": {
                "learning_jsonl": f"investment/learning/{laboratory_id}/{as_of_ist}.jsonl",
                "entry_prediction": (
                    f"investment/fno/lab_v1_predictions/{_safe_sym(symbol).replace('.', '_')}.json"
                    if pred_file
                    else None
                ),
            },
            "chain_complete": False,
            "honesty": (
                "Joined from durable close-path stores. Single RT is PROVISIONAL — "
                "not L5, not a strategy edge, belief_update unchanged unless gated."
            ),
            "assembled_at": _now(),
        }
        # Prefer prediction file path with lab_v1 helper naming
        if pred_file:
            try:
                from atlas.investment import fno_lab_v1 as lab_v1

                pth = lab_v1.prediction_path(data_dir, option_symbol=symbol)
                if pth is not None:
                    row["sources"]["entry_prediction"] = str(
                        pth.relative_to(Path(data_dir))
                    )
            except Exception:  # noqa: BLE001
                pass
        row["chain_complete"] = _chain_complete(row)
        rows.append(row)

    complete = [r for r in rows if r.get("chain_complete")]
    incomplete = [r for r in rows if not r.get("chain_complete")]
    return {
        "version": VERSION,
        "ok": True,
        "laboratory_id": laboratory_id,
        "as_of_ist": as_of_ist,
        "n_rows": len(rows),
        "n_complete": len(complete),
        "n_incomplete": len(incomplete),
        "pipeline_complete": bool(rows) and not incomplete,
        "symbols": [r.get("symbol") for r in rows],
        "incomplete_symbols": [r.get("symbol") for r in incomplete],
        "rows": rows,
        "built_at": _now(),
        "honesty": (
            "Canonical closed-loop join for Lab v1 session_flat RTs. "
            "Does not invent IV/greeks/news. Does not promote lessons to live control."
        ),
    }


def persist_closed_loop_dataset(
    data_dir: str | Path | None,
    doc: dict[str, Any],
    *,
    resolve_predictions: bool = True,
) -> dict[str, Any]:
    """Write day jsonl + summary; optionally stamp entry predictions as consumed."""
    if not data_dir or not isinstance(doc, dict):
        return {"ok": False, "reason": "missing_args"}
    day = str(doc.get("as_of_ist") or "")
    lab = str(doc.get("laboratory_id") or LABORATORY_ID)
    jsonl = day_jsonl_path(data_dir, as_of_ist=day, laboratory_id=lab)
    summary = day_summary_path(data_dir, as_of_ist=day, laboratory_id=lab)
    if jsonl is None or summary is None:
        return {"ok": False, "reason": "bad_path"}
    rows = [r for r in (doc.get("rows") or []) if isinstance(r, dict)]
    try:
        jsonl.parent.mkdir(parents=True, exist_ok=True)
        with jsonl.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, default=str) + "\n")
        meta = {k: v for k, v in doc.items() if k != "rows"}
        meta["path"] = str(jsonl)
        meta["n_rows"] = len(rows)
        summary.write_text(json.dumps(meta, indent=2, default=str) + "\n", encoding="utf-8")
        latest = day_dir(data_dir, lab)
        if latest is not None:
            (latest / "_latest.summary.json").write_text(
                json.dumps(meta, indent=2, default=str) + "\n", encoding="utf-8"
            )
    except OSError as exc:
        _log.debug("closed-loop persist failed", exc_info=True)
        return {"ok": False, "reason": type(exc).__name__}

    resolved = 0
    if resolve_predictions:
        for row in rows:
            if not row.get("chain_complete"):
                continue
            if _resolve_prediction(data_dir, row):
                resolved += 1

    return {
        "ok": True,
        "path": str(jsonl),
        "summary_path": str(summary),
        "n_rows": len(rows),
        "n_complete": int(doc.get("n_complete") or 0),
        "pipeline_complete": bool(doc.get("pipeline_complete")),
        "predictions_resolved": resolved,
    }


def _resolve_prediction(data_dir: str | Path, row: dict[str, Any]) -> bool:
    """Stamp entry prediction as consumed by a closed-loop outcome (idempotent)."""
    symbol = str(row.get("symbol") or "")
    if not symbol:
        return False
    try:
        from atlas.investment import fno_lab_v1 as lab_v1

        pred = lab_v1.load_entry_prediction(data_dir, option_symbol=symbol)
        if not isinstance(pred, dict):
            return False
        if pred.get("prediction_status") == "consumed" and pred.get(
            "closed_loop_experience_id"
        ) == row.get("experience_id"):
            return True
        pred["prediction_status"] = "consumed"
        pred["consumed_at"] = _now()
        pred["closed_loop_experience_id"] = row.get("experience_id")
        pred["closed_loop_as_of_ist"] = row.get("as_of_ist")
        pred["outcome_realized_pnl"] = (row.get("outcome") or {}).get("realized_pnl")
        pred["outcome_direction_match"] = (row.get("outcome") or {}).get(
            "direction_match"
        )
        pred["prediction_error"] = row.get("prediction_error")
        pred["honesty_consumed"] = (
            "Decide-time prediction consumed by session_flat close. "
            "Not L5. Not a live-control license."
        )
        out = lab_v1.persist_entry_prediction(data_dir, pred)
        return bool(out.get("ok"))
    except Exception:  # noqa: BLE001
        _log.debug("resolve prediction failed for %s", symbol, exc_info=True)
        return False


def build_and_persist_day(
    data_dir: str | Path | None,
    *,
    as_of_ist: str,
    laboratory_id: str = LABORATORY_ID,
    resolve_predictions: bool = True,
) -> dict[str, Any]:
    doc = assemble_closed_loop_rows(
        data_dir, as_of_ist=as_of_ist, laboratory_id=laboratory_id
    )
    if not doc.get("ok"):
        return doc
    persisted = persist_closed_loop_dataset(
        data_dir, doc, resolve_predictions=resolve_predictions
    )
    return {**doc, "persist": persisted, "rows": doc.get("rows")}


def load_closed_loop_episodes(
    data_dir: str | Path | None,
    *,
    laboratory_id: str = LABORATORY_ID,
    max_days: int = 60,
) -> list[dict[str, Any]]:
    """Every persisted episode, newest day last. The cognitive loop reasons over
    all closed episodes it has, not only today's."""
    if not data_dir:
        return []
    root = Path(data_dir) / STORE_REL / str(laboratory_id)
    if not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.jsonl"))[-max_days:]:
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
        except (OSError, json.JSONDecodeError):
            continue
    return rows


def load_closed_loop_day(
    data_dir: str | Path | None,
    *,
    as_of_ist: str,
    laboratory_id: str = LABORATORY_ID,
) -> dict[str, Any] | None:
    path = day_jsonl_path(data_dir, as_of_ist=as_of_ist, laboratory_id=laboratory_id)
    summary = day_summary_path(
        data_dir, as_of_ist=as_of_ist, laboratory_id=laboratory_id
    )
    if path is None or not path.is_file():
        return None
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
    except (OSError, json.JSONDecodeError):
        return None
    meta: dict[str, Any] = {}
    if summary is not None and summary.is_file():
        try:
            meta = json.loads(summary.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = {}
    if not isinstance(meta, dict):
        meta = {}
    meta["rows"] = rows
    meta.setdefault("n_rows", len(rows))
    meta.setdefault("as_of_ist", as_of_ist)
    meta.setdefault("laboratory_id", laboratory_id)
    return meta
