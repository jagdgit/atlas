"""Built-in mission templates (Phase A · §A.5, D-TPL/B7).

Shipped blueprints, upserted by name on boot. **Hello Watcher** is fully working (the A.8
acceptance vehicle); domain templates gained real workers in Phases B–D.

Bump a template's ``template_version`` here when you change it; existing operator
missions keep the version they were instantiated with (B7).

Each entry is the kwargs passed to ``TemplateRepository.upsert_by_name``.
Philosophy metadata (MP1) lives in ``success_criteria.philosophy`` via
:func:`atlas.missions.philosophy.with_philosophy`.
"""

from __future__ import annotations

from typing import Any

from atlas.missions.philosophy import with_philosophy

BUILTIN_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "hello_watcher",
        "template_version": 2,
        "description": "Reference heartbeat worker — the Phase-A acceptance vehicle.",
        "config_schema_type": "hello_watcher",
        "config_schema_version": 1,
        "default_config": {"greeting": "hello", "tick_limit": 0, "tick_interval_seconds": 60},
        "worker_specs": [{"type": "hello_watcher", "interval_seconds": 60}],
        "knowledge_domains": [],
        "success_criteria": with_philosophy({}, "hello_watcher"),
    },
    {
        "name": "research",
        "template_version": 3,
        "description": "Continuous literature research on a topic (Phase D — Research Watcher).",
        "config_schema_type": "research_watcher",
        "config_schema_version": 1,
        "default_config": {
            "topic": "",
            "max_iterations": 3,
            "max_documents": 12,
            "per_query": 5,
            "embed": False,
            "alert_min_confidence": "medium",
            "tick_interval_seconds": 86400,
        },
        "worker_specs": [{"type": "research_watcher", "interval_seconds": 86400}],
        "knowledge_domains": ["research"],
        "success_criteria": with_philosophy({}, "research"),
    },
    {
        "name": "knowledge_verification",
        "template_version": 2,
        "description": (
            "Continuously verify UNVERIFIED knowledge findings via the shared "
            "VerificationEngine (KV.7). Optional budget-capped gather (default off); "
            "cross-source contradiction detection on by default (KV.8)."
        ),
        "config_schema_type": "knowledge_verification",
        "config_schema_version": 1,
        "default_config": {
            "batch_limit": 10,
            "gather": False,
            "max_gather_iterations": 2,
            "claim_types": ["claim"],
            "asset_id": "",
            "job_id": "",
            "source_url": "",
            "alert_on_promoted": True,
            "detect_contradictions": True,
            "tick_interval_seconds": 3600,
        },
        "worker_specs": [{"type": "knowledge_verification", "interval_seconds": 3600}],
        "knowledge_domains": ["external", "research"],
        "success_criteria": with_philosophy({}, "knowledge_verification"),
    },
    {
        "name": "paper_trading",
        "template_version": 4,
        "description": (
            "COMPAT alias for decision_simulation (Market Intelligence M5). "
            "Simulation-only — NO real money (P10). Prefer template "
            "decision_simulation for new missions."
        ),
        "config_schema_type": "paper_trading",
        "config_schema_version": 1,
        "default_config": {
            "instruments": [],
            "starting_cash": 100000,
            "strategy": {"sma_fast": 10, "sma_slow": 30, "rsi_period": 14},
            "max_position_qty": 0,
            "max_exposure_pct": 0,
            "bars_per_tick": 1,
            "drawdown_alert_pct": 0,
            "tick_interval_seconds": 300,
        },
        "worker_specs": [{"type": "paper_trading", "interval_seconds": 300}],
        "knowledge_domains": ["finance", "markets"],
        "success_criteria": with_philosophy({}, "paper_trading"),
    },
    {
        "name": "decision_simulation",
        "template_version": 1,
        "description": (
            "Market Intelligence M5 — Buy/Sell/Hold/Watch simulation via Decision Engine "
            "(P10, no broker login). Compat worker type paper_trading until ledger split (M6)."
        ),
        "config_schema_type": "paper_trading",
        "config_schema_version": 1,
        "default_config": {
            "instruments": [],
            "starting_cash": 100000,
            "strategy": {"sma_fast": 10, "sma_slow": 30, "rsi_period": 14},
            "max_position_qty": 0,
            "max_exposure_pct": 0,
            "bars_per_tick": 1,
            "drawdown_alert_pct": 0,
            "tick_interval_seconds": 300,
        },
        "worker_specs": [{"type": "paper_trading", "interval_seconds": 300}],
        "knowledge_domains": ["finance", "markets"],
        "success_criteria": with_philosophy({}, "decision_simulation"),
    },
    {
        "name": "market_observer",
        "template_version": 2,
        "description": (
            "Market Intelligence M1 — observe bars/moves via MarketReader adapters "
            "(asset_replay default; Yahoo opt-in; keyed providers when env set)."
        ),
        "config_schema_type": "generic",
        "config_schema_version": 1,
        "default_config": {
            "role": "Market Observer",
            "roadmap": "MI.3",
            "provider": "",
            "symbols": [],
            "instruments": [],
            "bars_limit": 60,
            "move_alert_pct": 5.0,
            "volume_min_ratio": 2.5,
            "spawn_research": False,
            "score_threshold": 0.7,
            "tick_interval_seconds": 300,
        },
        "worker_specs": [{"type": "market_observer", "interval_seconds": 300}],
        "knowledge_domains": ["finance", "markets"],
        "success_criteria": with_philosophy({}, "market_observer"),
    },
    {
        "name": "company_intelligence",
        "template_version": 1,
        "description": (
            "Market Intelligence M2 — filings/ratios learning (stub until MI.5)."
        ),
        "config_schema_type": "generic",
        "config_schema_version": 1,
        "default_config": {
            "role": "Company Intelligence",
            "roadmap": "MI.5",
            "tickers": [],
            "tick_interval_seconds": 86400,
        },
        "worker_specs": [{"type": "program_stub", "interval_seconds": 86400}],
        "knowledge_domains": ["finance", "markets"],
        "success_criteria": with_philosophy({}, "company_intelligence"),
    },
    {
        "name": "news_intelligence",
        "template_version": 2,
        "description": (
            "Market Intelligence M3 — headlines/items → typed candidates → Knowledge "
            "(optional verify). Hermetic headlines config; live RSS later."
        ),
        "config_schema_type": "generic",
        "config_schema_version": 1,
        "default_config": {
            "role": "News Intelligence",
            "roadmap": "MI.4",
            "headlines": [],
            "items": [],
            "verify": False,
            "gather": False,
            "verify_batch_limit": 5,
            "tick_interval_seconds": 3600,
        },
        "worker_specs": [{"type": "news_intelligence", "interval_seconds": 3600}],
        "knowledge_domains": ["finance", "markets", "external"],
        "success_criteria": with_philosophy({}, "news_intelligence"),
    },
    {
        "name": "event_research",
        "template_version": 2,
        "description": (
            "Market Intelligence M4 — interesting events → research Jobs (MI6). "
            "Polls MarketInterestingMove; score_threshold gated."
        ),
        "config_schema_type": "generic",
        "config_schema_version": 1,
        "default_config": {
            "role": "Event Research",
            "roadmap": "MI.4",
            "spawn_research": True,
            "score_threshold": 0.7,
            "pending_events": [],
            "event_scan_limit": 20,
            "tick_interval_seconds": 3600,
        },
        "worker_specs": [{"type": "event_research", "interval_seconds": 3600}],
        "knowledge_domains": ["finance", "markets", "research"],
        "success_criteria": with_philosophy({}, "event_research"),
    },
    {
        "name": "portfolio_ledger",
        "template_version": 1,
        "description": (
            "Market Intelligence M6 — fee/tax-aware sim ledger + Broker Profiles (stub until MI.6)."
        ),
        "config_schema_type": "generic",
        "config_schema_version": 1,
        "default_config": {
            "role": "Portfolio Ledger",
            "roadmap": "MI.6",
            "broker_profile": "paper_demo",
            "tick_interval_seconds": 300,
        },
        "worker_specs": [{"type": "program_stub", "interval_seconds": 300}],
        "knowledge_domains": ["finance", "markets"],
        "success_criteria": with_philosophy({}, "portfolio_ledger"),
    },
    {
        "name": "investment_mentor",
        "template_version": 1,
        "description": (
            "Market Intelligence M7 — lessons + recommendations → Experience OS (stub until MI.7)."
        ),
        "config_schema_type": "generic",
        "config_schema_version": 1,
        "default_config": {
            "role": "Investment Mentor",
            "roadmap": "MI.7",
            "tick_interval_seconds": 604800,
        },
        "worker_specs": [{"type": "program_stub", "interval_seconds": 604800}],
        "knowledge_domains": ["finance", "markets", "experience"],
        "success_criteria": with_philosophy({}, "investment_mentor"),
    },
    {
        "name": "job_hunting",
        "template_version": 3,
        "description": "Continuous job search against operator constraints (Phase D — recommend-only, P14).",
        "config_schema_type": "job_watcher",
        "config_schema_version": 1,
        "default_config": {
            "sources": [],
            "locations": [],
            "companies": [],
            "skills": [],
            "min_salary": 0,
            "min_skill_overlap": 0,
            "include_inferred_skills": True,
            "max_recommendations": 5,
            "tick_interval_seconds": 86400,
        },
        "worker_specs": [{"type": "job_watcher", "interval_seconds": 86400}],
        "knowledge_domains": ["personal", "career"],
        "success_criteria": with_philosophy({}, "job_hunting"),
    },
    {
        "name": "patent_watch",
        "template_version": 2,
        "description": "Monitor new patents in an area (Phase B/D).",
        "config_schema_type": "generic",
        "default_config": {"queries": [], "sources": ["uspto", "google_patents", "wipo"]},
        "worker_specs": [],
        "knowledge_domains": ["research", "engineering"],
        "success_criteria": with_philosophy({}, "patent_watch"),
    },
    {
        "name": "repository_learning",
        "template_version": 3,
        "description": "Continuously ingest + understand a code repository (Phase B — Engineering).",
        "config_schema_type": "repo_watcher",
        "config_schema_version": 1,
        "default_config": {
            "repo_url": "", "repo_path": "", "branch": None,
            "languages": ["python"], "embed_code": False, "policy": "project",
            "tick_interval_seconds": 3600,
        },
        "worker_specs": [{"type": "repo_watcher", "interval_seconds": 3600}],
        "knowledge_domains": ["engineering"],
        "success_criteria": with_philosophy({}, "repository_learning"),
    },
    {
        "name": "owner_knowledge",
        "template_version": 2,
        "description": "Continuously learn the owner from their archive (Phase C — Personal).",
        "config_schema_type": "owner_knowledge",
        "config_schema_version": 1,
        "default_config": {
            "archive_roots": [],
            "build_profile": True,
            "embed": False,
            "policy": "project",
            "tick_interval_seconds": 3600,
        },
        "worker_specs": [{"type": "owner_knowledge", "interval_seconds": 3600}],
        "knowledge_domains": ["personal", "engineering", "experience"],
        "success_criteria": with_philosophy({}, "owner_knowledge"),
    },
    {
        "name": "technology_watch",
        "template_version": 3,
        "description": "Track breaking changes across chosen technologies (Phase D — recommend-only).",
        "config_schema_type": "tech_security_watcher",
        "config_schema_version": 1,
        "default_config": {
            "sources": [],
            "mode": "technology",
            "technologies": [],
            "components": [],
            "focus": [],
            "severity_floor": "medium",
            "tick_interval_seconds": 86400,
        },
        "worker_specs": [{"type": "tech_security_watcher", "interval_seconds": 86400}],
        "knowledge_domains": ["engineering"],
        "success_criteria": with_philosophy({}, "technology_watch"),
    },
    {
        "name": "security_monitoring",
        "template_version": 3,
        "description": "Watch security advisories relevant to the stack (Phase D — recommend-only, P14).",
        "config_schema_type": "tech_security_watcher",
        "config_schema_version": 1,
        "default_config": {
            "sources": [],
            "mode": "security",
            "technologies": [],
            "components": [],
            "focus": [],
            "severity_floor": "high",
            "tick_interval_seconds": 86400,
        },
        "worker_specs": [{"type": "tech_security_watcher", "interval_seconds": 86400}],
        "knowledge_domains": ["engineering", "security"],
        "success_criteria": with_philosophy({}, "security_monitoring"),
    },
    {
        "name": "self_improvement",
        "template_version": 2,
        "description": "Watch Atlas eval regressions and propose gated improvements (Phase D · P14).",
        "config_schema_type": "self_improvement",
        "config_schema_version": 1,
        "default_config": {
            "fixture_root": "",
            "metric_floors": {},
            "regression_drop": 0.05,
            "gate_fixes": True,
            "tick_interval_seconds": 86400,
        },
        "worker_specs": [{"type": "self_improvement", "interval_seconds": 86400}],
        "knowledge_domains": ["engineering"],
        "success_criteria": with_philosophy({}, "self_improvement"),
    },
]
