"""SI.1 — Business Identity Engine (mandatory before MVR).

Permanent rule: never start due diligence until Atlas answers
\"what kind of business is this, and how should it be analyzed?\"

Does **not** invent KPIs or fundamentals. Uses hermetic hints, universe sector,
sector packs, and operator confirmation. Unknown → CapabilityGap / blocked strategy.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from atlas.investment.research import sector_packs as packs
from atlas.investment.research.models import normalize_symbol

STATUS_RESOLVED = "resolved"
STATUS_WEAK = "weak"
STATUS_UNKNOWN = "unknown"

CONF_HIGH = "high"
CONF_MEDIUM = "medium"
CONF_LOW = "low"
CONF_NONE = "none"

# Pack → capital intensity defaults (honest heuristics, not invented financials).
_PACK_CAPITAL: dict[str, str] = {
    "healthcare": "capital_heavy",
    "defence": "capital_heavy",
    "manufacturing": "capital_heavy",
    "banks": "balance_sheet_heavy",
    "saas_it": "asset_light",
    "consumer": "asset_light",
    "pharma": "capital_heavy",
    "energy_utilities": "capital_heavy",
    "generic": "unknown",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def empty_identity(symbol: str = "") -> dict[str, Any]:
    return {
        "symbol": normalize_symbol(symbol) if symbol else "",
        "business_type": "",
        "industry": "",
        "sector": "",
        "subsector": "",
        "capital_intensity": "unknown",
        "key_drivers": [],
        "revenue_model": "",
        "distinctiveness_seed": "",
        "pack_id": None,
        "status": STATUS_UNKNOWN,
        "confidence": {
            "business_identity": CONF_NONE,
            "sector_membership": CONF_NONE,
        },
        "source": None,
        "as_of": None,
        "operator_confirmed": False,
        "blocked_reason": "identity_unknown",
        "version": "si.1",
    }


def resolve_identity(
    symbol: str,
    *,
    dossier: dict[str, Any] | None = None,
    universe_sector: str | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build or refresh business identity from available honest sources.

    Priority: operator override on dossier > hint > profile/universe sector > pack.
    Never fabricates a sector when nothing is known.
    """
    sym = normalize_symbol(symbol)
    doc = dossier if isinstance(dossier, dict) else {}
    existing = doc.get("business_identity") if isinstance(doc.get("business_identity"), dict) else {}

    # Operator-confirmed always wins.
    if existing.get("operator_confirmed") and existing.get("status") in {
        STATUS_RESOLVED,
        STATUS_WEAK,
    }:
        out = {**empty_identity(sym), **existing}
        out["symbol"] = sym
        return out

    hint = packs.hint_for(sym) or {}
    prof = profile if isinstance(profile, dict) else {}
    sector = (
        str(existing.get("sector") or "").strip()
        or str(hint.get("sector") or "").strip()
        or str(prof.get("sector") or "").strip()
        or str(universe_sector or "").strip()
    )
    subsector = (
        str(existing.get("subsector") or "").strip()
        or str(hint.get("subsector") or "").strip()
        or str(prof.get("subsector") or "").strip()
    )
    pack = packs.pack_for(sym, sector=sector)
    pack_id = (
        (existing.get("pack_id") if existing.get("operator_confirmed") else None)
        or (hint.get("pack") if hint else None)
        or (pack.get("id") if pack else None)
        or doc.get("pack")
    )
    if pack is None and pack_id:
        pack = packs.pack_by_id(str(pack_id))

    business_type = (
        str(existing.get("business_type") or "").strip()
        or subsector
        or (str(pack.get("label") or "") if pack else "")
        or sector
    )
    industry = (
        str(existing.get("industry") or "").strip()
        or sector
        or (str(pack.get("label") or "") if pack else "")
    )

    key_drivers: list[str] = []
    if existing.get("key_drivers"):
        key_drivers = [str(x) for x in existing["key_drivers"] if x][:8]
    elif hint.get("watch_items"):
        key_drivers = [str(x) for x in hint.get("watch_items") or []][:6]
    elif pack and pack.get("primary_kpis"):
        key_drivers = [str(x) for x in pack.get("primary_kpis") or []][:6]

    revenue_model = str(existing.get("revenue_model") or "").strip()
    if not revenue_model and hint.get("facts"):
        revenue_model = str((hint.get("facts") or [""])[0])[:280]
    if not revenue_model and pack and pack.get("mental_model"):
        revenue_model = str(pack.get("mental_model") or "")[:280]

    distinct = str(existing.get("distinctiveness_seed") or "").strip()
    if not distinct and hint.get("facts") and len(hint.get("facts") or []) > 1:
        distinct = str(hint["facts"][1])[:280]
    if not distinct and pack and pack.get("moat_lenses"):
        distinct = f"Hypothesis — examine: {', '.join(list(pack.get('moat_lenses') or [])[:3])}"

    capital = str(existing.get("capital_intensity") or "").strip() or "unknown"
    if capital == "unknown" and pack_id:
        capital = _PACK_CAPITAL.get(str(pack_id), "unknown")

    # Status / confidence
    if sector and (business_type or pack_id):
        if hint or pack_id:
            status = STATUS_RESOLVED
            id_conf = CONF_MEDIUM if hint else CONF_LOW
            sec_conf = CONF_HIGH if hint or pack_id else CONF_MEDIUM
            source = "hint" if hint else ("pack" if pack_id else "universe")
        else:
            status = STATUS_WEAK
            id_conf = CONF_LOW
            sec_conf = CONF_MEDIUM
            source = "universe"
    elif sector:
        status = STATUS_WEAK
        id_conf = CONF_LOW
        sec_conf = CONF_LOW
        source = "universe"
    else:
        status = STATUS_UNKNOWN
        id_conf = CONF_NONE
        sec_conf = CONF_NONE
        source = None

    out = empty_identity(sym)
    out.update(
        {
            "business_type": business_type,
            "industry": industry,
            "sector": sector,
            "subsector": subsector,
            "capital_intensity": capital,
            "key_drivers": key_drivers,
            "revenue_model": revenue_model,
            "distinctiveness_seed": distinct,
            "pack_id": str(pack_id) if pack_id else None,
            "status": status,
            "confidence": {
                "business_identity": id_conf,
                "sector_membership": sec_conf,
            },
            "source": source,
            "as_of": utc_now_iso(),
            "operator_confirmed": False,
            "blocked_reason": None if status != STATUS_UNKNOWN else "identity_unknown",
        }
    )
    return out


def apply_operator_identity(
    symbol: str,
    payload: dict[str, Any],
    *,
    dossier: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Operator sets/confirms identity — highest confidence path."""
    sym = normalize_symbol(symbol)
    base = resolve_identity(sym, dossier=dossier)
    for key in (
        "business_type",
        "industry",
        "sector",
        "subsector",
        "capital_intensity",
        "revenue_model",
        "distinctiveness_seed",
        "pack_id",
    ):
        if payload.get(key) is not None and str(payload.get(key)).strip() != "":
            base[key] = payload[key]
    if isinstance(payload.get("key_drivers"), list):
        base["key_drivers"] = [str(x) for x in payload["key_drivers"] if x][:8]

    # Re-resolve pack from sector if needed
    if base.get("sector") and not base.get("pack_id"):
        pack = packs.pack_for(sym, sector=str(base.get("sector") or ""))
        if pack:
            base["pack_id"] = pack.get("id")

    has_core = bool(base.get("sector") or base.get("business_type"))
    base["status"] = STATUS_RESOLVED if has_core else STATUS_UNKNOWN
    base["confidence"] = {
        "business_identity": CONF_HIGH if has_core else CONF_NONE,
        "sector_membership": CONF_HIGH if base.get("sector") else CONF_NONE,
    }
    base["source"] = "operator"
    base["operator_confirmed"] = True
    base["as_of"] = utc_now_iso()
    base["blocked_reason"] = None if has_core else "identity_unknown"
    base["symbol"] = sym
    return base


def identity_gate(
    identity: dict[str, Any] | None,
    *,
    force: bool = False,
    allow_without_identity: bool = False,
) -> dict[str, Any]:
    """SI.1 gate — block full MVR when identity is unknown (unless force/override)."""
    ident = identity if isinstance(identity, dict) else empty_identity()
    status = str(ident.get("status") or STATUS_UNKNOWN)
    if force or allow_without_identity:
        return {
            "ok": True,
            "gated": False,
            "override": True,
            "status": status,
            "reason": "operator_force" if force else "allow_without_identity",
        }
    if status == STATUS_UNKNOWN:
        return {
            "ok": False,
            "gated": True,
            "override": False,
            "status": status,
            "reason": "identity_unknown",
            "detail": (
                "Business identity is unknown — Atlas will not start generic MVR. "
                "POST /v1/market/research/{symbol}/identity to classify the business, "
                "or pass force=true to override."
            ),
            "capability_gap": "business_identity",
        }
    return {
        "ok": True,
        "gated": False,
        "override": False,
        "status": status,
        "reason": None,
    }


def attach_identity_to_dossier(doc: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
    """Stamp identity + pack onto dossier; seed business section fields when empty."""
    out = dict(doc)
    out["business_identity"] = dict(identity)
    if identity.get("pack_id"):
        out["pack"] = identity["pack_id"]
    sections = dict(out.get("sections") or {})
    biz = dict(sections.get("business") or {})
    fields = dict(biz.get("fields") or {})
    if identity.get("sector") and not fields.get("sector"):
        fields["sector"] = identity["sector"]
    if identity.get("business_type") and not fields.get("business_type"):
        fields["business_type"] = identity["business_type"]
    if identity.get("subsector") and not fields.get("subsector"):
        fields["subsector"] = identity["subsector"]
    if identity.get("capital_intensity") and identity["capital_intensity"] != "unknown":
        fields.setdefault("capital_intensity", identity["capital_intensity"])
    summary_bits = [
        identity.get("business_type"),
        identity.get("sector"),
        identity.get("revenue_model"),
    ]
    if not fields.get("summary"):
        summary = " · ".join(str(x) for x in summary_bits if x)
        if summary:
            fields["summary"] = summary[:400]
    biz["fields"] = fields
    if identity.get("status") == STATUS_RESOLVED:
        biz["confidence"] = identity.get("confidence", {}).get("business_identity") or CONF_MEDIUM
    sections["business"] = biz
    out["sections"] = sections
    return out
