"""Intelligence Programs — soft product grouping over Missions (MI.1 / MI11).

Platform abstraction (solar-plant test): Programs are applications built on
Mission OS. Domain adapters (Broker Profiles, MarketReader) live *inside* a
Program definition as metadata — never as platform OS boxes.

No DB table required for MI.1: definitions are code-seeded; runtime status is
derived from templates + live missions (labels ``program:<id>``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from atlas.missions.philosophy import (
    LIFECYCLE_STAGES,
    STAGE_ACTIVE,
    STAGE_PARTIAL,
    STAGE_WAITING,
    philosophy_for,
)

# Member readiness for operator display.
MEMBER_ENABLED = "enabled"  # template exists; can instantiate
MEMBER_STUB = "stub"  # planned; template not shipped yet (MI.2+)
MEMBER_COMPAT = "compat"  # legacy façade (paper_trading)

# Cognitive lifecycle display labels (philosophy stages → operator copy).
LIFECYCLE_LABELS: dict[str, str] = {
    "observe": "Observe",
    "learn": "Learn",
    "assess_resources": "Assess Resources",
    "decide": "Decide",
    "record_why": "Record Why",
    "evaluate": "Evaluate",
    "reflect": "Reflect",
    "improve": "Improve",
}


def india_equity_learner_overrides() -> dict[str, dict[str, Any]]:
    """OX.1 / IL-Q5 preset: ₹10k India cash-equity learner (auto universe, live feed)."""
    from atlas.investment.portfolios import india_equity_learner_persona

    persona = india_equity_learner_persona(capital=10000.0)
    sim = {
        "instruments": [],
        "starting_cash": 10000.0,
        "feed_mode": "live",
        "live_provider": "yahoo",
        "market_session": "nse_equity",
        "respect_market_hours": True,
        "universe_index": "NIFTY50",
        "auto_max_instruments": 10,
        "program_id": "market_intelligence",
        "broker_profile": "zerodha",
        "portfolio_key": "india_equity_learner",
        "portfolio_label": "₹10k India Equity Learner",
        "persona": persona,
        "asset_class": "cash_equity",
    }
    return {
        "investment_universe": {
            "index": "NIFTY50",
            "max_watchlist": 15,
            "mode": "auto",
            "program_id": "market_intelligence",
            # IL.5 — live Yahoo .NS bars for ranking (when market.yahoo_enabled)
            "provider": "yahoo",
            "use_quality_seed": True,
        },
        "decision_simulation": dict(sim),
        "paper_trading": dict(sim),
        "portfolio_ledger": {
            "starting_cash": 10000.0,
            "broker_profile": "zerodha",
            "portfolio_key": "india_equity_learner",
        },
        "investment_mentor": {
            "portfolio_key": "india_equity_learner",
        },
        "market_observer": {
            "program_id": "market_intelligence",
            "symbols": [],
            "instruments": [],
            "provider": "yahoo",
        },
        "company_intelligence": {
            "program_id": "market_intelligence",
            "tickers": [],
            "companies": [],
        },
        "news_intelligence": {
            "program_id": "market_intelligence",
            "headlines": [],
            "items": [],
            "seed_from_watchlist": True,
        },
        "government_intelligence": {
            "program_id": "market_intelligence",
            "include_defaults": True,
            "items": [],
        },
        "investor_reports": {
            "program_id": "market_intelligence",
            "portfolio_key": "india_equity_learner",
            "morning_hour_start": 7,
            "morning_hour_end": 10,
        },
    }


@dataclass(frozen=True)
class ProgramMember:
    """One planned or live mission role inside a Program."""

    role: str
    template: str
    kind: str
    cadence: str
    status: str = MEMBER_STUB  # enabled | stub | compat
    description: str = ""


@dataclass(frozen=True)
class ProgramDefinition:
    """Reusable Program blueprint (Market / Engineering / Personal / …)."""

    id: str
    title: str
    description: str
    members: tuple[ProgramMember, ...]
    domain_adapters: tuple[str, ...] = ()
    # Cognitive stages the Program as a whole aims to cover.
    lifecycle: dict[str, str] = field(default_factory=dict)

    def member_templates(self) -> list[str]:
        return [m.template for m in self.members]


def _market_lifecycle() -> dict[str, str]:
    return {
        "observe": STAGE_ACTIVE,  # MI.3 MarketReader
        "learn": STAGE_ACTIVE,  # MI.4 news + MI.5 company
        "decide": STAGE_ACTIVE,  # decision_simulation + event spawn
        "record_why": STAGE_ACTIVE,
        "evaluate": STAGE_ACTIVE,
        "reflect": STAGE_PARTIAL,  # experience journal (OI-MP1)
        "improve": STAGE_WAITING,  # mentor (M7)
    }


BUILTIN_PROGRAMS: tuple[ProgramDefinition, ...] = (
    ProgramDefinition(
        id="market_intelligence",
        title="Market Intelligence",
        description=(
            "Reference Program: observe markets, learn claims, verify, "
            "simulate decisions, ledger fills, and mentor from outcomes. "
            "Simulation only — never broker login (P10)."
        ),
        members=(
            ProgramMember(
                role="Investment Universe",
                template="investment_universe",
                kind="monitoring",
                cadence="pre-open + periodic",
                status=MEMBER_ENABLED,
                description="NIFTY universe → watchlist + ranked candidates (M0 / OI-IL0)",
            ),
            ProgramMember(
                role="Market Observer",
                template="market_observer",
                kind="monitoring",
                cadence="continuous",
                status=MEMBER_ENABLED,
                description="Bars, moves, interesting events (MarketReader)",
            ),
            ProgramMember(
                role="Company Intelligence",
                template="company_intelligence",
                kind="learning",
                cadence="daily/weekly",
                status=MEMBER_ENABLED,
                description="Filings / ratios (config_seed; official adapters when keys)",
            ),
            ProgramMember(
                role="News Intelligence",
                template="news_intelligence",
                kind="learning",
                cadence="hourly",
                status=MEMBER_ENABLED,
                description="News claims → Knowledge (optional verify)",
            ),
            ProgramMember(
                role="Government Intelligence",
                template="government_intelligence",
                kind="learning",
                cadence="pre-open + 6h",
                status=MEMBER_ENABLED,
                description="Union Budget / PLI / industry policy → sector ranking nudges",
            ),
            ProgramMember(
                role="Investor Reports",
                template="investor_reports",
                kind="maintenance",
                cadence="morning IST",
                status=MEMBER_ENABLED,
                description="Email daily plan + trade decision reports (Gmail)",
            ),
            ProgramMember(
                role="Event Research",
                template="event_research",
                kind="research",
                cadence="on trigger",
                status=MEMBER_ENABLED,
                description="Interesting events → research Jobs",
            ),
            ProgramMember(
                role="Decision Simulation",
                template="decision_simulation",
                kind="simulation",
                cadence="continuous",
                status=MEMBER_ENABLED,
                description="Buy/Sell/Hold/Watch + journal (paper_trading is compat alias)",
            ),
            ProgramMember(
                role="Portfolio Ledger",
                template="portfolio_ledger",
                kind="simulation",
                cadence="with fills",
                status=MEMBER_ENABLED,
                description="Fee/tax-aware sim ledger + Broker Profiles (P10)",
            ),
            ProgramMember(
                role="Investment Mentor",
                template="investment_mentor",
                kind="maintenance",
                cadence="weekly",
                status=MEMBER_ENABLED,
                description="Lessons + recommendations → Experience OS (OI-MP5)",
            ),
        ),
        domain_adapters=(
            "MarketReader",
            "Broker Profiles",
            "Interesting-event scores",
        ),
        lifecycle=_market_lifecycle(),
    ),
    ProgramDefinition(
        id="engineering_intelligence",
        title="Engineering Intelligence",
        description=(
            "Learn from repositories and design artifacts; advise on architecture. "
            "Repository Observer + Technology Watch + Engineering Mentor (OI-MP4)."
        ),
        members=(
            ProgramMember(
                role="Repository Observer",
                template="repository_learning",
                kind="learning",
                cadence="continuous",
                status=MEMBER_ENABLED,
                description="Architecture / patterns → engineering knowledge",
            ),
            ProgramMember(
                role="Technology Watch",
                template="technology_watch",
                kind="monitoring",
                cadence="hourly",
                status=MEMBER_ENABLED,
                description="Advisory feed watch",
            ),
            ProgramMember(
                role="Engineering Mentor",
                template="engineering_mentor",
                kind="maintenance",
                cadence="weekly",
                status=MEMBER_ENABLED,
                description="Weekly engineering judgment → Experience OS (OI-MP4)",
            ),
        ),
        domain_adapters=("Repo readers", "Architecture graph"),
        lifecycle={
            "observe": STAGE_ACTIVE,
            "learn": STAGE_ACTIVE,
            "decide": STAGE_PARTIAL,
            "record_why": STAGE_ACTIVE,
            "evaluate": STAGE_PARTIAL,
            "reflect": STAGE_PARTIAL,
            "improve": STAGE_PARTIAL,
        },
    ),
    ProgramDefinition(
        id="personal_intelligence",
        title="Personal Intelligence",
        description=(
            "Owner archive → personal knowledge; career and life advisors. "
            "Observer + Career Advisor + Personal Mentor."
        ),
        members=(
            ProgramMember(
                role="Personal Observer",
                template="owner_knowledge",
                kind="learning",
                cadence="continuous",
                status=MEMBER_ENABLED,
                description="Docs / chats / notes → personal knowledge",
            ),
            ProgramMember(
                role="Career Advisor",
                template="job_hunting",
                kind="career",
                cadence="daily",
                status=MEMBER_ENABLED,
                description="Job hunt simulation / coaching",
            ),
            ProgramMember(
                role="Personal Mentor",
                template="personal_mentor",
                kind="maintenance",
                cadence="weekly",
                status=MEMBER_ENABLED,
                description="Weekly owner/career judgment → Experience OS",
            ),
        ),
        domain_adapters=("Personal archive readers",),
        lifecycle={
            "observe": STAGE_ACTIVE,
            "learn": STAGE_ACTIVE,
            "decide": STAGE_PARTIAL,
            "record_why": STAGE_ACTIVE,
            "evaluate": STAGE_PARTIAL,
            "reflect": STAGE_PARTIAL,
            "improve": STAGE_PARTIAL,
        },
    ),
)


def get_program(program_id: str) -> ProgramDefinition | None:
    for prog in BUILTIN_PROGRAMS:
        if prog.id == program_id:
            return prog
    return None


def list_programs() -> list[ProgramDefinition]:
    return list(BUILTIN_PROGRAMS)


def program_label(program_id: str) -> str:
    return f"program:{program_id}"


def lifecycle_board(lifecycle: dict[str, str] | None) -> list[dict[str, str]]:
    """Operator-facing rows for the cognitive lifecycle strip."""
    lc = lifecycle or {}
    rows: list[dict[str, str]] = []
    for stage in LIFECYCLE_STAGES:
        status = str(lc.get(stage) or "n/a")
        rows.append(
            {
                "stage": stage,
                "label": LIFECYCLE_LABELS.get(stage, stage),
                "status": status,
            }
        )
    return rows


class ProgramService:
    """Derive Program cockpit views from definitions + live missions/templates."""

    name = "programs"
    VERSION = "mca.1"

    def __init__(
        self,
        *,
        missions: Any | None = None,
        templates: Any | None = None,
        knowledge: Any | None = None,
        world_models: Any | None = None,
        knowledge_graph: Any | None = None,
        mission_context: Any | None = None,
        materials: Any | None = None,
    ) -> None:
        self._missions = missions
        self._templates = templates
        self._knowledge = knowledge
        self._world_models = world_models
        self._knowledge_graph = knowledge_graph
        self._mission_context = mission_context
        self._materials = materials

    def list(self) -> list[dict[str, Any]]:
        return [self.describe(p.id) for p in BUILTIN_PROGRAMS]

    def describe(self, program_id: str) -> dict[str, Any]:
        prog = get_program(program_id)
        if prog is None:
            raise LookupError(f"unknown program: {program_id}")
        name_to_id, id_to_name = self._template_maps()
        live = self._missions_for_program(prog, id_to_name)
        members_out: list[dict[str, Any]] = []
        for m in prog.members:
            template_exists = m.template in name_to_id
            effective = m.status
            if effective == MEMBER_STUB and template_exists:
                effective = MEMBER_ENABLED
            live_for = [
                {
                    "id": str(row.get("id")),
                    "title": row.get("title"),
                    "status": row.get("status"),
                }
                for row in live
                if row.get("template_name") == m.template
                or (
                    m.template == "decision_simulation"
                    and row.get("template_name") == "paper_trading"
                )
            ]
            members_out.append(
                {
                    "role": m.role,
                    "template": m.template,
                    "kind": m.kind,
                    "cadence": m.cadence,
                    "status": effective,
                    "description": m.description,
                    "template_available": template_exists,
                    "can_start": template_exists
                    and effective in {MEMBER_ENABLED, MEMBER_COMPAT},
                    "missions": live_for,
                    "philosophy": philosophy_for(m.template)
                    if template_exists
                    else {
                        "mission_kind": m.kind,
                        "never_stops": True,
                        "lifecycle": {s: STAGE_WAITING for s in LIFECYCLE_STAGES},
                    },
                }
            )
        return {
            "id": prog.id,
            "title": prog.title,
            "description": prog.description,
            "domain_adapters": list(prog.domain_adapters),
            "label": program_label(prog.id),
            "lifecycle": lifecycle_board(prog.lifecycle),
            "members": members_out,
            "mission_count": len(live),
            "startable_count": sum(1 for x in members_out if x["can_start"]),
            "stub_count": sum(1 for x in members_out if x["status"] == MEMBER_STUB),
            "version": self.VERSION,
        }

    def start(
        self,
        program_id: str,
        *,
        activate: bool = True,
        title_prefix: str | None = None,
        member_overrides: dict[str, dict[str, Any]] | None = None,
        preset: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Instantiate startable members with template defaults (no raw JSON).

        Stub members are listed but not created. Skips a template if a non-archived
        mission already exists for that member under this Program.

        ``preset="india_equity_learner"`` (OX.1 / IL-Q5) applies ₹10k + live + empty
        instruments (M0 auto-mode) overrides per member template.
        ``member_overrides`` maps template name → config_overrides merged on top.

        ``dry_run=True`` (OX.2) returns would_start / would_skip without creating
        missions — used by Chat preview and ``POST /v1/programs/{id}/plan``.
        """
        view = self.describe(program_id)
        if self._templates is None:
            raise RuntimeError("templates service not wired")
        overrides = dict(member_overrides or {})
        if (preset or "").strip().lower() in {
            "india_equity_learner",
            "india_learner",
            "inr_10k",
            "₹10000",
        }:
            for tmpl, doc in india_equity_learner_overrides().items():
                overrides[tmpl] = {**doc, **overrides.get(tmpl, {})}
            title_prefix = title_prefix or "India ₹10k learner"
        started: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for member in view["members"]:
            if not member["can_start"]:
                skipped.append(
                    {
                        "template": member["template"],
                        "role": member["role"],
                        "reason": "stub"
                        if member["status"] == MEMBER_STUB
                        else "unavailable",
                    }
                )
                continue
            existing = [
                m
                for m in member["missions"]
                if m.get("status") in {"active", "waiting", "paused", "draft"}
            ]
            if existing:
                skipped.append(
                    {
                        "template": member["template"],
                        "role": member["role"],
                        "reason": "already_present",
                        "mission_id": existing[0].get("id"),
                    }
                )
                continue
            prefix = title_prefix or view["title"]
            title = f"{prefix} · {member['role']}"
            cfg_over = dict(overrides.get(member["template"]) or {})
            # Compat: decision_simulation and paper_trading share paper_trading schema.
            if member["template"] == "decision_simulation" and not cfg_over:
                cfg_over = dict(overrides.get("paper_trading") or {})
            if dry_run:
                started.append(
                    {
                        "template": member["template"],
                        "role": member["role"],
                        "title": title,
                        "would_start": True,
                        "config_overrides": cfg_over,
                    }
                )
                continue
            result = self._templates.instantiate(
                member["template"],
                title=title,
                config_overrides=cfg_over or None,
                labels=[program_label(program_id), f"role:{member['template']}"],
                metadata={
                    "program_id": program_id,
                    "template": member["template"],
                    "preset": preset,
                },
                activate=activate,
            )
            mission = result["mission"]
            started.append(
                {
                    "template": member["template"],
                    "role": member["role"],
                    "mission_id": str(mission.id),
                    "status": getattr(mission, "status", None),
                }
            )
        return {
            "program": self.describe(program_id) if not dry_run else view,
            "started": started,
            "skipped": skipped,
            "preset": preset,
            "dry_run": dry_run,
            "side_effecting": not dry_run,
        }

    def preview_start(
        self,
        program_id: str,
        *,
        title_prefix: str | None = None,
        member_overrides: dict[str, dict[str, Any]] | None = None,
        preset: str | None = None,
    ) -> dict[str, Any]:
        """OX.2 — same as ``start`` but never creates missions."""
        return self.start(
            program_id,
            activate=False,
            title_prefix=title_prefix,
            member_overrides=member_overrides,
            preset=preset,
            dry_run=True,
        )

    def context(
        self, topic: str, *, program_id: str | None = None, limit: int = 12
    ) -> dict[str, Any]:
        """Delegate to Mission Context API (MCA.1); keep legacy gather if unbound."""
        if self._mission_context is not None:
            return self._mission_context.gather(
                topic, program_id=program_id, limit=limit
            )
        # Fallback for hermetic tests that only inject world_models / graph.
        from atlas.missions.context import MissionContextService

        return MissionContextService(
            knowledge=self._knowledge,
            world_models=self._world_models,
            knowledge_graph=self._knowledge_graph,
        ).gather(topic, program_id=program_id, limit=limit)

    def share_materials(
        self,
        program_id: str,
        path: str,
        *,
        kind: str | None = None,
        domain: str = "personal",
        process_now: bool = True,
    ) -> dict[str, Any]:
        """Share resume / past work once — Personal + Engineering consume the same job."""
        if self._materials is None:
            raise RuntimeError("program materials service not wired")
        return self._materials.share(
            path,
            program_id=program_id,
            kind=kind,
            domain=domain,
            process_now=process_now,
        )

    def chat(
        self,
        program_id: str,
        message: str,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Program-scoped chat (share paths + operator guidance)."""
        if self._materials is None:
            raise RuntimeError("program materials service not wired")
        return self._materials.chat(
            program_id, message, session_id=session_id
        )

    def _template_maps(self) -> tuple[dict[str, str], dict[str, str]]:
        name_to_id: dict[str, str] = {}
        id_to_name: dict[str, str] = {}
        if self._templates is None:
            return name_to_id, id_to_name
        try:
            for t in self._templates.list_templates():
                name_to_id[t.name] = str(t.id)
                id_to_name[str(t.id)] = t.name
        except Exception:  # noqa: BLE001
            return {}, {}
        return name_to_id, id_to_name

    def _missions_for_program(
        self, prog: ProgramDefinition, id_to_name: dict[str, str]
    ) -> list[dict[str, Any]]:
        if self._missions is None:
            return []
        label = program_label(prog.id)
        member_templates = set(prog.member_templates())
        # Compat: legacy paper_trading missions belong to Decision Simulation.
        if "decision_simulation" in member_templates:
            member_templates.add("paper_trading")
        try:
            all_rows = self._missions.list_missions(limit=100)
        except Exception:  # noqa: BLE001
            return []
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for m in all_rows or []:
            data = m.to_dict() if hasattr(m, "to_dict") else dict(m)
            mid = str(data.get("id"))
            if mid in seen:
                continue
            labels = list(data.get("labels") or [])
            tid = str(data.get("template_id") or "")
            tname = id_to_name.get(tid) or (data.get("metadata") or {}).get("template")
            in_program = label in labels
            in_members = bool(tname and tname in member_templates)
            if not (in_program or in_members):
                continue
            data["template_name"] = tname
            out.append(data)
            seen.add(mid)
        return out
