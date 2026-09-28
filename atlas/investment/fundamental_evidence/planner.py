"""Plan missing fundamental fields for a symbol (deterministic)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from atlas.investment.fundamental_evidence.policy import (
    ACQUIRABLE_FIELDS,
    FIELD_TO_UQ_CODE,
    metric_source_policy,
)

VERSION = "fea.plan.v1"


def _present(row: dict[str, Any], field: str) -> bool:
    if field == "fcf":
        return row.get("fcf") is not None or row.get("free_cash_flow") is not None
    if field == "debt_to_equity":
        return (
            row.get("debt_to_equity") is not None
            or row.get("debt_equity") is not None
            or row.get("d_e") is not None
        )
    if field == "sector":
        s = str(row.get("sector") or "").strip()
        return bool(s) and s.lower() not in {"unknown", "n/a", "none"}
    if field == "identity":
        return bool(row.get("name") or row.get("legal_name") or row.get("identity_ok"))
    return row.get(field) is not None


def plan_symbol_acquisition(
    data_dir: str | Path | None,
    symbol: str,
    *,
    required_fields: list[str] | tuple[str, ...] | None = None,
    program_id: str = "market_intelligence",
    purpose: str = "swing_thesis",
) -> dict[str, Any]:
    """Evidence Planner: WHAT is missing + WHICH sources are allowed."""
    from atlas.investment.fundamentals import get_symbol, normalize_symbol

    sym = normalize_symbol(symbol)
    want = [
        str(f).strip()
        for f in (required_fields or ("pe", "fcf", "roe", "debt_to_equity", "sector", "identity"))
        if str(f).strip() in ACQUIRABLE_FIELDS or str(f).strip() == "debt_to_equity"
    ]
    row = get_symbol(data_dir, sym, program_id=program_id) or {}
    present: list[str] = []
    missing: list[str] = []
    for f in want:
        if _present(row, f):
            present.append(f)
        else:
            missing.append(f)

    steps: list[dict[str, Any]] = []
    for field in missing:
        policy = metric_source_policy(field)
        network = [p for p in policy if p.get("mode") == "network"]
        secondary = [p for p in policy if p.get("mode") == "secondary"]
        operator = [p for p in policy if p.get("mode") == "operator_only"]
        deferred = [p for p in policy if p.get("mode") == "deferred"]
        steps.append(
            {
                "field": field,
                "uq_code": FIELD_TO_UQ_CODE.get(field),
                "priority": "HIGH"
                if field in {"fcf", "pe"}
                else "NORMAL",
                "try_network": [p.get("provider") for p in network],
                "try_secondary": [p.get("provider") for p in secondary],
                "operator_fallback": [p.get("provider") for p in operator],
                "deferred": [p.get("provider") for p in deferred],
                "never": ["zerodha", "screener_html_scrape"],
            }
        )

    return {
        "version": VERSION,
        "kind": "EVIDENCE_ACQUISITION_PLAN",
        "symbol": sym,
        "purpose": purpose,
        "program_id": program_id,
        "required": want,
        "present": present,
        "missing": missing,
        "steps": steps,
        "complete": not missing,
        "honesty": (
            "Planner only — does not fetch. Network = NSE/XBRL. Yahoo is "
            "secondary/cross-check, not the default drain. Screener remains operator import."
        ),
    }
