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
    """~28% universal MVR + ~72% sector pack questions (by count)."""
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

    questions: list[dict[str, Any]] = []
    for i, text in enumerate(universal_texts[:n_univ]):
        questions.append(
            _q(
                qid=f"univ-q{i+1}",
                text=text,
                kind="universal",
                priority=10 + i,
                symbol=sym,
                pack_id=pack_id,
                critical=i < 2,
            )
        )

    sector_texts = list(pack.get("extra_questions") or [])
    # KPI-framed prompts fill when pack questions are thin
    for kpi in pack.get("primary_kpis") or []:
        sector_texts.append(f"What is the evidence path for sector KPI: {kpi}?")
    for i, text in enumerate(sector_texts[:n_sec]):
        questions.append(
            _q(
                qid=f"sec-q{i+1}",
                text=text,
                kind="sector",
                priority=20 + i,
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


def apply_strategy_to_dossier(doc: dict[str, Any], strategy: dict[str, Any]) -> dict[str, Any]:
    """Stamp strategy; merge question_plan into dossier questions (idempotent by id)."""
    out = dict(doc)
    out["research_strategy"] = dict(strategy)
    if strategy.get("sector_pack_id"):
        out["pack"] = strategy["sector_pack_id"]

    existing = list(out.get("questions") or [])
    have = {q.get("id") for q in existing if isinstance(q, dict)}
    merged = list(existing)
    for q in strategy.get("question_plan") or []:
        if not isinstance(q, dict):
            continue
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
