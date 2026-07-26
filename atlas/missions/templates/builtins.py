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
        "template_version": 3,
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
        "template_version": 4,
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
        "template_version": 3,
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
        "template_version": 5,
        "description": (
            "COMPAT alias for decision_simulation (Market Intelligence M5). "
            "Simulation-only — NO real money (P10). Prefer India learner "
            "(live + empty instruments → M0) or template decision_simulation. "
            "asset_replay defaults are for CI/demos, not the operator happy path."
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
            "feed_mode": "asset_replay",
            "live_provider": "yahoo",
            "market_session": "always_open",
            "respect_market_hours": True,
        },
        "worker_specs": [{"type": "paper_trading", "interval_seconds": 300}],
        "knowledge_domains": ["finance", "markets"],
        "success_criteria": with_philosophy({}, "paper_trading"),
    },
    {
        "name": "decision_simulation",
        "template_version": 2,
        "description": (
            "Market Intelligence M5 — Buy/Sell/Hold/Watch simulation via Decision Engine "
            "(P10, no broker login). Operator path: live feed + empty instruments → M0 "
            "watchlist; asset_replay is for CI/demos. IL.11 instrument_pack "
            "(cash_equity ready; other classes stub capability_gap). Compat worker "
            "paper_trading until ledger split (M6)."
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
            "feed_mode": "asset_replay",
            "live_provider": "yahoo",
            "market_session": "always_open",
            "respect_market_hours": True,
            "portfolio_key": "default",
            "portfolio_label": "Default",
            "persona": {
                "objective": "Learning",
                "risk": "medium",
                "time_horizon": "medium",
                "capital": 100000,
                "allowed_assets": ["cash_equity"],
                "strategy": {},
                "currency": "USD",
            },
            "asset_class": "cash_equity",
            "program_id": "market_intelligence",
        },
        "worker_specs": [{"type": "paper_trading", "interval_seconds": 300}],
        "knowledge_domains": ["finance", "markets"],
        "success_criteria": with_philosophy({}, "decision_simulation"),
    },
    {
        "name": "investment_universe",
        "template_version": 3,
        "description": (
            "Market Intelligence M0 — NIFTY universe → ranked watchlist with WHY ± "
            "explanations for Decision Simulation auto-mode (OI-IL0 / IL.3). "
            "IL.5 hermetic quality_seed (sector proxies) + optional Yahoo provider. "
            "IL.8 screener snapshots (operator JSON / computed bars — no scrape). "
            "Publishes IL.6 Daily Investment Plan into watchlist extra. "
            "Not a new Intelligence."
        ),
        "config_schema_type": "generic",
        "config_schema_version": 1,
        "default_config": {
            "role": "Investment Universe",
            "roadmap": "OI-IL0",
            "index": "NIFTY50",
            "max_watchlist": 15,
            "mode": "auto",
            "program_id": "market_intelligence",
            "pinned_symbols": [],
            "lookback_bars": 40,
            "lookback_short": 5,
            "lookback_long": 20,
            "min_bars": 5,
            "cold_start_coverage": 0.25,
            "rank_weights": {
                "momentum": 0.35,
                "liquidity": 0.25,
                "quality": 0.15,
                "policy": 0.15,
                "experience": 0.10,
            },
            "quality_seed": {},
            "use_quality_seed": True,
            "use_screener_signals": True,
            "screener_computed": True,
            "provider": "",
            "tick_interval_seconds": 3600,
        },
        "worker_specs": [
            {"type": "investment_universe", "interval_seconds": 3600},
            # IL.6 — pre-open refresh Mon–Fri 08:45 IST (= 03:15 UTC; IST has no DST)
            {"type": "investment_universe", "cron": "15 3 * * 1-5", "interval_seconds": 3600},
        ],
        "knowledge_domains": ["finance", "markets"],
        "success_criteria": with_philosophy({}, "investment_universe"),
    },
    {
        "name": "market_observer",
        "template_version": 4,
        "description": (
            "Market Intelligence M1 — observe bars/moves via MarketReader adapters "
            "(live Yahoo opt-in / keyed providers for operators; asset_replay for "
            "CI/demos). Empty symbols → ranked Investment Universe watchlist (IL.4)."
        ),
        "config_schema_type": "generic",
        "config_schema_version": 1,
        "default_config": {
            "role": "Market Observer",
            "roadmap": "MI.3",
            "provider": "",
            "program_id": "market_intelligence",
            "symbols": [],
            "instruments": [],
            "auto_max_instruments": 15,
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
        "template_version": 4,
        "description": (
            "Market Intelligence M2 — company profiles/filings → Knowledge "
            "(config_seed hermetic; SEC/NSE/BSE skeletons when keys exist; no scrape). "
            "Empty tickers → ranked watchlist (IL.4)."
        ),
        "config_schema_type": "generic",
        "config_schema_version": 1,
        "default_config": {
            "role": "Company Intelligence",
            "roadmap": "MI.5",
            "provider": "config_seed",
            "program_id": "market_intelligence",
            "tickers": [],
            "companies": [],
            "auto_max_tickers": 15,
            "force": False,
            "tick_interval_seconds": 86400,
        },
        "worker_specs": [{"type": "company_intelligence", "interval_seconds": 86400}],
        "knowledge_domains": ["finance", "markets"],
        "success_criteria": with_philosophy({}, "company_intelligence"),
    },
    {
        "name": "news_intelligence",
        "template_version": 4,
        "description": (
            "Market Intelligence M3 — headlines/items → typed candidates → Knowledge "
            "(optional verify). Hermetic headlines config; empty → watchlist seeds "
            "(IL.4); live RSS later."
        ),
        "config_schema_type": "generic",
        "config_schema_version": 1,
        "default_config": {
            "role": "News Intelligence",
            "roadmap": "MI.4",
            "program_id": "market_intelligence",
            "headlines": [],
            "items": [],
            "seed_from_watchlist": True,
            "auto_max_symbols": 10,
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
        "name": "government_intelligence",
        "template_version": 1,
        "description": (
            "Market Intelligence — Indian government budget / industrial policy themes "
            "mapped to NSE sectors for ranking nudges (PLI, capex, defence, renewables). "
            "Hermetic catalog + operator items; not a live gazette scrape."
        ),
        "config_schema_type": "generic",
        "config_schema_version": 1,
        "default_config": {
            "role": "Government Intelligence",
            "roadmap": "MI-GOV",
            "program_id": "market_intelligence",
            "include_defaults": True,
            "items": [],
            "policies": [],
            "tick_interval_seconds": 21600,
        },
        "worker_specs": [
            {"type": "government_intelligence", "interval_seconds": 21600},
            {"type": "government_intelligence", "cron": "0 1 * * 1-5", "interval_seconds": 21600},
        ],
        "knowledge_domains": ["finance", "markets", "policy"],
        "success_criteria": with_philosophy({}, "government_intelligence"),
    },
    {
        "name": "investor_reports",
        "template_version": 2,
        "description": (
            "Morning + evening investor email: daily plan (why + notionals), government "
            "policy brief, EOD fills/portfolio after NSE close. Trade buy/sell emails are "
            "sent from Decision Simulation fills. Configure Gmail via ATLAS_EMAIL_* / "
            "ATLAS_SMTP_PASSWORD / ATLAS_INVESTOR_REPORT_TO."
        ),
        "config_schema_type": "generic",
        "config_schema_version": 1,
        "default_config": {
            "role": "Investor Reports",
            "roadmap": "MI-MAIL",
            "program_id": "market_intelligence",
            "portfolio_key": "india_equity_learner",
            "morning_hour_start": 7,
            "morning_hour_end": 10,
            "evening_hour_start": 15,
            "evening_minute_start": 45,
            "evening_hour_end": 18,
            "force": False,
            "tick_interval_seconds": 1800,
        },
        "worker_specs": [
            {"type": "investor_reports", "interval_seconds": 1800},
            {"type": "investor_reports", "cron": "0 3 * * 1-5", "interval_seconds": 1800},
            {"type": "investor_reports", "cron": "45 10 * * 1-5", "interval_seconds": 1800},
        ],
        "knowledge_domains": ["finance", "markets"],
        "success_criteria": with_philosophy({}, "investor_reports"),
    },
    {
        "name": "event_research",
        "template_version": 3,
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
        "template_version": 3,
        "description": (
            "Market Intelligence M6 — fee/tax-aware sim ledger + Broker Profiles "
            "(paper_demo / zerodha / groww / angel / custom). Simulation only (P10)."
        ),
        "config_schema_type": "generic",
        "config_schema_version": 1,
        "default_config": {
            "role": "Portfolio Ledger",
            "roadmap": "MI.6",
            "broker_profile": "paper_demo",
            "starting_cash": 100000.0,
            "base_currency": "INR",
            "pending_fills": [],
            "marks": {},
            "tick_interval_seconds": 300,
        },
        "worker_specs": [{"type": "portfolio_ledger", "interval_seconds": 300}],
        "knowledge_domains": ["finance", "markets"],
        "success_criteria": with_philosophy({}, "portfolio_ledger"),
    },
    {
        "name": "investment_mentor",
        "template_version": 3,
        "description": (
            "Market Intelligence M7 — weekly lessons + recommendations → Experience OS "
            "(Decision Simulation recalls via advice_for)."
        ),
        "config_schema_type": "generic",
        "config_schema_version": 1,
        "default_config": {
            "role": "Investment Mentor",
            "roadmap": "MI.7",
            "focus": "markets",
            "lookback": 40,
            "force": False,
            "seed_experiences": [],
            "tick_interval_seconds": 604800,
        },
        "worker_specs": [{"type": "investment_mentor", "interval_seconds": 604800}],
        "knowledge_domains": ["finance", "markets", "experience"],
        "success_criteria": with_philosophy({}, "investment_mentor"),
    },
    {
        "name": "engineering_mentor",
        "template_version": 2,
        "description": (
            "Engineering Intelligence (OI-MP4) — weekly engineering-judgment lessons "
            "from repository / architecture Experiences → Experience OS "
            "(advice_for + optional soft-bias)."
        ),
        "config_schema_type": "generic",
        "config_schema_version": 1,
        "default_config": {
            "role": "Engineering Mentor",
            "roadmap": "OI-MP4",
            "focus": "engineering",
            "lookback": 40,
            "force": False,
            "seed_experiences": [],
            "tick_interval_seconds": 604800,
        },
        "worker_specs": [{"type": "engineering_mentor", "interval_seconds": 604800}],
        "knowledge_domains": ["engineering", "architecture", "experience"],
        "success_criteria": with_philosophy({}, "engineering_mentor"),
    },
    {
        "name": "personal_mentor",
        "template_version": 2,
        "description": (
            "Personal Intelligence — weekly owner/career judgment lessons from "
            "personal Experiences → Experience OS (advice_for + optional soft-bias)."
        ),
        "config_schema_type": "generic",
        "config_schema_version": 1,
        "default_config": {
            "role": "Personal Mentor",
            "focus": "personal",
            "lookback": 40,
            "force": False,
            "seed_experiences": [],
            "tick_interval_seconds": 604800,
        },
        "worker_specs": [{"type": "personal_mentor", "interval_seconds": 604800}],
        "knowledge_domains": ["personal", "career", "experience"],
        "success_criteria": with_philosophy({}, "personal_mentor"),
    },
    {
        "name": "learning_governance",
        "template_version": 2,
        "description": (
            "Layer 2 Daily Learning Governance Report (OI-MP3) — concepts, lessons, "
            "conflicts, capability gaps, sim portfolio. Not a per-media Learning Report."
        ),
        "config_schema_type": "generic",
        "config_schema_version": 1,
        "default_config": {
            "role": "Learning Governance",
            "roadmap": "OI-MP3",
            "force": False,
            "limit": 200,
            "tick_interval_seconds": 86400,
        },
        "worker_specs": [{"type": "learning_governance", "interval_seconds": 86400}],
        "knowledge_domains": ["governance", "knowledge", "experience"],
        "success_criteria": with_philosophy({}, "learning_governance"),
    },
    {
        "name": "system_introspection",
        "template_version": 2,
        "description": (
            "System Introspection (OI-F3) — periodic self-analysis of knowledge, "
            "uncertainty, reader failures, mission cost, policy blocks, and improve-next."
        ),
        "config_schema_type": "generic",
        "config_schema_version": 1,
        "default_config": {
            "role": "System Introspection",
            "roadmap": "OI-F3",
            "force": False,
            "limit": 200,
            "journal_experience": True,
            "tick_interval_seconds": 86400,
        },
        "worker_specs": [{"type": "system_introspection", "interval_seconds": 86400}],
        "knowledge_domains": ["governance", "engineering", "knowledge"],
        "success_criteria": with_philosophy({}, "system_introspection"),
    },
    {
        "name": "job_hunting",
        "template_version": 4,
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
        "template_version": 3,
        "description": "Monitor new patents in an area (Phase B/D).",
        "config_schema_type": "generic",
        "default_config": {"queries": [], "sources": ["uspto", "google_patents", "wipo"]},
        "worker_specs": [],
        "knowledge_domains": ["research", "engineering"],
        "success_criteria": with_philosophy({}, "patent_watch"),
    },
    {
        "name": "repository_learning",
        "template_version": 4,
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
        "template_version": 3,
        "description": "Continuously learn the owner from their archive (Phase C — Personal).",
        "config_schema_type": "owner_knowledge",
        "config_schema_version": 1,
        "default_config": {
            "archive_roots": [],
            "build_profile": True,
            "embed": False,
            "policy": "project",
            "tick_interval_seconds": 3600,
            "files_per_tick": 40,
        },
        "worker_specs": [{"type": "owner_knowledge", "interval_seconds": 3600}],
        "knowledge_domains": ["personal", "engineering", "experience"],
        "success_criteria": with_philosophy({}, "owner_knowledge"),
    },
    {
        "name": "technology_watch",
        "template_version": 4,
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
        "template_version": 4,
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
        "template_version": 3,
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
