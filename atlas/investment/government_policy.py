"""Indian government budget / policy → sector & symbol nudges (Market Program).

Hermetic catalog of Union Budget / PLI / industry-boost themes mapped to NSE
sectors. Operator (or later RSS) items deepen the store. Feeds ranking
``policy_delta_by_symbol`` — influence, not advice (P10).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "gov.1"
STORE_REL = Path("market") / "government" / "policy_snapshot.json"

# Sector keywords → NSE sector labels used in NIFTY membership.
SECTOR_ALIASES: dict[str, tuple[str, ...]] = {
    "Banks": ("bank", "banking", "financial services", "nbfc", "credit"),
    "IT": ("it ", " information technology", "software", "saas", "digital india"),
    "Automobile": ("auto", "ev", "electric vehicle", "mobility", "two-wheeler"),
    "Pharma": ("pharma", "pharmaceutical", "healthcare", "ayush"),
    "Energy": ("energy", "oil", "gas", "power", "renewable", "solar", "green hydrogen"),
    "Metals": ("steel", "metal", "aluminium", "mining", "coal"),
    "Cement": ("cement", "construction materials"),
    "Realty": ("real estate", "housing", "realty", "urban"),
    "FMCG": ("fmcg", "consumer", "food processing"),
    "Telecom": ("telecom", "5g", "broadband", "spectrum"),
    "Capital Goods": ("defence", "defense", "capex", "infrastructure", "rail", "roads", "ports"),
    "Chemicals": ("chemical", "fertilizer", "specialty chemical"),
    "Consumer Durables": ("consumer durable", "electronics manufacturing", "pli electronics"),
}

# Built-in policy themes (Union Budget / industrial policy style). Positive = boost.
DEFAULT_POLICY_CATALOG: list[dict[str, Any]] = [
    {
        "id": "budget_infra_capex",
        "title": "Union Budget — elevated infrastructure / railway / roads capex",
        "summary": (
            "Higher public capex on roads, railways, and logistics typically supports "
            "Capital Goods, Cement, Metals, and select Realty names."
        ),
        "sectors": ["Capital Goods", "Cement", "Metals", "Realty"],
        "delta": 0.12,
        "source": "catalog:union_budget",
        "kind": "budget",
    },
    {
        "id": "pli_electronics_auto",
        "title": "PLI schemes — electronics manufacturing & auto/EV",
        "summary": (
            "Production-Linked Incentive schemes for electronics and EV/auto supply chains "
            "support Consumer Durables, Automobile, and related manufacturing."
        ),
        "sectors": ["Consumer Durables", "Automobile", "IT"],
        "delta": 0.10,
        "source": "catalog:pli",
        "kind": "industrial_policy",
    },
    {
        "id": "renewable_energy_push",
        "title": "Renewable energy / green hydrogen policy push",
        "summary": (
            "Policy support for renewables and green hydrogen aids Energy names with "
            "clean-energy exposure and related capital goods."
        ),
        "sectors": ["Energy", "Capital Goods"],
        "delta": 0.09,
        "source": "catalog:energy_transition",
        "kind": "policy",
    },
    {
        "id": "defence_indigenisation",
        "title": "Defence indigenisation & Make in India",
        "summary": (
            "Higher defence budget and indigenisation preferences support Capital Goods "
            "and specialised manufacturing linked to defence orders."
        ),
        "sectors": ["Capital Goods"],
        "delta": 0.11,
        "source": "catalog:defence",
        "kind": "budget",
    },
    {
        "id": "digital_india_fintech",
        "title": "Digital public infrastructure / fintech enablement",
        "summary": (
            "UPI / account aggregator / digital India rails support IT services and "
            "financial digitalisation themes (Banks / IT)."
        ),
        "sectors": ["IT", "Banks"],
        "delta": 0.07,
        "source": "catalog:digital_india",
        "kind": "policy",
    },
    {
        "id": "pharma_api_incentives",
        "title": "Pharma / API manufacturing incentives",
        "summary": (
            "Incentives for bulk drugs and pharma manufacturing support Pharma sector "
            "names with domestic API / formulation exposure."
        ),
        "sectors": ["Pharma"],
        "delta": 0.08,
        "source": "catalog:pharma",
        "kind": "industrial_policy",
    },
    {
        "id": "housing_urban",
        "title": "Affordable housing / urban development outlays",
        "summary": (
            "Housing and urban schemes can lift Cement, Realty, and related consumer "
            "demand themes — treat as a soft sector nudge."
        ),
        "sectors": ["Realty", "Cement", "FMCG"],
        "delta": 0.06,
        "source": "catalog:housing",
        "kind": "budget",
    },
    {
        "id": "telecom_spectrum_capex",
        "title": "Telecom / 5G infrastructure cycle",
        "summary": (
            "Spectrum and network rollout cycles support Telecom operators and related "
            "capex suppliers."
        ),
        "sectors": ["Telecom", "Capital Goods"],
        "delta": 0.05,
        "source": "catalog:telecom",
        "kind": "policy",
    },
]

_WORD = re.compile(r"[a-z0-9]+", re.I)


def store_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / STORE_REL


def load_snapshot(data_dir: str | Path) -> dict[str, Any]:
    path = store_path(data_dir)
    if not path.is_file():
        return empty_snapshot()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except Exception:  # noqa: BLE001
        pass
    return empty_snapshot()


def empty_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "updated_at": None,
        "items": [],
        "sector_deltas": {},
        "notes": [
            "Hermetic government-policy catalog for India equity ranking nudges.",
            "Operator items / Budget notes deepen this store — not live gazette scrape.",
        ],
    }


def save_snapshot(data_dir: str | Path, snap: dict[str, Any]) -> Path:
    path = store_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    snap = dict(snap)
    snap["version"] = VERSION
    snap["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(snap, indent=2, sort_keys=True), encoding="utf-8")
    return path


def refresh_catalog(
    data_dir: str | Path,
    *,
    operator_items: list[dict[str, Any]] | None = None,
    include_defaults: bool = True,
) -> dict[str, Any]:
    """Rebuild snapshot from catalog + operator items; compute sector deltas."""
    items: list[dict[str, Any]] = []
    if include_defaults:
        items.extend(dict(x) for x in DEFAULT_POLICY_CATALOG)
    for raw in operator_items or []:
        if not isinstance(raw, dict):
            continue
        item = _normalize_item(raw)
        if item:
            items.append(item)
    # Dedupe by id (operator overrides catalog)
    by_id: dict[str, dict[str, Any]] = {}
    for it in items:
        by_id[str(it["id"])] = it
    merged = list(by_id.values())
    sector_deltas = aggregate_sector_deltas(merged)
    snap = empty_snapshot()
    snap["items"] = merged
    snap["sector_deltas"] = sector_deltas
    snap["item_count"] = len(merged)
    save_snapshot(data_dir, snap)
    return snap


def _normalize_item(raw: dict[str, Any]) -> dict[str, Any] | None:
    title = str(raw.get("title") or "").strip()
    summary = str(raw.get("summary") or raw.get("text") or "").strip()
    if not title and not summary:
        return None
    sectors = raw.get("sectors")
    if not isinstance(sectors, list) or not sectors:
        sectors = infer_sectors(f"{title} {summary}")
    try:
        delta = float(raw.get("delta") if raw.get("delta") is not None else 0.05)
    except (TypeError, ValueError):
        delta = 0.05
    delta = max(-0.25, min(0.25, delta))
    iid = str(raw.get("id") or "").strip() or _slug(title or summary[:40])
    return {
        "id": iid,
        "title": title or iid,
        "summary": summary,
        "sectors": [str(s) for s in sectors if s],
        "delta": delta,
        "source": str(raw.get("source") or "operator"),
        "kind": str(raw.get("kind") or "policy"),
    }


def _slug(text: str) -> str:
    parts = _WORD.findall(text.lower())[:8]
    return "_".join(parts) or "policy_item"


def infer_sectors(text: str) -> list[str]:
    low = f" {(text or '').lower()} "
    hits: list[str] = []
    for sector, keys in SECTOR_ALIASES.items():
        if any(k in low for k in keys):
            hits.append(sector)
    return hits


def aggregate_sector_deltas(items: list[dict[str, Any]]) -> dict[str, float]:
    acc: dict[str, float] = {}
    for it in items:
        try:
            d = float(it.get("delta") or 0.0)
        except (TypeError, ValueError):
            continue
        for sector in it.get("sectors") or []:
            key = str(sector).strip()
            if not key:
                continue
            acc[key] = acc.get(key, 0.0) + d
    # Bound per sector
    return {k: max(-0.35, min(0.35, v)) for k, v in acc.items()}


def policy_delta_by_symbol(
    members: list[dict[str, Any]],
    *,
    sector_deltas: dict[str, float] | None = None,
    data_dir: str | Path | None = None,
) -> dict[str, float]:
    """Map membership rows → soft policy deltas from sector alignment."""
    if sector_deltas is None and data_dir is not None:
        sector_deltas = (load_snapshot(data_dir).get("sector_deltas") or {})
    sector_deltas = sector_deltas or {}
    if not sector_deltas:
        return {}
    # Normalize keys for fuzzy match
    norm = {k.lower(): float(v) for k, v in sector_deltas.items()}
    out: dict[str, float] = {}
    for m in members:
        sym = str(m.get("symbol") or "").strip()
        if not sym:
            continue
        sector = str(m.get("sector") or "").strip()
        if not sector:
            continue
        delta = norm.get(sector.lower())
        if delta is None:
            # partial match (e.g. "Financial Services" vs Banks)
            low = sector.lower()
            for sk, sv in norm.items():
                if sk in low or low in sk:
                    delta = (delta or 0.0) + sv
        if delta:
            out[sym] = max(-0.35, min(0.35, float(delta)))
    return out


def format_policy_brief(snap: dict[str, Any] | None, *, limit: int = 8) -> str:
    snap = snap or empty_snapshot()
    lines = [
        "Government / policy context (India equity — simulation nudges only)",
        f"Updated: {snap.get('updated_at') or 'n/a'} · items={snap.get('item_count') or len(snap.get('items') or [])}",
        "",
    ]
    for it in (snap.get("items") or [])[:limit]:
        secs = ", ".join(it.get("sectors") or []) or "—"
        lines.append(
            f"• [{it.get('kind', 'policy')}] {it.get('title')} "
            f"(sectors: {secs}; Δ={it.get('delta', 0):+.2f})"
        )
        if it.get("summary"):
            lines.append(f"  {it['summary']}")
    sectors = snap.get("sector_deltas") or {}
    if sectors:
        lines.append("")
        lines.append("Net sector deltas:")
        for k, v in sorted(sectors.items(), key=lambda kv: -abs(float(kv[1])))[:12]:
            lines.append(f"  {k}: {float(v):+.3f}")
    lines.append("")
    lines.append("Not investment advice. Simulation Program only (P10).")
    return "\n".join(lines)


def ensure_defaults(data_dir: str | Path, logger: logging.Logger | None = None) -> dict[str, Any]:
    log = logger or logging.getLogger("atlas.investment.government_policy")
    snap = load_snapshot(data_dir)
    if snap.get("items"):
        return snap
    log.info("seeding hermetic India government policy catalog")
    return refresh_catalog(data_dir, include_defaults=True)
