"""UTS.F — Missed Opportunity Ledger (T+20 top-5 not-held outperformers).

Fail-closed: skip rows when marks missing for symbol or book. ``why_missed``
comes only from durable triage / switch state — never invented narrative.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

_log = logging.getLogger("atlas.investment.missed_opportunity")
VERSION = "uts.f.missed_opportunity"
STORE_REL = Path("investment") / "missed_opportunity"
_IST = ZoneInfo("Asia/Kolkata")

WHY_NEVER_TOP15 = "never_top15"
WHY_WATCHLIST_NOT_BOUGHT = "watchlist_not_bought"
WHY_IN_QUEUE_NOT_HELD = "in_queue_not_held"
WHY_BLOCKED_COSTS = "blocked_costs"
WHY_MISSING_ER = "missing_er"
WHY_PLC_A = "plc_a"
WHY_NOT_EVALUATED = "not_evaluated"
WHY_SWITCH_HELD_INCUMBENT = "held_incumbent_vs_challenger"

PriceFn = Callable[[str, str], float | None]


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


def classify_why_missed(
    symbol: str,
    *,
    rank_on_t: int | None,
    max_watchlist: int = 15,
    in_watchlist: bool = False,
    in_queue: bool = False,
    switch_rows_for_symbol: list[dict[str, Any]] | None = None,
) -> str:
    """Deterministic why_missed from durable state only."""
    sym = str(symbol or "").strip().upper()
    for row in switch_rows_for_symbol or []:
        if not isinstance(row, dict):
            continue
        chal = str(row.get("challenger_symbol") or "").strip().upper()
        hold = str(row.get("hold_symbol") or "").strip().upper()
        if chal != sym and hold != sym:
            continue
        code = str(row.get("reason_code") or "")
        if "plc_a" in code:
            return WHY_PLC_A
        if "missing_er" in code or "cold_start" in code:
            return WHY_MISSING_ER
        if "blocked_costs" in code:
            return WHY_BLOCKED_COSTS
        if code in {"hold_incumbent", "switch_blocked_costs"} and chal == sym:
            return WHY_SWITCH_HELD_INCUMBENT
    if in_queue and not in_watchlist:
        return WHY_IN_QUEUE_NOT_HELD
    if in_watchlist:
        return WHY_WATCHLIST_NOT_BOUGHT
    try:
        rank = int(rank_on_t) if rank_on_t is not None else None
    except (TypeError, ValueError):
        rank = None
    if rank is not None and rank > int(max_watchlist):
        return WHY_NEVER_TOP15
    return WHY_NOT_EVALUATED


def compute_missed_opportunities(
    triage_rows: list[dict[str, Any]] | None,
    *,
    held_on_t: set[str] | frozenset[str] | None,
    decision_ist: str,
    as_of_ist: str,
    price_fn: PriceFn,
    book_return_20d: float | None,
    top_n: int = 5,
    max_watchlist: int = 15,
    queue_symbols: set[str] | frozenset[str] | None = None,
    switch_decisions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Pure: top-N not-held names by excess vs book over [T, T+horizon]."""
    held = {str(s).strip().upper() for s in (held_on_t or set()) if s}
    queue = {str(s).strip().upper() for s in (queue_symbols or set()) if s}
    if book_return_20d is None:
        return {
            "ok": False,
            "honesty": "book_return_20d missing — ledger skipped (fail-closed)",
            "decision_ist": decision_ist,
            "as_of_ist": as_of_ist,
            "rows": [],
        }
    try:
        book_r = float(book_return_20d)
    except (TypeError, ValueError):
        return {
            "ok": False,
            "honesty": "book_return_20d non-numeric — ledger skipped",
            "rows": [],
        }

    # Index switch decisions by challenger/hold for why_missed.
    by_sym: dict[str, list[dict[str, Any]]] = {}
    for sd in switch_decisions or []:
        if not isinstance(sd, dict):
            continue
        if str(sd.get("decision_ist") or "")[:10] != str(decision_ist)[:10]:
            continue
        for key in ("challenger_symbol", "hold_symbol"):
            s = str(sd.get(key) or "").strip().upper()
            if s:
                by_sym.setdefault(s, []).append(sd)

    candidates: list[dict[str, Any]] = []
    skipped_missing = 0
    for row in triage_rows or []:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").strip().upper()
        if not sym or sym in held:
            continue
        px0 = price_fn(sym, decision_ist)
        px1 = price_fn(sym, as_of_ist)
        ret = _pct_return(px0, px1)
        if ret is None:
            skipped_missing += 1
            continue
        excess = round(ret - book_r, 6)
        try:
            rank = int(row.get("rank")) if row.get("rank") is not None else None
        except (TypeError, ValueError):
            rank = None
        in_wl = rank is not None and rank <= int(max_watchlist)
        in_q = sym in queue
        why = classify_why_missed(
            sym,
            rank_on_t=rank,
            max_watchlist=max_watchlist,
            in_watchlist=in_wl,
            in_queue=in_q,
            switch_rows_for_symbol=by_sym.get(sym),
        )
        candidates.append(
            {
                "symbol": sym,
                "rank_on_t": rank,
                "acceleration_on_t": row.get("acceleration_3d"),
                "in_watchlist_on_t": in_wl,
                "in_opportunity_queue_on_t": in_q,
                "return_20d_symbol": ret,
                "return_20d_book": book_r,
                "excess_vs_book": excess,
                "why_missed": why,
                "score_on_t": row.get("score"),
            }
        )

    # Top by excess vs book (missed alpha).
    candidates.sort(
        key=lambda r: (
            float(r.get("excess_vs_book") or -1e9),
            -(int(r.get("rank_on_t") or 10_000)),
        ),
        reverse=True,
    )
    top = candidates[: max(1, int(top_n))]
    return {
        "ok": True,
        "version": VERSION,
        "decision_ist": decision_ist,
        "as_of_ist": as_of_ist,
        "horizon_d": 20,
        "top_n": int(top_n),
        "book_return_20d": book_r,
        "candidates_scored": len(candidates),
        "skipped_missing_marks": skipped_missing,
        "rows": top,
        "honesty": (
            None
            if top
            else "No not-held names with complete marks outperformed the book."
        ),
    }


def persist_missed_ledger(
    data_dir: str | Path | None,
    payload: dict[str, Any],
    *,
    laboratory_id: str,
) -> dict[str, Any]:
    if not data_dir or not isinstance(payload, dict):
        return {"ok": False, "honesty": "no data_dir/payload"}
    root = store_dir(data_dir, laboratory_id=laboratory_id)
    root.mkdir(parents=True, exist_ok=True)
    day = str(payload.get("decision_ist") or ist_today())[:10]
    path = root / f"{day}.json"
    doc = {**payload, "laboratory_id": laboratory_id, "persisted_at": _now()}
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    # Also append summary line for LI consumption.
    with (root / "ledger.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "decision_ist": day,
                    "as_of_ist": payload.get("as_of_ist"),
                    "n": len(payload.get("rows") or []),
                    "top": [
                        {
                            "symbol": r.get("symbol"),
                            "excess_vs_book": r.get("excess_vs_book"),
                            "why_missed": r.get("why_missed"),
                        }
                        for r in (payload.get("rows") or [])[:5]
                        if isinstance(r, dict)
                    ],
                    "version": VERSION,
                    "at": _now(),
                }
            )
            + "\n"
        )
    try:
        from atlas.investment.learning_intelligence import append_evolution_event

        top = (payload.get("rows") or [{}])[0] if payload.get("rows") else {}
        append_evolution_event(
            data_dir,
            laboratory_id=laboratory_id,
            axis="allocation",
            from_score=None,
            to_score=None,
            reason=(
                f"missed_opp {top.get('symbol')} excess={top.get('excess_vs_book')} "
                f"why={top.get('why_missed')}"
                if top
                else "missed_opp empty"
            ),
            phase_id="UTS.F",
        )
    except Exception:  # noqa: BLE001
        _log.debug("missed-opp LI event skipped", exc_info=True)
    return {"ok": True, "path": str(path), "rows": len(payload.get("rows") or [])}


def load_missed_ledger(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    decision_ist: str | None = None,
) -> dict[str, Any]:
    if not data_dir:
        return {"ok": False, "rows": []}
    root = store_dir(data_dir, laboratory_id=laboratory_id)
    if decision_ist:
        path = root / f"{str(decision_ist)[:10]}.json"
        if not path.is_file():
            return {"ok": False, "rows": [], "reason": "missing"}
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            return doc if isinstance(doc, dict) else {"ok": False, "rows": []}
        except Exception:  # noqa: BLE001
            return {"ok": False, "rows": [], "reason": "read_failed"}
    # Latest by mtime
    files = sorted(root.glob("????-??-??.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return {"ok": False, "rows": [], "reason": "empty"}
    try:
        doc = json.loads(files[0].read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {"ok": False, "rows": []}
    except Exception:  # noqa: BLE001
        return {"ok": False, "rows": [], "reason": "read_failed"}


def format_missed_opportunity_evening_lines(ledger: dict[str, Any] | None) -> list[str]:
    if not isinstance(ledger, dict) or not ledger.get("ok"):
        reason = (ledger or {}).get("honesty") or (ledger or {}).get("reason") or "none"
        return [
            f"  Missed opportunities (T+20): (no ledger yet — {reason})"
        ]
    rows = [r for r in (ledger.get("rows") or []) if isinstance(r, dict)]
    lines = [
        f"  Missed opportunities (T+20 from {ledger.get('decision_ist')}): "
        f"{len(rows)} name(s) · book_ret={ledger.get('book_return_20d')}"
    ]
    if not rows:
        lines.append("    (none with complete marks above book)")
        return lines
    for r in rows[:5]:
        ex = r.get("excess_vs_book")
        ex_s = f"{float(ex):+.2%}" if isinstance(ex, (int, float)) else "—"
        lines.append(
            f"    {r.get('symbol')} #{r.get('rank_on_t')} excess={ex_s} "
            f"why={r.get('why_missed')}"
        )
    return lines


def run_missed_opportunity_job(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    program_id: str = "market_intelligence",
    as_of_ist: str | None = None,
    horizon_d: int = 20,
    top_n: int = 5,
    max_watchlist: int = 15,
    price_fn: PriceFn | None = None,
    held_on_t: set[str] | None = None,
    book_return_20d: float | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """T+20 job: load triage for day T = as_of − horizon, score misses."""
    as_of = as_of_ist or ist_today()
    as_of_d = date.fromisoformat(str(as_of)[:10])
    decision_d = as_of_d - timedelta(days=int(horizon_d))
    decision_ist = decision_d.isoformat()
    if not data_dir:
        return {"ok": False, "honesty": "no data_dir"}
    if price_fn is None:
        return {
            "ok": False,
            "honesty": "price_fn required — refuse to invent marks",
            "decision_ist": decision_ist,
            "as_of_ist": as_of,
        }

    from atlas.investment.triage_memory import load_triage_day

    triage = load_triage_day(data_dir, program_id, decision_ist)
    if not triage.get("ok"):
        return {
            "ok": False,
            "honesty": f"no triage ladder for {decision_ist}",
            "decision_ist": decision_ist,
            "as_of_ist": as_of,
            "rows": [],
        }
    queue_syms = {
        str(q.get("symbol") or "").strip().upper()
        for q in (triage.get("opportunity_queue") or [])
        if isinstance(q, dict)
    }
    switch_rows: list[dict[str, Any]] = []
    try:
        from atlas.investment.switch_learning import list_switch_decisions

        switch_rows = list_switch_decisions(
            data_dir, laboratory_id=laboratory_id, limit=200
        )
    except Exception:  # noqa: BLE001
        switch_rows = []

    payload = compute_missed_opportunities(
        triage.get("rows") or [],
        held_on_t=held_on_t or set(),
        decision_ist=decision_ist,
        as_of_ist=as_of,
        price_fn=price_fn,
        book_return_20d=book_return_20d,
        top_n=top_n,
        max_watchlist=max_watchlist,
        queue_symbols=queue_syms,
        switch_decisions=switch_rows,
    )
    if persist and payload.get("ok"):
        persist_missed_ledger(data_dir, payload, laboratory_id=laboratory_id)
    return payload
