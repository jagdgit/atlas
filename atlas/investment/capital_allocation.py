"""OI-LINT0 Phase 3B — next-rupee challenger table (wire L1 E[R] + UTS).

Daily comparison: each holding + **cash** vs best alternative.
Prototype E[R] is the comparison currency; missing terms lower completeness,
they do not silently become 0% alpha. ROTATE only when advantage clears the
switch threshold (costs + uncertainty margin).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from atlas.investment.opportunity_switch import (
    DEFAULT_PENALTY_K,
    DEFAULT_PENALTY_M,
    DEFAULT_SWITCH_COST,
    DEFAULT_THRESHOLD,
    REASON_BLOCKED_COSTS,
    REASON_BLOCKED_MISSING_ER,
    REASON_HOLD_INCUMBENT,
    estimate_opportunity_metrics,
    review_hold_vs_challengers,
    risk_adjusted_score,
)

VERSION = "lint0.capital_allocation.v1"
STORE_REL = Path("investment") / "allocation"
_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.capital_allocation")

CASH_SYMBOL = "CASH"
DEFAULT_CASH_ER = 0.0
DEFAULT_CASH_CONFIDENCE = 0.92
ALLOC_KEEP = "KEEP"
ALLOC_HOLD = "HOLD"
ALLOC_ROTATE = "ROTATE"
ALLOC_CASH = "CASH"


def ist_today() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def build_switch_threshold(
    *,
    threshold: float = DEFAULT_THRESHOLD,
    transaction_cost: float = DEFAULT_SWITCH_COST,
    slippage: float = 0.0,
    tax_cost: float = 0.0,
    penalty_k: float = DEFAULT_PENALTY_K,
    penalty_m: float = DEFAULT_PENALTY_M,
    cold_start_threshold: float | None = None,
    exploratory: bool = False,
) -> dict[str, Any]:
    """Explicit ROTATE bar — patient when economically rational."""
    eff = float(cold_start_threshold) if exploratory and cold_start_threshold else float(threshold)
    return {
        "version": VERSION,
        "min_advantage": round(eff, 6),
        "transaction_cost": round(float(transaction_cost), 6),
        "slippage": round(float(slippage), 6),
        "tax_cost": round(float(tax_cost), 6),
        "confidence_penalty_k": round(float(penalty_k), 6),
        "confidence_penalty_m": round(float(penalty_m), 6),
        "exploratory": bool(exploratory),
        "honesty": (
            "ROTATE only when net advantage exceeds min_advantage after costs "
            "and confidence penalty — not on daily rank noise."
        ),
    }


def _sym(row: dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return ""
    return str(row.get("symbol") or "").strip().upper()


def _qty(row: dict[str, Any] | None) -> float:
    if not isinstance(row, dict):
        return 0.0
    for k in ("qty", "quantity", "shares"):
        try:
            v = float(row.get(k) or 0)
        except (TypeError, ValueError):
            continue
        if v > 0:
            return v
    return 0.0


def cash_row(
    cash: float,
    *,
    expected_return: float = DEFAULT_CASH_ER,
    confidence: float = DEFAULT_CASH_CONFIDENCE,
) -> dict[str, Any]:
    er = float(expected_return)
    conf = float(confidence)
    return {
        "symbol": CASH_SYMBOL,
        "role": "residual",
        "cash": round(float(cash), 2),
        "expected_return": er,
        "er_completeness": 1.0,
        "er_model": "cash_baseline",
        "er_basis": "risk_free_excess",
        "confidence": conf,
        "opportunity_score": risk_adjusted_score(er, conf),
        "portfolio_fit": "residual",
        "risk": "none",
    }


def allocation_action_from_review(review: dict[str, Any] | None) -> str:
    """Map UTS switch review → investor-facing allocation action."""
    if not isinstance(review, dict):
        return ALLOC_HOLD
    decision = str(review.get("decision") or "hold").lower()
    reason = str(review.get("reason_code") or "")
    if decision == "switch":
        return ALLOC_ROTATE
    if reason in {REASON_BLOCKED_COSTS, REASON_BLOCKED_MISSING_ER}:
        return ALLOC_HOLD
    if reason == REASON_HOLD_INCUMBENT:
        return ALLOC_KEEP
    adv = review.get("expected_advantage")
    try:
        if adv is not None and float(adv) <= 0:
            return ALLOC_KEEP
    except (TypeError, ValueError):
        pass
    return ALLOC_HOLD


def _holding_row(
    hold: dict[str, Any],
    review: dict[str, Any] | None,
    *,
    switch_threshold: dict[str, Any],
) -> dict[str, Any]:
    sym = _sym(hold)
    metrics = (
        (review or {}).get("hold_metrics")
        if isinstance((review or {}).get("hold_metrics"), dict)
        else estimate_opportunity_metrics(hold)
    )
    chal_m = (review or {}).get("challenger_metrics") if isinstance(review, dict) else None
    er = metrics.get("expected_return")
    conf = metrics.get("confidence")
    action = allocation_action_from_review(review)
    missing = list(metrics.get("missing") or metrics.get("missing_terms") or [])
    return {
        "symbol": sym,
        "role": "holding",
        "qty": _qty(hold),
        "expected_return": er,
        "er_completeness": metrics.get("er_completeness"),
        "er_model": metrics.get("er_model"),
        "er_basis": metrics.get("er_basis"),
        "confidence": conf,
        "opportunity_score": metrics.get("risk_adjusted_score")
        or risk_adjusted_score(er, conf),
        "portfolio_fit": "incumbent",
        "risk": "open",
        "best_challenger": (review or {}).get("challenger_symbol"),
        "challenger_advantage": (review or {}).get("expected_advantage"),
        "challenger_expected_return": (
            chal_m.get("expected_return") if isinstance(chal_m, dict) else None
        ),
        "challenger_er_completeness": (
            chal_m.get("er_completeness") if isinstance(chal_m, dict) else None
        ),
        "allocation_action": action,
        "reason_code": (review or {}).get("reason_code"),
        "switch_threshold": switch_threshold,
        "missing_er": REASON_BLOCKED_MISSING_ER
        in str((review or {}).get("reason_code") or ""),
        "missing_terms": missing,
        "evaluated_challengers": int((review or {}).get("evaluated_challengers") or 0),
    }


def _best_deploy_target(
    *,
    cash_doc: dict[str, Any],
    deploy_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Best use of the next rupee vs book vs cash."""
    pool: list[dict[str, Any]] = [cash_doc]
    for row in deploy_candidates:
        if not isinstance(row, dict):
            continue
        sym = _sym(row)
        if not sym or sym == CASH_SYMBOL:
            continue
        metrics = estimate_opportunity_metrics(row)
        pool.append(
            {
                "symbol": sym,
                "expected_return": metrics.get("expected_return"),
                "er_completeness": metrics.get("er_completeness"),
                "confidence": metrics.get("confidence"),
                "opportunity_score": metrics.get("risk_adjusted_score"),
                "role": "challenger",
                "missing_terms": list(metrics.get("missing") or []),
            }
        )
    scored = [
        r
        for r in pool
        if r.get("opportunity_score") is not None or r.get("symbol") == CASH_SYMBOL
    ]
    if not scored:
        return {
            "symbol": CASH_SYMBOL,
            "allocation_action": ALLOC_CASH,
            "reason": "no_scored_opportunities",
            "honesty": "No E[R] scored — default honest answer is hold cash.",
        }
    best = max(
        scored,
        key=lambda r: (
            float(r.get("opportunity_score") or -1e9),
            float(r.get("er_completeness") or 0),
        ),
    )
    sym = str(best.get("symbol") or CASH_SYMBOL)
    action = ALLOC_CASH if sym == CASH_SYMBOL else "DEPLOY"
    return {
        "symbol": sym,
        "allocation_action": action,
        "expected_return": best.get("expected_return"),
        "er_completeness": best.get("er_completeness"),
        "confidence": best.get("confidence"),
        "opportunity_score": best.get("opportunity_score"),
        "reason": "best_risk_adjusted_er",
        "honesty": (
            "Next ₹1 comparison uses prototype_v1 × confidence; "
            "unknown terms reduce completeness, not silently 0%."
        ),
    }


def build_challenger_table(
    *,
    holds: list[dict[str, Any]] | None,
    challengers: list[dict[str, Any]] | None,
    cash: float = 0.0,
    reviews: list[dict[str, Any]] | None = None,
    laboratory_id: str = "india_equity_learner",
    as_of_ist: str | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    cold_start_threshold: float = 0.05,
    transaction_cost: float = DEFAULT_SWITCH_COST,
    slippage: float = 0.0,
    tax_cost: float = 0.0,
    penalty_k: float = DEFAULT_PENALTY_K,
    penalty_m: float = DEFAULT_PENALTY_M,
    exploratory: bool = False,
    cash_expected_return: float = DEFAULT_CASH_ER,
    cash_confidence: float = DEFAULT_CASH_CONFIDENCE,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Daily challenger table — holdings, cash, best alternative each."""
    day = (as_of_ist or ist_today()).strip()
    switch_thr = build_switch_threshold(
        threshold=threshold,
        transaction_cost=transaction_cost,
        slippage=slippage,
        tax_cost=tax_cost,
        penalty_k=penalty_k,
        penalty_m=penalty_m,
        cold_start_threshold=cold_start_threshold,
        exploratory=exploratory,
    )
    review_by_hold = {
        str(r.get("hold_symbol") or "").upper(): r
        for r in (reviews or [])
        if isinstance(r, dict) and r.get("hold_symbol")
    }
    rows: list[dict[str, Any]] = []
    held_syms = set()
    for hold in holds or []:
        if not isinstance(hold, dict) or _qty(hold) <= 0:
            continue
        sym = _sym(hold)
        held_syms.add(sym)
        rev = review_by_hold.get(sym)
        if rev is None:
            rev = review_hold_vs_challengers(
                hold,
                challengers,
                threshold=threshold,
                cold_start_threshold=cold_start_threshold,
                transaction_cost=transaction_cost,
                slippage=slippage,
                tax_cost=tax_cost,
                penalty_k=penalty_k,
                penalty_m=penalty_m,
                exploratory=exploratory,
                laboratory_id=laboratory_id,
                cfg=cfg,
            )
        rows.append(_holding_row(hold, rev, switch_threshold=switch_thr))

    cash_doc = cash_row(cash, expected_return=cash_expected_return, confidence=cash_confidence)
    deploy_pool = [
        c
        for c in (challengers or [])
        if isinstance(c, dict) and _sym(c) and _sym(c) not in held_syms
    ]
    best_deploy = _best_deploy_target(cash_doc=cash_doc, deploy_candidates=deploy_pool)
    cash_doc["best_challenger"] = (
        best_deploy.get("symbol") if best_deploy.get("symbol") != CASH_SYMBOL else None
    )
    cash_doc["allocation_action"] = (
        ALLOC_CASH if best_deploy.get("symbol") == CASH_SYMBOL else ALLOC_HOLD
    )
    cash_doc["switch_threshold"] = switch_thr
    rows.append(cash_doc)

    return {
        "version": VERSION,
        "kind": "challenger_table",
        "laboratory_id": laboratory_id,
        "as_of_ist": day,
        "cash": round(float(cash), 2),
        "rows": rows,
        "best_deploy": best_deploy,
        "switch_threshold": switch_thr,
        "holdings_n": sum(1 for r in rows if r.get("role") == "holding"),
        "honesty": (
            "Every holding has a best challenger; cash is always in the set. "
            "missing_er is a capability gap — not a nudge to trade more."
        ),
    }


def table_path(
    data_dir: str | Path | None,
    laboratory_id: str,
    as_of_ist: str | None = None,
) -> Path | None:
    if not data_dir:
        return None
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in laboratory_id)[:80]
    return Path(data_dir) / STORE_REL / (safe or "lab") / f"{(as_of_ist or ist_today()).strip()}.json"


def persist_allocation_table(
    data_dir: str | Path | None,
    table: dict[str, Any],
) -> dict[str, Any]:
    if not data_dir or not isinstance(table, dict):
        return {"ok": False, "reason": "no_data_dir"}
    path = table_path(
        data_dir,
        str(table.get("laboratory_id") or "india_equity_learner"),
        as_of_ist=str(table.get("as_of_ist") or ""),
    )
    if path is None:
        return {"ok": False, "reason": "no_path"}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(table, indent=2, default=str), encoding="utf-8")
        return {"ok": True, "path": str(path)}
    except OSError as exc:
        _log.debug("allocation persist failed", exc_info=True)
        return {"ok": False, "reason": type(exc).__name__}


def load_allocation_table(
    data_dir: str | Path | None,
    laboratory_id: str,
    as_of_ist: str | None = None,
) -> dict[str, Any] | None:
    path = table_path(data_dir, laboratory_id, as_of_ist=as_of_ist)
    if path is None or not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def row_for_symbol(table: dict[str, Any] | None, symbol: str) -> dict[str, Any] | None:
    if not isinstance(table, dict):
        return None
    want = str(symbol or "").strip().upper()
    for row in table.get("rows") or []:
        if isinstance(row, dict) and _sym(row) == want:
            return row
    return None


def packet_allocation_fields(table: dict[str, Any] | None, symbol: str) -> dict[str, Any]:
    """DI packet meta — best challenger vs book vs cash."""
    row = row_for_symbol(table, symbol)
    if not row:
        return {}
    out = {
        "best_challenger": row.get("best_challenger"),
        "challenger_advantage": row.get("challenger_advantage"),
        "allocation_action": row.get("allocation_action"),
        "expected_return": row.get("expected_return"),
        "er_completeness": row.get("er_completeness"),
        "opportunity_score": row.get("opportunity_score"),
        "missing_er": bool(row.get("missing_er")),
    }
    if isinstance(table, dict) and table.get("best_deploy"):
        out["best_deploy"] = table.get("best_deploy")
    return out


def allocation_blocking_unknowns(table: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Unknowns that could change the next-rupee decision (curiosity priority)."""
    if not isinstance(table, dict):
        return []
    out: list[dict[str, Any]] = []
    for row in table.get("rows") or []:
        if not isinstance(row, dict):
            continue
        sym = _sym(row)
        if not sym or sym == CASH_SYMBOL:
            continue
        completeness = row.get("er_completeness")
        try:
            low = completeness is None or float(completeness) < 0.55
        except (TypeError, ValueError):
            low = True
        if not low and not row.get("missing_er"):
            continue
        for unk in list(row.get("missing_terms") or [])[:6]:
            out.append(
                {
                    "symbol": sym,
                    "unknown": str(unk),
                    "reason": "allocation_er_gap",
                    "priority": "high",
                    "er_completeness": completeness,
                    "role": row.get("role"),
                }
            )
        if row.get("missing_er") and not row.get("missing_terms"):
            out.append(
                {
                    "symbol": sym,
                    "unknown": "expected_return",
                    "reason": "allocation_missing_er",
                    "priority": "high",
                    "er_completeness": completeness,
                    "role": row.get("role"),
                }
            )
    return out


def merge_allocation_curiosity(
    queue_doc: dict[str, Any] | None,
    table: dict[str, Any] | None,
) -> dict[str, Any]:
    """Boost curiosity queue items that block allocation comparisons."""
    doc = dict(queue_doc or {})
    items = [i for i in (doc.get("items") or []) if isinstance(i, dict)]
    blockers = allocation_blocking_unknowns(table)
    if not blockers:
        return doc
    boost_keys = {(b["symbol"], b["unknown"]) for b in blockers}
    for it in items:
        key = (str(it.get("symbol") or ""), str(it.get("unknown") or ""))
        if key in boost_keys:
            it["priority"] = "high"
            it["allocation_blocking"] = True
            it["goal"] = f"resolve unknown for next-rupee compare: {it.get('unknown')}"
    for b in blockers:
        key = (b["symbol"], b["unknown"])
        if any(
            str(i.get("symbol")) == b["symbol"] and str(i.get("unknown")) == b["unknown"]
            for i in items
        ):
            continue
        items.append(
            {
                **b,
                "allocation_blocking": True,
                "laboratory_id": (table or {}).get("laboratory_id"),
                "goal": f"resolve unknown for next-rupee compare: {b['unknown']}",
                "status": "queued",
                "evidence_needed": ["fundamentals", "ranker inputs"],
                "created_at": datetime.now(_IST).isoformat(),
            }
        )
    doc["items"] = items[-200:]
    doc["allocation_boosted"] = len(blockers)
    return doc


def format_allocation_evening_lines(table: dict[str, Any] | None, *, limit: int = 6) -> list[str]:
    """Evening mail — allocation table above the fold."""
    if not isinstance(table, dict) or not table.get("rows"):
        return [
            "",
            "── Next ₹1 / challenger table (OI-LINT0 3B) ──",
            "  (unavailable — no allocation table persisted today)",
        ]
    lines = [
        "",
        "── Next ₹1 / challenger table (book vs challengers vs cash) ──",
        f"  as_of={table.get('as_of_ist')} · lab={table.get('laboratory_id')} · "
        f"cash=₹{table.get('cash', '—')}",
    ]
    bd = table.get("best_deploy") if isinstance(table.get("best_deploy"), dict) else {}
    if bd:
        lines.append(
            f"  best deploy: {bd.get('symbol')} "
            f"score={bd.get('opportunity_score')} "
            f"E[R]={bd.get('expected_return')} "
            f"completeness={bd.get('er_completeness')}"
        )
    thr = table.get("switch_threshold") if isinstance(table.get("switch_threshold"), dict) else {}
    if thr:
        lines.append(
            f"  ROTATE bar: min_advantage={thr.get('min_advantage')} "
            f"+ costs={thr.get('transaction_cost')}"
        )
    for row in [r for r in (table.get("rows") or []) if isinstance(r, dict)][: max(1, limit)]:
        sym = row.get("symbol")
        er = row.get("expected_return")
        comp = row.get("er_completeness")
        act = row.get("allocation_action")
        ch = row.get("best_challenger")
        adv = row.get("challenger_advantage")
        er_s = "—" if er is None else f"{float(er):+.2%}"
        comp_s = "—" if comp is None else f"{float(comp):.2f}"
        adv_s = "" if adv is None else f" adv={float(adv):+.4f}"
        ch_s = f" vs {ch}" if ch else ""
        lines.append(
            f"  · {sym} [{row.get('role')}]: E[R]={er_s} comp={comp_s} "
            f"action={act}{ch_s}{adv_s}"
        )
    lines.append(f"  Honesty: {table.get('honesty')}")
    return lines
