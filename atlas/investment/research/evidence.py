"""IRA Phase F — evidence hierarchy, impact map, sufficiency (F0/F1).

Evidence before eloquence. Operator snapshots are ladder layer 1 (level F).
"""

from __future__ import annotations

from typing import Any

# Hierarchy: A (highest) … G (AI inference — never alone for medium+ confidence)
EVIDENCE_LEVELS: dict[str, dict[str, Any]] = {
    "A": {"label": "Audited annual report", "weight": 1.0},
    "B": {"label": "Quarterly filing", "weight": 0.9},
    "C": {"label": "Investor presentation", "weight": 0.7},
    "D": {"label": "Conference call", "weight": 0.65},
    "E": {"label": "News report", "weight": 0.45},
    "F": {"label": "Operator note / snapshot", "weight": 0.55},
    "G": {"label": "AI inference", "weight": 0.2},
}

PRIORITY_CRITICAL = "critical"
PRIORITY_IMPORTANT = "important"
PRIORITY_OPTIONAL = "optional"

# Field → dossier sections to strengthen / invalidate on ingest (incremental only).
FIELD_SECTION_IMPACT: dict[str, list[str]] = {
    "fcf": ["cash_flow", "valuation", "thesis"],
    "pe": ["valuation", "thesis"],
    "price": ["valuation", "thesis"],
    "shares": ["valuation", "thesis"],
    "share_count": ["valuation", "thesis"],
    "roe": ["financial_health", "profitability"],
    "roic": ["financial_health", "profitability", "moat"],
    "debt_to_equity": ["financial_health", "risks", "thesis"],
    "debt_equity": ["financial_health", "risks", "thesis"],
    "operating_margin": ["profitability", "growth"],
    "net_margin": ["profitability"],
    "revenue_cagr": ["growth", "valuation"],
    "earnings_cagr": ["growth", "valuation"],
    "capex": ["cash_flow", "valuation"],
    "fcf_growth": ["cash_flow", "valuation", "thesis"],
    "discount_rate": ["valuation", "thesis"],
    "promoter_holding": ["management", "risks"],
}

# Always refresh thesis stance/summary patch when valuation-impacting fields change.
VALUATION_FIELDS = {"fcf", "pe", "price", "shares", "share_count", "fcf_growth", "discount_rate", "capex"}


def sections_impacted_by_fields(fields: dict[str, Any] | None) -> list[str]:
    """Unique dossier sections to refresh for the given snapshot fields."""
    out: list[str] = []
    seen: set[str] = set()
    for key, val in (fields or {}).items():
        if val is None or val == "":
            continue
        k = str(key).strip().lower()
        if k in {"symbol", "note", "source", "as_of", "evidence_confidence", "confidence"}:
            continue
        for sec in FIELD_SECTION_IMPACT.get(k) or []:
            if sec == "thesis":
                continue  # thesis patched after valuation, not a section name
            if sec not in seen:
                seen.add(sec)
                out.append(sec)
    # Valuation always if any valuation field present
    if any(k in VALUATION_FIELDS for k in (fields or {}) if (fields or {}).get(k) is not None):
        if "valuation" not in seen:
            out.append("valuation")
        if "cash_flow" not in seen and (fields or {}).get("fcf") is not None:
            out.insert(0, "cash_flow")
    return out


def prioritize_missing_inputs(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Split missing_inputs into critical / important / optional buckets."""
    buckets: dict[str, list[dict[str, Any]]] = {
        PRIORITY_CRITICAL: [],
        PRIORITY_IMPORTANT: [],
        PRIORITY_OPTIONAL: [],
    }
    for row in items or []:
        if not isinstance(row, dict):
            continue
        if row.get("present"):
            continue
        pri = str(row.get("priority") or PRIORITY_IMPORTANT)
        if pri not in buckets:
            pri = PRIORITY_IMPORTANT
        buckets[pri].append(row)
    return buckets


def evidence_sufficiency(
    *,
    valuation: dict[str, Any] | None = None,
    sections: dict[str, Any] | None = None,
    mvr_satisfied: bool = False,
    mos: float | None = None,
    critical_flags: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Per-need sufficiency — not a 0–100 score."""
    sections = sections or {}
    valuation = valuation if isinstance(valuation, dict) else {}
    cf = sections.get("cash_flow") if isinstance(sections.get("cash_flow"), dict) else {}
    mgmt = sections.get("management") if isinstance(sections.get("management"), dict) else {}
    fcf = valuation.get("fcf")
    if fcf is None and isinstance(cf.get("fields"), dict):
        fcf = (cf.get("fields") or {}).get("fcf")
    pe = valuation.get("pe")
    method = str(valuation.get("method") or "insufficient")
    mos_v = mos if mos is not None else valuation.get("margin_of_safety_pct")
    flags = [f for f in (critical_flags or []) if isinstance(f, dict)]

    def _cf_status() -> str:
        if fcf is not None and float(fcf) > 0:
            gaps = cf.get("gaps") or []
            return "sufficient" if not gaps else "weak"
        if cf.get("status") in {"present", "stale"}:
            return "weak"
        return "missing"

    def _mgmt_status() -> str:
        conf = str(mgmt.get("confidence") or "very_low")
        gaps = mgmt.get("gaps") or []
        fields = mgmt.get("fields") if isinstance(mgmt.get("fields"), dict) else {}
        ev = fields.get("evidence")
        if conf in {"medium", "high"} and not gaps:
            return "sufficient"
        if ev or conf == "low":
            return "weak"
        return "missing" if gaps or conf == "very_low" else "weak"

    def _val_status() -> str:
        if any(f.get("kind") == "valuation_irrelevant" for f in flags):
            return "insufficient"
        if method == "insufficient" or mos_v is None:
            return "insufficient"
        if method in {"multiples", "simple_multiple"} and pe is not None:
            return "weak"
        if "dcf" in method and fcf is not None:
            return "sufficient" if mos_v is not None else "weak"
        return "weak"

    decision = "watch"
    if any(f.get("kind") == "thesis_invalidating" for f in flags):
        decision = "avoid"
    elif mvr_satisfied and mos_v is not None and float(mos_v) >= 15.0:
        decision = "size_allowed"

    return {
        "cash_flow": _cf_status(),
        "management": _mgmt_status(),
        "valuation": _val_status(),
        "decision": decision,
        "critical_flags": len(flags),
        "note": (
            "Evidence sufficiency is per need — not coverage, confidence, or research quality. "
            "Critical flags outweigh completed checklists."
        ),
    }


# Filing kind → hierarchy level (IRA.25)
FILING_KIND_LEVEL: dict[str, str] = {
    "annual": "A",
    "ar": "A",
    "annual_report": "A",
    "quarterly": "B",
    "results": "B",
    "presentation": "C",
    "investor_presentation": "C",
    "deck": "C",
    "slides": "C",
    "call": "D",
    "conference_call": "D",
    "earnings_call": "D",
    "transcript": "D",
    "news": "E",
    "operator": "F",
    "note": "F",
    "inference": "G",
    "ai": "G",
}


def level_for_filing(kind: str | None, *, source: str | None = None) -> str:
    k = (kind or "filing").strip().lower()
    if k in FILING_KIND_LEVEL:
        return FILING_KIND_LEVEL[k]
    src = (source or "").lower()
    if "hermetic" in src:
        return "F"
    if "operator" in src:
        return "F"
    return "F"


def make_evidence(
    *,
    claim: str,
    level: str = "F",
    status: str = "present",
    source: str = "",
    ref: str = "",
    confidence: str = "low",
) -> dict[str, Any]:
    lv = (level or "F").upper()
    meta = EVIDENCE_LEVELS.get(lv) or EVIDENCE_LEVELS["F"]
    return {
        "claim": claim,
        "level": lv,
        "level_label": meta.get("label"),
        "status": status,  # present | not_found | contradicted
        "source": source,
        "ref": ref,
        "confidence": confidence,
    }


def section_evidence_levels(section: dict[str, Any] | None) -> list[str]:
    if not isinstance(section, dict):
        return []
    fields = section.get("fields") if isinstance(section.get("fields"), dict) else {}
    raw = fields.get("evidence")
    levels: list[str] = []
    if isinstance(raw, list):
        for row in raw:
            if isinstance(row, dict) and row.get("level"):
                levels.append(str(row["level"]).upper())
    elif isinstance(raw, dict) and raw.get("level"):
        levels.append(str(raw["level"]).upper())
    return sorted(set(levels))


def section_has_substantive_evidence(section: dict[str, Any] | None) -> bool:
    """True if section cites evidence other than pure AI inference / empty stub."""
    if not isinstance(section, dict):
        return False
    fields = section.get("fields") if isinstance(section.get("fields"), dict) else {}
    raw = fields.get("evidence")
    rows = raw if isinstance(raw, list) else ([raw] if isinstance(raw, dict) else [])
    for row in rows:
        if not isinstance(row, dict):
            continue
        lv = str(row.get("level") or "G").upper()
        st = str(row.get("status") or "")
        if st == "not_found":
            continue  # honest gap — not enough to raise confidence
        if lv in {"A", "B", "C", "D", "E", "F"} and st in {"present", "ref_only", ""}:
            return True
    # Operator snapshot / filings in sources
    for s in section.get("sources") or []:
        sl = str(s).lower()
        if any(x in sl for x in ("operator", "filing", "snapshot", "ttl_refresh")):
            return True
    return False


def cap_confidence_without_evidence(dossier: dict[str, Any]) -> list[str]:
    """IRA.25b — confidence > very_low requires evidence pointer (never fake depth)."""
    from atlas.investment.research.models import CONF_VERY_LOW

    flipped: list[str] = []
    sections = dossier.get("sections") if isinstance(dossier.get("sections"), dict) else {}
    for name, sec in sections.items():
        if not isinstance(sec, dict):
            continue
        conf = str(sec.get("confidence") or CONF_VERY_LOW)
        if conf == CONF_VERY_LOW:
            continue
        if section_has_substantive_evidence(sec):
            continue
        # Allow low confidence on hermetic business sketch only
        if name == "business" and conf == "low":
            continue
        if name == "risks" and conf == "low":
            continue
        sec["confidence"] = CONF_VERY_LOW
        gaps = list(sec.get("gaps") or [])
        note = f"{name}: confidence capped — no evidence above AI/stub (IRA.25b)"
        if note not in gaps:
            gaps.append(note)
        sec["gaps"] = gaps
        sections[name] = sec
        flipped.append(name)
    dossier["sections"] = sections
    return flipped


def sections_impacted_by_filings(filings: list[dict[str, Any]] | None) -> list[str]:
    """Filing refs strengthen growth/management/risks — not a full rebuild."""
    if not filings:
        return ["growth", "management"]
    out = ["growth", "management", "risks"]
    kinds = {str(f.get("kind") or "").lower() for f in filings if isinstance(f, dict)}
    if kinds & {"annual", "ar", "annual_report", "quarterly", "results"}:
        if "cash_flow" not in out:
            out.append("cash_flow")
        if "financial_health" not in out:
            out.append("financial_health")
    if kinds & {"deck", "presentation", "investor_presentation", "slides"}:
        if "growth" not in out:
            out.append("growth")
    if kinds & {"transcript", "call", "earnings_call", "conference_call"}:
        if "management" not in out:
            out.append("management")
    return out


def sections_impacted_by_claims(claims: list[dict[str, Any]] | None) -> list[str]:
    """IIP.4 — map extracted claim kinds onto dossier sections."""
    out: list[str] = []
    seen: set[str] = set()
    for c in claims or []:
        if not isinstance(c, dict):
            continue
        hint = str(c.get("section_hint") or "")
        kind = str(c.get("kind") or "")
        targets = [hint] if hint else []
        if kind == "guidance":
            targets.extend(["growth", "risks"])
        elif kind == "risk":
            targets.extend(["risks", "management"])
        elif kind == "kpi":
            targets.extend(["growth", "financial_health", "profitability"])
        elif kind == "cash":
            targets.extend(["cash_flow"])
        for sec in targets:
            if sec and sec not in seen and sec != "thesis":
                seen.add(sec)
                out.append(sec)
    if not out:
        return ["growth", "management", "risks"]
    return out


def schedule_research_questions(
    dossier: dict[str, Any],
    *,
    limit: int = 6,
) -> list[dict[str, Any]]:
    """IRA.26 — next work from Open (skip Blocked/Deferred); Planning-friendly queue."""
    from atlas.investment.research.models import classify_questions

    q = classify_questions(dossier)
    work: list[dict[str, Any]] = []
    # Critical missing valuation inputs first
    val = dossier.get("valuation") if isinstance(dossier.get("valuation"), dict) else {}
    for row in prioritize_missing_inputs(list(val.get("missing_inputs") or [])).get(
        PRIORITY_CRITICAL, []
    ):
        work.append(
            {
                "kind": "missing_input",
                "priority": 1,
                "id": row.get("id"),
                "text": f"Obtain: {row.get('label') or row.get('id')}",
                "reason": "critical for MoS / DCF",
            }
        )
    # Sector primary KPIs (IRA sector leap) — actionable lens after critical inputs
    try:
        from atlas.investment.research import sector_packs as _packs

        sp = _packs.pack_by_id(dossier.get("pack")) if dossier.get("pack") else None
        if not sp:
            biz = (dossier.get("sections") or {}).get("business") or {}
            biz_f = (biz.get("fields") if isinstance(biz, dict) else {}) or {}
            sp = _packs.pack_for(
                str(dossier.get("symbol") or ""),
                sector=str(biz_f.get("sector") or ""),
            )
        for row in _packs.sector_kpi_work_items(sp, limit=4):
            work.append(row)
    except Exception:  # noqa: BLE001
        pass
    for row in q.get("open") or []:
        pri = 2
        if row.get("pack") == "management" and row.get("critical"):
            pri = 1  # F3 critical management questions float up
        work.append(
            {
                "kind": "question",
                "priority": pri,
                "id": row.get("id"),
                "text": row.get("text"),
                "reason": (
                    "critical management checklist"
                    if pri == 1
                    else "open research question"
                ),
                "answer_note": row.get("answer_note"),
            }
        )
    # Outcome priors nudge — weakened/falsified → re-examine management first
    priors = dossier.get("outcome_priors") if isinstance(dossier.get("outcome_priors"), dict) else {}
    if priors.get("last_result") in {"weakened", "falsified"}:
        work.insert(
            0,
            {
                "kind": "outcome_prior",
                "priority": 0,
                "id": "outcome-prior",
                "text": (
                    f"Re-examine after thesis {priors.get('last_result')}: "
                    f"{priors.get('last_note') or 'checkpoint'}"
                ),
                "reason": "ThesisOutcome prior (IRA.29)",
            },
        )
    # Blocked shown as waiting — not scheduled for burn
    for row in (q.get("blocked") or [])[:3]:
        work.append(
            {
                "kind": "blocked",
                "priority": 9,
                "id": row.get("id"),
                "text": row.get("text"),
                "reason": "blocked — wait for CapabilityGap / filings",
            }
        )
    work.sort(key=lambda r: int(5 if r.get("priority") is None else r.get("priority")))
    return work[: max(1, int(limit))]


def critical_flags_summary(flags: list[dict[str, Any]] | None) -> dict[str, Any]:
    flags = [f for f in (flags or []) if isinstance(f, dict)]
    invalidating = [f for f in flags if f.get("kind") == "thesis_invalidating"]
    val_irr = [f for f in flags if f.get("kind") == "valuation_irrelevant"]
    return {
        "count": len(flags),
        "thesis_invalidating": len(invalidating),
        "valuation_irrelevant": len(val_irr),
        "active": flags[-8:],
        "note": (
            "Critical evidence outweighs checklist completion — "
            "one falsifying fact can end the thesis."
        ),
    }
