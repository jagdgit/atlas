"""SI.5 — Distinctiveness block (“why this company exists”).

RC5 prompts before valuation deep-dive. Honesty: unknowns become explicit gaps,
never boilerplate “quality franchise.” Feeds thesis.distinctiveness score fields.
"""

from __future__ import annotations

from typing import Any

from atlas.investment.research import sector_packs as packs
from atlas.investment.research.models import normalize_symbol, utc_now_iso

VERSION = "si.5"

STATUS_RESOLVED = "resolved"
STATUS_WEAK = "weak"
STATUS_UNKNOWN = "unknown"

GAP_REASON = "unknown — need evidence for why this firm exists (not a sector template)"
GAP_POSITION = "unknown — competitive position not established from evidence"
GAP_DRIVERS = "unknown — value drivers not yet company-specific"
GAP_FALSIFIERS = "unknown — falsifiers not pinned (avoid generic risk lists)"


def empty_block(symbol: str = "") -> dict[str, Any]:
    return {
        "version": VERSION,
        "symbol": normalize_symbol(symbol) if symbol else "",
        "status": STATUS_UNKNOWN,
        "reason_to_exist": GAP_REASON,
        "position": GAP_POSITION,
        "value_drivers": [],
        "falsifiers": [],
        "gaps": [
            "reason_to_exist",
            "position",
            "value_drivers",
            "falsifiers",
        ],
        "hypothesis": True,
        "pack_id": None,
        "score_pct": 0.0,
        "hits": [],
        "identifiable_without_name": False,
        "generic": True,
        "note": (
            "Distinctiveness before MoS: why this firm exists, position, "
            "value drivers, falsifiers — gaps over boilerplate."
        ),
        "as_of": None,
    }


def _clean_list(items: list[Any] | None, *, limit: int = 6) -> list[str]:
    out: list[str] = []
    for x in items or []:
        s = str(x).strip()
        if s and s not in out:
            out.append(s)
        if len(out) >= limit:
            break
    return out


def build_distinctiveness(
    *,
    symbol: str,
    identity: dict[str, Any] | None = None,
    pack: dict[str, Any] | None = None,
    thesis: dict[str, Any] | None = None,
    company_name: str = "",
) -> dict[str, Any]:
    """Assemble RC5 distinctiveness from identity + pack; score via pack tokens.

    Does not invent company-specific claims. Pack/identity seeds are labeled
    hypotheses until evidence upgrades them.
    """
    ident = identity if isinstance(identity, dict) else {}
    pack = pack if isinstance(pack, dict) else {}
    thesis = thesis if isinstance(thesis, dict) else {}
    out = empty_block(symbol)
    pack_id = pack.get("id") or ident.get("pack_id")
    weak_pack = bool(pack.get("weak")) or pack_id in {None, "generic"}
    id_status = str(ident.get("status") or STATUS_UNKNOWN)

    gaps: list[str] = []

    # --- reason_to_exist ---
    reason = str(ident.get("distinctiveness_seed") or "").strip()
    if not reason and ident.get("business_type") and id_status != STATUS_UNKNOWN:
        bt = str(ident.get("business_type") or "").strip()
        sector = str(ident.get("sector") or "").strip()
        if bt and bt.lower() not in {"unknown", "generic"}:
            reason = (
                f"Hypothesis — operates as {bt}"
                + (f" in {sector}" if sector and sector.lower() != "unknown" else "")
                + "; company-specific reason still thin"
            )
    if not reason and pack.get("mental_model") and not weak_pack:
        reason = f"Hypothesis (pack lens) — {str(pack.get('mental_model') or '')[:280]}"
    if not reason and pack.get("thesis_interest") and not weak_pack:
        reason = f"Hypothesis (pack lens) — {str(pack.get('thesis_interest') or '')[:280]}"
    if not reason:
        reason = GAP_REASON
        gaps.append("reason_to_exist")

    # --- position ---
    position = ""
    moats = _clean_list(pack.get("moat_lenses"), limit=4)
    if moats and not weak_pack and "unknown" not in moats[0].lower():
        position = f"Hypothesis — examine position via: {'; '.join(moats)}"
    elif ident.get("revenue_model"):
        position = f"Sketch — {str(ident.get('revenue_model') or '')[:240]}"
    if not position:
        position = GAP_POSITION
        gaps.append("position")

    # --- value_drivers ---
    drivers = _clean_list(ident.get("key_drivers"), limit=6)
    if not drivers:
        drivers = _clean_list(pack.get("positive_drivers"), limit=4)
    if not drivers:
        drivers = _clean_list(pack.get("primary_kpis"), limit=4)
    th_drivers = thesis.get("drivers") if isinstance(thesis.get("drivers"), dict) else {}
    if not drivers:
        drivers = _clean_list(th_drivers.get("positive"), limit=4)
    if not drivers or weak_pack:
        if not drivers:
            gaps.append("value_drivers")
        if weak_pack and "value_drivers" not in gaps:
            # Keep any seed lists but mark gap — not company-specific yet
            gaps.append("value_drivers")

    # --- falsifiers ---
    falsifiers = _clean_list(thesis.get("falsifiers"), limit=6)
    if not falsifiers:
        falsifiers = _clean_list(pack.get("falsifiers"), limit=6)
    if not falsifiers or weak_pack:
        if not falsifiers:
            falsifiers = []
            gaps.append("falsifiers")
        elif weak_pack and "falsifiers" not in gaps:
            gaps.append("falsifiers")

    # Status
    if id_status == STATUS_UNKNOWN or weak_pack:
        status = STATUS_UNKNOWN if id_status == STATUS_UNKNOWN else STATUS_WEAK
    elif gaps:
        status = STATUS_WEAK
    else:
        status = STATUS_RESOLVED

    out.update(
        {
            "status": status,
            "reason_to_exist": reason,
            "position": position,
            "value_drivers": drivers,
            "falsifiers": falsifiers,
            "gaps": gaps,
            "hypothesis": True,  # hermetic/hint era — never claim proven
            "pack_id": pack_id,
            "as_of": utc_now_iso(),
        }
    )

    # Feed score engine with RC5 fields + thesis prose
    score_thesis = {
        **thesis,
        "summary": " ".join(
            str(x)
            for x in (
                thesis.get("summary"),
                reason,
                position,
                " ".join(drivers),
                " ".join(falsifiers),
            )
            if x
        ),
        "falsifiers": falsifiers or thesis.get("falsifiers") or [],
        "drivers": {
            **(th_drivers or {}),
            "positive": drivers or list((th_drivers or {}).get("positive") or []),
        },
    }
    score = packs.thesis_distinctiveness(
        score_thesis,
        pack if pack else None,
        company_name=company_name or str(ident.get("business_type") or ""),
    )
    out.update(
        {
            "score_pct": score.get("score_pct"),
            "hits": score.get("hits") or [],
            "tokens_checked": score.get("tokens_checked") or [],
            "identifiable_without_name": bool(score.get("identifiable_without_name")),
            "generic": bool(score.get("generic")) or status != STATUS_RESOLVED,
            "note": score.get("note") or out["note"],
        }
    )
    return out
