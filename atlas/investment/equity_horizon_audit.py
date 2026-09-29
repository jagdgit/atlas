"""Equity horizon audit — thesis/hold horizon vs churn (first slice).

After F&O stated-E[R] acceptance, this audit asks whether the swing equity lab
holds names for an intended multi-day horizon or exits mainly via control/churn.

Does **not** mutate strategy, capital, or PLC.A. Advice-only report.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "equity.horizon_audit.v1"
DEFAULT_LAB = "india_equity_learner"


def _ist_today() -> str:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def audit_path(data_dir: str | Path | None, *, as_of_ist: str | None = None) -> Path | None:
    if not data_dir:
        return None
    day = as_of_ist or _ist_today()
    return Path(data_dir) / "investment" / "equity_horizon_audit" / f"{day}.json"


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _kpi(data_dir: Path, lab: str, day: str) -> dict[str, Any]:
    p = data_dir / "market" / "trading_kpis" / lab / f"{day}.json"
    doc = _load_json(p) or {}
    k = doc.get("kpis") if isinstance(doc.get("kpis"), dict) else doc
    return k if isinstance(k, dict) else {}


def _allocation_latest(data_dir: Path, lab: str) -> list[dict[str, Any]]:
    root = data_dir / "investment" / "allocation" / lab
    if not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for p in sorted(root.glob("*_latest.json")):
        doc = _load_json(p)
        if not doc:
            continue
        sym = str(doc.get("symbol") or p.name.split("_")[0] or "")
        rows.append(
            {
                "symbol": sym,
                "acp": doc.get("acp") or doc.get("state") or doc.get("action"),
                "updated_at": doc.get("updated_at") or doc.get("recorded_at"),
                "path": str(p.name),
            }
        )
    return rows


def _next_rupee(data_dir: Path, lab: str, day: str) -> dict[str, Any]:
    p = data_dir / "investment" / "next_rupee" / lab / f"{day}.json"
    return _load_json(p) or {}


def build_equity_horizon_audit(
    data_dir: str | Path | None,
    *,
    laboratory_id: str = DEFAULT_LAB,
    as_of_ist: str | None = None,
) -> dict[str, Any]:
    """First-slice horizon audit for the swing equity lab."""
    day = as_of_ist or _ist_today()
    root = Path(data_dir) if data_dir else None
    if root is None:
        return {
            "version": VERSION,
            "ok": False,
            "reason": "no_data_dir",
            "honesty": "Cannot audit without data_dir.",
        }

    kpi = _kpi(root, laboratory_id, day)
    holds = _allocation_latest(root, laboratory_id)
    nr = _next_rupee(root, laboratory_id, day)

    open_n = int(kpi.get("open_positions") or 0)
    fills = int(kpi.get("fills_today") or 0)
    buys = int(kpi.get("buys_today") or 0)
    sells = int(kpi.get("sells_today") or 0)
    day_pnl = kpi.get("day_pnl")

    # Intended swing horizon — persona medium ≈ multi-day, not session_flat.
    intended = {
        "lab": laboratory_id,
        "persona_time_horizon": "medium",
        "holding_philosophy": "multi_day_swing_thesis",
        "not": "session_flat / intraday flat_eod",
    }

    churn_signals: list[str] = []
    if fills == 0 and open_n > 0:
        churn_signals.append("no_fills_today_open_holds — mark-only day (consistent with swing hold)")
    if sells > 0 and buys == 0:
        churn_signals.append("sells_without_buys_today — check control_exit vs thesis exit")
    if buys > 0 and sells > 0:
        churn_signals.append("same_day_buy_and_sell — possible execution_churn")
    if open_n == 0 and fills == 0:
        churn_signals.append("flat_idle — no horizon sample today")

    findings = {
        "open_positions": open_n,
        "fills_today": fills,
        "buys_today": buys,
        "sells_today": sells,
        "day_pnl": day_pnl,
        "total_pnl": kpi.get("total_pnl"),
        "holdings_value": kpi.get("holdings_value"),
        "acp_latest_n": len(holds),
        "acp_symbols": [h.get("symbol") for h in holds[:12]],
        "next_rupee_destination": (nr.get("destination") or nr.get("next_rupee") or {}).get(
            "destination"
        )
        if isinstance(nr.get("destination") or nr.get("next_rupee"), dict)
        else nr.get("destination"),
    }

    # Verdict — first slice is diagnostic, not a pass/fail strategy claim.
    if open_n > 0 and fills == 0:
        verdict = "HOLDING_CONSISTENT"
        detail = (
            "Open swing holdings with zero fills today — book is marking, not churning. "
            "Horizon integrity looks healthier than same-day round-trip churn."
        )
    elif sells > buys and sells > 0:
        verdict = "EXIT_PRESSURE"
        detail = (
            "Sells dominate today — inspect whether exits are thesis-driven or control/churn."
        )
    elif fills == 0 and open_n == 0:
        verdict = "NO_SAMPLE"
        detail = "No open holds and no fills — nothing to audit for horizon."
    else:
        verdict = "MIXED"
        detail = "Activity present — review ACP + exit reasons before claiming horizon health."

    doc = {
        "version": VERSION,
        "kind": "EQUITY_HORIZON_AUDIT",
        "laboratory_id": laboratory_id,
        "as_of_ist": day,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "intended_horizon": intended,
        "findings": findings,
        "churn_signals": churn_signals,
        "acp_latest": holds[:20],
        "verdict": verdict,
        "detail": detail,
        "gates_preserved": {
            "strategy_mutation": False,
            "plc_a": "unchanged",
            "validated_learning": "not_claimed",
            "control_signal_v1": "not_touched",
        },
        "honesty": (
            "First-slice diagnostic after F&O stated-E[R] acceptance. "
            "Does not prove thesis quality. Does not unlock L5. "
            "Densify later with per-hold days_held + exit_reason_code once ledger "
            "join is wired."
        ),
        "next": [
            "Keep collecting equity decision→outcome pairs",
            "Densify days_held / exit_reason when trade ledger join is available",
            "F&O attribution densify stays parallel (OI-FNO-ATTR0)",
        ],
    }
    return doc


def persist_equity_horizon_audit(
    data_dir: str | Path | None,
    doc: dict[str, Any] | None = None,
    *,
    laboratory_id: str = DEFAULT_LAB,
    as_of_ist: str | None = None,
) -> dict[str, Any]:
    report = doc or build_equity_horizon_audit(
        data_dir, laboratory_id=laboratory_id, as_of_ist=as_of_ist
    )
    path = audit_path(data_dir, as_of_ist=str(report.get("as_of_ist") or as_of_ist or ""))
    if path is None:
        return {**report, "persisted": False}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
        latest = path.parent / "_latest.json"
        latest.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
        report = dict(report)
        report["persisted"] = True
        report["path"] = str(path)
    except OSError:
        report = dict(report)
        report["persisted"] = False
    return report
