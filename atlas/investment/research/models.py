"""Investing Research Agent (IRA) — Market Program domain schemas.

Phase A: dossier sections, Research Questions, Research Plan, Research Memory,
MVR, coverage, awareness. Not a platform OS.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

VERSION = "ira.e2"
DEFAULT_PROGRAM = "market_intelligence"

# Canonical dossier sections (10 categories + secondary bucket).
SECTIONS = (
    "business",
    "profitability",
    "financial_health",
    "cash_flow",
    "valuation",
    "growth",
    "earnings_quality",
    "management",
    "moat",
    "risks",
)

# Minimum Viable Research — unlocks decision path (not full DD).
MVR_SECTIONS = (
    "business",
    "management",
    "financial_health",
    "cash_flow",
    "valuation",
    "risks",
)

# Depth weights for coverage — valuation/cash/management matter more than a thin stub.
SECTION_COVERAGE_WEIGHTS: dict[str, float] = {
    "business": 1.5,
    "management": 1.5,
    "financial_health": 1.5,
    "cash_flow": 2.0,
    "valuation": 2.0,
    "risks": 1.0,
    "moat": 1.5,
    "profitability": 1.0,
    "growth": 1.0,
    "earnings_quality": 1.0,
}

QUALITY_BASIC = "basic"
QUALITY_DEVELOPING = "developing"
QUALITY_SUBSTANTIVE = "substantive"
QUALITY_DEEP = "deep"

# Freshness TTL hints (seconds) — refresh policy for incremental updates.
SECTION_TTL_SECONDS: dict[str, int] = {
    "business": 90 * 86400,
    "moat": 90 * 86400,
    "management": 45 * 86400,
    "profitability": 14 * 86400,
    "financial_health": 14 * 86400,
    "cash_flow": 14 * 86400,
    "growth": 14 * 86400,
    "earnings_quality": 14 * 86400,
    "risks": 7 * 86400,
    "valuation": 12 * 3600,
}

CONF_VERY_LOW = "very_low"
CONF_LOW = "low"
CONF_MEDIUM = "medium"
CONF_HIGH = "high"

PHASE_QUEUED = "queued"
PHASE_RESEARCHING = "researching"
PHASE_MVR_READY = "mvr_ready"
PHASE_THESIS_READY = "thesis_ready"
PHASE_DECIDED = "decided"
PHASE_MONITORING = "monitoring"
PHASE_BLOCKED = "blocked"

MVR_QUESTIONS: tuple[str, ...] = (
    "Is the business understandable and durable enough to own?",
    "Is management capital allocation trustworthy?",
    "Is debt sustainable?",
    "Does the company generate (or can it generate) free cash flow?",
    "Is valuation attractive vs a conservative intrinsic estimate?",
    "What could permanently impair the business?",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if s and not s.endswith(".NS") and "." not in s:
        return f"{s}.NS"
    return s


def empty_section(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "status": "empty",  # empty | present | stale | blocked
        "confidence": CONF_VERY_LOW,
        "as_of": None,
        "fields": {},
        "gaps": [f"{name}: not researched yet"],
        "sources": [],
    }


def empty_dossier(symbol: str, *, program_id: str = DEFAULT_PROGRAM) -> dict[str, Any]:
    sym = normalize_symbol(symbol)
    sections = {s: empty_section(s) for s in SECTIONS}
    return {
        "version": VERSION,
        "symbol": sym,
        "program_id": program_id,
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "sections": sections,
        "questions": [],
        "plan": {"steps": [], "cursor": 0},
        "memories": [],
        "valuation": None,
        "thesis": None,
        "phase": PHASE_QUEUED,
        "trigger": None,
        "mode": "mvr",
        "doing_now": "idle",
        "blocked_on": [],
        "known_unknowns": list(MVR_QUESTIONS),
        "known_knowns": [],
        "next": "start_research",
        "outcomes": [],
    }


def default_mvr_questions(symbol: str) -> list[dict[str, Any]]:
    sym = normalize_symbol(symbol)
    now = utc_now_iso()
    out = []
    for i, text in enumerate(MVR_QUESTIONS):
        out.append(
            {
                "id": f"q{i+1}",
                "symbol": sym,
                "text": text,
                "status": "open",  # open | answered | blocked
                "created_at": now,
                "answered_at": None,
                "memory_ids": [],
            }
        )
    return out


def default_research_plan(symbol: str) -> dict[str, Any]:
    steps = [
        {"id": "collect", "label": "Collect available facts / filings refs / quality seeds", "status": "pending"},
        {"id": "business", "label": "Sketch business understanding", "status": "pending"},
        {"id": "cash_debt", "label": "Assess cash flow + debt", "status": "pending"},
        {"id": "valuation", "label": "Form valuation case (multiples; DCF when data exists)", "status": "pending"},
        {"id": "management_risks", "label": "Management signals + impairment risks", "status": "pending"},
        {"id": "thesis", "label": "Write investment thesis", "status": "pending"},
        {"id": "mvr_gate", "label": "Evaluate Minimum Viable Research", "status": "pending"},
    ]
    return {"symbol": normalize_symbol(symbol), "steps": steps, "cursor": 0, "updated_at": utc_now_iso()}


def section_present(section: dict[str, Any] | None) -> bool:
    if not isinstance(section, dict):
        return False
    return str(section.get("status") or "") in {"present", "stale"}


def _meaningful_fields(fields: dict[str, Any] | None) -> int:
    """Count fields that look like real content (not empty stubs)."""
    n = 0
    for k, v in (fields or {}).items():
        if v is None or v == "" or v == [] or v == {}:
            continue
        if isinstance(v, str) and v.lower() in {"unknown", "n/a", "none"}:
            continue
        if k in {"note", "source"} and isinstance(v, str) and "unknown" in v.lower():
            continue
        n += 1
    return n


def section_depth(section: dict[str, Any] | None) -> float:
    """How deeply a section is researched (0–1). Present+gappy ≠ full credit."""
    if not isinstance(section, dict):
        return 0.0
    st = str(section.get("status") or "empty")
    if st == "empty":
        return 0.0
    if st == "blocked":
        return 0.12  # acknowledged but not filled
    gaps = [str(g) for g in (section.get("gaps") or [])]
    fields = section.get("fields") if isinstance(section.get("fields"), dict) else {}
    conf = str(section.get("confidence") or CONF_VERY_LOW)
    n_fields = _meaningful_fields(fields)

    # Base credit for having opened the section (addressed, not ignored).
    depth = 0.12
    if st == "stale":
        depth = 0.10
    if n_fields >= 1:
        depth += 0.18
    if n_fields >= 3:
        depth += 0.15
    if conf == CONF_LOW:
        depth += 0.12
    elif conf == CONF_MEDIUM:
        depth += 0.28
    elif conf == CONF_HIGH:
        depth += 0.40
    # Explicit gaps: section exists but depth is shallow
    if gaps:
        depth *= max(0.25, 1.0 - 0.18 * min(len(gaps), 4))
    if conf == CONF_VERY_LOW:
        depth = min(depth, 0.28)
    # Cap stale slightly lower
    if st == "stale":
        depth *= 0.85
    return round(min(1.0, max(0.0, depth)), 3)


def mvr_status(dossier: dict[str, Any]) -> dict[str, Any]:
    sections = dossier.get("sections") if isinstance(dossier.get("sections"), dict) else {}
    missing: list[str] = []
    present: list[str] = []
    for name in MVR_SECTIONS:
        if section_present(sections.get(name)):
            present.append(name)
        else:
            missing.append(name)
    # Cash flow / valuation may be "present" via honest gap markers.
    for name in ("cash_flow", "valuation"):
        sec = sections.get(name) or {}
        gaps = sec.get("gaps") or []
        if name in missing and any("unknown" in str(g).lower() or "gap" in str(g).lower() for g in gaps):
            # Explicit gap counts as MVR acknowledgement → watch-only later, but section "addressed".
            if name in missing:
                missing.remove(name)
                present.append(name)
    satisfied = len(missing) == 0
    return {
        "satisfied": satisfied,
        "required": list(MVR_SECTIONS),
        "present": present,
        "missing": missing,
    }


def coverage_detail(dossier: dict[str, Any]) -> dict[str, Any]:
    """Weighted depth coverage + per-section fill (operator-honest)."""
    sections = dossier.get("sections") if isinstance(dossier.get("sections"), dict) else {}
    by_section: dict[str, float] = {}
    got = 0.0
    total_w = 0.0
    for name in SECTIONS:
        w = float(SECTION_COVERAGE_WEIGHTS.get(name, 1.0))
        depth = section_depth(sections.get(name))
        # Sector unknown → business coverage cannot exceed 10% (IRA sector leap)
        if name == "business":
            fields = (sections.get("business") or {}).get("fields") or {}
            sec = str(fields.get("sector") or "").strip().lower()
            if not sec or sec == "unknown":
                depth = min(depth, 0.10)
        by_section[name] = round(100.0 * depth, 1)
        got += w * depth
        total_w += w
    pct = round(100.0 * got / max(total_w, 1e-9), 1)
    layers = coverage_layers(dossier, by_section=by_section)
    return {
        "coverage_pct": pct,
        "by_section": by_section,
        "by_evidence": layers.get("by_evidence"),
        "by_reasoning": layers.get("by_reasoning"),
        "method": "weighted_section_depth",
        "note": (
            "Coverage = weighted section depth (gaps/very_low confidence reduce credit). "
            "Sector unknown caps business ≤10%. "
            "Not the same as confidence, research quality, or thesis distinctiveness."
        ),
    }


def coverage_layers(
    dossier: dict[str, Any],
    *,
    by_section: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Split coverage into evidence vs reasoning (operator clarity).

    Evidence: sections with evidence pointers / numeric fields / filings.
    Reasoning: thesis drivers, pack questions, watch items, summary depth.
    """
    sections = dossier.get("sections") if isinstance(dossier.get("sections"), dict) else {}
    by_section = by_section or {}
    # Evidence score from management/cash/valuation/business evidence density
    ev_hits = 0
    ev_total = 4
    for name in ("business", "management", "cash_flow", "valuation"):
        sec = sections.get(name) if isinstance(sections.get(name), dict) else {}
        fields = sec.get("fields") if isinstance(sec.get("fields"), dict) else {}
        evidence = fields.get("evidence") if isinstance(fields.get("evidence"), list) else []
        numeric = sum(
            1
            for k, v in fields.items()
            if k not in {"note", "evidence", "pack", "checklist_summary", "operator_notes", "filings_refs"}
            and v is not None
            and v != ""
            and not isinstance(v, (dict, list))
        )
        has_filings = bool(fields.get("filings_refs"))
        if evidence or numeric >= 2 or has_filings:
            ev_hits += 1
        elif by_section.get(name, 0) >= 20:
            ev_hits += 0.4
    by_evidence = round(100.0 * ev_hits / max(ev_total, 1), 1)

    thesis = dossier.get("thesis") if isinstance(dossier.get("thesis"), dict) else {}
    drivers = thesis.get("drivers") if isinstance(thesis.get("drivers"), dict) else {}
    reason_score = 0.0
    if thesis.get("summary"):
        reason_score += 0.25
    if thesis.get("base") and "working capital / execution" not in str(thesis.get("base") or "").lower():
        reason_score += 0.2
    elif thesis.get("base"):
        reason_score += 0.08
    if drivers.get("positive") or drivers.get("concerns"):
        reason_score += 0.25
    pack_qs = sum(
        1
        for q in (dossier.get("questions") or [])
        if isinstance(q, dict) and q.get("pack") and q.get("pack") != "management"
    )
    if pack_qs:
        reason_score += min(0.2, 0.05 * pack_qs)
    if dossier.get("pack"):
        reason_score += 0.1
    by_reasoning = round(100.0 * min(1.0, reason_score), 1)
    return {
        "by_evidence": by_evidence,
        "by_reasoning": by_reasoning,
        "note": (
            "Evidence = facts/filings/numbers present; "
            "Reasoning = thesis/drivers/pack lens. High reasoning + low evidence = template risk."
        ),
    }


def coverage_pct(dossier: dict[str, Any]) -> float:
    """Weighted fraction of intended DD surface examined in depth (0–100)."""
    return float(coverage_detail(dossier)["coverage_pct"])


def research_quality(dossier: dict[str, Any]) -> dict[str, Any]:
    """Shallow vs deep — independent of coverage % and confidence labels.

    basic: stubs / explicit gaps dominate
    developing: some ratios or pack depth
    substantive: PE/FCF + medium conf on key sections
    deep: rare — high conf + few gaps on MVR
    """
    sections = dossier.get("sections") if isinstance(dossier.get("sections"), dict) else {}
    depths = [section_depth(sections.get(n)) for n in MVR_SECTIONS]
    avg = sum(depths) / max(len(depths), 1)
    val = sections.get("valuation") or {}
    fields = val.get("fields") if isinstance(val.get("fields"), dict) else {}
    # valuation may live on dossier root
    root_val = dossier.get("valuation") if isinstance(dossier.get("valuation"), dict) else {}
    pe = fields.get("pe") if fields.get("pe") is not None else root_val.get("pe")
    fcf = fields.get("fcf") if fields.get("fcf") is not None else root_val.get("fcf")
    has_numbers = pe is not None or fcf is not None
    gap_heavy = sum(
        1
        for n in MVR_SECTIONS
        if len((sections.get(n) or {}).get("gaps") or []) >= 1
        or str((sections.get(n) or {}).get("confidence") or "") == CONF_VERY_LOW
    )
    memories = len(dossier.get("memories") or [])
    filings_touch = any(
        "filing" in str(s).lower()
        for sec in sections.values()
        if isinstance(sec, dict)
        for s in (sec.get("sources") or [])
    )

    level = QUALITY_BASIC
    if avg >= 0.55 and has_numbers and gap_heavy <= 2:
        level = QUALITY_SUBSTANTIVE
    elif avg >= 0.35 and (has_numbers or memories >= 3 or filings_touch):
        level = QUALITY_DEVELOPING
    elif avg >= 0.22:
        level = QUALITY_DEVELOPING if has_numbers else QUALITY_BASIC
    if avg >= 0.75 and gap_heavy == 0 and has_numbers and memories >= 5:
        level = QUALITY_DEEP

    return {
        "level": level,
        "avg_mvr_depth": round(avg, 3),
        "has_valuation_inputs": bool(has_numbers),
        "gap_heavy_sections": gap_heavy,
        "meaning": {
            QUALITY_BASIC: "Most sections exist as stubs or honest gaps — shallow.",
            QUALITY_DEVELOPING: "Some quantitative or pack depth; still not investment-grade.",
            QUALITY_SUBSTANTIVE: "Key numbers present with fewer gaps — usable for sizing debate.",
            QUALITY_DEEP: "High-depth MVR with evidence trail — rare without live filings.",
        }.get(level, ""),
    }


def classify_questions(dossier: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Answered / open / blocked / deferred buckets for scheduling & UI."""
    answered: list[dict[str, Any]] = []
    open_q: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for q in dossier.get("questions") or []:
        if not isinstance(q, dict):
            continue
        st = str(q.get("status") or "open")
        row = {
            "id": q.get("id"),
            "text": q.get("text"),
            "status": st,
            "answer_note": q.get("answer_note"),
            "pack": q.get("pack"),
        }
        if st == "answered":
            answered.append(row)
        elif st == "blocked":
            blocked.append(row)
        elif st == "deferred":
            deferred.append(row)
        else:
            # open + answered_gap still need work
            open_q.append(row)
    for b in dossier.get("blocked_on") or []:
        blocked.append(
            {
                "id": f"block-{len(blocked)+1}",
                "text": str(b),
                "status": "blocked",
                "answer_note": "Capability / data block",
            }
        )
    return {
        "answered": answered,
        "open": open_q,
        "blocked": blocked,
        "deferred": deferred,
    }


def overall_confidence(dossier: dict[str, Any]) -> str:
    sections = dossier.get("sections") if isinstance(dossier.get("sections"), dict) else {}
    rank = {
        CONF_VERY_LOW: 0,
        CONF_LOW: 1,
        CONF_MEDIUM: 2,
        CONF_HIGH: 3,
    }
    scores: list[int] = []
    for name in MVR_SECTIONS:
        sec = sections.get(name) or {}
        if section_present(sec) or (sec.get("gaps") and sec.get("status") != "empty"):
            scores.append(rank.get(str(sec.get("confidence") or CONF_VERY_LOW), 0))
    if not scores:
        return CONF_VERY_LOW
    avg = sum(scores) / len(scores)
    # Valuation low confidence pulls overall down (IRA review).
    val = sections.get("valuation") or {}
    if rank.get(str(val.get("confidence") or CONF_VERY_LOW), 0) <= 1 and section_present(val):
        avg = min(avg, 1.5)
    if avg >= 2.5:
        return CONF_HIGH
    if avg >= 1.5:
        return CONF_MEDIUM
    if avg >= 0.75:
        return CONF_LOW
    return CONF_VERY_LOW


def mark_section(
    dossier: dict[str, Any],
    name: str,
    *,
    fields: dict[str, Any] | None = None,
    confidence: str = CONF_LOW,
    gaps: list[str] | None = None,
    sources: list[str] | None = None,
    status: str = "present",
) -> None:
    sections = dossier.setdefault("sections", {})
    sec = dict(sections.get(name) or empty_section(name))
    sec["status"] = status
    sec["confidence"] = confidence
    sec["as_of"] = utc_now_iso()
    if fields:
        merged = dict(sec.get("fields") or {})
        merged.update(fields)
        sec["fields"] = merged
    if gaps is not None:
        sec["gaps"] = list(gaps)
    if sources:
        sec["sources"] = sorted(set(list(sec.get("sources") or []) + list(sources)))
    sections[name] = sec
    dossier["updated_at"] = utc_now_iso()


def parse_iso_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        s = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:  # noqa: BLE001
        return None


def section_age_seconds(section: dict[str, Any] | None, *, now: datetime | None = None) -> float | None:
    if not isinstance(section, dict):
        return None
    as_of = parse_iso_ts(section.get("as_of"))
    if as_of is None:
        return None
    now = now or datetime.now(timezone.utc)
    return max(0.0, (now - as_of).total_seconds())


def section_is_stale(
    name: str,
    section: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    ttl_override: dict[str, int] | None = None,
) -> bool:
    """True when section missing as_of, empty, or past TTL."""
    if not isinstance(section, dict):
        return True
    st = str(section.get("status") or "empty")
    if st in {"empty", "blocked"}:
        return True
    if st == "stale":
        return True
    ttl_map = ttl_override or SECTION_TTL_SECONDS
    ttl = int(ttl_map.get(name) or 14 * 86400)
    age = section_age_seconds(section, now=now)
    if age is None:
        return True
    return age > ttl


def stale_sections(dossier: dict[str, Any], *, now: datetime | None = None) -> list[str]:
    sections = dossier.get("sections") if isinstance(dossier.get("sections"), dict) else {}
    out: list[str] = []
    for name in SECTIONS:
        if section_is_stale(name, sections.get(name), now=now):
            out.append(name)
    return out


def mark_stale_sections(dossier: dict[str, Any], *, now: datetime | None = None) -> list[str]:
    """Flip past-TTL present sections to status=stale; return names flipped."""
    sections = dossier.setdefault("sections", {})
    flipped: list[str] = []
    for name in SECTIONS:
        sec = sections.get(name)
        if not isinstance(sec, dict):
            continue
        if str(sec.get("status")) == "present" and section_is_stale(name, sec, now=now):
            sec = dict(sec)
            sec["status"] = "stale"
            sections[name] = sec
            flipped.append(name)
    if flipped:
        dossier["updated_at"] = utc_now_iso()
    return flipped
