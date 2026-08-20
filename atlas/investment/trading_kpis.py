"""Operator KPIs for the India equity learner book.

These are the numbers operators asked for when reviewing morning/evening mail
and the Market UI: portfolio total, today's delta, fill vs plan, why buys
happened / did not, and what Atlas recorded as learning. Snapshots land under
``market/trading_kpis/<portfolio_key>/<ist_date>.json`` so strategy changes can
be judged against a durable history.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_log = logging.getLogger("atlas.investment.trading_kpis")
_IST = ZoneInfo("Asia/Kolkata")

VERSION = "trading.kpis.1"
STORE_REL = Path("market") / "trading_kpis"


def tag_trades_ist_day(
    trades: list[dict[str, Any]] | None, *, ist_date: str
) -> list[dict[str, Any]]:
    """Stamp ``ist_day_match`` so KPIs never treat a historical blotter as today."""
    out: list[dict[str, Any]] = []
    for t in trades or []:
        if not isinstance(t, dict):
            continue
        row = dict(t)
        ts = row.get("created_at") or row.get("ts") or row.get("filled_at") or row.get("t")
        match = False
        if ts is not None:
            try:
                if isinstance(ts, datetime):
                    dt = ts
                else:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                match = dt.astimezone(_IST).strftime("%Y-%m-%d") == ist_date
            except Exception:  # noqa: BLE001
                match = False
        row["ist_day_match"] = match
        out.append(row)
    return out

# Canonical operator KPI set (keep in sync with docs/TRADING_STRATEGY_PLAYBOOK.md).
KPI_KEYS = (
    "cash",
    "holdings_value",
    "equity",
    "day_pnl",
    "day_return_pct",
    "total_pnl",
    "total_return_pct",
    "net_contributed_capital",
    "open_positions",
    "fills_today",
    "buys_today",
    "sells_today",
    "candidates_planned",
    "candidates_filled",
    "plan_fill_rate",
    "fees_paid",
    "size_trims",
    "portfolio_gate_blocks",
    "top_no_fill_reasons",
    "phase",
    "confidence",
    "lessons_count",
    "research_studied",
)


def _f(x: Any, default: float | None = None) -> float | None:
    if x is None:
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def kpis_dir(data_dir: str | Path) -> Path:
    return Path(data_dir) / STORE_REL


def kpis_path(data_dir: str | Path, *, portfolio_key: str, ist_date: str) -> Path:
    safe = (portfolio_key or "india_equity_learner").replace("/", "_").strip() or "default"
    return kpis_dir(data_dir) / safe / f"{ist_date}.json"


def load_day_kpis(
    data_dir: str | Path | None,
    *,
    portfolio_key: str,
    ist_date: str,
) -> dict[str, Any]:
    if not data_dir:
        return {}
    path = kpis_path(data_dir, portfolio_key=portfolio_key, ist_date=ist_date)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:  # noqa: BLE001
        _log.debug("trading kpis read failed: %s", path, exc_info=True)
        return {}


def save_day_kpis(
    data_dir: str | Path | None,
    *,
    portfolio_key: str,
    ist_date: str,
    kpis: dict[str, Any],
) -> dict[str, Any]:
    if not data_dir:
        return dict(kpis or {})
    path = kpis_path(data_dir, portfolio_key=portfolio_key, ist_date=ist_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "version": VERSION,
        "ist_date": ist_date,
        "portfolio_key": portfolio_key or "india_equity_learner",
        "kpis": dict(kpis or {}),
    }
    try:
        path.write_text(json.dumps(doc, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        _log.debug("trading kpis write failed: %s", path, exc_info=True)
    return doc


def _kpi_label_for(port: dict[str, Any], notes: dict[str, Any]) -> str | None:
    pk = str(
        port.get("portfolio_key") or notes.get("portfolio_key") or ""
    ).strip()
    try:
        from atlas.investment.index_proxy_lot import KPI_LABEL, is_fno_lab

        if is_fno_lab({}, pk):
            return KPI_LABEL
    except Exception:  # noqa: BLE001
        pass
    return None


def build_trading_kpis(
    *,
    portfolio: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
    session_note: dict[str, Any] | None = None,
    research_digest: dict[str, Any] | None = None,
    gate_log: list[dict[str, Any]] | None = None,
    ist_date: str | None = None,
) -> dict[str, Any]:
    """Assemble the operator KPI snapshot from live book + plan + session notes."""
    port = portfolio if isinstance(portfolio, dict) else {}
    plan_d = plan if isinstance(plan, dict) else {}
    notes = session_note if isinstance(session_note, dict) else {}
    digest = research_digest if isinstance(research_digest, dict) else {}

    positions = port.get("positions") or port.get("holdings") or []
    if isinstance(positions, dict):
        positions = list(positions.values())
    positions = [p for p in positions if isinstance(p, dict)]

    raw_trades = [t for t in (port.get("recent_trades") or []) if isinstance(t, dict)]
    # Untagged blotter is not "today" — require explicit IST match (OI-STAB0 honesty).
    if any("ist_day_match" in t for t in raw_trades):
        trades = [t for t in raw_trades if t.get("ist_day_match")]
    elif ist_date:
        trades = [
            t
            for t in tag_trades_ist_day(raw_trades, ist_date=ist_date)
            if t.get("ist_day_match")
        ]
    else:
        trades = []
    buys = [t for t in trades if str(t.get("side") or "").lower() == "buy"]
    sells = [t for t in trades if str(t.get("side") or "").lower() == "sell"]

    candidates = [c for c in (plan_d.get("candidates") or []) if isinstance(c, dict)]
    planned_syms = {
        str(c.get("symbol") or "").upper() for c in candidates if c.get("symbol")
    }
    filled_syms = {
        str(t.get("symbol") or "").upper() for t in buys if t.get("symbol")
    }
    candidates_filled = len(planned_syms & filled_syms) if planned_syms else len(filled_syms)
    candidates_planned = len(planned_syms)
    plan_fill_rate = (
        round(candidates_filled / candidates_planned, 4) if candidates_planned else None
    )

    reason_counts = dict(notes.get("reason_counts") or {})
    top_reasons = sorted(
        ((str(k), int(v)) for k, v in reason_counts.items()),
        key=lambda kv: (-kv[1], kv[0]),
    )[:8]

    gate = list(gate_log or notes.get("portfolio_gate_log") or [])
    size_trims = sum(1 for g in gate if isinstance(g, dict) and g.get("trimmed_from"))
    gate_blocks = sum(
        1
        for g in gate
        if isinstance(g, dict) and g.get("allowed") is False and not g.get("trimmed_from")
    )

    equity = _f(port.get("equity") if port.get("equity") is not None else port.get("equity_value"))
    holdings = _f(
        port.get("holdings_value")
        if port.get("holdings_value") is not None
        else port.get("positions_value")
    )

    return {
        "cash": _f(port.get("cash")),
        "holdings_value": holdings,
        "equity": equity,
        "day_pnl": _f(port.get("day_pnl")),
        "day_return_pct": _f(port.get("day_return_pct")),
        "total_pnl": _f(port.get("total_pnl")),
        "total_return_pct": _f(port.get("total_return_pct")),
        "net_contributed_capital": _f(port.get("net_contributed_capital")),
        "open_positions": len(positions),
        "fills_today": len(trades),
        "buys_today": len(buys),
        "sells_today": len(sells),
        "candidates_planned": candidates_planned,
        "candidates_filled": candidates_filled,
        "plan_fill_rate": plan_fill_rate,
        "fees_paid": _f(port.get("fees_paid"), 0.0),
        "size_trims": size_trims,
        "portfolio_gate_blocks": gate_blocks,
        "top_no_fill_reasons": [
            {"reason": r, "count": n} for r, n in top_reasons
        ],
        "phase": plan_d.get("phase") or notes.get("phase"),
        "confidence": plan_d.get("confidence") or notes.get("confidence"),
        "lessons_count": len(list(digest.get("lessons") or [])),
        "research_studied": len(list(digest.get("studied") or [])),
        "valuation_basis": port.get("valuation_basis"),
        "marks_pct": port.get("marks_pct"),
        "marks_available": port.get("marks_available"),
        "marks_total": port.get("marks_total"),
        "ist_date": ist_date,
        "filled_symbols": sorted(filled_syms),
        "planned_symbols": sorted(planned_syms),
        "kpi_label": _kpi_label_for(port, notes),
    }


def format_kpi_section(kpis: dict[str, Any] | None) -> list[str]:
    """Plain-text block for morning/evening emails."""
    if not isinstance(kpis, dict) or not kpis:
        return []
    header = str(kpis.get("kpi_label") or "").strip() or "Trading KPIs (operator scorecard)"
    lines = ["", f"{header}:"]

    def money(v: Any) -> str:
        if v is None:
            return "—"
        try:
            return f"₹{float(v):,.2f}"
        except (TypeError, ValueError):
            return str(v)

    def signed(v: Any) -> str:
        if v is None:
            return "—"
        try:
            return f"{float(v):+,.2f}"
        except (TypeError, ValueError):
            return str(v)

    lines.append(
        f"  Book: cash {money(kpis.get('cash'))} · holdings {money(kpis.get('holdings_value'))} "
        f"· equity {money(kpis.get('equity'))}"
    )
    day_pct = kpis.get("day_return_pct")
    tot_pct = kpis.get("total_return_pct")
    lines.append(
        "  Today P&L: ₹"
        + signed(kpis.get("day_pnl"))
        + (f" ({float(day_pct):+.2f}%)" if day_pct is not None else "")
        + " · Total P&L: ₹"
        + signed(kpis.get("total_pnl"))
        + (f" ({float(tot_pct):+.2f}%)" if tot_pct is not None else "")
    )
    lines.append(
        f"  Net capital in: {money(kpis.get('net_contributed_capital'))} · "
        f"open positions: {kpis.get('open_positions')}"
    )
    rate = kpis.get("plan_fill_rate")
    rate_s = f"{float(rate):.0%}" if rate is not None else "—"
    lines.append(
        f"  Plan→fill: {kpis.get('candidates_filled')}/{kpis.get('candidates_planned')} "
        f"({rate_s}) · buys {kpis.get('buys_today')} · sells {kpis.get('sells_today')}"
    )
    lines.append(
        f"  Gate: blocks {kpis.get('portfolio_gate_blocks')} · size trims {kpis.get('size_trims')} "
        f"· fees {money(kpis.get('fees_paid'))}"
    )
    lines.append(
        f"  Learning: phase={kpis.get('phase') or '—'} · confidence={kpis.get('confidence') or '—'} "
        f"· researched {kpis.get('research_studied')} · lessons {kpis.get('lessons_count')}"
    )
    basis = kpis.get("valuation_basis")
    if basis:
        marks_pct = kpis.get("marks_pct")
        marks_bit = (
            f" · marks {kpis.get('marks_available')}/{kpis.get('marks_total')}"
            f" ({float(marks_pct):.0f}%)"
            if marks_pct is not None and kpis.get("marks_total") is not None
            else ""
        )
        lines.append(f"  Valuation: {basis}{marks_bit}")
    reasons = kpis.get("top_no_fill_reasons") or []
    if reasons:
        lines.append("  Top no-fill / hold reasons:")
        for row in reasons[:5]:
            if isinstance(row, dict):
                lines.append(f"    · {row.get('reason')}: {row.get('count')}")
            else:
                lines.append(f"    · {row}")
    return lines
