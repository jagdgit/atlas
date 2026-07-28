"""SI.4 — Valuation path branching on missing evidence.

Strategy picks paths; this module enforces honesty on the ValuationCase:
activate a usable path, mark unavailable paths, never invent DCF MoS.
"""

from __future__ import annotations

from typing import Any

from atlas.investment.research.models import utc_now_iso

# Path kinds used across packs (stable IDs for UI / gates)
PATH_DCF = "dcf_fcf"
PATH_PE = "multiples_pe"
PATH_PB = "pb_roe"
PATH_SECTOR = "sector_relative"
PATH_ORDER_BOOK = "order_book_earnings"
PATH_WATCH = "watch_insufficient"

PATH_LABELS: dict[str, str] = {
    PATH_DCF: "DCF on FCF",
    PATH_PE: "PE vs fair / peers",
    PATH_PB: "P/B vs RoE",
    PATH_SECTOR: "Sector-relative multiples",
    PATH_ORDER_BOOK: "Order-book-aware earnings",
    PATH_WATCH: "Watch — insufficient evidence",
}


def classify_method(text: str) -> str:
    """Map free-text pack valuation method → path kind."""
    low = (text or "").lower()
    if "dcf" in low:
        return PATH_DCF
    if "p/b" in low or "price to book" in low or ("book" in low and "roe" in low):
        return PATH_PB
    if "order-book" in low or "order book" in low:
        return PATH_ORDER_BOOK
    # PE / multiples before generic "peer/sector" (many PE lines say "peer multiples")
    if "pe" in low or "p/e" in low or "multiple" in low or "fcf yield" in low:
        return PATH_PE
    if "peer" in low or "sector" in low or "relative" in low:
        return PATH_SECTOR
    if "watch" in low or "insufficient" in low:
        return PATH_WATCH
    return PATH_SECTOR


def path_requirements(kind: str) -> list[str]:
    if kind == PATH_DCF:
        return ["fcf", "price_or_shares"]
    if kind == PATH_PE:
        return ["pe"]
    if kind == PATH_PB:
        return ["price", "book_or_roe"]  # soft: roe helps fair band
    if kind == PATH_ORDER_BOOK:
        return ["earnings_or_pe"]
    if kind == PATH_SECTOR:
        return ["pe_or_sector"]
    return []


def _has(inputs: dict[str, Any], key: str) -> bool:
    if key == "price_or_shares":
        return inputs.get("price") is not None or inputs.get("shares") is not None
    if key == "book_or_roe":
        return inputs.get("book_value") is not None or inputs.get("roe") is not None
    if key == "earnings_or_pe":
        return inputs.get("pe") is not None or inputs.get("earnings") is not None
    if key == "pe_or_sector":
        return inputs.get("pe") is not None or bool(inputs.get("sector"))
    return inputs.get(key) is not None


def inputs_from_ratios(ratios: dict[str, Any] | None) -> dict[str, Any]:
    r = dict(ratios or {})
    out: dict[str, Any] = {}
    for k in ("fcf", "pe", "price", "shares", "share_count", "roe", "book_value", "sector"):
        if r.get(k) is not None:
            out["shares" if k == "share_count" else k] = r.get(k)
    return out


def evaluate_path(
    kind: str,
    *,
    inputs: dict[str, Any],
    label: str | None = None,
) -> dict[str, Any]:
    """Return usable / missing for one path kind."""
    reqs = path_requirements(kind)
    missing = [req for req in reqs if not _has(inputs, req)]
    # Soften: PATH_PB usable with roe alone for qualitative band (still no MoS without price)
    if kind == PATH_PB and missing == ["price"] and _has(inputs, "book_or_roe"):
        # usable for method label but MoS stays unknown
        return {
            "kind": kind,
            "label": label or PATH_LABELS.get(kind, kind),
            "usable": True,
            "mos_possible": False,
            "missing": ["price"],
            "reason": None,
        }
    if kind == PATH_DCF and "fcf" in missing:
        return {
            "kind": kind,
            "label": label or PATH_LABELS.get(kind, kind),
            "usable": False,
            "mos_possible": False,
            "missing": missing,
            "reason": "fcf_absent",
        }
    if missing and kind != PATH_WATCH:
        return {
            "kind": kind,
            "label": label or PATH_LABELS.get(kind, kind),
            "usable": False,
            "mos_possible": False,
            "missing": missing,
            "reason": "missing_inputs:" + ",".join(missing),
        }
    mos_ok = True
    if kind == PATH_DCF:
        mos_ok = _has(inputs, "price_or_shares") and inputs.get("fcf") is not None
    elif kind == PATH_PE:
        mos_ok = inputs.get("pe") is not None
    elif kind in {PATH_SECTOR, PATH_ORDER_BOOK}:
        mos_ok = inputs.get("pe") is not None
    elif kind == PATH_PB:
        mos_ok = inputs.get("price") is not None and (
            inputs.get("book_value") is not None or inputs.get("roe") is not None
        )
    else:
        mos_ok = False
    return {
        "kind": kind,
        "label": label or PATH_LABELS.get(kind, kind),
        "usable": True,
        "mos_possible": mos_ok,
        "missing": [],
        "reason": None,
    }


def branch_valuation_paths(
    pack: dict[str, Any] | None,
    *,
    inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """SI.4 core — ordered candidates → active / fallbacks / unavailable + next evidence."""
    pack = pack if isinstance(pack, dict) else {}
    inp = dict(inputs or {})
    methods = [str(m) for m in (pack.get("valuation_methods") or []) if m]

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in methods:
        kind = classify_method(m)
        if kind in seen:
            continue
        seen.add(kind)
        candidates.append(evaluate_path(kind, inputs=inp, label=m))

    # Always consider PE and watch as safety nets
    for kind, label in (
        (PATH_PE, PATH_LABELS[PATH_PE]),
        (PATH_WATCH, PATH_LABELS[PATH_WATCH]),
    ):
        if kind not in seen:
            candidates.append(evaluate_path(kind, inputs=inp, label=label))
            seen.add(kind)

    usable = [c for c in candidates if c.get("usable") and c.get("kind") != PATH_WATCH]
    if not usable:
        usable = [evaluate_path(PATH_WATCH, inputs=inp)]

    active = usable[0]
    fallbacks = usable[1:3]
    unavailable = [c for c in candidates if not c.get("usable")]

    # Next evidence: unlock first unavailable preferred path (esp. DCF)
    next_evidence: list[dict[str, str]] = []
    for c in unavailable:
        for req in c.get("missing") or []:
            next_evidence.append(
                {
                    "need": req,
                    "unlocks": str(c.get("kind")),
                    "detail": f"Provide {req} to activate {c.get('label')}",
                }
            )
        if len(next_evidence) >= 4:
            break

    note = None
    if any(c.get("reason") == "fcf_absent" for c in unavailable):
        note = "DCF path unavailable without FCF — active path is multiples/sector-relative; MoS will not claim DCF"
    elif active.get("kind") == PATH_WATCH:
        note = "No usable valuation path — gather PE/FCF/price before MoS"
    elif pack.get("weak") or pack.get("id") == "generic":
        note = "Weak/generic pack — path confidence capped"

    return {
        "version": "si.4",
        "active": {
            "kind": active.get("kind"),
            "label": active.get("label"),
            "mos_possible": bool(active.get("mos_possible")),
        },
        "fallbacks": [
            {"kind": f.get("kind"), "label": f.get("label"), "mos_possible": f.get("mos_possible")}
            for f in fallbacks
        ],
        "unavailable": [
            {
                "kind": u.get("kind"),
                "label": u.get("label"),
                "reason": u.get("reason"),
                "missing": u.get("missing") or [],
            }
            for u in unavailable
        ],
        "next_evidence": next_evidence[:6],
        "candidates": candidates,
        "note": note,
        "as_of": utc_now_iso(),
        # Back-compat with SI.3 field names used in UI
        "primary": active.get("label"),
        "methods_from_pack": methods,
        "evidence": {
            "fcf_present": inp.get("fcf") is not None,
            "pe_present": inp.get("pe") is not None,
            "price_present": inp.get("price") is not None,
        },
    }


def apply_branching_to_valuation_case(
    case: dict[str, Any],
    branching: dict[str, Any],
) -> dict[str, Any]:
    """Stamp path branching onto ValuationCase; never invent DCF MoS when DCF inactive."""
    out = dict(case)
    active = (branching or {}).get("active") or {}
    kind = str(active.get("kind") or "")
    out["path_branching"] = {
        "version": branching.get("version") or "si.4",
        "active_path": kind,
        "active_label": active.get("label"),
        "mos_possible": active.get("mos_possible"),
        "fallbacks": branching.get("fallbacks") or [],
        "unavailable": branching.get("unavailable") or [],
        "next_evidence": branching.get("next_evidence") or [],
        "note": branching.get("note"),
    }
    out["active_valuation_path"] = kind
    out["active_valuation_path_label"] = active.get("label")

    # Honesty: if DCF is not the active path, do not present DCF as the MoS source
    dcf_blocked = any(
        (u.get("kind") == PATH_DCF and u.get("reason") == "fcf_absent")
        for u in (branching.get("unavailable") or [])
    )
    if kind != PATH_DCF:
        # Keep dcf stub only if fcf present for later; MoS method must not claim DCF IV
        if out.get("mos_method") == "price_vs_iv" and out.get("fcf") is None:
            out["margin_of_safety_pct"] = None
            out["mos_method"] = "unavailable"
            gaps = list(out.get("gaps") or [])
            msg = "MoS cleared — DCF/IV path inactive without FCF"
            if msg not in gaps:
                gaps.append(msg)
            out["gaps"] = gaps
        if dcf_blocked:
            gaps = list(out.get("gaps") or [])
            msg = "path: DCF unavailable (fcf_absent) — using " + str(active.get("label") or kind)
            if msg not in gaps:
                gaps.append(msg)
            out["gaps"] = gaps
            # Prefer PE MoS when available
            if out.get("pe") is not None and out.get("fair_pe") is not None:
                from atlas.investment.research.valuation import margin_of_safety_pct

                mos, mos_m = margin_of_safety_pct(
                    intrinsic=None,
                    price=out.get("price"),
                    pe=out.get("pe"),
                    fair_pe=out.get("fair_pe"),
                )
                out["margin_of_safety_pct"] = mos
                out["mos_method"] = mos_m

    if kind == PATH_WATCH or not active.get("mos_possible"):
        if out.get("margin_of_safety_pct") is not None and kind == PATH_WATCH:
            # Watch path: keep MoS only if PE band exists; label honestly
            if out.get("mos_method") not in {"pe_vs_fair", "price_vs_iv"}:
                out["margin_of_safety_pct"] = None
                out["mos_method"] = "unavailable"

    # Method label reflects active path
    if active.get("label"):
        out["method_label"] = str(active.get("label"))
        out["method"] = kind or out.get("method")

    if branching.get("note"):
        out["path_note"] = branching["note"]

    return out
