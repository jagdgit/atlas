"""OI-LINT0 Phase 5 — research intelligence (curiosity gate + evidence verify).

Curiosity runs only when resolving the unknown could change allocation.
Belief writes require verified extracts — unknown beats invented.
News queue drains to evidence or explicit unknown (never seed stubs).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from atlas.investment.curiosity import normalize_unknown
from atlas.investment.market_events import TIER_DISCOVERY, TIER_PRIMARY, TIER_SECONDARY

VERSION = "lint0.research_intelligence.v1"
_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.research_intelligence")

ALLOCATION_SENSITIVE = frozenset(
    {
        "fcf",
        "free_cash_flow",
        "pe",
        "pb",
        "roe",
        "roic",
        "debt_to_equity",
        "debt_equity",
        "debt",
        "promoter_holding",
        "promoter",
        "expected_return",
        "valuation",
        "identity",
        "thesis",
    }
)

NEWS_UNKNOWNS = frozenset(
    {
        "news",
        "company",
        "company_news",
        "sector_news",
        "management_commentary",
        "policy",
        "gov",
        "macro",
    }
)

VERIFIABLE_FIELDS = frozenset(
    {
        "fcf",
        "pe",
        "pb",
        "roe",
        "roic",
        "debt_to_equity",
        "debt_equity",
        "de",
        "promoter_holding",
        "promoter",
        "identity",
        "margin_of_safety_pct",
        "mos",
    }
)

# IRA evidence levels that may support belief write (not G alone)
_BELIEF_WRITE_LEVELS = frozenset({"A", "B", "C", "D", "F"})


def curiosity_affects_allocation(
    unknown: str,
    *,
    symbol: str,
    allocation_blockers: list[dict[str, Any]] | None = None,
    is_open: bool = False,
) -> bool:
    """Research only if resolving this unknown could change the next-rupee decision."""
    norm = normalize_unknown(unknown)
    sym = str(symbol or "").strip().upper()
    blockers = allocation_blockers or []
    for b in blockers:
        if not isinstance(b, dict):
            continue
        if str(b.get("symbol") or "").upper() == sym and normalize_unknown(
            str(b.get("unknown") or "")
        ) == norm:
            return True
    if norm in ALLOCATION_SENSITIVE and is_open:
        return True
    if norm in NEWS_UNKNOWNS:
        return is_open
    if norm in ALLOCATION_SENSITIVE:
        return bool(blockers) and is_open
    return False


def filter_curiosity_candidates(
    candidates: list[dict[str, Any]],
    *,
    allocation_blockers: list[dict[str, Any]] | None = None,
    open_symbols: set[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Drop curiosity items that cannot affect allocation (Phase 5 rule 30)."""
    open_set = {str(s).upper() for s in (open_symbols or set())}
    kept: list[dict[str, Any]] = []
    skipped = 0
    for c in candidates:
        if not isinstance(c, dict):
            continue
        sym = str(c.get("symbol") or "").strip().upper()
        unk = str(c.get("unknown") or "")
        is_open = (not open_set) or sym in open_set
        if curiosity_affects_allocation(
            unk,
            symbol=sym,
            allocation_blockers=allocation_blockers,
            is_open=is_open,
        ):
            c = dict(c)
            c["allocation_sensitive"] = True
            kept.append(c)
        else:
            skipped += 1
    return kept, skipped


def verify_extract(
    field: str,
    value: Any,
    *,
    source: str | None = None,
    source_tier: int | None = None,
    evidence_level: str | None = None,
) -> dict[str, Any]:
    """Verify one extract before it may influence belief / thesis."""
    f = normalize_unknown(str(field or ""))
    if value is None or value == "":
        return {
            "field": f,
            "status": "unknown",
            "may_write_belief": False,
            "reason": "missing_value",
        }
    tier = int(source_tier) if source_tier is not None else None
    lvl = str(evidence_level or "").upper() or None
    if tier == TIER_DISCOVERY or lvl == "G":
        return {
            "field": f,
            "status": "research_question",
            "may_write_belief": False,
            "reason": "tier3_or_inference_only",
        }
    if f == "identity" and tier not in (TIER_PRIMARY, TIER_SECONDARY, None):
        if tier == TIER_DISCOVERY:
            return {
                "field": f,
                "status": "research_question",
                "may_write_belief": False,
                "reason": "identity_requires_primary_source",
            }
    if tier == TIER_PRIMARY or lvl in {"A", "B"}:
        ok = True
    elif tier == TIER_SECONDARY or lvl in {"C", "D", "F"}:
        ok = f in VERIFIABLE_FIELDS
    else:
        ok = f in {"pe", "roe", "pb"} and str(source or "").startswith(
            ("fundamentals", "screener", "yahoo", "operator")
        )
    return {
        "field": f,
        "status": "verified" if ok else "weak",
        "may_write_belief": bool(ok),
        "source": source,
        "source_tier": tier,
        "evidence_level": lvl,
        "reason": "ok" if ok else "insufficient_provenance",
    }


def gate_belief_revision_output(
    parsed: dict[str, Any],
    allowed_evidence_ids: set[str],
    *,
    fundamentals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Strip unverified LLM claims before WSO write."""
    claims = list(parsed.get("claims") or [])
    verified: list[dict[str, Any]] = []
    rejected: list[str] = []
    fund = fundamentals if isinstance(fundamentals, dict) else {}
    for c in claims:
        if isinstance(c, str):
            rejected.append(c[:80])
            continue
        if not isinstance(c, dict):
            continue
        text = str(c.get("text") or c.get("claim") or "")
        cites = [str(x) for x in (c.get("evidence_ids") or c.get("citations") or []) if x]
        if c.get("assumption"):
            verified.append(c)
            continue
        if cites and allowed_evidence_ids and not any(x in allowed_evidence_ids for x in cites):
            rejected.append(text[:80])
            continue
        low = text.lower()
        for field in VERIFIABLE_FIELDS:
            if field in low and field not in fund and fund.get(field) is None:
                v = verify_extract(field, None)
                if not v.get("may_write_belief"):
                    rejected.append(f"{field}: unverified in fundamentals")
                    break
        else:
            verified.append(c)
    out = dict(parsed)
    out["claims"] = verified
    blocked = bool(rejected) and not verified
    if blocked and str(parsed.get("status") or "") not in {"insufficient_evidence", "unchanged"}:
        out["status"] = "insufficient_evidence"
        out["reason"] = (
            (str(parsed.get("reason") or "") + "; " if parsed.get("reason") else "")
            + f"unverified claims rejected ({len(rejected)})"
        )[:500]
    if blocked and parsed.get("thesis_text"):
        out["thesis_text"] = ""
    return {
        "parsed": out,
        "verified_claims": verified,
        "rejected": rejected,
        "blocked": blocked,
    }


def _news_evidence_for_symbol(
    data_dir: str | None,
    symbol: str,
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    if not data_dir or not symbol:
        return []
    try:
        from atlas.investment.observations import DecisionObservationStore
        from atlas.investment.symbol_aliases import news_is_evidence

        store = DecisionObservationStore(data_dir=data_dir)
        rows = store.list_symbol(symbol=symbol, limit=limit, kind="news_event")
        return [r for r in rows if news_is_evidence(r)]
    except Exception:  # noqa: BLE001
        return []


def drain_news_curiosity(
    queue_doc: dict[str, Any] | None,
    data_dir: str | None,
    *,
    laboratory_id: str | None = None,
) -> dict[str, Any]:
    """Drain news/commentary queue items → evidence found or explicit unknown."""
    doc = dict(queue_doc or {})
    items = [i for i in (doc.get("items") or []) if isinstance(i, dict)]
    resolved = 0
    unknown_explicit = 0
    for item in items:
        if str(item.get("status") or "") != "queued":
            continue
        norm = normalize_unknown(str(item.get("unknown") or ""))
        if norm not in NEWS_UNKNOWNS:
            continue
        sym = str(item.get("symbol") or "").strip()
        evidence = _news_evidence_for_symbol(data_dir, sym)
        if evidence:
            item["status"] = "resolved"
            item["resolution"] = "evidence_found"
            item["evidence_count"] = len(evidence)
            item["drained_at"] = datetime.now(_IST).isoformat()
            item["note"] = "Tier-1/2 news observation landed — not a seed stub."
            resolved += 1
        else:
            item["status"] = "unknown_explicit"
            item["resolution"] = "no_real_news_yet"
            item["drained_at"] = datetime.now(_IST).isoformat()
            item["note"] = "Queued news unknown — no verified headline; stays out of belief."
            unknown_explicit += 1
    doc["items"] = items
    doc["news_drain"] = {
        "resolved": resolved,
        "unknown_explicit": unknown_explicit,
        "laboratory_id": laboratory_id,
    }
    return doc


def format_research_intelligence_lines(doc: dict[str, Any] | None) -> list[str]:
    q = doc if isinstance(doc, dict) else {}
    drain = q.get("news_drain") if isinstance(q.get("news_drain"), dict) else {}
    lines = [
        "",
        "── Research intelligence (OI-LINT0 Phase 5) ──",
    ]
    if drain:
        lines.append(
            f"  news drain: resolved={drain.get('resolved', 0)} · "
            f"explicit_unknown={drain.get('unknown_explicit', 0)}"
        )
    skipped = int(q.get("allocation_filtered_skipped") or 0)
    if skipped:
        lines.append(
            f"  curiosity filtered (no allocation impact): {skipped}"
        )
    lines.append(
        "  Belief writes require verified extracts; PLC.A stays fail-closed for new swing names."
    )
    return lines
