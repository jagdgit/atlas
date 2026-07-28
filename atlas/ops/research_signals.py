"""ARMF Phase C — next-tick preview, research progress & velocity (Ops + scheduler)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas.ops.program_health import PROGRAM_LABELS, _program_key
from atlas.ops.worker_states import (
    STATE_AT_RISK,
    STATE_READY,
    STATE_STARVED,
    STATE_WAITING_HOST,
)


def next_tick_preview(
    worker_rows: list[dict[str, Any]] | None = None,
    *,
    arbiter_snap: dict[str, Any] | None = None,
    limit: int = 8,
    hide_types: frozenset[str] | set[str] | None = None,
) -> dict[str, Any]:
    """C9 — who is lined up for the next tick slots (explainable, not a promise)."""
    arb = arbiter_snap or {}
    eff = arb.get("effective_global_max") or arb.get("global_max")
    inflight = int(arb.get("total_inflight") or 0)
    free = max(0, int(eff) - inflight) if eff is not None else None
    hidden = frozenset(hide_types) if hide_types is not None else frozenset({"hello_watcher"})

    candidates: list[dict[str, Any]] = []
    for row in worker_rows or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("type") or "") in hidden:
            continue
        state = row.get("ops_state")
        if state not in (STATE_READY, STATE_AT_RISK, STATE_WAITING_HOST, STATE_STARVED):
            continue
        owner = row.get("owner") if isinstance(row.get("owner"), dict) else {}
        prog = _program_key(owner, service_class=row.get("service_class"))
        age = float(row.get("starvation_age_seconds") or 0)
        # Prefer Market realtime / paper over generic starved noise
        wtype = str(row.get("type") or "")
        type_boost = 0
        if wtype in {"paper_trading", "decision_simulation", "market_observer"}:
            type_boost = -1
        # Rank: at_risk/starved first, then waiting_host, then ready; older first
        rank = {
            STATE_STARVED: 0,
            STATE_AT_RISK: 1,
            STATE_WAITING_HOST: 2,
            STATE_READY: 3,
        }.get(str(state), 9)
        candidates.append(
            {
                "worker_id": row.get("id"),
                "mission_id": row.get("mission_id"),
                "type": row.get("type"),
                "ops_state": state,
                "program": prog,
                "label": PROGRAM_LABELS.get(prog, prog),
                "service_class": row.get("service_class"),
                "age_seconds": age,
                "wait_reason": row.get("wait_reason"),
                "_rank": (rank + type_boost, -age),
            }
        )
    candidates.sort(key=lambda c: c["_rank"])
    for c in candidates:
        c.pop("_rank", None)

    by_program: dict[str, list[dict[str, Any]]] = {}
    for c in candidates:
        by_program.setdefault(str(c["program"]), []).append(c)

    return {
        "version": "armf.c9",
        "free_tick_slots": free,
        "effective_global_max": eff,
        "total_inflight": inflight,
        "next": candidates[: max(0, limit)],
        "by_program": {
            p: rows[:3] for p, rows in by_program.items()
        },
        "note": "Preview only — Host Guard may still defer. hello_watcher hidden by default.",
    }


def research_progress_snapshot(
    data_dir: str | Path | None,
    *,
    program_id: str = "market_intelligence",
    limit: int = 40,
) -> dict[str, Any]:
    """C11 — dossier coverage as scheduler attention signal (low % → high need)."""
    root = Path(data_dir).expanduser() if data_dir else None
    if root is None:
        return {"version": "armf.c11", "dossiers": [], "attention": []}
    path = root / "investment" / "research" / program_id
    if not path.exists():
        return {
            "version": "armf.c11",
            "program_id": program_id,
            "dossiers": [],
            "attention": [],
            "count": 0,
        }

    from atlas.investment.research.models import coverage_pct

    rows: list[dict[str, Any]] = []
    for p in sorted(path.glob("*.json")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(doc, dict):
            continue
        try:
            cov = float(coverage_pct(doc))
        except Exception:  # noqa: BLE001
            cov = 0.0
        # Normalize 0..100 → 0..1 if needed
        if cov > 1.0:
            cov = cov / 100.0
        sym = str(doc.get("symbol") or p.stem)
        need = round(1.0 - max(0.0, min(1.0, cov)), 4)  # high need when low coverage
        rows.append(
            {
                "symbol": sym,
                "coverage": round(cov, 4),
                "attention_need": need,
                "updated_at": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    rows.sort(key=lambda r: (-float(r["attention_need"]), str(r["symbol"])))
    attention = [r for r in rows if float(r["attention_need"]) >= 0.25][:limit]
    return {
        "version": "armf.c11",
        "program_id": program_id,
        "count": len(rows),
        "dossiers": rows[:limit],
        "attention": attention,
        "note": "Prefer advancing low-coverage dossiers over polishing near-complete ones.",
    }


def research_velocity_snapshot(
    data_dir: str | Path | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """C12 — did Atlas produce more knowledge today? (dossier mtimes + session notes)."""
    now = now or datetime.now(timezone.utc)
    # IST calendar day for market notes
    try:
        from zoneinfo import ZoneInfo

        ist = now.astimezone(ZoneInfo("Asia/Kolkata"))
    except Exception:  # noqa: BLE001
        ist = now
    day = ist.strftime("%Y-%m-%d")
    root = Path(data_dir).expanduser() if data_dir else None
    out: dict[str, Any] = {
        "version": "armf.c12",
        "as_of_day": day,
        "programs": {},
        "note": "Primary question: did Atlas produce more knowledge today?",
    }
    if root is None:
        return out

    # Market: dossiers touched today + session note buys
    research_root = root / "investment" / "research" / "market_intelligence"
    advanced = 0
    if research_root.exists():
        start = ist.replace(hour=0, minute=0, second=0, microsecond=0)
        start_ts = start.timestamp()
        for p in research_root.glob("*.json"):
            if p.stat().st_mtime >= start_ts:
                advanced += 1

    buys = 0
    notes_path = root / "market" / "session_notes"
    note_file = None
    if notes_path.exists():
        for book in notes_path.iterdir():
            if not book.is_dir():
                continue
            candidate = book / f"{day}.json"
            if candidate.exists():
                note_file = candidate
                try:
                    note = json.loads(candidate.read_text(encoding="utf-8"))
                    if isinstance(note, dict):
                        buys += int(note.get("buys") or note.get("buy_count") or 0)
                        # common shapes
                        fills = note.get("fills") or note.get("trades") or []
                        if isinstance(fills, list):
                            buys = max(buys, sum(1 for f in fills if str(f.get("side") or "").lower() in ("buy", "b")))
                except Exception:  # noqa: BLE001
                    pass

    out["programs"]["market_intelligence"] = {
        "label": "Market",
        "dossiers_advanced_today": advanced,
        "session_buys_today": buys,
        "session_note": str(note_file) if note_file else None,
    }
    # Placeholders for other programs (honest zeros until wired)
    out["programs"]["engineering_intelligence"] = {
        "label": "Engineering",
        "observations_today": 0,
        "note": "wire mentor/repo events later",
    }
    out["programs"]["personal_intelligence"] = {
        "label": "Personal",
        "facts_confirmed_today": 0,
        "note": "wire personal journal later",
    }
    return out
