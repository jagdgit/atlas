"""OI-LINT0 Phase 4 — learning events, prediction error, five-track lessons.

Connects existing packets, E[R], attribution, and outcome_check into durable
EXPERIENCE records. Unknown attribution stays unknown — never invented.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

VERSION = "lint0.learning_objects.v1"
STORE_REL = Path("investment") / "learning"
_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.learning_objects")

LEARNING_EVENT_KINDS = frozenset(
    {
        "fill",
        "exit",
        "eod_flatten",
        "unexpected_move",
        "new_fundamental",
        "news_event",
        "policy_event",
        "contradiction",
        "falsifier",
        "strategy_failure",
        "missed_opportunity",
        "llm_failure",
        "challenger_crossed_threshold",
        "lab_policy_hold",
        "thesis_invalid",
        "outcome_check",
    }
)

LESSON_TRACKS = (
    "strategy",
    "market",
    "thesis",
    "atlas",
    "relative_opportunity",
)

_INTRADAY_LABS = frozenset({"equity_intraday_learner"})


def ist_today() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in (s or ""))[:80]


def _f(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def infer_learning_event_kind(
    *,
    action: str | None = None,
    strategy_tag: str | None = None,
    trigger: str | None = None,
) -> str:
    tag = str(strategy_tag or "").strip().lower()
    act = str(action or "").strip().lower()
    trig = str(trigger or "").strip().lower()
    if tag == "eod_flatten" or trig == "eod_flatten":
        return "eod_flatten"
    if tag in {"switch_advantage_cleared", "switch_exploratory"}:
        return "challenger_crossed_threshold"
    if tag.startswith("switch_blocked"):
        return "missed_opportunity"
    if tag in {"lab_policy_hold", "plc_a_hold"}:
        return "lab_policy_hold"
    if tag in {"thesis_invalid", "identity_quarantined"}:
        return "thesis_invalid"
    if trig in {"llm_unavailable", "unreviewed"} or tag == "llm_unavailable":
        return "llm_failure"
    if "contradiction" in tag or trig == "contradiction":
        return "contradiction"
    if trig == "falsifier" or "falsifier" in tag:
        return "falsifier"
    if trig in {"news_event", "policy_event"}:
        return trig
    if trig == "outcome_check" or tag == "outcome_check":
        return "outcome_check"
    if act == "buy":
        return "fill"
    if act in {"sell", "reduce"}:
        return "exit"
    if trig == "unexpected_move":
        return "unexpected_move"
    if trig == "new_fundamental":
        return "new_fundamental"
    return "fill" if act == "buy" else "exit" if act in {"sell", "reduce"} else "unexpected_move"


def compute_prediction_error(
    *,
    predicted_er: float | None,
    realized_return_pct: float | None,
    predicted_direction: str | None = None,
    observed_direction: str | None = None,
) -> dict[str, Any]:
    """Prediction vs outcome — explicit error, not silent match."""
    pred = _f(predicted_er)
    real = _f(realized_return_pct)
    err = None
    if pred is not None and real is not None:
        err = round(real - (pred * 100.0 if abs(pred) <= 1.5 else pred), 4)
    dir_match = "unknown"
    pd = str(predicted_direction or "").lower()
    od = str(observed_direction or "").lower()
    if pd and od and pd != "unknown" and od != "unknown":
        dir_match = "matched" if pd == od else "missed"
    status = "unknown"
    if err is not None:
        status = "computed"
    elif dir_match in {"matched", "missed"}:
        status = "direction_only"
    return {
        "predicted_er": pred,
        "realized_return_pct": real,
        "error_pct": err,
        "predicted_direction": pd or None,
        "observed_direction": od or None,
        "direction_match": dir_match,
        "status": status,
        "honesty": (
            "Prediction error requires stated E[R] or direction at decision time."
            if status == "unknown"
            else "error = realized − predicted (percent space when E[R] is decimal)."
        ),
    }


def build_lessons(
    *,
    strategy: str | None = None,
    market: str | None = None,
    thesis: str | None = None,
    atlas: str | None = None,
    relative_opportunity: str | None = None,
) -> dict[str, str | None]:
    """Five separate lesson tracks — never one blended IQ line."""
    return {
        "strategy": (strategy or "")[:500] or None,
        "market": (market or "")[:500] or None,
        "thesis": (thesis or "")[:500] or None,
        "atlas": (atlas or "")[:500] or None,
        "relative_opportunity": (relative_opportunity or "")[:500] or None,
    }


def attribution_required_for_close(
    *,
    laboratory_id: str | None,
    strategy_tag: str | None = None,
) -> bool:
    lab = str(laboratory_id or "").strip().lower()
    tag = str(strategy_tag or "").strip().lower()
    if lab in _INTRADAY_LABS or tag == "eod_flatten":
        return True
    return tag in {"exit", "sell", "reduce", "eod_flatten"}


def build_trading_experience(
    *,
    laboratory_id: str,
    symbol: str,
    event_kind: str,
    packet: dict[str, Any] | None = None,
    trade: dict[str, Any] | None = None,
    outcome_check: dict[str, Any] | None = None,
    attribution: dict[str, Any] | None = None,
    allocation: dict[str, Any] | None = None,
    as_of_ist: str | None = None,
) -> dict[str, Any]:
    """Context → decision → predicted E[R] → action → outcome → error → lessons."""
    pkt = packet if isinstance(packet, dict) else {}
    tr = trade if isinstance(trade, dict) else {}
    oc = outcome_check if isinstance(outcome_check, dict) else {}
    attr = attribution if isinstance(attribution, dict) else {}
    alloc = allocation if isinstance(allocation, dict) else {}

    expected = pkt.get("expected") if isinstance(pkt.get("expected"), dict) else {}
    meta = pkt.get("meta") if isinstance(pkt.get("meta"), dict) else {}
    if not alloc and isinstance(meta.get("allocation"), dict):
        alloc = meta["allocation"]

    pred_er = _f(expected.get("expected_return"))
    pnl = _f(tr.get("realized_pnl"))
    qty = _f(tr.get("quantity") or tr.get("qty"))
    price = _f(tr.get("price") or tr.get("fill_price"))
    cost = abs(qty * price) if qty and price else None
    realized_pct = None
    if pnl is not None and cost and cost > 0:
        realized_pct = round(100.0 * pnl / cost, 4)
    if realized_pct is None:
        realized_pct = _f(oc.get("price_change_pct"))

    pred_err = compute_prediction_error(
        predicted_er=pred_er,
        realized_return_pct=realized_pct,
        predicted_direction=oc.get("expected_direction"),
        observed_direction=oc.get("observed_direction"),
    )

    attr_payload = attr.get("payload") if isinstance(attr.get("payload"), dict) else {}
    causal = attr_payload.get("causal_factors") if isinstance(attr_payload.get("causal_factors"), dict) else {}
    attr_status = "unknown"
    if causal.get("helped") or causal.get("hurt"):
        attr_status = "attributed"
    elif causal.get("unknown"):
        attr_status = "all_unknown"
    elif attr:
        attr_status = "partial"

    need_attr = attribution_required_for_close(
        laboratory_id=laboratory_id,
        strategy_tag=str(pkt.get("strategy_tag") or event_kind),
    )
    closed = event_kind in {"exit", "eod_flatten", "fill"} and (
        event_kind != "fill" or str(pkt.get("action") or "").lower() == "sell"
    )

    strategy_lesson = None
    market_lesson = None
    thesis_lesson = None
    atlas_lesson = None
    rel_lesson = None
    if event_kind == "eod_flatten":
        strategy_lesson = (
            "Intraday lab closed flat — strategy expectancy recorded without "
            "overnight carry contamination."
        )
        atlas_lesson = "EOD flatten is mandatory for equity_intraday_learner."
    elif pred_err.get("direction_match") == "missed":
        strategy_lesson = "Direction miss — review signal vs thesis at entry."
        thesis_lesson = f"Thesis change candidate: {oc.get('thesis_change') or 'review'}"
    elif pred_err.get("direction_match") == "matched":
        strategy_lesson = "Direction matched stated expectation — thin sample until n grows."
    if attr_status == "all_unknown":
        market_lesson = "Could not determine primary cause — unknown remains unknown."
    elif attr_status == "attributed":
        helped = causal.get("helped") or []
        market_lesson = f"Attributed factors: {', '.join(str(x) for x in helped[:3])}"
    if alloc.get("best_challenger"):
        rel_lesson = (
            f"Next-rupee vs {alloc.get('best_challenger')}: "
            f"advantage={alloc.get('challenger_advantage')} "
            f"action={alloc.get('allocation_action')}"
        )

    belief_update = "unchanged"
    if oc.get("write_candidate"):
        belief_update = "candidate"
    elif oc.get("thesis_change") in {"weaken", "strengthen"}:
        belief_update = str(oc.get("thesis_change"))
    if event_kind == "llm_failure":
        belief_update = "UNREVIEWED"
        atlas_lesson = "LLM unavailable — not belief unchanged."

    exp_id = str(uuid4())
    return {
        "version": VERSION,
        "kind": "EXPERIENCE",
        "experience_id": exp_id,
        "event_kind": event_kind
        if event_kind in LEARNING_EVENT_KINDS
        else "unexpected_move",
        "laboratory_id": laboratory_id,
        "symbol": str(symbol or "").upper(),
        "as_of_ist": as_of_ist or ist_today(),
        "context": {
            "decision_id": pkt.get("decision_id") or pkt.get("id"),
            "strategy_tag": pkt.get("strategy_tag"),
            "action": pkt.get("action"),
            "er_completeness": expected.get("er_completeness"),
            "er_model": expected.get("er_model"),
        },
        "decision": {
            "action": pkt.get("action") or tr.get("side"),
            "reasons_for": list(pkt.get("reasons_for") or [])[:4],
            "reasons_against": list(pkt.get("reasons_against") or [])[:4],
            "allocation": alloc or None,
        },
        "predicted": {
            "expected_return": pred_er,
            "expected_direction": oc.get("expected_direction"),
            "confidence": expected.get("opportunity_confidence"),
        },
        "outcome": {
            "realized_pnl": pnl,
            "realized_return_pct": realized_pct,
            "trade_id": tr.get("id") or tr.get("trade_id"),
        },
        "prediction_error": pred_err,
        "evidence": {
            "observation_ids": list(pkt.get("observation_ids") or [])[:12],
            "outcome_check_id": oc.get("source_decision_id"),
            "attribution_id": attr.get("id"),
        },
        "attribution": {
            "status": attr_status,
            "required": bool(need_attr and closed),
            "satisfied": attr_status in {"attributed", "all_unknown", "partial"},
            "causal_factors": causal or None,
        },
        "lessons": build_lessons(
            strategy=strategy_lesson,
            market=market_lesson,
            thesis=thesis_lesson,
            atlas=atlas_lesson,
            relative_opportunity=rel_lesson,
        ),
        "belief_update": belief_update,
        "honesty": (
            "Experience requires decision + prediction + outcome + attribution "
            "or explicit unknown — not tick counts."
        ),
    }


def store_dir(data_dir: str | Path | None, laboratory_id: str) -> Path | None:
    if not data_dir:
        return None
    return Path(data_dir) / STORE_REL / _safe(laboratory_id or "lab")


def day_path(
    data_dir: str | Path | None,
    laboratory_id: str,
    as_of_ist: str | None = None,
) -> Path | None:
    root = store_dir(data_dir, laboratory_id)
    if root is None:
        return None
    return root / f"{(as_of_ist or ist_today()).strip()}.jsonl"


def record_learning_event(
    data_dir: str | Path | None,
    event: dict[str, Any],
) -> dict[str, Any]:
    """Append one LEARNING_EVENT or EXPERIENCE row."""
    if not data_dir or not isinstance(event, dict):
        return {"ok": False, "reason": "no_data_dir"}
    lab = str(event.get("laboratory_id") or "india_equity_learner")
    day = str(event.get("as_of_ist") or ist_today())
    path = day_path(data_dir, lab, day)
    if path is None:
        return {"ok": False, "reason": "no_path"}
    row = dict(event)
    row.setdefault("recorded_at", datetime.now(timezone.utc).isoformat())
    row.setdefault("version", VERSION)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
        return {"ok": True, "path": str(path), "experience_id": row.get("experience_id")}
    except OSError as exc:
        _log.debug("learning event persist failed", exc_info=True)
        return {"ok": False, "reason": type(exc).__name__}


def load_learning_events(
    data_dir: str | Path | None,
    laboratory_id: str,
    *,
    as_of_ist: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    path = day_path(data_dir, laboratory_id, as_of_ist)
    if path is None or not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                out.append(obj)
            if len(out) >= max(1, int(limit)):
                break
    except OSError:
        return []
    return out


def summarize_learning_day(events: list[dict[str, Any]] | None) -> dict[str, Any]:
    rows = [e for e in (events or []) if isinstance(e, dict)]
    experiences = [r for r in rows if r.get("kind") == "EXPERIENCE"]
    errors_computed = sum(
        1
        for r in experiences
        if (r.get("prediction_error") or {}).get("status") == "computed"
    )
    dir_miss = sum(
        1
        for r in experiences
        if (r.get("prediction_error") or {}).get("direction_match") == "missed"
    )
    attr_required = sum(
        1 for r in experiences if (r.get("attribution") or {}).get("required")
    )
    attr_ok = sum(
        1
        for r in experiences
        if (r.get("attribution") or {}).get("required")
        and (r.get("attribution") or {}).get("satisfied")
    )
    by_kind: dict[str, int] = {}
    for r in rows:
        k = str(r.get("event_kind") or "unknown")
        by_kind[k] = by_kind.get(k, 0) + 1
    return {
        "version": VERSION,
        "events": len(rows),
        "experiences": len(experiences),
        "prediction_errors_computed": errors_computed,
        "direction_misses": dir_miss,
        "attribution_required": attr_required,
        "attribution_satisfied": attr_ok,
        "by_kind": by_kind,
    }


def format_learning_objects_lines(summary: dict[str, Any] | None, *, limit: int = 4) -> list[str]:
    s = summary if isinstance(summary, dict) else {}
    lines = [
        "",
        "── Prediction error & experiences (OI-LINT0 Phase 4) ──",
        f"  experiences today: {s.get('experiences', 0)} · "
        f"prediction errors computed: {s.get('prediction_errors_computed', 0)} · "
        f"direction misses: {s.get('direction_misses', 0)}",
        f"  closed-lab attribution: {s.get('attribution_satisfied', 0)}/"
        f"{s.get('attribution_required', 0)} required",
    ]
    kinds = s.get("by_kind") if isinstance(s.get("by_kind"), dict) else {}
    if kinds:
        top = ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())[: max(1, limit)])
        lines.append(f"  event kinds: {top}")
    if int(s.get("experiences") or 0) == 0:
        lines.append("  (no durable experiences yet — fills/exits/flatten write here)")
    lines.append(
        "  Honesty: learned = prediction + outcome + error + attribution — not activity."
    )
    return lines


def record_from_trade_close(
    data_dir: str | Path | None,
    *,
    symbol: str,
    trade: dict[str, Any],
    laboratory_id: str,
    packet: dict[str, Any] | None = None,
    strategy_tag: str | None = None,
) -> dict[str, Any]:
    kind = infer_learning_event_kind(
        action="sell",
        strategy_tag=strategy_tag or (packet or {}).get("strategy_tag"),
    )
    exp = build_trading_experience(
        laboratory_id=laboratory_id,
        symbol=symbol,
        event_kind=kind,
        packet=packet,
        trade=trade,
    )
    return record_learning_event(data_dir, exp)


def record_from_outcome_check(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    packet: dict[str, Any],
    outcome_check: dict[str, Any],
) -> dict[str, Any]:
    exp = build_trading_experience(
        laboratory_id=laboratory_id,
        symbol=str(packet.get("symbol") or ""),
        event_kind="outcome_check",
        packet=packet,
        outcome_check=outcome_check,
    )
    return record_learning_event(data_dir, exp)


def record_challenger_threshold_event(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    review: dict[str, Any],
    executed: bool = False,
) -> dict[str, Any]:
    rev = review if isinstance(review, dict) else {}
    row = {
        "version": VERSION,
        "kind": "LEARNING_EVENT",
        "event_kind": "challenger_crossed_threshold",
        "laboratory_id": laboratory_id,
        "symbol": rev.get("hold_symbol"),
        "as_of_ist": ist_today(),
        "payload": {
            "hold_symbol": rev.get("hold_symbol"),
            "challenger_symbol": rev.get("challenger_symbol"),
            "expected_advantage": rev.get("expected_advantage"),
            "threshold": rev.get("threshold"),
            "decision": rev.get("decision"),
            "reason_code": rev.get("reason_code"),
            "executed": bool(executed),
        },
    }
    return record_learning_event(data_dir, row)
