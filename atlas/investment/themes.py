"""Macro Theme Engine v1 (IIP.2) — hypotheses → beneficiary roles → symbols.

Hermetic seed maps for India-first themes. Not a live industry database —
edges are labeled ``source=hermetic_theme_seed``. Market Knowledge Graph (IIP.5)
will deepen relationships later.
"""

from __future__ import annotations

from typing import Any

VERSION = "iip.2.themes"

# role → illustrative Yahoo .NS symbols (subset overlapping our staged universes)
_THEME_SEEDS: tuple[dict[str, Any], ...] = (
    {
        "theme_id": "data_centers",
        "label": "Data Centers",
        "hypothesis": "India's data-center demand will grow with cloud and AI workloads.",
        "horizon_default": "structural",
        "status": "active",
        "beneficiary_roles": [
            "power",
            "cooling",
            "transmission",
            "cables",
            "transformers",
            "realty_reit",
            "it_services",
        ],
        "symbols": {
            "power": ["TATAPOWER.NS", "NTPC.NS", "POWERGRID.NS", "TORNTPOWER.NS"],
            "cooling": ["VOLTAS.NS", "BLUESTARCO.NS"],
            "transmission": ["POWERGRID.NS", "KEI.NS"],
            "cables": ["POLYCAB.NS", "KEI.NS"],
            "transformers": ["SIEMENS.NS", "ABB.NS"],
            "realty_reit": ["OBEROIRLTY.NS", "PRESTIGE.NS", "GODREJPROP.NS"],
            "it_services": ["TCS.NS", "INFY.NS", "HCLTECH.NS", "LTTS.NS"],
        },
        "policy_hints": ["digital_india", "power_capex"],
    },
    {
        "theme_id": "green_energy",
        "label": "Renewable Energy / Green Power",
        "hypothesis": "Energy transition + PLI / grid investment support renewable manufacturers and utilities.",
        "horizon_default": "structural",
        "status": "active",
        "beneficiary_roles": ["utilities", "epc_equipment", "cables", "storage_proxy"],
        "symbols": {
            "utilities": ["TATAPOWER.NS", "NTPC.NS", "NHPC.NS", "TORNTPOWER.NS", "POWERGRID.NS"],
            "epc_equipment": ["SUZLON.NS", "SIEMENS.NS", "ABB.NS", "KEI.NS"],
            "cables": ["POLYCAB.NS", "KEI.NS"],
            "storage_proxy": ["EXIDEIND.NS", "HBLPOWER.NS"],
        },
        "policy_hints": ["energy_transition", "pli"],
    },
    {
        "theme_id": "defence",
        "label": "Defence & Aerospace",
        "hypothesis": "Indigenisation and higher defence budgets lift capital-goods and electronics suppliers.",
        "horizon_default": "structural",
        "status": "active",
        "beneficiary_roles": ["platforms", "electronics", "shipyards"],
        "symbols": {
            "platforms": ["BEL.NS", "HAL.NS", "BHEL.NS"],
            "electronics": ["BEL.NS", "DATAPATTNS.NS", "ZENTEC.NS", "KAYNES.NS"],
            "shipyards": ["MAZDOCK.NS", "GRSE.NS"],
        },
        "policy_hints": ["defence"],
    },
    {
        "theme_id": "ev_battery",
        "label": "EV / Battery / Auto ancillaries",
        "hypothesis": "EV adoption and localisation raise demand for batteries, precision auto, and power electronics.",
        "horizon_default": "long_term",
        "status": "active",
        "beneficiary_roles": ["oem", "ancillary", "battery", "electronics"],
        "symbols": {
            "oem": ["M&M.NS", "TATAMOTORS.NS", "TMPV.NS", "BAJAJ-AUTO.NS", "TVSMOTOR.NS"],
            "ancillary": ["MOTHERSON.NS", "SONACOMS.NS", "UNOMINDA.NS", "BHARATFORG.NS"],
            "battery": ["EXIDEIND.NS", "HBLPOWER.NS"],
            "electronics": ["DIXON.NS", "KAYNES.NS"],
        },
        "policy_hints": ["ev", "pli"],
    },
    {
        "theme_id": "ai_it",
        "label": "AI / IT services",
        "hypothesis": "Enterprise AI and digital programmes sustain IT services demand with mix shift to higher value.",
        "horizon_default": "long_term",
        "status": "active",
        "beneficiary_roles": ["tier1", "midcap_it", "product_eng"],
        "symbols": {
            "tier1": ["TCS.NS", "INFY.NS", "HCLTECH.NS", "WIPRO.NS", "TECHM.NS"],
            "midcap_it": ["PERSISTENT.NS", "COFORGE.NS", "LTTS.NS", "MPHASIS.NS", "CYIENT.NS"],
            "product_eng": ["TATAELXSI.NS", "KPITTECH.NS", "OFSS.NS"],
        },
        "policy_hints": ["digital_india"],
    },
    {
        "theme_id": "railways",
        "label": "Railways & mobility infra",
        "hypothesis": "Capex in rail and urban mobility supports EPC, coaches, and signalling-adjacent suppliers.",
        "horizon_default": "structural",
        "status": "active",
        "beneficiary_roles": ["epc", "services"],
        "symbols": {
            "epc": ["RVNL.NS", "IRCON.NS", "LT.NS"],
            "services": ["IRCTC.NS", "CONCOR.NS"],
        },
        "policy_hints": ["budget_infra_capex"],
    },
    {
        "theme_id": "healthcare",
        "label": "Healthcare delivery & pharma",
        "hypothesis": "Formalisation and specialty care growth support hospitals and selected pharma exporters.",
        "horizon_default": "long_term",
        "status": "active",
        "beneficiary_roles": ["hospitals", "pharma"],
        "symbols": {
            "hospitals": ["APOLLOHOSP.NS", "MAXHEALTH.NS", "FORTIS.NS", "METROPOLIS.NS"],
            "pharma": ["SUNPHARMA.NS", "CIPLA.NS", "DRREDDY.NS", "LUPIN.NS", "TORNTPHARM.NS"],
        },
        "policy_hints": ["pharma"],
    },
    {
        "theme_id": "power_grid",
        "label": "Power transmission & grid",
        "hypothesis": "Grid modernisation and renewable evacuation require transmission and cable capacity.",
        "horizon_default": "structural",
        "status": "active",
        "beneficiary_roles": ["transmission", "cables", "equipment"],
        "symbols": {
            "transmission": ["POWERGRID.NS"],
            "cables": ["POLYCAB.NS", "KEI.NS"],
            "equipment": ["SIEMENS.NS", "ABB.NS", "CGPOWER.NS"],
        },
        "policy_hints": ["energy_transition", "budget_infra_capex"],
    },
)


def list_themes(*, active_only: bool = True) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in _THEME_SEEDS:
        if active_only and str(raw.get("status") or "active") not in {"active", "watch"}:
            continue
        out.append(_public_theme(raw))
    return out


def get_theme(theme_id: str) -> dict[str, Any] | None:
    key = (theme_id or "").strip().lower().replace(" ", "_").replace("-", "_")
    # Accept THEME_GREEN_ENERGY style ids
    if key.startswith("theme_"):
        key = key[len("theme_") :]
    for raw in _THEME_SEEDS:
        if str(raw.get("theme_id")) == key:
            return _public_theme(raw)
    return None


def _public_theme(raw: dict[str, Any]) -> dict[str, Any]:
    symbols_by_role = dict(raw.get("symbols") or {})
    all_syms: list[str] = []
    seen: set[str] = set()
    for role_syms in symbols_by_role.values():
        for s in role_syms or []:
            sym = str(s).strip().upper()
            if not sym.endswith(".NS") and "." not in sym:
                sym = f"{sym}.NS"
            if sym and sym not in seen:
                seen.add(sym)
                all_syms.append(sym)
    return {
        "theme_id": raw["theme_id"],
        "label": raw.get("label") or raw["theme_id"],
        "hypothesis": raw.get("hypothesis") or "",
        "horizon_default": raw.get("horizon_default") or "structural",
        "status": raw.get("status") or "active",
        "beneficiary_roles": list(raw.get("beneficiary_roles") or []),
        "symbols_by_role": symbols_by_role,
        "symbols": all_syms,
        "count": len(all_syms),
        "policy_hints": list(raw.get("policy_hints") or []),
        "source": "hermetic_theme_seed",
        "version": VERSION,
    }


def theme_universe_id(theme_id: str) -> str:
    tid = (theme_id or "").strip().lower().replace(" ", "_")
    if tid.startswith("theme_"):
        return tid.upper()
    return f"THEME_{tid.upper()}"


def expand_theme_candidates(
    theme_id: str | None = None,
    *,
    themes: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return candidate rows: symbol + theme + role + why + horizon."""
    ids: list[str]
    if themes:
        ids = [str(t) for t in themes]
    elif theme_id:
        ids = [theme_id]
    else:
        ids = [t["theme_id"] for t in list_themes()]

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tid in ids:
        theme = get_theme(tid)
        if not theme:
            continue
        horizon = theme.get("horizon_default") or "structural"
        for role, syms in (theme.get("symbols_by_role") or {}).items():
            for s in syms or []:
                sym = str(s).strip().upper()
                if not sym.endswith(".NS") and "." not in sym:
                    sym = f"{sym}.NS"
                key = f"{theme['theme_id']}:{sym}"
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    {
                        "symbol": sym,
                        "theme_id": theme["theme_id"],
                        "theme_label": theme.get("label"),
                        "role": role,
                        "horizon": horizon,
                        "mode": "hypothesis",
                        "why": (
                            f"Theme beneficiary ({theme.get('label')}: {role}) — "
                            f"{theme.get('hypothesis')}"
                        ),
                        "hypothesis": theme.get("hypothesis"),
                        "source": "hermetic_theme_seed",
                    }
                )
    return out


def themes_view() -> dict[str, Any]:
    themes = list_themes()
    return {
        "themes": themes,
        "count": len(themes),
        "version": VERSION,
        "note": (
            "Hermetic theme seeds for hypothesis discovery (IIP.2). "
            "Not a complete industry map — MKG (IIP.5) will deepen edges."
        ),
    }
