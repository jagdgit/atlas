"""OI-STAB0 D4 — Clean equity session readiness checklist (observe+explain).

Success = observe + explain, not buys. Gates match the STAB0 dashboard.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "stab0.session_readiness.v1"
_log = logging.getLogger("atlas.investment.session_readiness")
_IST = ZoneInfo("Asia/Kolkata")

DEFAULT_LAB = "india_equity_learner"


def fno_lab_paused() -> bool:
    """STAB0 Lock 1 — FNO pause is opt-in via env after operator unlock 2026-08-13."""
    raw = (os.environ.get("ATLAS_STAB0_PAUSE_FNO") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _today_ist() -> str:
    return datetime.now(_IST).date().isoformat()


def evaluate_equity_session(
    data_dir: str | Path | None,
    *,
    day: str | None = None,
    laboratory_id: str = DEFAULT_LAB,
    market_data: Any | None = None,
    host_guard: Any | None = None,
    budget: Any | None = None,
    reasoning: Any | None = None,
) -> dict[str, Any]:
    """Return pass/fail gates for one IST equity session (honest, not aspirational)."""
    day_ist = day or _today_ist()
    root = Path(data_dir) if data_dir else None
    gates: list[dict[str, Any]] = []

    def gate(key: str, ok: bool, detail: str, *, required: bool = True) -> None:
        gates.append(
            {
                "key": key,
                "ok": bool(ok),
                "required": bool(required),
                "detail": detail,
            }
        )

    # --- journal ---
    journal_n = 0
    try:
        from atlas.activity import get_journal

        j = get_journal()
        if j is not None and hasattr(j, "format_day_brief"):
            brief = j.format_day_brief(day_ist)
            journal_n = int(brief.get("count") or 0)
    except Exception:  # noqa: BLE001
        pass
    gate(
        "activity_journal",
        journal_n > 0,
        f"{journal_n} activity event(s) today" if journal_n else "no activity events yet",
    )

    # --- session notes / KPIs ---
    notes: dict[str, Any] = {}
    kpi: dict[str, Any] = {}
    if root is not None:
        try:
            from atlas.investment.session_notes import load_day_notes

            notes = load_day_notes(
                root, portfolio_key=laboratory_id, ist_date=day_ist
            )
        except Exception:  # noqa: BLE001
            notes = {}
        kpi_path = root / "market" / "trading_kpis" / laboratory_id / f"{day_ist}.json"
        if kpi_path.is_file():
            try:
                kpi = json.loads(kpi_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                kpi = {}

    gap = notes.get("feed_gap_days")
    if gap is None and isinstance(kpi, dict):
        gap = (kpi.get("session") or {}).get("feed_gap_days") if isinstance(
            kpi.get("session"), dict
        ) else kpi.get("feed_gap_days")
    try:
        gap_f = float(gap) if gap is not None else None
    except (TypeError, ValueError):
        gap_f = None

    basis = notes.get("valuation_basis") or (
        kpi.get("valuation_basis") if isinstance(kpi, dict) else None
    )
    marks_pct = notes.get("marks_pct")
    if marks_pct is None and isinstance(kpi, dict):
        marks_pct = kpi.get("marks_pct")
    try:
        marks_f = float(marks_pct) if marks_pct is not None else None
    except (TypeError, ValueError):
        marks_f = None
    session_fresh_marks = bool(
        marks_f is not None
        and marks_f >= 95.0
        and isinstance(basis, str)
        and (
            "latest daily" in basis.lower()
            or "session-fresh" in basis.lower()
            or "session fresh" in basis.lower()
        )
    )
    # Daily bars: a Thu→Mon calendar delta is a weekend/holiday, not a missing tape.
    gap_ok = gap_f is None or gap_f < 1.0 or session_fresh_marks
    gap_detail = (
        f"feed_gap_days={gap_f}"
        if gap_f is not None
        else "feed_gap not recorded yet"
    )
    if gap_f is not None and gap_f >= 1.0 and session_fresh_marks:
        gap_detail += " (calendar; marks session-fresh — not a missing tape)"
    gate(
        "feed_gap",
        gap_ok,
        gap_detail,
        required=gap_f is not None,
    )

    marks_ok = marks_f is None or marks_f >= 95.0
    dishonest = isinstance(basis, str) and "average cost" in basis.lower() and (
        marks_f is None or marks_f < 95.0
    )
    gate(
        "marks_valuation",
        marks_ok and not dishonest,
        (
            f"basis={basis or '?'} marks_pct={marks_f if marks_f is not None else '?'}"
        ),
        required=basis is not None or marks_f is not None,
    )

    reasons = notes.get("reason_counts") or {}
    session_idle = int(reasons.get("session_closed") or 0) + int(
        reasons.get("mark_only") or 0
    )
    data_blocks = (
        int(reasons.get("capability_gap") or 0)
        + int(reasons.get("empty_live_feed") or 0)
        + int(reasons.get("feed_error") or 0)
        + int(reasons.get("yahoo_cooldown") or 0)
    )
    gate(
        "idle_vs_block",
        True,  # informational — always "ok" but detail separates expected idle
        (
            f"expected_idle(session_closed+mark_only)={session_idle} · "
            f"data/capability_blocks={data_blocks}"
        ),
        required=False,
    )

    # --- Yahoo soak ---
    yahoo_429 = None
    if market_data is not None and hasattr(market_data, "yahoo_soak_today"):
        try:
            soak = market_data.yahoo_soak_today(day_ist=day_ist)
            yahoo_429 = int(soak.get("status_429") or 0)
        except Exception:  # noqa: BLE001
            yahoo_429 = None
    elif root is not None:
        try:
            from atlas.investment.market_data_service import MarketDataService

            yahoo_429 = int(
                MarketDataService(data_dir=root)
                .yahoo_soak_today(day_ist=day_ist)
                .get("status_429")
                or 0
            )
        except Exception:  # noqa: BLE001
            yahoo_429 = None
    gate(
        "yahoo_429",
        yahoo_429 is None or yahoo_429 == 0,
        f"yahoo_429={yahoo_429 if yahoo_429 is not None else 'n/a'}",
        required=yahoo_429 is not None,
    )

    # --- host / archive / ticks ---
    archive_ok = True
    archive_detail = "host_guard unbound"
    if host_guard is not None and hasattr(host_guard, "status"):
        try:
            hg = host_guard.status()
            archive_ok = int(hg.get("max_archive_workers") or 1) <= 1 or not hg.get(
                "archive_rth_clamped", True
            )
            # During RTH we want clamped=1; after hours max may be 2
            if hg.get("archive_rth_clamped"):
                archive_ok = int(hg.get("max_archive_workers") or 1) == 1
            archive_detail = (
                f"archive={hg.get('archive_workers_running')}/"
                f"{hg.get('max_archive_workers')} "
                f"rth_clamped={hg.get('archive_rth_clamped')} "
                f"configured={hg.get('configured_max_archive_workers')}"
            )
        except Exception:  # noqa: BLE001
            archive_detail = "host_guard status failed"
    gate("archive_rth", archive_ok, archive_detail, required=False)

    ticks_detail = "budget unbound"
    ticks_ok = True
    if budget is not None and hasattr(budget, "snapshot"):
        try:
            b = budget.snapshot()
            eff = int(b.get("effective_ticks") or 0)
            pref = int(b.get("preferred_ticks") or 0)
            ticks_ok = eff >= min(4, pref) or b.get("clamp_reason") == "pressure_half"
            ticks_detail = (
                f"effective={eff} preferred={pref} hard={b.get('hard_tick_ceiling')} "
                f"clamp={b.get('clamp_reason')} profile={b.get('profile')}"
            )
            # Informational: prefer reporting honesty over hard fail after hours
            ticks_ok = True
        except Exception:  # noqa: BLE001
            ticks_detail = "budget snapshot failed"
    gate("tick_slots", ticks_ok, ticks_detail, required=False)

    # --- FNO pause honesty ---
    fno_paused = fno_lab_paused()
    fno_detail = (
        "ATLAS_STAB0_PAUSE_FNO=1 (operator lock)"
        if fno_paused
        else "FNO lab unlocked — ticks allowed"
    )
    if root is not None and not fno_paused:
        try:
            from atlas.investment.session_notes import load_day_notes as _ldn

            fno_notes = _ldn(
                root, portfolio_key="india_fno_learner", ist_date=day_ist
            )
            rc = fno_notes.get("reason_counts") or {}
            if rc:
                fno_detail = f"unlocked · reason_counts={rc}"
        except Exception:  # noqa: BLE001
            pass
    gate("fno_status", True, fno_detail, required=False)

    # --- beliefs (track only; Phase 5 frozen) ---
    belief_detail = "reasoning unbound"
    if reasoning is not None:
        try:
            total = None
            if hasattr(reasoning, "consultation_metrics"):
                m = reasoning.consultation_metrics()
                if isinstance(m, dict):
                    if isinstance(m.get("total"), (int, float)):
                        total = int(m["total"])
                    nested = m.get("consultations_today")
                    if total is None and isinstance(nested, dict) and nested.get("total") is not None:
                        total = int(nested["total"])
                    elif total is None and isinstance(nested, (int, float)):
                        total = int(nested)
            if total is None and hasattr(reasoning, "metrics"):
                mx = reasoning.metrics()
                nested = (mx or {}).get("consultations_today")
                if isinstance(nested, dict) and nested.get("total") is not None:
                    total = int(nested["total"])
                elif isinstance(nested, (int, float)):
                    total = int(nested)
            belief_detail = f"consultations_today={total}"
        except Exception:  # noqa: BLE001
            belief_detail = "belief metrics unavailable"
    gate("belief_consults_tracked", True, belief_detail, required=False)

    required = [g for g in gates if g.get("required")]
    optional = [g for g in gates if not g.get("required")]
    if not required:
        status = "incomplete"
    elif all(g["ok"] for g in required):
        status = "pass"
    else:
        status = "fail"

    return {
        "version": VERSION,
        "day_ist": day_ist,
        "laboratory_id": laboratory_id,
        "status": status,
        "success_metric": "observe_and_explain",
        "gates": gates,
        "counts": {
            "required": len(required),
            "required_ok": sum(1 for g in required if g["ok"]),
            "optional_ok": sum(1 for g in optional if g["ok"]),
        },
        "note": (
            "Clean equity session = journal + honest marks/idle reasons + Yahoo calm. "
            "Buys are not a success metric. SELF0 Phase 5 remains frozen."
        ),
    }
