"""OI-ICR3 — Opportunity-cost learning object + capital_regret_20d.

Records Chosen vs Rejected (challengers + cash) at ACP / ICR.2 decision time,
schedules 1/5/20d horizons, and resolves honest returns (null when marks missing).

``capital_regret_20d = chosen_return_20d − best_feasible_rejected_return_20d``

Allocator quality KPI — separate from portfolio P&L. Never invents prices.
"""

from __future__ import annotations

import json
import logging
import statistics
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

from atlas.investment.capital_allocation import CASH_SYMBOL, DEFAULT_CASH_ER

VERSION = "icr.3.opportunity_cost.v1"
STORE_REL = Path("investment") / "opportunity_cost"
_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.allocation_regret")

HORIZON_DAYS: tuple[int, ...] = (1, 5, 20)
PriceFn = Callable[[str, str], float | None]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_^." else "_" for c in (s or ""))


def ist_today(now: datetime | None = None) -> str:
    dt = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_IST).date().isoformat()


def store_dir(data_dir: str | Path, *, laboratory_id: str) -> Path:
    from atlas.investment.laboratory import normalize_laboratory_id

    lab = normalize_laboratory_id(laboratory_id=laboratory_id)
    return Path(data_dir) / STORE_REL / _safe(lab)


def _by_id_dir(data_dir: str | Path, laboratory_id: str) -> Path:
    d = store_dir(data_dir, laboratory_id=laboratory_id) / "by_id"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pct_return(px0: float | None, px1: float | None) -> float | None:
    """Fraction return (0.01 = +1%), matching capital_regret example math."""
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


def _f(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
                "chosen_return": None,
                "rejected_returns": {},
                "best_rejected_return": None,
                "best_rejected_symbol": None,
                "opportunity_cost": None,
                "capital_regret": None,
                "honesty": None,
            }
        )
    return rows


def _attribution_from_acp(acp: dict[str, Any], resolution: dict[str, Any] | None) -> str:
    res = resolution if isinstance(resolution, dict) else {}
    code = str(res.get("reason_code") or acp.get("reason_code") or "").lower()
    if "quarantine" in code:
        return "quarantine"
    if "missing_er" in code or "missing" in code:
        return "missing_er"
    if "cost" in code or "switch" in code:
        return "costs"
    if "avoid" in code or "mos" in code or "thesis" in code:
        return "thesis"
    if "technical" in code or "momentum" in code:
        return "technical"
    stance = str((acp.get("incumbent") or {}).get("thesis_stance") or "").upper()
    if stance in {"AVOID", "INVALID"}:
        return "thesis"
    identity = str((acp.get("incumbent") or {}).get("identity") or "").upper()
    if identity == "QUARANTINED":
        return "quarantine"
    return "allocation_default"


def _leg(
    symbol: str,
    *,
    role: str,
    expected_return: float | None = None,
    confidence: str | None = None,
    mark: float | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    return {
        "symbol": str(symbol or "").strip().upper(),
        "role": role,
        "expected_return": expected_return,
        "confidence": confidence,
        "mark": mark,
        "note": note,
    }


def legs_from_acp(
    acp: dict[str, Any],
    *,
    resolution: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    """Derive chosen + rejected legs and choice_kind from ACP / ICR.2 resolution."""
    inc = acp.get("incumbent") if isinstance(acp.get("incumbent"), dict) else {}
    cash = acp.get("cash") if isinstance(acp.get("cash"), dict) else {}
    res = resolution if isinstance(resolution, dict) else {}
    action = str(res.get("action") or "")
    decision = str(acp.get("decision") or "")
    inc_sym = str(inc.get("symbol") or "").upper()
    cash_sym = str(cash.get("symbol") or CASH_SYMBOL)

    challengers: list[dict[str, Any]] = []
    for c in acp.get("challengers") or []:
        if not isinstance(c, dict):
            continue
        sym = str(c.get("symbol") or "").upper()
        if not sym or sym == inc_sym:
            continue
        challengers.append(
            _leg(
                sym,
                role="challenger",
                expected_return=_f(c.get("expected_return")),
                confidence=str(c.get("confidence") or "") or None,
                mark=_f(c.get("mark") or c.get("price")),
                note="best" if c.get("is_best") else None,
            )
        )

    cash_leg = _leg(
        cash_sym,
        role="cash",
        expected_return=_f(cash.get("expected_return"))
        if cash.get("expected_return") is not None
        else DEFAULT_CASH_ER,
        confidence=str(cash.get("confidence") or "high") or "high",
        mark=None,
        note="cash_competitor",
    )
    inc_leg = _leg(
        inc_sym,
        role="incumbent",
        expected_return=_f(inc.get("expected_return")),
        confidence=str(inc.get("confidence") or "") or None,
        mark=_f(inc.get("mark") or inc.get("price")),
        note=str(inc.get("thesis_stance") or "") or None,
    )

    if action == "EXIT_TO_CASH":
        chosen = cash_leg
        rejected = [inc_leg] + challengers
        return chosen, rejected, "exit_to_cash"

    if action == "SWITCH_TO" or decision == "SWITCH_REVIEW":
        chal_sym = str(res.get("challenger_symbol") or "")
        if not chal_sym:
            for c in challengers:
                if c.get("note") == "best":
                    chal_sym = c["symbol"]
                    break
        if chal_sym:
            chosen = next(
                (c for c in challengers if c["symbol"] == chal_sym),
                _leg(chal_sym, role="challenger"),
            )
            rejected = [inc_leg, cash_leg] + [
                c for c in challengers if c["symbol"] != chal_sym
            ]
            return chosen, rejected, "switch_to_challenger"

    # Default: kept incumbent (KEEP / HOLD / WAIT / EXIT_REVIEW wait)
    chosen = inc_leg
    rejected = challengers + [cash_leg]
    kind = "keep_incumbent"
    if decision == "EXIT_REVIEW":
        kind = "exit_review_wait"
    elif decision == "HOLD":
        kind = "hold_thin"
    return chosen, rejected, kind


def schedule_opportunity_cost(
    data_dir: str | Path | None,
    acp: dict[str, Any] | None,
    *,
    laboratory_id: str | None = None,
    resolution: dict[str, Any] | None = None,
    decision_ist: str | None = None,
    marks: dict[str, float] | None = None,
) -> dict[str, Any] | None:
    """Persist one opportunity-cost object from an ACP (idempotent per acp_id/day)."""
    if not data_dir or not isinstance(acp, dict):
        return None
    lab = laboratory_id or str(acp.get("laboratory_id") or "india_equity_learner")
    day = (decision_ist or str(acp.get("as_of_ist") or ist_today()))[:10]
    acp_id = str(acp.get("acp_id") or "")
    state_hash = str(acp.get("state_hash") or "")
    chosen, rejected, choice_kind = legs_from_acp(acp, resolution=resolution)
    if not chosen.get("symbol"):
        return None

    # Stamp marks from live book when available
    mk = marks or {}
    if chosen.get("mark") is None and chosen["symbol"] != CASH_SYMBOL:
        chosen["mark"] = _f(mk.get(chosen["symbol"]))
    for r in rejected:
        if r.get("mark") is None and r["symbol"] != CASH_SYMBOL:
            r["mark"] = _f(mk.get(r["symbol"]))

    # Dedupe: same acp_id or state_hash already scheduled today
    root = _by_id_dir(data_dir, lab)
    for p in root.glob("*.json"):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(doc, dict):
            continue
        if str(doc.get("decision_ist") or "")[:10] != day:
            continue
        if acp_id and str(doc.get("acp_id") or "") == acp_id:
            return doc
        if state_hash and str(doc.get("state_hash") or "") == state_hash:
            if str((doc.get("chosen") or {}).get("symbol")) == chosen["symbol"]:
                return doc

    oc_id = str(uuid4())
    row: dict[str, Any] = {
        "oc_id": oc_id,
        "version": VERSION,
        "created_at": _now(),
        "decision_ist": day,
        "laboratory_id": lab,
        "acp_id": acp_id or None,
        "state_hash": state_hash or None,
        "choice_kind": choice_kind,
        "acp_decision": acp.get("decision"),
        "exit_action": (resolution or {}).get("action") if resolution else None,
        "chosen": chosen,
        "rejected": rejected,
        "why": acp.get("why") or acp.get("operator_line"),
        "expected": {
            "chosen_er": chosen.get("expected_return"),
            "rejected_ers": {
                r["symbol"]: r.get("expected_return") for r in rejected if r.get("symbol")
            },
        },
        "attribution": _attribution_from_acp(acp, resolution),
        "unknowns": list(
            ((resolution or {}).get("waiting_for") if resolution else None)
            or (acp.get("unknowns") if isinstance(acp.get("unknowns"), list) else [])
            or []
        )[:8],
        "horizons": _schedule_horizons(day),
        "status": "open",
        "capital_regret_20d": None,
        "learning": "allocation_forecast_quality",
    }
    path = root / f"{oc_id}.json"
    try:
        path.write_text(json.dumps(row, indent=2, default=str) + "\n", encoding="utf-8")
    except OSError:
        _log.debug("ICR.3 schedule write failed", exc_info=True)
        return None
    row["path"] = str(path)

    # Learning event (schedule)
    try:
        from atlas.investment.learning_objects import record_learning_event

        record_learning_event(
            data_dir,
            {
                "kind": "LEARNING_EVENT",
                "event_kind": "opportunity_cost_scheduled",
                "laboratory_id": lab,
                "symbol": chosen.get("symbol"),
                "as_of_ist": day,
                "payload": {
                    "oc_id": oc_id,
                    "choice_kind": choice_kind,
                    "rejected": [r.get("symbol") for r in rejected],
                    "attribution": row["attribution"],
                },
            },
        )
    except Exception:  # noqa: BLE001
        pass
    return row


def schedule_from_lab_acps(
    data_dir: str | Path | None,
    packets: list[dict[str, Any]] | None,
    *,
    laboratory_id: str,
    resolutions: list[dict[str, Any]] | None = None,
    marks: dict[str, float] | None = None,
) -> dict[str, Any]:
    res_by = {
        str(r.get("symbol") or "").upper(): r
        for r in (resolutions or [])
        if isinstance(r, dict)
    }
    scheduled: list[dict[str, Any]] = []
    for acp in packets or []:
        if not isinstance(acp, dict):
            continue
        sym = str((acp.get("incumbent") or {}).get("symbol") or "").upper()
        row = schedule_opportunity_cost(
            data_dir,
            acp,
            laboratory_id=laboratory_id,
            resolution=res_by.get(sym),
            marks=marks,
        )
        if row:
            scheduled.append(row)
    return {
        "version": VERSION,
        "count": len(scheduled),
        "oc_ids": [r.get("oc_id") for r in scheduled],
    }


def list_opportunity_costs(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    limit: int = 200,
) -> list[dict[str, Any]]:
    if not data_dir:
        return []
    root = _by_id_dir(data_dir, laboratory_id)
    rows: list[dict[str, Any]] = []
    for p in sorted(root.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(doc, dict):
            doc.setdefault("path", str(p))
            rows.append(doc)
        if len(rows) >= max(1, int(limit)):
            break
    return rows


def _leg_return(
    leg: dict[str, Any],
    *,
    decision_ist: str,
    due_ist: str,
    price_fn: PriceFn | None,
) -> float | None:
    sym = str(leg.get("symbol") or "").upper()
    if not sym:
        return None
    if sym == CASH_SYMBOL or sym in {"CASH", "INR", "_CASH_"}:
        return 0.0
    if price_fn is None:
        # Fall back to stamped mark only when we cannot mark the end honestly
        return None
    px0 = price_fn(sym, decision_ist)
    if px0 is None:
        px0 = _f(leg.get("mark"))
    px1 = price_fn(sym, due_ist)
    return _pct_return(_f(px0), _f(px1))


def resolve_horizon(
    data_dir: str | Path | None,
    oc_id: str,
    horizon_d: int,
    *,
    laboratory_id: str,
    price_fn: PriceFn | None = None,
) -> dict[str, Any]:
    if not data_dir or not oc_id:
        return {"ok": False, "reason": "no_id"}
    path = _by_id_dir(data_dir, laboratory_id) / f"{oc_id}.json"
    if not path.is_file():
        return {"ok": False, "reason": "not_found"}
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"ok": False, "reason": "read_error"}
    if not isinstance(row, dict):
        return {"ok": False, "reason": "bad_doc"}

    decision_ist = str(row.get("decision_ist") or "")[:10]
    chosen = row.get("chosen") if isinstance(row.get("chosen"), dict) else {}
    rejected = [r for r in (row.get("rejected") or []) if isinstance(r, dict)]
    target = None
    for h in row.get("horizons") or []:
        if isinstance(h, dict) and int(h.get("horizon_d") or 0) == int(horizon_d):
            target = h
            break
    if target is None:
        return {"ok": False, "reason": "horizon_missing"}
    if target.get("status") == "done":
        return {"ok": True, "already": True, "row": row}

    due = str(target.get("due_ist") or "")[:10]
    cr = _leg_return(
        chosen, decision_ist=decision_ist, due_ist=due, price_fn=price_fn
    )
    rej_map: dict[str, float | None] = {}
    for r in rejected:
        rej_map[str(r.get("symbol") or "")] = _leg_return(
            r, decision_ist=decision_ist, due_ist=due, price_fn=price_fn
        )

    feasible = [(s, v) for s, v in rej_map.items() if s and v is not None]
    if cr is None or not feasible:
        target["status"] = "missing_prices"
        target["honesty"] = (
            "Chosen or all rejected legs lack honest marks — capital_regret null"
        )
        target["chosen_return"] = cr
        target["rejected_returns"] = rej_map
        target["completed_at"] = _now()
        path.write_text(json.dumps(row, indent=2, default=str) + "\n", encoding="utf-8")
        return {"ok": False, "honesty": target["honesty"], "row": row}

    best_sym, best_rej = max(feasible, key=lambda x: x[1])
    opp = round(float(cr) - float(best_rej), 6)
    target.update(
        {
            "status": "done",
            "completed_at": _now(),
            "chosen_return": cr,
            "rejected_returns": rej_map,
            "best_rejected_return": best_rej,
            "best_rejected_symbol": best_sym,
            "opportunity_cost": opp,
            "capital_regret": opp,
            "honesty": None,
        }
    )
    if int(horizon_d) == 20:
        row["capital_regret_20d"] = opp
        row["status"] = "resolved_20d"
    # Close when all horizons terminal
    statuses = [
        str(h.get("status") or "")
        for h in (row.get("horizons") or [])
        if isinstance(h, dict)
    ]
    if statuses and all(s in {"done", "missing_prices"} for s in statuses):
        row["status"] = "closed"

    path.write_text(json.dumps(row, indent=2, default=str) + "\n", encoding="utf-8")

    try:
        from atlas.investment.learning_objects import record_learning_event

        record_learning_event(
            data_dir,
            {
                "kind": "LEARNING_EVENT",
                "event_kind": "opportunity_cost_resolved",
                "laboratory_id": laboratory_id,
                "symbol": chosen.get("symbol"),
                "as_of_ist": ist_today(),
                "payload": {
                    "oc_id": oc_id,
                    "horizon_d": horizon_d,
                    "chosen_return": cr,
                    "best_rejected": best_sym,
                    "best_rejected_return": best_rej,
                    "capital_regret": opp,
                    "attribution": row.get("attribution"),
                },
            },
        )
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "row": row, "capital_regret": opp}


def evaluate_due_opportunity_costs(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    as_of_ist: str | None = None,
    price_fn: PriceFn | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    as_of = (as_of_ist or ist_today())[:10]
    try:
        as_of_d = date.fromisoformat(as_of)
    except ValueError:
        as_of_d = date.fromisoformat(ist_today())
    if price_fn is None:
        try:
            from atlas.investment.counterfactual_learning import default_price_fn

            price_fn = default_price_fn(data_dir)
        except Exception:  # noqa: BLE001
            price_fn = None

    completed = 0
    missing = 0
    details: list[dict[str, Any]] = []
    for row in list_opportunity_costs(data_dir, laboratory_id=laboratory_id, limit=500):
        if completed + missing >= limit:
            break
        oc_id = str(row.get("oc_id") or "")
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
            out = resolve_horizon(
                data_dir,
                oc_id,
                int(h.get("horizon_d") or 0),
                laboratory_id=laboratory_id,
                price_fn=price_fn,
            )
            if out.get("ok"):
                completed += 1
            else:
                missing += 1
            details.append(
                {
                    "oc_id": oc_id,
                    "horizon_d": h.get("horizon_d"),
                    "ok": out.get("ok"),
                    "capital_regret": out.get("capital_regret"),
                    "honesty": out.get("honesty"),
                }
            )
            if completed + missing >= limit:
                break
    return {
        "ok": True,
        "version": VERSION,
        "as_of_ist": as_of,
        "completed": completed,
        "missing_prices": missing,
        "details": details[:20],
    }


def capital_regret_kpi(
    rows: list[dict[str, Any]] | None,
    *,
    horizon_d: int = 20,
) -> dict[str, Any]:
    """Mean / median capital regret for resolved horizons (allocator quality)."""
    vals: list[float] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if horizon_d == 20 and row.get("capital_regret_20d") is not None:
            try:
                vals.append(float(row["capital_regret_20d"]))
                continue
            except (TypeError, ValueError):
                pass
        for h in row.get("horizons") or []:
            if (
                isinstance(h, dict)
                and int(h.get("horizon_d") or 0) == int(horizon_d)
                and h.get("status") == "done"
                and h.get("capital_regret") is not None
            ):
                try:
                    vals.append(float(h["capital_regret"]))
                except (TypeError, ValueError):
                    pass
                break
    if not vals:
        return {
            "version": VERSION,
            "horizon_d": horizon_d,
            "n": 0,
            "mean": None,
            "median": None,
            "honesty": "No resolved capital_regret samples yet",
        }
    return {
        "version": VERSION,
        "horizon_d": horizon_d,
        "n": len(vals),
        "mean": round(statistics.mean(vals), 6),
        "median": round(statistics.median(vals), 6),
        "min": round(min(vals), 6),
        "max": round(max(vals), 6),
        "honesty": None,
    }


def format_capital_regret_evening_lines(
    data_dir: str | Path | None,
    laboratory_id: str,
    *,
    limit: int = 4,
) -> list[str]:
    rows = list_opportunity_costs(data_dir, laboratory_id=laboratory_id, limit=100)
    kpi = capital_regret_kpi(rows, horizon_d=20)
    lines = [
        "",
        "── Capital regret 20d (OI-ICR3 — allocator quality, not P&L) ──",
    ]
    if int(kpi.get("n") or 0) == 0:
        open_n = sum(1 for r in rows if str(r.get("status") or "") == "open")
        lines.append(
            f"  resolved: 0 · scheduled open: {open_n} — "
            f"{kpi.get('honesty') or 'waiting horizons'}"
        )
        return lines
    lines.append(
        f"  n={kpi['n']} · mean={kpi['mean']:+.2%} · median={kpi['median']:+.2%}"
        f" · range [{kpi['min']:+.2%}, {kpi['max']:+.2%}]"
    )
    shown = 0
    for r in rows:
        if shown >= limit:
            break
        if r.get("capital_regret_20d") is None:
            continue
        ch = (r.get("chosen") or {}).get("symbol")
        lines.append(
            f"  {ch}: capital_regret_20d={float(r['capital_regret_20d']):+.2%}"
            f" ({r.get('choice_kind')}; attr={r.get('attribution')})"
        )
        shown += 1
    return lines
