"""LI.1b — laboratory resume after power / internet outages.

Swing, intraday, and F&O share one rule: the sim ledger in Postgres is durable.
Outages do not wipe cash or positions. On reconnect Atlas marks to market and
records an honest session note — it does **not** invent fills for the dark window.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from atlas.investment.laboratory import normalize_laboratory_id

VERSION = "li.1b.laboratory_resume"


def record_feed_gap(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    ist_date: str,
    gap_hours: float | None = None,
    reason: str = "internet_or_power_outage",
    note: str = "",
) -> dict[str, Any] | None:
    """Append outage/resume honesty into per-lab session notes."""
    from atlas.investment.session_notes import load_day_notes, merge_day_notes

    lid = normalize_laboratory_id(laboratory_id=laboratory_id)
    if not data_dir:
        return None
    existing = load_day_notes(data_dir, portfolio_key=lid, ist_date=ist_date) or {}
    gaps = list(existing.get("feed_gaps") or [])
    entry = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "reason": reason,
        "gap_hours": gap_hours,
        "note": (note or "")[:300],
        "version": VERSION,
    }
    gaps.append(entry)
    return merge_day_notes(
        data_dir,
        portfolio_key=lid,
        ist_date=ist_date,
        reason_counts={"ledger_resume": 1},
        samples=[note or reason],
        extra={
            "feed_gaps": gaps[-20:],
            "feed_gap_days": int(existing.get("feed_gap_days") or 0) + 1,
            "last_resume_at": entry["at"],
            "last_resume_reason": reason,
            "laboratory_id": lid,
        },
    )


def resume_laboratory_ledger(
    *,
    portfolio_service: Any,
    market_reader: Any | None,
    mission_id: str,
    laboratory_id: str,
    starting_cash: float = 0.0,
    data_dir: str | Path | None = None,
    ist_date: str | None = None,
    personality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Re-bind ledger after outage and mark open positions from live/replay bars.

    Returns a catch-up report. Never invents trades for the offline window.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    lid = normalize_laboratory_id(laboratory_id=laboratory_id)
    day = ist_date or datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
    person = personality if isinstance(personality, dict) else {}
    holding = str(person.get("holding_philosophy") or "")

    ensured = portfolio_service.ensure_portfolio(
        mission_id=str(mission_id),
        name=lid,
        starting_cash=float(starting_cash or 0),
    )
    pid = ensured.get("id") if isinstance(ensured, dict) else ensured
    positions = []
    if hasattr(portfolio_service, "list_positions"):
        positions = list(portfolio_service.list_positions(pid) or [])

    prices: dict[str, float] = {}
    mark_errors: list[str] = []
    if market_reader is not None and positions:
        for pos in positions:
            if not isinstance(pos, dict):
                continue
            sym = str(pos.get("symbol") or "")
            if not sym:
                continue
            try:
                out = market_reader.bars_for(sym, provider="yahoo", limit=2)
                bars = (out or {}).get("bars") if isinstance(out, dict) else None
                if bars:
                    close = bars[-1].get("close") if isinstance(bars[-1], dict) else None
                    if close is not None:
                        prices[sym] = float(close)
            except Exception as exc:  # noqa: BLE001
                mark_errors.append(f"{sym}: {exc}")

    snap: dict[str, Any] = {}
    if hasattr(portfolio_service, "snapshot"):
        snap = portfolio_service.snapshot(pid, prices=prices or None) or {}
    elif isinstance(ensured, dict):
        snap = {
            "cash": ensured.get("cash"),
            "positions": positions,
            "equity": ensured.get("cash"),
        }

    overnight_warning = None
    if holding in {"flat_eod", "no_overnight"} and positions:
        overnight_warning = (
            "Intraday personality expects flat EOD — open positions after outage "
            "need operator/strategy review (no silent invent-exit)."
        )

    if data_dir:
        record_feed_gap(
            data_dir,
            laboratory_id=lid,
            ist_date=day,
            reason="ledger_resume_after_outage",
            note=overnight_warning or "marked existing positions; no invented fills",
        )

    return {
        "version": VERSION,
        "laboratory_id": lid,
        "mission_id": str(mission_id),
        "sim_portfolio_id": pid,
        "positions_open": len(positions),
        "marks_applied": len(prices),
        "mark_errors": mark_errors[:10],
        "cash": snap.get("cash"),
        "equity": snap.get("equity"),
        "overnight_warning": overnight_warning,
        "invented_fills": False,
        "note": (
            "Ledger restored from durable sim store; prices refreshed when feed available. "
            "Fills during the dark window were not fabricated."
        ),
    }
