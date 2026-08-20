"""OI-LINT0 Phase 2 — thesis must match company identity or it is quarantined.

Hospital-network prose on CIPLA is THESIS_INVALID: it must not influence swing
decisions. Unknown identity stays unknown (does not invent a sector).
"""

from __future__ import annotations

from typing import Any

VERSION = "lint0.thesis_identity.v1"

IDENTITY_VALID = "VALID"
IDENTITY_QUARANTINED = "QUARANTINED"
IDENTITY_UNKNOWN = "UNKNOWN"

STATUS_THESIS_INVALID = "THESIS_INVALID"

# High-confidence hospital-chain language (Apollo-style pack). Never valid for pharma OEMs.
_HOSPITAL_MARKERS = (
    "hospital occupancy",
    "hospital network",
    "branded hospital",
    "arpob",
    "average revenue per occupied bed",
    "occupied bed",
    "doctor retention",
    "bed expansion",
    "bed expansion roic",
    "payer mix",
    "insurance reimbursement",
)

_PACK_MARKERS: dict[str, tuple[str, ...]] = {
    "healthcare": _HOSPITAL_MARKERS,
    "pharma": (
        "formulation",
        "generic",
        "anda",
        "api",
        "respiratory",
        "pharmaceutical",
        "drug",
    ),
    "banks": ("nim", "casa", "credit cost", "npa", "deposit"),
    "saas_it": ("it services", "deal pipeline", "attrition", "utilization"),
    "defence": ("order book", "defence", "defense", "isro"),
    "manufacturing": (
        "motorcycle",
        "two-wheeler",
        "commercial vehicle",
        "oem",
        "volume",
        "dealer",
    ),
}

# Packs that must not be confused with each other.
_INCOMPATIBLE = frozenset(
    {
        frozenset({"pharma", "healthcare"}),
        frozenset({"banks", "pharma"}),
        frozenset({"banks", "healthcare"}),
        frozenset({"saas_it", "healthcare"}),
        frozenset({"saas_it", "pharma"}),
        frozenset({"defence", "healthcare"}),
        frozenset({"manufacturing", "healthcare"}),
        frozenset({"manufacturing", "pharma"}),
        frozenset({"manufacturing", "banks"}),
    }
)


def _blob(awareness: dict[str, Any] | None) -> str:
    if not isinstance(awareness, dict):
        return ""
    parts: list[str] = []
    thesis = awareness.get("thesis")
    if isinstance(thesis, dict):
        for k in ("summary", "hypothesis", "one_liner", "trigger", "text", "body"):
            if thesis.get(k):
                parts.append(str(thesis.get(k)))
        for d in thesis.get("drivers") or []:
            if isinstance(d, str):
                parts.append(d)
            elif isinstance(d, dict):
                parts.append(str(d.get("text") or d.get("driver") or ""))
    elif isinstance(thesis, str):
        parts.append(thesis)
    for key in ("summary", "thesis_drivers"):
        val = awareness.get(key)
        if isinstance(val, str):
            parts.append(val)
        elif isinstance(val, list):
            parts.extend(str(x) for x in val if x)
    dist = awareness.get("thesis_distinctiveness") or awareness.get("distinctiveness")
    if isinstance(dist, dict):
        for vd in dist.get("value_drivers") or []:
            if isinstance(vd, str):
                parts.append(vd)
            elif isinstance(vd, dict):
                parts.append(str(vd.get("text") or ""))
    return " ".join(parts).lower()


def _identity_pack(symbol: str, awareness: dict[str, Any] | None) -> tuple[str | None, str]:
    """Return (pack_id, source). Never invents a pack."""
    aw = awareness if isinstance(awareness, dict) else {}
    ident = aw.get("business_identity") if isinstance(aw.get("business_identity"), dict) else {}
    pack = str(ident.get("pack_id") or ident.get("pack") or "").strip().lower() or None
    if pack:
        return pack, "business_identity"
    sector = str(ident.get("sector") or aw.get("sector") or "").strip()
    try:
        from atlas.investment.research import sector_packs as packs

        hint = packs.hint_for(symbol)
        if hint and hint.get("pack"):
            return str(hint["pack"]).strip().lower(), "symbol_hint"
        resolved = packs.pack_for(symbol, sector=sector or None)
        if resolved and resolved.get("id"):
            return str(resolved["id"]).strip().lower(), "sector"
    except Exception:  # noqa: BLE001
        pass
    return None, "unknown"


def infer_thesis_pack(text: str) -> str | None:
    blob = (text or "").lower()
    if not blob.strip():
        return None
    if any(m in blob for m in _HOSPITAL_MARKERS):
        return "healthcare"
    scores: dict[str, int] = {}
    for pack, markers in _PACK_MARKERS.items():
        if pack == "healthcare":
            continue
        n = sum(1 for m in markers if m in blob)
        if n:
            scores[pack] = n
    if not scores:
        return None
    return max(scores, key=lambda k: scores[k])


def validate_thesis_identity(
    symbol: str,
    awareness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare thesis prose to the symbol's identity pack.

    mismatch → identity QUARANTINED, stance THESIS_INVALID.
    """
    text = _blob(awareness)
    id_pack, id_source = _identity_pack(symbol, awareness)
    thesis_pack = infer_thesis_pack(text)
    reasons: list[str] = []
    identity = IDENTITY_UNKNOWN
    if id_pack:
        identity = IDENTITY_VALID

    incompatible = False
    if id_pack and thesis_pack and id_pack != thesis_pack:
        pair = frozenset({id_pack, thesis_pack})
        if pair in _INCOMPATIBLE or (
            id_pack == "pharma" and thesis_pack == "healthcare"
        ):
            incompatible = True
            reasons.append(
                f"thesis_pack={thesis_pack} vs identity_pack={id_pack} ({id_source})"
            )

    if id_pack == "pharma" and any(m in text for m in _HOSPITAL_MARKERS):
        incompatible = True
        if "hospital-network language on a pharmaceutical company" not in " ".join(reasons):
            reasons.append("hospital-network language on a pharmaceutical company")

    if id_pack and id_pack != "healthcare" and any(m in text for m in _HOSPITAL_MARKERS):
        incompatible = True
        reasons.append("hospital-chain markers vs non-hospital identity")

    if incompatible:
        identity = IDENTITY_QUARANTINED

    return {
        "version": VERSION,
        "symbol": str(symbol or "").strip().upper(),
        "identity": identity,
        "identity_pack": id_pack,
        "identity_source": id_source,
        "thesis_pack": thesis_pack,
        "thesis_invalid": identity == IDENTITY_QUARANTINED,
        "status": STATUS_THESIS_INVALID if identity == IDENTITY_QUARANTINED else identity,
        "reasons": reasons,
        "has_thesis_text": bool(text.strip()),
    }
