"""FEA dispatcher: UQ → priority plan → due symbols. Does not fetch.

Catalog-only names stay deferred. NSE backoff is per-symbol so nse_unavailable
does not occupy every tick. Does not loosen PLC.A / UNKNOWN rules.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from atlas.investment.fundamental_evidence.policy import (
    ACQUIRABLE_FIELDS,
    CODE_TO_FIELD,
)

VERSION = "fea.dispatch.v1"
_IST = ZoneInfo("Asia/Kolkata")

PRIORITY_BUY = 0
PRIORITY_CANDIDATE = 1
PRIORITY_WATCH = 2
PRIORITY_CATALOG = 3

PRIORITY_LABEL = {
    PRIORITY_BUY: "P0_buy",
    PRIORITY_CANDIDATE: "P1_candidate",
    PRIORITY_WATCH: "P2_watch",
    PRIORITY_CATALOG: "P3_catalog",
}

# retry 1: 20m, 2: 1h, 3: 3h, 4: 6h, 5+: next session (09:00 IST)
NSE_BACKOFF_SECONDS = (20 * 60, 60 * 60, 3 * 3600, 6 * 3600)


def _now(now: datetime | None = None) -> datetime:
    if now is not None:
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now
    return datetime.now(timezone.utc)


def _norm_sym(raw: Any) -> str:
    s = str(raw or "").strip().upper()
    if s.endswith(".NS") or s.endswith(".BO"):
        return s
    if s and "." not in s:
        return f"{s}.NS"
    return s


def next_nse_retry_at(fail_n: int, *, now: datetime | None = None) -> datetime:
    """Exponential NSE retry. fail_n is 1 after the first unavailable."""
    ts = _now(now)
    n = max(1, int(fail_n or 1))
    if n >= 5:
        local = ts.astimezone(_IST)
        nxt = local.replace(hour=9, minute=0, second=0, microsecond=0)
        if local >= nxt:
            nxt = nxt + timedelta(days=1)
        return nxt.astimezone(timezone.utc)
    delay = NSE_BACKOFF_SECONDS[min(n, len(NSE_BACKOFF_SECONDS)) - 1]
    return ts + timedelta(seconds=delay)


def task_due(task: dict[str, Any], *, now: datetime | None = None) -> bool:
    raw = str((task or {}).get("next_retry_at") or "").strip()
    if not raw:
        return True
    try:
        nxt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return True
    if nxt.tzinfo is None:
        nxt = nxt.replace(tzinfo=timezone.utc)
    return _now(now) >= nxt


def classify_priority(
    symbol: str,
    *,
    holdings: set[str] | frozenset[str] | None = None,
    buy_blocked: set[str] | frozenset[str] | None = None,
    candidates: set[str] | frozenset[str] | None = None,
) -> tuple[int, str]:
    """P0 open BUY / hold → P1 PLC.A technical candidate → P2 watch UQ → P3 catalog."""
    sym = _norm_sym(symbol)
    bare = sym.replace(".NS", "")
    holds = {_norm_sym(s) for s in (holdings or set())}
    blocked = {_norm_sym(s) for s in (buy_blocked or set())}
    cands = {_norm_sym(s) for s in (candidates or set())}
    if sym in holds or bare in {h.replace(".NS", "") for h in holds}:
        return PRIORITY_BUY, PRIORITY_LABEL[PRIORITY_BUY]
    if sym in blocked or bare in {h.replace(".NS", "") for h in blocked}:
        return PRIORITY_BUY, PRIORITY_LABEL[PRIORITY_BUY]
    if sym in cands or bare in {h.replace(".NS", "") for h in cands}:
        return PRIORITY_CANDIDATE, PRIORITY_LABEL[PRIORITY_CANDIDATE]
    return PRIORITY_WATCH, PRIORITY_LABEL[PRIORITY_WATCH]


def load_priority_context(
    data_dir: str | Path | None,
    *,
    laboratory_id: str = "india_equity_learner",
) -> dict[str, set[str]]:
    """Best-effort: holdings, PLC.A-blocked BUYs, SMA/plan candidates. Never invent."""
    holdings: set[str] = set()
    buy_blocked: set[str] = set()
    candidates: set[str] = set()
    if not data_dir:
        return {"holdings": holdings, "buy_blocked": buy_blocked, "candidates": candidates}
    try:
        from atlas.investment.uncertainty_queue import extra_material_from_lab

        extra = extra_material_from_lab(data_dir, laboratory_id=laboratory_id) or set()
        candidates |= {_norm_sym(s) for s in extra}
    except Exception:  # noqa: BLE001
        pass
    try:
        from atlas.investment.decision_packets import DecisionPacketStore, ist_today

        store = DecisionPacketStore(data_dir=str(data_dir))
        for pkt in store.list_day(
            portfolio_key=laboratory_id, ts_ist=ist_today(), limit=200
        ):
            if not isinstance(pkt, dict):
                continue
            sym = _norm_sym(pkt.get("symbol"))
            if not sym:
                continue
            kind = str(pkt.get("kind") or pkt.get("action") or "").lower()
            tag = str(pkt.get("strategy_tag") or "").lower()
            gate = pkt.get("plc_a") if isinstance(pkt.get("plc_a"), dict) else {}
            missing = gate.get("missing") or pkt.get("missing_fields") or []
            if kind in {"buy", "sell"} and not missing:
                holdings.add(sym)
            elif (
                "fundamentals_incomplete" in tag
                or missing
                or kind == "buy"
            ):
                buy_blocked.add(sym)
            elif tag in {"sma_cross_rsi", "plan_watch"}:
                candidates.add(sym)
    except Exception:  # noqa: BLE001
        pass
    return {"holdings": holdings, "buy_blocked": buy_blocked, "candidates": candidates}


def plan_batch_acquisition(
    data_dir: str | Path | None,
    *,
    laboratory_id: str = "india_equity_learner",
    limit: int = 6,
    now: datetime | None = None,
    holdings: set[str] | None = None,
    buy_blocked: set[str] | None = None,
    candidates: set[str] | None = None,
    include_catalog: bool = False,
) -> dict[str, Any]:
    """UQ material → due batch, highest priority first. Does not scan the catalog."""
    from atlas.investment.uncertainty_queue import STATUS_PENDING, list_tasks

    ctx = {"holdings": set(), "buy_blocked": set(), "candidates": set()}
    if holdings is None and buy_blocked is None and candidates is None:
        ctx = load_priority_context(data_dir, laboratory_id=laboratory_id)
    else:
        ctx = {
            "holdings": set(holdings or []),
            "buy_blocked": set(buy_blocked or []),
            "candidates": set(candidates or []),
        }

    tasks = list_tasks(data_dir, laboratory_id, status=STATUS_PENDING) if data_dir else []
    by_sym: dict[str, dict[str, Any]] = {}
    backing_off: list[dict[str, Any]] = []
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        field = CODE_TO_FIELD.get(str(t.get("unknown") or ""))
        if not field or field not in ACQUIRABLE_FIELDS:
            continue
        sym = _norm_sym(t.get("symbol"))
        if not sym:
            continue
        if not task_due(t, now=now):
            backing_off.append(
                {
                    "symbol": sym,
                    "next_retry_at": t.get("next_retry_at"),
                    "nse_backoff_n": t.get("nse_backoff_n"),
                    "unknown": t.get("unknown"),
                }
            )
            continue
        row = by_sym.setdefault(
            sym,
            {"symbol": sym, "fields": [], "task_ids": [], "importance": t.get("importance")},
        )
        if field not in row["fields"]:
            row["fields"].append(field)
        tid = t.get("id")
        if tid and tid not in row["task_ids"]:
            row["task_ids"].append(tid)

    due: list[dict[str, Any]] = []
    for sym, row in by_sym.items():
        pr, label = classify_priority(
            sym,
            holdings=ctx["holdings"],
            buy_blocked=ctx["buy_blocked"],
            candidates=ctx["candidates"],
        )
        if pr == PRIORITY_CATALOG and not include_catalog:
            continue
        row["priority"] = pr
        row["priority_label"] = label
        due.append(row)
    due.sort(key=lambda r: (int(r.get("priority") or PRIORITY_WATCH), str(r.get("symbol") or "")))
    cap = max(1, min(int(limit or 6), 12))
    selected = due[:cap]
    counts = {PRIORITY_LABEL[i]: 0 for i in range(4)}
    for r in selected:
        counts[str(r.get("priority_label"))] = counts.get(str(r.get("priority_label")), 0) + 1
    back_syms = sorted({b["symbol"] for b in backing_off})
    return {
        "version": VERSION,
        "kind": "FEA_BATCH_PLAN",
        "laboratory_id": laboratory_id,
        "due": selected,
        "due_n": len(selected),
        "queue_depth": len(by_sym) + len(back_syms),
        "backing_off": backing_off,
        "backing_off_n": len(back_syms),
        "priority_due": counts,
        "include_catalog": False,
        "yahoo_secondary": False,
        "honesty": (
            "Dispatcher plans UQ-material symbols only. Catalog-only names are "
            "not acquired. NSE backoff skips nse_unavailable until next_retry_at."
        ),
    }


def schedule_nse_retry(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    symbol: str,
    reason: str = "nse_unavailable",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Stamp exponential next_retry_at on all pending UQ rows for the symbol."""
    from atlas.investment.uncertainty_queue import STATUS_PENDING, list_tasks, store_dir

    if not data_dir:
        return {"ok": False, "reason": "no_data_dir"}
    sym = _norm_sym(symbol)
    bare = sym.replace(".NS", "")
    stamped = 0
    nxt: datetime | None = None
    fail_n = 0
    root = store_dir(data_dir, laboratory_id)
    for t in list_tasks(data_dir, laboratory_id, status=STATUS_PENDING) or []:
        tsym = _norm_sym(t.get("symbol"))
        if tsym.replace(".NS", "") != bare:
            continue
        fail_n = max(fail_n, int(t.get("nse_backoff_n") or 0) + 1)
    nxt = next_nse_retry_at(fail_n or 1, now=now)
    iso = nxt.isoformat()
    for t in list_tasks(data_dir, laboratory_id, status=STATUS_PENDING) or []:
        tsym = _norm_sym(t.get("symbol"))
        if tsym.replace(".NS", "") != bare:
            continue
        tid = str(t.get("id") or "")
        path = root / f"{tid}.json"
        if not path.is_file():
            continue
        try:
            import json

            doc = json.loads(path.read_text(encoding="utf-8"))
            doc["nse_backoff_n"] = fail_n or 1
            doc["next_retry_at"] = iso
            doc["last_nse_status"] = str(reason or "nse_unavailable")
            doc["updated_at"] = _now(now).isoformat()
            path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
            stamped += 1
        except (OSError, ValueError):
            continue
    return {
        "ok": True,
        "symbol": sym,
        "stamped": stamped,
        "fail_n": fail_n or 1,
        "next_retry_at": iso,
        "reason": reason,
    }
