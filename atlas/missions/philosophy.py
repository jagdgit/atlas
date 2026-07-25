"""Mission philosophy metadata (MP1) — kinds, lifecycle, template classification.

Mirrors ``docs/ATLAS_MISSION_PHILOSOPHY.md``. Seeded into template
``success_criteria.philosophy`` so operators and UIs can show cognitive stage
without a new DB table.
"""

from __future__ import annotations

from typing import Any

# Mission kinds (Mission Operating Model).
KIND_LEARNING = "learning"
KIND_MONITORING = "monitoring"
KIND_RESEARCH = "research"
KIND_SIMULATION = "simulation"
KIND_MAINTENANCE = "maintenance"
KIND_CAREER = "career"

LIFECYCLE_STAGES = (
    "observe",
    "learn",
    "decide",
    "record_why",
    "evaluate",
    "reflect",
    "improve",
)

# Stage readiness for operator display.
STAGE_ACTIVE = "active"  # mission routinely does this
STAGE_PARTIAL = "partial"  # present but thin
STAGE_WAITING = "waiting"  # required by philosophy, not yet real
STAGE_NA = "n/a"  # not applicable for this kind


def _stages(**kwargs: str) -> dict[str, str]:
    out = {s: STAGE_NA for s in LIFECYCLE_STAGES}
    out.update(kwargs)
    return out


# Per-template philosophy (source of truth for builtins success_criteria).
TEMPLATE_PHILOSOPHY: dict[str, dict[str, Any]] = {
    "hello_watcher": {
        "mission_kind": KIND_MAINTENANCE,
        "never_stops": True,
        "lifecycle": _stages(observe=STAGE_ACTIVE, record_why=STAGE_PARTIAL),
    },
    "owner_knowledge": {
        "mission_kind": KIND_LEARNING,
        "never_stops": True,
        "lifecycle": _stages(
            observe=STAGE_ACTIVE,
            learn=STAGE_ACTIVE,
            record_why=STAGE_ACTIVE,
            evaluate=STAGE_PARTIAL,
            reflect=STAGE_WAITING,
            improve=STAGE_WAITING,
        ),
    },
    "repository_learning": {
        "mission_kind": KIND_LEARNING,
        "never_stops": True,
        "lifecycle": _stages(
            observe=STAGE_ACTIVE,
            learn=STAGE_ACTIVE,
            record_why=STAGE_ACTIVE,
            evaluate=STAGE_PARTIAL,
            reflect=STAGE_WAITING,
            improve=STAGE_WAITING,
        ),
    },
    "research": {
        "mission_kind": KIND_RESEARCH,
        "never_stops": False,
        "lifecycle": _stages(
            observe=STAGE_ACTIVE,
            learn=STAGE_ACTIVE,
            decide=STAGE_PARTIAL,
            record_why=STAGE_ACTIVE,
            evaluate=STAGE_PARTIAL,
            reflect=STAGE_WAITING,
            improve=STAGE_WAITING,
        ),
    },
    "knowledge_verification": {
        "mission_kind": KIND_MAINTENANCE,
        "never_stops": True,
        "lifecycle": _stages(
            observe=STAGE_ACTIVE,  # scans UNVERIFIED findings
            evaluate=STAGE_ACTIVE,  # VerificationEngine
            record_why=STAGE_ACTIVE,  # journal + events
            learn=STAGE_PARTIAL,  # write-back confidence/maturity
            decide=STAGE_PARTIAL,  # batch selection / gather opt-in
            reflect=STAGE_WAITING,
            improve=STAGE_WAITING,
        ),
    },
    "paper_trading": {
        "mission_kind": KIND_SIMULATION,
        "never_stops": True,
        "lifecycle": _stages(
            observe=STAGE_PARTIAL,  # fixture/replay today; live = OI-D1
            learn=STAGE_PARTIAL,
            decide=STAGE_ACTIVE,
            record_why=STAGE_ACTIVE,
            evaluate=STAGE_ACTIVE,
            reflect=STAGE_PARTIAL,  # experience journal growing (OI-MP1)
            improve=STAGE_WAITING,
        ),
        "planned_split": [
            "market_observer",
            "company_intelligence",
            "news_intelligence",
            "event_research",
            "decision_simulation",
            "portfolio_ledger",
            "investment_mentor",
        ],
    },
    "decision_simulation": {
        "mission_kind": KIND_SIMULATION,
        "never_stops": True,
        "lifecycle": _stages(
            observe=STAGE_PARTIAL,
            learn=STAGE_PARTIAL,
            decide=STAGE_ACTIVE,
            record_why=STAGE_ACTIVE,
            evaluate=STAGE_ACTIVE,
            reflect=STAGE_PARTIAL,
            improve=STAGE_WAITING,
        ),
        "compat_alias": "paper_trading",
    },
    "market_observer": {
        "mission_kind": KIND_MONITORING,
        "never_stops": True,
        "lifecycle": _stages(
            observe=STAGE_ACTIVE,
            record_why=STAGE_ACTIVE,
            decide=STAGE_PARTIAL,  # interesting-event scoring
            learn=STAGE_WAITING,  # claims from moves → MI.4
            evaluate=STAGE_PARTIAL,
            reflect=STAGE_WAITING,
            improve=STAGE_WAITING,
        ),
    },
    "company_intelligence": {
        "mission_kind": KIND_LEARNING,
        "never_stops": True,
        "lifecycle": _stages(
            observe=STAGE_ACTIVE,
            learn=STAGE_ACTIVE,
            record_why=STAGE_ACTIVE,
            evaluate=STAGE_PARTIAL,
            reflect=STAGE_WAITING,
            improve=STAGE_WAITING,
        ),
    },
    "news_intelligence": {
        "mission_kind": KIND_LEARNING,
        "never_stops": True,
        "lifecycle": _stages(
            observe=STAGE_ACTIVE,
            learn=STAGE_ACTIVE,
            record_why=STAGE_ACTIVE,
            evaluate=STAGE_PARTIAL,  # optional verify
            reflect=STAGE_WAITING,
            improve=STAGE_WAITING,
        ),
    },
    "event_research": {
        "mission_kind": KIND_RESEARCH,
        "never_stops": False,
        "lifecycle": _stages(
            observe=STAGE_ACTIVE,
            learn=STAGE_PARTIAL,
            decide=STAGE_ACTIVE,  # spawn Job when score clears
            record_why=STAGE_ACTIVE,
            evaluate=STAGE_PARTIAL,
            reflect=STAGE_WAITING,
            improve=STAGE_WAITING,
        ),
    },
    "portfolio_ledger": {
        "mission_kind": KIND_SIMULATION,
        "never_stops": True,
        "lifecycle": _stages(
            observe=STAGE_PARTIAL,
            decide=STAGE_WAITING,
            record_why=STAGE_ACTIVE,
            evaluate=STAGE_PARTIAL,
            reflect=STAGE_WAITING,
            improve=STAGE_WAITING,
        ),
    },
    "investment_mentor": {
        "mission_kind": KIND_MAINTENANCE,
        "never_stops": True,
        "lifecycle": _stages(
            observe=STAGE_PARTIAL,
            evaluate=STAGE_PARTIAL,
            reflect=STAGE_ACTIVE,
            improve=STAGE_PARTIAL,
            record_why=STAGE_ACTIVE,
            learn=STAGE_ACTIVE,
            decide=STAGE_WAITING,
        ),
    },
    "engineering_mentor": {
        "mission_kind": KIND_MAINTENANCE,
        "never_stops": True,
        "lifecycle": _stages(
            observe=STAGE_PARTIAL,
            evaluate=STAGE_PARTIAL,
            reflect=STAGE_ACTIVE,
            improve=STAGE_PARTIAL,
            record_why=STAGE_ACTIVE,
            learn=STAGE_ACTIVE,
            decide=STAGE_WAITING,
        ),
    },
    "learning_governance": {
        "mission_kind": KIND_MAINTENANCE,
        "never_stops": True,
        "lifecycle": _stages(
            observe=STAGE_ACTIVE,
            evaluate=STAGE_ACTIVE,
            reflect=STAGE_ACTIVE,
            learn=STAGE_PARTIAL,
            record_why=STAGE_ACTIVE,
            improve=STAGE_WAITING,
            decide=STAGE_WAITING,
        ),
    },
    "technology_watch": {
        "mission_kind": KIND_MONITORING,
        "never_stops": True,
        "lifecycle": _stages(
            observe=STAGE_ACTIVE,
            decide=STAGE_ACTIVE,
            record_why=STAGE_ACTIVE,
            learn=STAGE_PARTIAL,
            evaluate=STAGE_PARTIAL,
            reflect=STAGE_WAITING,
            improve=STAGE_WAITING,
        ),
    },
    "security_monitoring": {
        "mission_kind": KIND_MONITORING,
        "never_stops": True,
        "lifecycle": _stages(
            observe=STAGE_ACTIVE,
            decide=STAGE_ACTIVE,
            record_why=STAGE_ACTIVE,
            learn=STAGE_PARTIAL,
            evaluate=STAGE_PARTIAL,
            reflect=STAGE_WAITING,
            improve=STAGE_WAITING,
        ),
    },
    "job_hunting": {
        "mission_kind": KIND_CAREER,
        "never_stops": True,
        "lifecycle": _stages(
            observe=STAGE_ACTIVE,
            decide=STAGE_ACTIVE,
            record_why=STAGE_ACTIVE,
            evaluate=STAGE_WAITING,  # no apply → weak outcome signal (P14)
            reflect=STAGE_WAITING,
            improve=STAGE_WAITING,
        ),
    },
    "self_improvement": {
        "mission_kind": KIND_MAINTENANCE,
        "never_stops": True,
        "lifecycle": _stages(
            observe=STAGE_ACTIVE,
            evaluate=STAGE_ACTIVE,
            decide=STAGE_ACTIVE,
            record_why=STAGE_ACTIVE,
            improve=STAGE_PARTIAL,  # gated proposals
            reflect=STAGE_PARTIAL,
            learn=STAGE_PARTIAL,
        ),
    },
    "patent_watch": {
        "mission_kind": KIND_MONITORING,
        "never_stops": True,
        "lifecycle": _stages(),  # stub — all n/a until worker exists
    },
}


def philosophy_for(template_name: str) -> dict[str, Any]:
    """Return a copy of philosophy metadata for a template name."""
    row = TEMPLATE_PHILOSOPHY.get(template_name) or {
        "mission_kind": KIND_LEARNING,
        "never_stops": True,
        "lifecycle": _stages(),
    }
    return {
        "mission_kind": row["mission_kind"],
        "never_stops": bool(row.get("never_stops", True)),
        "lifecycle": dict(row.get("lifecycle") or {}),
        **(
            {"planned_split": list(row["planned_split"])}
            if row.get("planned_split")
            else {}
        ),
        **(
            {"compat_alias": row["compat_alias"]}
            if row.get("compat_alias")
            else {}
        ),
    }


def with_philosophy(
    success_criteria: dict[str, Any] | None, template_name: str
) -> dict[str, Any]:
    """Merge philosophy block into template success_criteria for seeding."""
    out = dict(success_criteria or {})
    out["philosophy"] = philosophy_for(template_name)
    return out
