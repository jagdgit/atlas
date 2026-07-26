"""IRA F3 — Management / capital-allocation evidence pack.

Checklist for operators — never invents capital-allocation history.
Answers map into management section evidence + questions.
"""

from __future__ import annotations

from typing import Any

from atlas.investment.research.evidence import make_evidence
from atlas.investment.research.models import CONF_LOW, CONF_VERY_LOW, utc_now_iso

# Operator-facing checklist (senior-analyst lenses without requiring all filled).
MANAGEMENT_CHECKLIST: tuple[dict[str, Any], ...] = (
    {
        "id": "capital_allocation",
        "label": "Capital allocation track record",
        "question": "Has management allocated capital well over a cycle (ROIC vs reinvestment)?",
        "critical": True,
    },
    {
        "id": "dilution",
        "label": "Dilution / equity issuance",
        "question": "Has equity been issued at poor prices or for empire-building?",
        "critical": True,
    },
    {
        "id": "related_party",
        "label": "Related-party transactions",
        "question": "Are related-party deals material and poorly disclosed?",
        "critical": True,
    },
    {
        "id": "roic_trend",
        "label": "ROIC / return trend",
        "question": "Is return on capital stable, rising, or eroding?",
        "critical": False,
    },
    {
        "id": "chairman_letter",
        "label": "Chairman / MD letter themes",
        "question": "Do letters show candour about risks and capital priorities?",
        "critical": False,
    },
    {
        "id": "promoter_skin",
        "label": "Promoter / insider skin in the game",
        "question": "Is promoter holding stable, rising, or declining materially?",
        "critical": False,
    },
    {
        "id": "governance_red_flags",
        "label": "Governance red flags",
        "question": "Any auditor change, SEBI action, or unexplained related entities?",
        "critical": True,
    },
)


def empty_management_pack() -> dict[str, Any]:
    items = []
    for row in MANAGEMENT_CHECKLIST:
        items.append(
            {
                **row,
                "status": "open",  # open | answered | weak | blocked
                "answer": None,
                "evidence_level": None,
                "updated_at": None,
            }
        )
    return {
        "version": "ira.f3",
        "as_of": utc_now_iso(),
        "items": items,
        "operator_notes": [],
    }


def apply_management_answers(
    pack: dict[str, Any] | None,
    answers: dict[str, Any] | list[dict[str, Any]],
    *,
    evidence_level: str = "F",
    operator_note: str | None = None,
) -> dict[str, Any]:
    """Merge operator answers into pack. answers: {id: text} or list of {id, answer, status?}."""
    base = empty_management_pack() if not isinstance(pack, dict) else dict(pack)
    items = {str(i.get("id")): dict(i) for i in (base.get("items") or []) if isinstance(i, dict)}
    for row in MANAGEMENT_CHECKLIST:
        items.setdefault(
            str(row["id"]),
            {**row, "status": "open", "answer": None, "evidence_level": None, "updated_at": None},
        )

    rows_in: list[dict[str, Any]] = []
    if isinstance(answers, dict):
        for k, v in answers.items():
            if k.startswith("_"):
                continue
            if isinstance(v, dict):
                rows_in.append({"id": k, **v})
            else:
                rows_in.append({"id": k, "answer": v})
    else:
        rows_in = [a for a in (answers or []) if isinstance(a, dict)]

    now = utc_now_iso()
    for raw in rows_in:
        iid = str(raw.get("id") or "").strip()
        if not iid or iid not in items:
            continue
        ans = str(raw.get("answer") or raw.get("text") or "").strip()
        if not ans:
            continue
        st = str(raw.get("status") or "answered").strip().lower()
        if st not in {"answered", "weak", "blocked", "open"}:
            st = "answered"
        items[iid]["answer"] = ans
        items[iid]["status"] = st
        items[iid]["evidence_level"] = str(raw.get("evidence_level") or evidence_level).upper()
        items[iid]["updated_at"] = now

    base["items"] = list(items.values())
    base["as_of"] = now
    if operator_note and str(operator_note).strip():
        notes = list(base.get("operator_notes") or [])
        notes.append({"at": now, "text": str(operator_note).strip(), "level": "F"})
        base["operator_notes"] = notes[-20:]
    return base


def management_section_fields(pack: dict[str, Any] | None) -> dict[str, Any]:
    """Build management section fields + evidence list from pack."""
    pack = pack if isinstance(pack, dict) else empty_management_pack()
    items = [i for i in (pack.get("items") or []) if isinstance(i, dict)]
    answered = [i for i in items if i.get("status") in {"answered", "weak"} and i.get("answer")]
    open_crit = [
        i for i in items if i.get("critical") and i.get("status") in {"open", "blocked", None}
    ]
    evidence = []
    for i in answered:
        evidence.append(
            make_evidence(
                claim=f"{i.get('label')}: {str(i.get('answer'))[:120]}",
                level=str(i.get("evidence_level") or "F"),
                status="present" if i.get("status") == "answered" else "weak",
                source="operator_management_pack",
                confidence=CONF_LOW if i.get("status") == "answered" else CONF_VERY_LOW,
            )
        )
    for i in open_crit:
        evidence.append(
            make_evidence(
                claim=str(i.get("label") or i.get("id")),
                level="F",
                status="not_found",
                source="management_pack",
                confidence=CONF_VERY_LOW,
            )
        )
    gaps = []
    for i in open_crit:
        gaps.append(f"management: {i.get('id')} unanswered (critical)")
    conf = CONF_VERY_LOW
    if answered and not open_crit:
        conf = CONF_LOW
    elif answered:
        conf = CONF_VERY_LOW
    notes = list(pack.get("operator_notes") or [])
    summary_bits = [f"{i.get('label')}={i.get('status')}" for i in items]
    return {
        "fields": {
            "note": (
                f"Management pack: {len(answered)}/{len(items)} answered; "
                f"{len(open_crit)} critical open"
            ),
            "pack": pack,
            "checklist_summary": summary_bits,
            "operator_notes": notes[-5:],
            "evidence": evidence[-16:],
        },
        "confidence": conf,
        "gaps": gaps,
        "sources": ["management_pack", "operator"],
    }


def management_questions_for_symbol(symbol: str) -> list[dict[str, Any]]:
    """Extra ResearchQuestions from management pack (appended once)."""
    now = utc_now_iso()
    out = []
    for i, row in enumerate(MANAGEMENT_CHECKLIST):
        out.append(
            {
                "id": f"mgmt-q{i+1}",
                "symbol": symbol,
                "text": row["question"],
                "status": "open",
                "created_at": now,
                "answered_at": None,
                "memory_ids": [],
                "pack": "management",
                "checklist_id": row["id"],
                "critical": bool(row.get("critical")),
            }
        )
    return out
