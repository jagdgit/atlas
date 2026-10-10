"""Weekend / idle-time historical scoring of blocked equity switches.

Scores past ``switch_blocked_plc_a`` decisions at 5 / 20 / 60 / 252 trading-day
horizons using durable daily bars only. Never changes the live switch threshold.
Never places orders.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "swing.switch_regret.v1"
STORE_REL = Path("investment") / "switch_learning"
DEFAULT_COST = 0.01  # same all-in proxy as opportunity_switch.DEFAULT_SWITCH_COST
HORIZONS = (5, 20, 60, 252)
_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.swing_switch_regret")


def _safe_float(v: Any) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def load_blocked_switch_decisions(
    data_dir: str | Path | None,
    *,
    laboratory_id: str = "india_equity_learner",
    reason_code: str = "switch_blocked_plc_a",
    max_files: int = 5000,
) -> list[dict[str, Any]]:
    """Unique (decision_ist, hold, challenger) rows from switch_learning/by_id."""
    if not data_dir:
        return []
    root = Path(data_dir) / STORE_REL / laboratory_id / "by_id"
    if not root.is_dir():
        return []
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json"))[: max(0, int(max_files))]:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict):
            continue
        if str(doc.get("reason_code") or "") != reason_code:
            continue
        day = str(doc.get("decision_ist") or "")[:10]
        hold = str(doc.get("hold_symbol") or "").upper()
        chal = str(doc.get("challenger_symbol") or "").upper()
        if not day or not hold or not chal:
            continue
        key = (day, hold, chal)
        if key in seen:
            continue
        seen.add(key)
        out.append(doc)
    return out


def _fwd_return(
    data_dir: Path, symbol: str, as_of: str, horizon: int
) -> float | None:
    from atlas.investment.bar_store import load_bars
    from atlas.investment.fel.datasets.builder import forward_return

    bars = load_bars(data_dir, symbol)
    if not bars:
        return None
    return forward_return(bars, as_of, horizon=horizon)


def score_decision(
    data_dir: str | Path | None,
    doc: dict[str, Any],
    *,
    horizons: tuple[int, ...] = HORIZONS,
    switch_cost: float = DEFAULT_COST,
) -> dict[str, Any]:
    """Score one blocked switch. Challenger wins if fwd_chal - cost > fwd_hold."""
    day = str(doc.get("decision_ist") or "")[:10]
    hold = str(doc.get("hold_symbol") or "").upper()
    chal = str(doc.get("challenger_symbol") or "").upper()
    row: dict[str, Any] = {
        "decision_ist": day,
        "hold_symbol": hold,
        "challenger_symbol": chal,
        "expected_advantage": _safe_float(doc.get("expected_advantage")),
        "threshold": _safe_float(doc.get("threshold")),
        "switch_cost": float(switch_cost),
        "threshold_changed": False,
        "horizons": {},
    }
    if not data_dir or not day or not hold or not chal:
        row["ok"] = False
        row["reason"] = "incomplete_row"
        return row
    root = Path(data_dir)
    for h in horizons:
        hold_r = _fwd_return(root, hold, day, int(h))
        chal_r = _fwd_return(root, chal, day, int(h))
        entry: dict[str, Any] = {
            "horizon_d": int(h),
            "hold_return": hold_r,
            "challenger_return": chal_r,
            "challenger_net": None if chal_r is None else round(chal_r - float(switch_cost), 6),
            "spread_net": None,
            "winner": None,
            "status": "ok",
        }
        if hold_r is None or chal_r is None:
            entry["status"] = "NOT_EVALUABLE"
            entry["reason"] = "missing_bars"
        else:
            spread = (chal_r - float(switch_cost)) - hold_r
            entry["spread_net"] = round(spread, 6)
            if spread > 0:
                entry["winner"] = "challenger"
            elif spread < 0:
                entry["winner"] = "hold"
            else:
                entry["winner"] = "tie"
        row["horizons"][str(h)] = entry
    row["ok"] = True
    return row


def run_switch_regret(
    data_dir: str | Path | None,
    *,
    laboratory_id: str = "india_equity_learner",
    horizons: tuple[int, ...] = HORIZONS,
    switch_cost: float = DEFAULT_COST,
    max_files: int = 5000,
) -> dict[str, Any]:
    """Batch score unique blocked switches. Live threshold is never modified."""
    docs = load_blocked_switch_decisions(
        data_dir, laboratory_id=laboratory_id, max_files=max_files
    )
    scored = [
        score_decision(data_dir, d, horizons=horizons, switch_cost=switch_cost)
        for d in docs
    ]
    summary: dict[str, Any] = {
        "version": VERSION,
        "laboratory_id": laboratory_id,
        "n_decisions": len(scored),
        "switch_cost": float(switch_cost),
        "threshold_changed": False,
        "horizons": {},
        "honesty": (
            "Historical blocked-switch regret on durable daily bars. "
            "Does not change the live 5% cold-start bar. Does not place orders. "
            "A single weekend sample is not a market belief."
        ),
        "as_of_ist": datetime.now(_IST).strftime("%Y-%m-%d"),
        "rows": scored,
    }
    for h in horizons:
        wins = defaultdict(int)
        spreads: list[float] = []
        missing = 0
        for row in scored:
            entry = (row.get("horizons") or {}).get(str(h)) or {}
            if entry.get("status") != "ok":
                missing += 1
                continue
            wins[str(entry.get("winner") or "?")] += 1
            if entry.get("spread_net") is not None:
                spreads.append(float(entry["spread_net"]))
        summary["horizons"][str(h)] = {
            "n_ok": sum(wins.values()),
            "n_missing": missing,
            "challenger_wins": wins.get("challenger", 0),
            "hold_wins": wins.get("hold", 0),
            "ties": wins.get("tie", 0),
            "mean_spread_net": round(sum(spreads) / len(spreads), 6) if spreads else None,
        }
    return summary


def persist_switch_regret(
    data_dir: str | Path | None, doc: dict[str, Any]
) -> Path | None:
    if not data_dir or not isinstance(doc, dict):
        return None
    day = str(doc.get("as_of_ist") or datetime.now(_IST).strftime("%Y-%m-%d"))
    lab = str(doc.get("laboratory_id") or "india_equity_learner")
    ops = Path(data_dir) / "ops" / "weekend_2026-10-10" / "swing_regret.json"
    try:
        ops.parent.mkdir(parents=True, exist_ok=True)
        ops.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
        return ops
    except OSError:
        _log.debug("ops persist failed", exc_info=True)
    alt = Path(data_dir) / STORE_REL / lab / f"switch_regret_{day}.json"
    try:
        alt.parent.mkdir(parents=True, exist_ok=True)
        alt.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
        return alt
    except OSError:
        return None
