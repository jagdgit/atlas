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
    "assess_resources",  # Resource OS gate before Execute (MP8 / RO8)
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
    # Host Guard (Resource OS) admits every Persistent Worker tick — partial until
    # Resource Planner / Mission Queue land.
    out["assess_resources"] = STAGE_PARTIAL
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
            assess_resources=STAGE_PARTIAL,  # Host Guard + archive queue; Planner ETA = target
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
            assess_resources=STAGE_PARTIAL,
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
            "investment_universe",
            "market_observer",
            "company_intelligence",
            "news_intelligence",
            "government_intelligence",
            "investor_reports",
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
    "investment_universe": {
        "mission_kind": KIND_MONITORING,
        "never_stops": True,
        "lifecycle": _stages(
            observe=STAGE_ACTIVE,
            learn=STAGE_PARTIAL,
            decide=STAGE_PARTIAL,  # ranks → candidates
            record_why=STAGE_ACTIVE,
            evaluate=STAGE_PARTIAL,
            reflect=STAGE_WAITING,
            improve=STAGE_WAITING,
        ),
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
    "government_intelligence": {
        "mission_kind": KIND_LEARNING,
        "never_stops": True,
        "lifecycle": _stages(
            observe=STAGE_ACTIVE,
            learn=STAGE_ACTIVE,
            decide=STAGE_PARTIAL,
            record_why=STAGE_ACTIVE,
            evaluate=STAGE_WAITING,
            reflect=STAGE_WAITING,
            improve=STAGE_WAITING,
        ),
    },
    "investor_reports": {
        "mission_kind": KIND_MONITORING,
        "never_stops": True,
        "lifecycle": _stages(
            observe=STAGE_PARTIAL,
            decide=STAGE_WAITING,
            record_why=STAGE_ACTIVE,
            evaluate=STAGE_WAITING,
            reflect=STAGE_WAITING,
            improve=STAGE_WAITING,
        ),
    },
    "opportunity_discovery": {
        "mission_kind": KIND_MONITORING,
        "never_stops": True,
        "lifecycle": _stages(
            observe=STAGE_ACTIVE,
            learn=STAGE_PARTIAL,
            decide=STAGE_PARTIAL,  # enqueue research suggestions
            record_why=STAGE_ACTIVE,
            evaluate=STAGE_WAITING,
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
    "personal_mentor": {
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
    "system_introspection": {
        "mission_kind": KIND_MAINTENANCE,
        "never_stops": True,
        "lifecycle": _stages(
            observe=STAGE_ACTIVE,
            evaluate=STAGE_ACTIVE,
            reflect=STAGE_ACTIVE,
            learn=STAGE_PARTIAL,
            record_why=STAGE_ACTIVE,
            improve=STAGE_PARTIAL,
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
            reflect=STAGE_PARTIAL,
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
            reflect=STAGE_PARTIAL,
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
            evaluate=STAGE_PARTIAL,  # OI-F4 outcome_feedback (still no auto-apply — P14)
            reflect=STAGE_PARTIAL,
            learn=STAGE_PARTIAL,
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
    """Merge philosophy (+ IR-RO3 resources) into template success_criteria for seeding."""
    out = dict(success_criteria or {})
    out["philosophy"] = philosophy_for(template_name)
    # Attach Work Resource Profile so Ops/scheduler can read service class without a join.
    from atlas.missions.templates.resources import with_resources

    return with_resources(out, template_name)
