"""LI.2 — Evidence Provider Manager (fundamentals provenance + reconcile).

Every numeric fundamental can carry multiple Evidence Values:
  value + provider + confidence + verified + as_of + ttl

Yahoo is a **medium** provider — never sole truth. Screener/filing/manual outrank it.
Conflicts (>15% relative gap by default) surface as unknowns — never invent a blend.
"""

from __future__ import annotations

import time
from typing import Any

VERSION = "li.2.evidence_providers"
DEFAULT_CONFLICT_PCT = 0.15

# provider_id → (confidence, verified_default)
PROVIDER_META: dict[str, tuple[str, bool]] = {
    "yahoo_fundamentals": ("medium", False),
    "screener_export": ("high", True),
    "operator_import": ("high", True),
    "manual": ("high", True),
    "filing": ("very_high", True),
    "licensed_api": ("high", True),
}

_CONFIDENCE_RANK = {
    "very_low": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "very_high": 4,
}


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def provider_meta(provider: str) -> tuple[str, bool]:
    return PROVIDER_META.get(str(provider or "").strip(), ("medium", False))


def make_evidence_value(
    *,
    field: str,
    value: Any,
    provider: str,
    source: str | None = None,
    as_of: str | None = None,
    confidence: str | None = None,
    verified: bool | None = None,
    ttl_hours: int | None = 168,
    raw_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    conf, ver_default = provider_meta(provider)
    return {
        "field": str(field),
        "value": value,
        "source": source or provider,
        "provider": str(provider),
        "as_of": as_of or _utc(),
        "confidence": confidence or conf,
        "verified": bool(ver_default if verified is None else verified),
        "ttl_hours": ttl_hours,
        "raw_ref": raw_ref or {},
        "recorded_at": _utc(),
        "version": VERSION,
    }


def _rank(ev: dict[str, Any]) -> tuple[int, int, str]:
    """Higher is better: verified, then confidence, then recency string."""
    return (
        1 if ev.get("verified") else 0,
        _CONFIDENCE_RANK.get(str(ev.get("confidence") or "medium"), 2),
        str(ev.get("as_of") or ""),
    )


def relative_gap(a: float, b: float) -> float | None:
    denom = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / denom


def reconcile_field(
    evidence: list[dict[str, Any]],
    *,
    conflict_pct: float = DEFAULT_CONFLICT_PCT,
) -> dict[str, Any]:
    """Pick preferred evidence; flag conflicts. Never invent a blended value."""
    usable = [e for e in evidence if isinstance(e, dict) and e.get("value") is not None]
    if not usable:
        return {
            "value": None,
            "preferred": None,
            "conflict": False,
            "unknowns": [],
            "all": [],
        }
    ordered = sorted(usable, key=_rank, reverse=True)
    preferred = ordered[0]
    try:
        pref_v = float(preferred["value"])
    except (TypeError, ValueError):
        return {
            "value": preferred.get("value"),
            "preferred": preferred,
            "conflict": False,
            "unknowns": [],
            "all": ordered,
        }

    conflict = False
    unknowns: list[str] = []
    for other in ordered[1:]:
        try:
            ov = float(other["value"])
        except (TypeError, ValueError):
            continue
        gap = relative_gap(pref_v, ov)
        if gap is not None and gap > conflict_pct:
            conflict = True
            unknowns.append(
                f"{preferred.get('field') or 'field'}_conflict"
            )
            break

    return {
        "value": preferred.get("value") if not conflict else preferred.get("value"),
        "preferred": preferred,
        # On conflict still return preferred (highest tier) but flag — do not average.
        "conflict": conflict,
        "unknowns": unknowns,
        "all": ordered,
        "down_weight": conflict and str(preferred.get("provider")) == "yahoo_fundamentals",
        "note": (
            f"Provider conflict >{conflict_pct:.0%}: prefer "
            f"{preferred.get('provider')} ({preferred.get('confidence')}); "
            "never invent blended PE/FCF."
            if conflict
            else None
        ),
    }


def append_evidence(
    row: dict[str, Any],
    evidence: dict[str, Any],
    *,
    apply_preferred: bool = True,
    conflict_pct: float = DEFAULT_CONFLICT_PCT,
) -> dict[str, Any]:
    """Attach evidence onto a symbol row; optionally set flat field from reconcile."""
    out = dict(row)
    field = str(evidence.get("field") or "")
    if not field:
        return out
    bag = dict(out.get("evidence") or {})
    hist = list(bag.get(field) or [])
    # de-dupe same provider+as_of+value
    key = (
        evidence.get("provider"),
        evidence.get("as_of"),
        evidence.get("value"),
    )
    hist = [
        h
        for h in hist
        if (h.get("provider"), h.get("as_of"), h.get("value")) != key
    ]
    hist.append(evidence)
    bag[field] = hist[-12:]
    out["evidence"] = bag

    if apply_preferred:
        recon = reconcile_field(bag[field], conflict_pct=conflict_pct)
        if recon.get("value") is not None:
            out[field] = recon["value"]
        conflicts = list(out.get("evidence_conflicts") or [])
        if recon.get("conflict"):
            tag = f"{field}_conflict"
            if tag not in conflicts:
                conflicts.append(tag)
            out["evidence_conflicts"] = conflicts
            out[f"{field}_preferred_provider"] = (recon.get("preferred") or {}).get(
                "provider"
            )
            out[f"{field}_down_weight"] = bool(recon.get("down_weight"))
        elif f"{field}_conflict" in conflicts:
            conflicts = [c for c in conflicts if c != f"{field}_conflict"]
            out["evidence_conflicts"] = conflicts
    return out


def evidence_from_flat_row(
    row: dict[str, Any],
    *,
    fields: tuple[str, ...] = ("pe", "fcf", "roe", "debt_to_equity", "pb", "market_cap", "shares"),
) -> dict[str, Any]:
    """Backfill evidence bags from legacy flat imports (screener/operator)."""
    out = dict(row)
    provider = str(row.get("source") or "operator_import")
    if provider in {"screener", "screener_csv"}:
        provider = "screener_export"
    for field in fields:
        val = row.get(field)
        if field == "fcf" and val is None:
            val = row.get("free_cash_flow")
        if val is None:
            continue
        bag = (out.get("evidence") or {}).get(field) or []
        if bag:
            continue
        ev = make_evidence_value(
            field=field,
            value=val,
            provider=provider,
            source=row.get("source") or provider,
            as_of=row.get("as_of"),
        )
        out = append_evidence(out, ev)
    return out


def coverage_by_provider(symbols: dict[str, Any]) -> dict[str, Any]:
    """Count PE/FCF presence by provider tier for evening / API."""
    by_pe: dict[str, int] = {}
    by_fcf: dict[str, int] = {}
    conflicts = 0
    for row in symbols.values():
        if not isinstance(row, dict):
            continue
        if row.get("evidence_conflicts"):
            conflicts += 1
        pe_ev = ((row.get("evidence") or {}).get("pe") or [])
        fcf_ev = ((row.get("evidence") or {}).get("fcf") or [])
        pe_providers = {str(e.get("provider")) for e in pe_ev if isinstance(e, dict)}
        fcf_providers = {str(e.get("provider")) for e in fcf_ev if isinstance(e, dict)}
        if not pe_providers and row.get("pe") is not None:
            pe_providers = {str(row.get("source") or "operator_import")}
        if not fcf_providers and (
            row.get("fcf") is not None or row.get("free_cash_flow") is not None
        ):
            fcf_providers = {str(row.get("source") or "operator_import")}
        for p in pe_providers:
            by_pe[p] = by_pe.get(p, 0) + 1
        for p in fcf_providers:
            by_fcf[p] = by_fcf.get(p, 0) + 1
    return {
        "pe_by_provider": by_pe,
        "fcf_by_provider": by_fcf,
        "symbols_with_conflicts": conflicts,
        "version": VERSION,
        "honesty": (
            "Yahoo counts are medium-confidence evidence — Screener/filing outrank them. "
            "Conflicts are flagged; values are never averaged."
        ),
    }


def packet_unknowns_from_row(row: dict[str, Any] | None) -> list[str]:
    """Extra unknowns for Decision Packets when evidence conflicts."""
    if not isinstance(row, dict):
        return []
    return [str(x) for x in (row.get("evidence_conflicts") or []) if x]
