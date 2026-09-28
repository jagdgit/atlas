"""Per-metric source hierarchy — preferred → fallbacks (no Screener scrape)."""

from __future__ import annotations

from typing import Any

VERSION = "fea.policy.v1"

# mode:
#   reuse         — already in fundamentals store
#   network       — live fetch on the normal path (NSE/XBRL)
#   secondary     — explicit cross-check only (Yahoo); not the default drain
#   operator_only — Screener CSV/xlsx import / ritual (never HTML scrape)
#   deferred      — filings / annual reports (future densify)
#   compute       — IRA only (MoS)

METRIC_SOURCE_POLICY: dict[str, list[dict[str, Any]]] = {
    "pe": [
        {"provider": "fundamentals_store", "mode": "reuse"},
        {"provider": "nse_xbrl", "mode": "network"},
        {"provider": "yahoo_fundamentals", "mode": "secondary"},
        {"provider": "screener_export", "mode": "operator_only"},
    ],
    "fcf": [
        {"provider": "fundamentals_store", "mode": "reuse"},
        {"provider": "nse_xbrl", "mode": "network"},
        {"provider": "yahoo_fundamentals", "mode": "secondary"},
        {"provider": "screener_export", "mode": "operator_only"},
    ],
    "roe": [
        {"provider": "fundamentals_store", "mode": "reuse"},
        {"provider": "nse_xbrl", "mode": "network"},
        {"provider": "yahoo_fundamentals", "mode": "secondary"},
        {"provider": "universe_seed", "mode": "reuse"},
        {"provider": "screener_export", "mode": "operator_only"},
    ],
    "debt_to_equity": [
        {"provider": "fundamentals_store", "mode": "reuse"},
        {"provider": "nse_xbrl", "mode": "network"},
        {"provider": "yahoo_fundamentals", "mode": "secondary"},
        {"provider": "universe_seed", "mode": "reuse"},
        {"provider": "screener_export", "mode": "operator_only"},
    ],
    "pb": [
        {"provider": "fundamentals_store", "mode": "reuse"},
        {"provider": "yahoo_fundamentals", "mode": "network"},
        {"provider": "screener_export", "mode": "operator_only"},
    ],
    "sector": [
        {"provider": "fundamentals_store", "mode": "reuse"},
        {"provider": "universe_catalog", "mode": "reuse"},
        {"provider": "screener_export", "mode": "operator_only"},
    ],
    "identity": [
        {"provider": "universe_catalog", "mode": "reuse"},
        {"provider": "company_profile", "mode": "reuse"},
    ],
    "mos": [
        {"provider": "ira_valuation", "mode": "compute"},
    ],
}

ACQUIRABLE_FIELDS = frozenset(
    {"pe", "fcf", "roe", "debt_to_equity", "pb", "sector", "identity"}
)

FIELD_TO_UQ_CODE = {
    "pe": "pe_missing",
    "fcf": "fcf_missing",
    "roe": "roe_missing",
    "pb": "pb_missing",
    "debt_to_equity": "debt_missing",
    "mos": "mos_unknown",
    "sector": "sector_missing",
    "identity": "identity_unknown",
}

CODE_TO_FIELD = {v: k for k, v in FIELD_TO_UQ_CODE.items()}
CODE_TO_FIELD["debt_missing"] = "debt_to_equity"


def metric_source_policy(field: str) -> list[dict[str, Any]]:
    return [dict(x) for x in (METRIC_SOURCE_POLICY.get(field) or [])]


def source_policy_table() -> dict[str, Any]:
    return {
        "version": VERSION,
        "kind": "FUNDAMENTAL_SOURCE_POLICY",
        "honesty": (
            "Zerodha never supplies PE/FCF/MoS. NSE/XBRL is primary raw statements. "
            "Yahoo is secondary/cross-check only (not the normal PE/ROE/D/E/FCF drain). "
            "Screener is operator export only (no HTML scrape). "
            "Sector/identity are catalog/profile, not XBRL P&L. MoS is IRA-computed."
        ),
        "metrics": {
            k: [dict(s) for s in v] for k, v in METRIC_SOURCE_POLICY.items()
        },
    }
