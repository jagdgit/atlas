"""OI-DELI0 P0.4 — durable trade lineage + order intent (shadow).

Every new fill gets a lineage record **or** an explicit integrity failure.
A write failure never blocks the fill; the trade is marked ``lineage_incomplete``.

Order intent is never reconstructed from the eventual outcome.
An engine HOLD must never be presented as the rationale for an overlay BUY.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

VERSION = "deli.trade_lineage.v1"
IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.trade_lineage")

# Shadow by default; ``enforce`` reserved for later reconciliation consumers.
MODE_ENV = "ATLAS_TRADE_LINEAGE_MODE"


def lineage_mode() -> str:
    return (os.environ.get(MODE_ENV) or "shadow").strip().lower() or "shadow"


def _ist_day(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(IST).date().isoformat()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def content_hash(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_order_intent(
    *,
    side: str,
    symbol: str,
    quantity: float,
    price: float | None = None,
    rationale_source: str,
    rationale_text: str | None = None,
    engine_decision_id: str | None = None,
    engine_action: str | None = None,
    overlay_decision_id: str | None = None,
    overlay_used: bool = False,
    laboratory_id: str | None = None,
    instrument_path: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an explicit pre-fill order intent (never invent from a fill)."""
    side_l = str(side or "").lower()
    engine_act = str(engine_action or "").lower() or None
    source = str(rationale_source or "").strip() or "unknown"

    # Hard rule: HOLD cannot own a BUY rationale.
    if side_l == "buy" and engine_act == "hold" and source == "engine":
        source = "invalid_engine_hold"
    if overlay_used and side_l == "buy":
        if source in {"", "unknown", "engine", "invalid_engine_hold"}:
            source = "fno_overlay"

    intent = {
        "version": VERSION,
        "order_intent_id": str(uuid4()),
        "created_at": _utcnow_iso(),
        "side": side_l,
        "symbol": str(symbol or ""),
        "quantity": float(quantity),
        "price": float(price) if price is not None else None,
        "rationale_source": source,
        "rationale_text": (str(rationale_text)[:500] if rationale_text else None),
        "engine_decision_id": str(engine_decision_id) if engine_decision_id else None,
        "engine_action": engine_act,
        "overlay_decision_id": str(overlay_decision_id) if overlay_decision_id else None,
        "overlay_used": bool(overlay_used),
        "laboratory_id": laboratory_id,
        "instrument_path": instrument_path,
    }
    if extra:
        intent["extra"] = dict(extra)
    intent["content_hash"] = content_hash(
        {k: v for k, v in intent.items() if k != "content_hash"}
    )
    return intent


def _validate(
    *,
    order_intent: dict[str, Any] | None,
    side: str,
    entry_decision_id: str | None,
    overlay_decision_id: str | None,
    parent_decision_id: str | None,
) -> list[str]:
    issues: list[str] = []
    if order_intent is None:
        issues.append("missing_order_intent")
    else:
        src = str(order_intent.get("rationale_source") or "")
        eng = str(order_intent.get("engine_action") or "").lower()
        if str(side).lower() == "buy" and eng == "hold":
            if src == "engine":
                issues.append("hold_as_buy_rationale")
            if entry_decision_id and order_intent.get("engine_decision_id"):
                if str(entry_decision_id) == str(order_intent.get("engine_decision_id")):
                    # Engine HOLD decision linked as the buy's entry decision.
                    if not overlay_decision_id:
                        issues.append("engine_hold_linked_as_entry_buy")
        if not order_intent.get("order_intent_id"):
            issues.append("order_intent_missing_id")
    if str(side).lower() == "buy" and not entry_decision_id and not overlay_decision_id:
        issues.append("missing_entry_decision_id")
    if str(side).lower() == "sell" and not entry_decision_id:
        # Exit decision may be absent until P0.5 — flag explicitly.
        issues.append("missing_exit_decision_id")
    return issues


def lineage_paths(data_dir: str | Path, *, laboratory_id: str, day: str) -> dict[str, Path]:
    root = Path(data_dir)
    lab = str(laboratory_id or "unknown").strip() or "unknown"
    return {
        "lineage": root
        / "investment"
        / "trade_lineage"
        / lab
        / f"{day}.jsonl",
        "failures": root / "investment" / "integrity" / "write_failures" / f"{day}.jsonl",
        "incomplete": root
        / "investment"
        / "integrity"
        / "lineage_incomplete"
        / lab
        / f"{day}.jsonl",
    }


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def write_trade_lineage(
    data_dir: str | Path | None,
    *,
    trade: dict[str, Any],
    laboratory_id: str | None = None,
    order_intent: dict[str, Any] | None = None,
    entry_decision_id: str | None = None,
    overlay_decision_id: str | None = None,
    parent_decision_id: str | None = None,
    exit_decision_id: str | None = None,
    exit_reason_code: str | None = None,
    prediction_id: str | None = None,
    evidence_snapshot_ref: str | None = None,
    evidence_snapshot: dict[str, Any] | None = None,
    instrument_path: str | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """Persist lineage in shadow mode. Never raises to the fill path."""
    log = logger or _log
    result: dict[str, Any] = {
        "ok": False,
        "lineage_incomplete": True,
        "mode": lineage_mode(),
        "version": VERSION,
    }
    if not data_dir:
        result["error"] = "no_data_dir"
        return result

    side = str(trade.get("side") or "").lower()
    fill_id = str(trade.get("id") or trade.get("trade_id") or "") or None
    lab = str(
        laboratory_id
        or trade.get("laboratory_id")
        or trade.get("portfolio_key")
        or "unknown"
    )
    day = _ist_day()

    snap_hash = None
    snap_ref = evidence_snapshot_ref
    if evidence_snapshot is not None and snap_ref is None:
        snap_hash = content_hash(evidence_snapshot)
        snap_ref = f"inline:sha256:{snap_hash}"
    elif evidence_snapshot is not None:
        snap_hash = content_hash(evidence_snapshot)

    # For overlay BUY: do not use engine HOLD decision as entry_decision_id.
    eng_act = None
    if isinstance(order_intent, dict):
        eng_act = str(order_intent.get("engine_action") or "").lower() or None
    effective_entry = entry_decision_id
    effective_parent = parent_decision_id
    if (
        side == "buy"
        and eng_act == "hold"
        and overlay_decision_id is None
        and entry_decision_id
        and isinstance(order_intent, dict)
        and str(order_intent.get("engine_decision_id") or "") == str(entry_decision_id)
    ):
        # Demote engine HOLD to parent; leave entry empty until P0.6 mints overlay id.
        effective_parent = entry_decision_id
        effective_entry = None

    issues = _validate(
        order_intent=order_intent,
        side=side,
        entry_decision_id=effective_entry or exit_decision_id,
        overlay_decision_id=overlay_decision_id,
        parent_decision_id=effective_parent,
    )
    if side == "sell":
        # Re-classify sell decision gap
        issues = [i for i in issues if i != "missing_entry_decision_id"]
        if not exit_decision_id:
            if "missing_exit_decision_id" not in issues:
                issues.append("missing_exit_decision_id")

    incomplete = bool(issues)
    record = {
        "version": VERSION,
        "lineage_id": str(uuid4()),
        "recorded_at": _utcnow_iso(),
        "ist_day": day,
        "mode": lineage_mode(),
        "laboratory_id": lab,
        "fill_trade_id": fill_id,
        "symbol": trade.get("symbol"),
        "side": side,
        "quantity": trade.get("quantity") or trade.get("qty"),
        "price": trade.get("price"),
        "entry_decision_id": effective_entry,
        "overlay_decision_id": overlay_decision_id,
        "parent_decision_id": effective_parent,
        "exit_decision_id": exit_decision_id if side == "sell" else None,
        "exit_reason_code": exit_reason_code if side == "sell" else None,
        "order_intent": order_intent,
        "order_intent_id": (order_intent or {}).get("order_intent_id")
        if isinstance(order_intent, dict)
        else None,
        "prediction_id": prediction_id,
        "evidence_snapshot_ref": snap_ref,
        "evidence_snapshot_hash": snap_hash,
        "instrument_path": instrument_path,
        "lineage_incomplete": incomplete,
        "integrity_issues": issues,
        "sim_decision_id_on_trade": trade.get("decision_id"),
    }
    record["content_hash"] = content_hash(
        {k: v for k, v in record.items() if k != "content_hash"}
    )
    result["lineage_id"] = record["lineage_id"]
    result["lineage_incomplete"] = incomplete
    result["integrity_issues"] = issues

    paths = lineage_paths(data_dir, laboratory_id=lab, day=day)
    try:
        _append_jsonl(paths["lineage"], record)
        if incomplete:
            _append_jsonl(
                paths["incomplete"],
                {
                    "lineage_id": record["lineage_id"],
                    "fill_trade_id": fill_id,
                    "symbol": record["symbol"],
                    "issues": issues,
                    "recorded_at": record["recorded_at"],
                },
            )
        result["ok"] = True
        result["path"] = str(paths["lineage"])
    except Exception as exc:  # noqa: BLE001
        log.exception("trade lineage write failed fill=%s", fill_id)
        result["ok"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["lineage_incomplete"] = True
        try:
            _append_jsonl(
                paths["failures"],
                {
                    "at": _utcnow_iso(),
                    "kind": "trade_lineage_write",
                    "fill_trade_id": fill_id,
                    "laboratory_id": lab,
                    "error": result["error"],
                    "record_stub": {
                        "symbol": record.get("symbol"),
                        "side": side,
                        "order_intent_id": record.get("order_intent_id"),
                    },
                },
            )
        except Exception:  # noqa: BLE001
            log.exception("integrity write_failure log also failed")
    return result


def shadow_after_fill(
    *,
    trade: dict[str, Any] | None,
    data_dir: str | Path | None = None,
    laboratory_id: str | None = None,
    lineage_ctx: dict[str, Any] | None = None,
    instrument_path: str | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """Called from ``apply_trade`` after a successful fill. Never raises."""
    log = logger or _log
    if not isinstance(trade, dict):
        return {"ok": False, "error": "no_trade"}
    ctx = dict(lineage_ctx or {})
    try:
        if data_dir is None:
            from atlas.config import get_config

            data_dir = get_config().paths.data
    except Exception:  # noqa: BLE001
        data_dir = None
    try:
        return write_trade_lineage(
            data_dir,
            trade=trade,
            laboratory_id=laboratory_id or ctx.get("laboratory_id"),
            order_intent=ctx.get("order_intent"),
            entry_decision_id=ctx.get("entry_decision_id"),
            overlay_decision_id=ctx.get("overlay_decision_id"),
            parent_decision_id=ctx.get("parent_decision_id"),
            exit_decision_id=ctx.get("exit_decision_id"),
            exit_reason_code=ctx.get("exit_reason_code"),
            prediction_id=ctx.get("prediction_id"),
            evidence_snapshot_ref=ctx.get("evidence_snapshot_ref"),
            evidence_snapshot=ctx.get("evidence_snapshot"),
            instrument_path=instrument_path or ctx.get("instrument_path"),
            logger=log,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("shadow_after_fill crashed")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "lineage_incomplete": True}
