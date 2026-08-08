"""SI.3 — Research Strategy Generator (identity → pack → question mix → valuation paths).

Produces a durable ``research_strategy`` on the dossier before / with MVR.
Does not invent fundamentals — only routes questions and valuation paths.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from atlas.investment.research.models import MVR_QUESTIONS, normalize_symbol, utc_now_iso

# Locked research order (plan §7)
RESEARCH_ORDER: tuple[str, ...] = (
    "business_identity",
    "industry_model",
    "unit_economics",
    "management",
    "growth",
    "financials",
    "valuation",
)

# Target mix: ~25% universal / ~75% sector (plan SI.3)
UNIVERSAL_SHARE = 0.28
SECTOR_SHARE = 0.72


def empty_strategy(symbol: str = "") -> dict[str, Any]:
    return {
        "version": "si.3",
        "symbol": normalize_symbol(symbol) if symbol else "",
        "sector_pack_id": None,
        "pack_version": None,
        "strategy_id": "blocked_identity",
        "question_plan": [],
        "valuation_paths": {
            "primary": None,
            "fallbacks": [],
            "unavailable": [],
            "note": "identity or pack missing",
        },
        "research_order": list(RESEARCH_ORDER),
        "blockers": ["identity_unknown"],
        "mix": {"universal": 0, "sector": 0, "universal_share": 0.0, "sector_share": 0.0},
        "as_of": None,
    }


def _q(
    *,
    qid: str,
    text: str,
    kind: str,
    priority: int,
    symbol: str,
    pack_id: str | None = None,
    critical: bool = False,
) -> dict[str, Any]:
    return {
        "id": qid,
        "symbol": symbol,
        "text": text,
        "kind": kind,  # universal | sector
        "priority": priority,
        "status": "open",
        "created_at": utc_now_iso(),
        "answered_at": None,
        "memory_ids": [],
        "pack": pack_id,
        "critical": critical,
        "source": "research_strategy",
    }


def build_valuation_paths(
    pack: dict[str, Any] | None,
    *,
    available_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """SI.3/SI.4 — choose primary / fallback paths; mark DCF unavailable without FCF."""
    from atlas.investment.research.valuation_paths import branch_valuation_paths

    return branch_valuation_paths(pack, inputs=available_inputs)


def build_question_plan(
    symbol: str,
    *,
    pack: dict[str, Any] | None,
    identity: dict[str, Any] | None = None,
    max_total: int = 16,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """~72% sector pack + ~28% universal MVR (by count).

    LQ.1 — sector questions are emitted **first** so the live dossier head
    differs by pack before generic MVR (Apollo ≠ MTAR).
    """
    sym = normalize_symbol(symbol)
    pack = pack if isinstance(pack, dict) else {}
    pack_id = pack.get("id")
    n_univ = max(1, int(round(max_total * UNIVERSAL_SHARE)))
    n_sec = max(0, max_total - n_univ)

    universal_texts = list(MVR_QUESTIONS)
    # Prefer identity / distinctiveness first when present
    if identity and identity.get("status") in {"resolved", "weak"}:
        seed = identity.get("distinctiveness_seed") or identity.get("business_type")
        if seed:
            universal_texts = [
                f"Given identity ({identity.get('business_type') or identity.get('sector')}): "
                f"what makes this firm distinct — and what would falsify that?",
                *universal_texts,
            ]

    sector_texts = list(pack.get("extra_questions") or [])
    # KPI-framed prompts fill when pack questions are thin
    for kpi in pack.get("primary_kpis") or []:
        sector_texts.append(f"What is the evidence path for sector KPI: {kpi}?")

    questions: list[dict[str, Any]] = []
    # Sector-led head (LQ.1)
    for i, text in enumerate(sector_texts[:n_sec]):
        questions.append(
            _q(
                qid=f"sec-q{i+1}",
                text=text,
                kind="sector",
                priority=10 + i,
                symbol=sym,
                pack_id=pack_id,
                critical=i < 2,
            )
        )
    for i, text in enumerate(universal_texts[:n_univ]):
        questions.append(
            _q(
                qid=f"univ-q{i+1}",
                text=text,
                kind="universal",
                priority=50 + i,
                symbol=sym,
                pack_id=pack_id,
                critical=i < 2,
            )
        )

    n_u = sum(1 for q in questions if q.get("kind") == "universal")
    n_s = sum(1 for q in questions if q.get("kind") == "sector")
    total = max(1, n_u + n_s)
    mix = {
        "universal": n_u,
        "sector": n_s,
        "universal_share": round(n_u / total, 3),
        "sector_share": round(n_s / total, 3),
        "target_universal_share": UNIVERSAL_SHARE,
        "target_sector_share": SECTOR_SHARE,
        "activation": "sector_first",
    }
    return questions, mix


def generate_research_strategy(
    symbol: str,
    *,
    identity: dict[str, Any] | None = None,
    pack: dict[str, Any] | None = None,
    available_inputs: dict[str, Any] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Build research_strategy block for the dossier."""
    sym = normalize_symbol(symbol)
    ident = identity if isinstance(identity, dict) else {}
    status = str(ident.get("status") or "unknown")
    pack = pack if isinstance(pack, dict) else None

    if status == "unknown" and not force:
        out = empty_strategy(sym)
        out["as_of"] = utc_now_iso()
        return out

    if pack is None and ident.get("pack_id"):
        from atlas.investment.research import sector_packs as packs

        pack = packs.pack_by_id(str(ident.get("pack_id")))

    blockers: list[str] = []
    if status == "unknown":
        blockers.append("identity_unknown")
    if pack is None or pack.get("id") == "generic" or pack.get("weak"):
        blockers.append("weak_or_missing_pack")

    questions, mix = build_question_plan(sym, pack=pack, identity=ident)
    valuation = build_valuation_paths(pack, available_inputs=available_inputs)

    strategy_id = f"pack:{(pack or {}).get('id') or 'none'}"
    if blockers:
        strategy_id = f"degraded:{strategy_id}"

    return {
        "version": "si.3",
        "symbol": sym,
        "sector_pack_id": (pack or {}).get("id"),
        "pack_version": (pack or {}).get("version") or "si.2",
        "strategy_id": strategy_id,
        "question_plan": questions,
        "valuation_paths": valuation,
        "research_order": list(RESEARCH_ORDER),
        "blockers": blockers,
        "mix": mix,
        "pack_label": (pack or {}).get("label"),
        "mental_model": (pack or {}).get("mental_model") or (pack or {}).get("thesis_interest"),
        "as_of": utc_now_iso(),
    }


def _is_replaceable_research_qid(qid: str) -> bool:
    """Seed MVR (q1..) and strategy/pack ids — replaced on LQ.1 activation."""
    q = str(qid or "")
    if q.startswith(("univ-q", "sec-q", "pack-q")):
        return True
    return bool(q.startswith("q") and q[1:].isdigit())


def apply_strategy_to_dossier(doc: dict[str, Any], strategy: dict[str, Any]) -> dict[str, Any]:
    """Stamp strategy; LQ.1 — sector-led question_plan becomes the live research head.

    Replaces seed ``q*`` / prior ``sec-q*`` / ``univ-q*`` / ``pack-q*``. Preserves
    management checklist and other non-strategy questions (and answered rows).
    """
    out = dict(doc)
    out["research_strategy"] = dict(strategy)
    if strategy.get("sector_pack_id"):
        out["pack"] = strategy["sector_pack_id"]

    existing = [q for q in (out.get("questions") or []) if isinstance(q, dict)]
    plan = [dict(q) for q in (strategy.get("question_plan") or []) if isinstance(q, dict)]
    strategy_id = str(strategy.get("strategy_id") or "")

    if plan and strategy_id != "blocked_identity":
        preserved: list[dict[str, Any]] = []
        answered_by_text: dict[str, dict[str, Any]] = {}
        for q in existing:
            qid = str(q.get("id") or "")
            if q.get("status") == "answered" and _is_replaceable_research_qid(qid):
                answered_by_text[str(q.get("text") or "")] = dict(q)
                continue
            if not _is_replaceable_research_qid(qid):
                preserved.append(dict(q))

        ordered = sorted(
            plan,
            key=lambda q: (
                0 if q.get("kind") == "sector" else 1,
                int(q.get("priority") or 99),
                str(q.get("id") or ""),
            ),
        )
        new_qs: list[dict[str, Any]] = []
        have: set[Any] = set()
        for q in ordered:
            text = str(q.get("text") or "")
            if text in answered_by_text:
                aq = dict(answered_by_text[text])
                aq["id"] = q.get("id") or aq.get("id")
                aq["kind"] = q.get("kind") or aq.get("kind")
                aq["priority"] = q.get("priority", aq.get("priority"))
                aq["source"] = "research_strategy"
                aq["pack"] = q.get("pack") or aq.get("pack")
                new_qs.append(aq)
                have.add(aq.get("id"))
                continue
            qid = q.get("id")
            if qid in have:
                continue
            new_qs.append(dict(q))
            have.add(qid)
        for q in preserved:
            qid = q.get("id")
            if qid in have:
                continue
            new_qs.append(q)
            have.add(qid)
        out["questions"] = new_qs
        research_head = [q for q in new_qs if q.get("kind") in {"sector", "universal"}]
        out["question_activation"] = {
            "version": "lq.1",
            "mode": "sector_first",
            "sector_pack_id": strategy.get("sector_pack_id"),
            "research_head_kinds": [q.get("kind") for q in research_head[:8]],
            "research_question_count": len(research_head),
        }
    else:
        # Blocked / empty plan — keep existing; append only if anything new appears
        have = {q.get("id") for q in existing}
        merged = list(existing)
        for q in plan:
            qid = q.get("id")
            if qid in have:
                continue
            merged.append(dict(q))
            have.add(qid)
        out["questions"] = merged

    # Surface valuation path note into valuation section gaps when DCF blocked
    val_paths = strategy.get("valuation_paths") or {}
    sections = dict(out.get("sections") or {})
    val_sec = dict(sections.get("valuation") or {})
    fields = dict(val_sec.get("fields") or {})
    if val_paths.get("primary"):
        fields["strategy_primary_path"] = val_paths["primary"]
    if val_paths.get("note"):
        fields["strategy_path_note"] = val_paths["note"]
    gaps = list(val_sec.get("gaps") or [])
    for u in val_paths.get("unavailable") or []:
        msg = f"path unavailable: {u.get('method')} ({u.get('reason')})"
        if msg not in gaps:
            gaps.append(msg)
    val_sec["fields"] = fields
    val_sec["gaps"] = gaps
    sections["valuation"] = val_sec
    out["sections"] = sections
    return out
