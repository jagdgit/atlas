"""UTS.E — Switch Decisions, counterfactual horizons, Learning Records → LI.

Durable per-lab store. Never invents returns or confidence — missing prices
leave horizons ``pending`` / ``missing_prices``. Threshold changes are
**proposals only** (no live auto-tune).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

_log = logging.getLogger("atlas.investment.switch_learning")
VERSION = "uts.e.switch_learning"
STORE_REL = Path("investment") / "switch_learning"
_IST = ZoneInfo("Asia/Kolkata")

# Counterfactual horizons (calendar offsets in IST dates).
HORIZON_DAYS: tuple[int, ...] = (1, 5, 20, 60)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in (s or ""))


def ist_today(now: datetime | None = None) -> str:
    dt = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_IST).date().isoformat()


def store_dir(data_dir: str | Path, *, laboratory_id: str) -> Path:
    from atlas.investment.laboratory import normalize_laboratory_id

    lab = normalize_laboratory_id(laboratory_id=laboratory_id)
    return Path(data_dir) / STORE_REL / _safe(lab)


def _schedule_horizons(decision_ist: str) -> list[dict[str, Any]]:
    base = date.fromisoformat(str(decision_ist)[:10])
    rows: list[dict[str, Any]] = []
    for d in HORIZON_DAYS:
        rows.append(
            {
                "horizon_d": d,
                "due_ist": (base + timedelta(days=int(d))).isoformat(),
                "status": "pending",
                "completed_at": None,
                "hold_return": None,
                "switched_return": None,
                "excess_return": None,
                "was_switch_better": None,
                "note": None,
            }
        )
    return rows


def record_switch_decision(
    data_dir: str | Path | None,
    review: dict[str, Any] | None,
    *,
    laboratory_id: str | None = None,
    portfolio_key: str | None = None,
    executed: bool = False,
    packet_id: str | None = None,
    timeline_id: str | None = None,
    decision_ist: str | None = None,
    market_regime: str | None = None,
    sector_regime: str | None = None,
    volatility_regime: str | None = None,
) -> dict[str, Any]:
    """Persist one Switch Decision (taken or blocked). Always durable when data_dir set."""
    lab = laboratory_id or portfolio_key or "india_equity_learner"
    day = decision_ist or ist_today()
    rev = review if isinstance(review, dict) else {}
    hold_m = rev.get("hold_metrics") if isinstance(rev.get("hold_metrics"), dict) else {}
    chal_m = (
        rev.get("challenger_metrics")
        if isinstance(rev.get("challenger_metrics"), dict)
        else {}
    )
    row: dict[str, Any] = {
        "switch_id": str(uuid4()),
        "version": VERSION,
        "created_at": _now(),
        "decision_ist": day,
        "laboratory_id": lab,
        "portfolio_key": portfolio_key or lab,
        "hold_symbol": rev.get("hold_symbol"),
        "challenger_symbol": rev.get("challenger_symbol"),
        "decision": rev.get("decision") or "hold",
        "reason_code": rev.get("reason_code"),
        "expected_advantage": rev.get("expected_advantage"),
        "threshold": rev.get("threshold"),
        "exploratory": bool(rev.get("exploratory")),
        "label": rev.get("label")
        or ("exploratory" if rev.get("exploratory") else "calibrated"),
        "executed": bool(executed),
        "packet_id": packet_id,
        "timeline_id": timeline_id,
        "hold_expected_return": hold_m.get("expected_return"),
        "hold_confidence": hold_m.get("confidence"),
        "challenger_expected_return": chal_m.get("expected_return"),
        "challenger_confidence": chal_m.get("confidence"),
        "context": {
            "market_regime": market_regime,
            "sector_regime": sector_regime,
            "volatility_regime": volatility_regime,
            "lab_phase": rev.get("label"),
        },
        "horizons": _schedule_horizons(day),
        "learning_record_id": None,
        "review": {
            "version": rev.get("version"),
            "evaluated_challengers": rev.get("evaluated_challengers"),
            "evaluation": rev.get("evaluation"),
        },
    }
    if not data_dir:
        return {"ok": False, "honesty": "no data_dir", "decision": row}
    root = store_dir(data_dir, laboratory_id=lab)
    by_id = root / "by_id"
    by_id.mkdir(parents=True, exist_ok=True)
    path = by_id / f"{row['switch_id']}.json"
    path.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
    day_path = root / "decisions" / f"{day}.jsonl"
    day_path.parent.mkdir(parents=True, exist_ok=True)
    with day_path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps({"switch_id": row["switch_id"], "decision_ist": day}) + "\n"
        )
    return {"ok": True, "path": str(path), "decision": row}


def get_switch_decision(
    data_dir: str | Path | None,
    switch_id: str,
    *,
    laboratory_id: str | None = None,
) -> dict[str, Any] | None:
    if not data_dir or not switch_id:
        return None
    lab = laboratory_id or "india_equity_learner"
    path = store_dir(data_dir, laboratory_id=lab) / "by_id" / f"{switch_id}.json"
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _persist(data_dir: str | Path, row: dict[str, Any]) -> None:
    lab = str(row.get("laboratory_id") or "india_equity_learner")
    sid = row.get("switch_id")
    if not sid:
        return
    path = store_dir(data_dir, laboratory_id=lab) / "by_id" / f"{sid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")


def list_switch_decisions(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if not data_dir:
        return []
    root = store_dir(data_dir, laboratory_id=laboratory_id) / "by_id"
    if not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(doc, dict):
            rows.append(doc)
        if len(rows) >= max(1, int(limit)):
            break
    return rows


def build_switch_learning_record(decision: dict[str, Any]) -> dict[str, Any]:
    """Assemble LI-shaped Switch Learning Record from a decision + horizons."""
    ctx = decision.get("context") if isinstance(decision.get("context"), dict) else {}
    horizons = list(decision.get("horizons") or [])
    outcomes = {
        str(h.get("horizon_d")): {
            "hold_return": h.get("hold_return"),
            "switched_return": h.get("switched_return"),
            "excess_return": h.get("excess_return"),
            "was_switch_better": h.get("was_switch_better"),
            "status": h.get("status"),
        }
        for h in horizons
        if isinstance(h, dict)
    }
    primary_driver = None
    if decision.get("expected_advantage") is not None:
        primary_driver = "expected_advantage"
    return {
        "learning_record_id": decision.get("learning_record_id") or str(uuid4()),
        "version": VERSION,
        "switch_id": decision.get("switch_id"),
        "laboratory_id": decision.get("laboratory_id"),
        "context": {
            "market_regime": ctx.get("market_regime"),
            "sector_regime": ctx.get("sector_regime"),
            "volatility_regime": ctx.get("volatility_regime"),
            "lab_phase": ctx.get("lab_phase") or decision.get("label"),
            "exploratory": bool(decision.get("exploratory")),
        },
        "decision": {
            "hold_symbol": decision.get("hold_symbol"),
            "challenger_symbol": decision.get("challenger_symbol"),
            "expected_advantage": decision.get("expected_advantage"),
            "confidence": {
                "hold": decision.get("hold_confidence"),
                "challenger": decision.get("challenger_confidence"),
            },
            "threshold": decision.get("threshold"),
            "reason_code": decision.get("reason_code"),
            "executed": bool(decision.get("executed")),
            "why": {
                "hold_er": decision.get("hold_expected_return"),
                "challenger_er": decision.get("challenger_expected_return"),
                "label": decision.get("label"),
            },
        },
        "outcome": outcomes,
        "attribution": {
            "primary_driver": primary_driver,
            "incorrect_assumption": None,
            "missing_information": None,
            "preventable": "unknown",
        },
        "created_at": _now(),
    }


def publish_learning_record_to_li(
    data_dir: str | Path | None,
    record: dict[str, Any],
    *,
    laboratory_id: str | None = None,
) -> dict[str, Any] | None:
    """Append Switch Learning Record to lab LI store + evolution event."""
    if not data_dir or not isinstance(record, dict):
        return None
    lab = laboratory_id or str(record.get("laboratory_id") or "india_equity_learner")
    root = store_dir(data_dir, laboratory_id=lab)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "learning_records.jsonl"
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:  # noqa: BLE001
        _log.debug("switch learning record append failed", exc_info=True)
        return None
    try:
        from atlas.investment.learning_intelligence import append_evolution_event

        hold = (record.get("decision") or {}).get("hold_symbol")
        chal = (record.get("decision") or {}).get("challenger_symbol")
        code = (record.get("decision") or {}).get("reason_code")
        append_evolution_event(
            data_dir,
            laboratory_id=lab,
            axis="allocation",
            from_score=None,
            to_score=None,
            reason=f"switch_learning {hold}→{chal} ({code})",
            phase_id="UTS.E",
        )
    except Exception:  # noqa: BLE001
        _log.debug("LI evolution event for switch skipped", exc_info=True)
    return {
        "ok": True,
        "path": str(path),
        "learning_record_id": record.get("learning_record_id"),
    }


def resolve_horizon(
    data_dir: str | Path | None,
    switch_id: str,
    horizon_d: int,
    *,
    laboratory_id: str | None = None,
    hold_return: float | None = None,
    switched_return: float | None = None,
    note: str | None = None,
    publish_li: bool = True,
) -> dict[str, Any]:
    """Complete one horizon when returns are known. Fail-closed if missing."""
    lab = laboratory_id or "india_equity_learner"
    row = get_switch_decision(data_dir, switch_id, laboratory_id=lab)
    if not row:
        return {"ok": False, "honesty": "switch decision not found"}
    if hold_return is None or switched_return is None:
        for h in row.get("horizons") or []:
            if isinstance(h, dict) and int(h.get("horizon_d") or 0) == int(horizon_d):
                if h.get("status") == "pending":
                    h["status"] = "missing_prices"
                    h["note"] = note or "hold_return/switched_return not supplied"
                    h["completed_at"] = _now()
        if data_dir:
            _persist(data_dir, row)
        return {
            "ok": False,
            "honesty": "missing returns — horizon left missing_prices",
            "decision": row,
        }
    try:
        hr = float(hold_return)
        sr = float(switched_return)
    except (TypeError, ValueError):
        return {"ok": False, "honesty": "non-numeric returns"}
    excess = round(sr - hr, 6)
    better = sr > hr
    found = False
    for h in row.get("horizons") or []:
        if not isinstance(h, dict) or int(h.get("horizon_d") or 0) != int(horizon_d):
            continue
        h["status"] = "done"
        h["completed_at"] = _now()
        h["hold_return"] = hr
        h["switched_return"] = sr
        h["excess_return"] = excess
        h["was_switch_better"] = better
        h["note"] = note
        found = True
        break
    if not found:
        return {"ok": False, "honesty": f"horizon {horizon_d}d not on decision"}
    rec = build_switch_learning_record(row)
    if not row.get("learning_record_id"):
        row["learning_record_id"] = rec["learning_record_id"]
    else:
        rec["learning_record_id"] = row["learning_record_id"]
    if publish_li and data_dir:
        publish_learning_record_to_li(data_dir, rec, laboratory_id=lab)
    if data_dir:
        _persist(data_dir, row)
    return {"ok": True, "decision": row, "learning_record": rec, "excess_return": excess}


PriceFn = Callable[[str, str], float | None]


def _pct_return(px0: float | None, px1: float | None) -> float | None:
    if px0 is None or px1 is None:
        return None
    try:
        a = float(px0)
        b = float(px1)
    except (TypeError, ValueError):
        return None
    if a <= 0:
        return None
    return round((b - a) / a, 6)


def run_due_switch_horizons(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    as_of_ist: str | None = None,
    price_fn: PriceFn | None = None,
    limit: int = 40,
    publish_li: bool = True,
) -> dict[str, Any]:
    """Drain due horizons. Requires ``price_fn(symbol, ist_date)`` — never invents."""
    as_of = as_of_ist or ist_today()
    as_of_d = date.fromisoformat(str(as_of)[:10])
    completed = 0
    missing = 0
    scanned = 0
    details: list[dict[str, Any]] = []
    for row in list_switch_decisions(data_dir, laboratory_id=laboratory_id, limit=200):
        scanned += 1
        decision_day = str(row.get("decision_ist") or "")[:10]
        hold = str(row.get("hold_symbol") or "")
        chal = str(row.get("challenger_symbol") or "")
        for h in row.get("horizons") or []:
            if not isinstance(h, dict) or h.get("status") != "pending":
                continue
            due = str(h.get("due_ist") or "")[:10]
            if not due:
                continue
            try:
                if date.fromisoformat(due) > as_of_d:
                    continue
            except ValueError:
                continue
            if completed + missing >= limit:
                break
            hr = sr = None
            if price_fn is not None and hold and chal and decision_day:
                px_h0 = price_fn(hold, decision_day)
                px_h1 = price_fn(hold, due)
                px_c0 = price_fn(chal, decision_day)
                px_c1 = price_fn(chal, due)
                hr = _pct_return(px_h0, px_h1)
                sr = _pct_return(px_c0, px_c1)
            out = resolve_horizon(
                data_dir,
                str(row.get("switch_id")),
                int(h.get("horizon_d") or 0),
                laboratory_id=laboratory_id,
                hold_return=hr,
                switched_return=sr,
                note="uts.e.due_drain",
                publish_li=publish_li,
            )
            if out.get("ok"):
                completed += 1
            else:
                missing += 1
            details.append(
                {
                    "switch_id": row.get("switch_id"),
                    "horizon_d": h.get("horizon_d"),
                    "ok": out.get("ok"),
                    "honesty": out.get("honesty"),
                }
            )
        if completed + missing >= limit:
            break
    return {
        "ok": True,
        "version": VERSION,
        "as_of_ist": as_of,
        "scanned": scanned,
        "completed": completed,
        "missing_prices": missing,
        "details": details[:20],
    }


def propose_threshold_adjustments(
    decisions: list[dict[str, Any]] | None,
    *,
    current_threshold: float = 0.02,
    min_resolved: int = 20,
    horizon_d: int = 20,
) -> list[dict[str, Any]]:
    """Threshold / confidence **proposals only** — never mutates live config."""
    resolved: list[dict[str, Any]] = []
    for d in decisions or []:
        if not isinstance(d, dict):
            continue
        if str(d.get("decision") or "") != "switch":
            continue
        for h in d.get("horizons") or []:
            if (
                isinstance(h, dict)
                and int(h.get("horizon_d") or 0) == int(horizon_d)
                and h.get("status") == "done"
                and h.get("was_switch_better") is not None
            ):
                resolved.append({"decision": d, "horizon": h})
                break
    proposals: list[dict[str, Any]] = []
    n = len(resolved)
    if n < int(min_resolved):
        proposals.append(
            {
                "kind": "threshold",
                "action": "hold",
                "current": current_threshold,
                "proposed": None,
                "sample": n,
                "min_required": min_resolved,
                "honesty": (
                    f"Insufficient resolved {horizon_d}d switch outcomes "
                    f"({n}/{min_resolved}) — no threshold change proposed."
                ),
                "apply": False,
            }
        )
        return proposals
    hits = sum(1 for r in resolved if r["horizon"].get("was_switch_better") is True)
    hit_rate = hits / n if n else 0.0
    proposed = float(current_threshold)
    rationale = "hit rate acceptable — keep threshold"
    if hit_rate < 0.40:
        proposed = round(min(0.10, float(current_threshold) + 0.01), 4)
        rationale = (
            f"Switch hit rate {hit_rate:.0%} below 40% at {horizon_d}d — "
            "propose stricter threshold"
        )
    elif hit_rate > 0.65 and float(current_threshold) > 0.01:
        proposed = round(max(0.01, float(current_threshold) - 0.005), 4)
        rationale = (
            f"Switch hit rate {hit_rate:.0%} above 65% at {horizon_d}d — "
            "propose slightly looser threshold"
        )
    proposals.append(
        {
            "kind": "threshold",
            "action": "propose",
            "current": current_threshold,
            "proposed": proposed,
            "sample": n,
            "hit_rate": round(hit_rate, 4),
            "horizon_d": horizon_d,
            "rationale": rationale,
            "apply": False,
            "honesty": "Proposal only — operator/policy must apply; no auto-tune.",
        }
    )
    return proposals
