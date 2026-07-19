"""Built-in mission templates (Phase A · §A.5, D-TPL/B7).

Shipped blueprints, upserted by name on boot. **Hello Watcher** is fully working (the A.8
acceptance vehicle); the seven domain templates are **stubs** — a mission + a permissive
``generic`` config + (for now) no workers — because their real workers/config schemas land in
Phases B/C/D. Bump a template's ``template_version`` here when you change it; existing operator
missions keep the version they were instantiated with (B7).

Each entry is the kwargs passed to ``TemplateRepository.upsert_by_name``.
"""

from __future__ import annotations

from typing import Any

BUILTIN_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "hello_watcher",
        "template_version": 1,
        "description": "Reference heartbeat worker — the Phase-A acceptance vehicle.",
        "config_schema_type": "hello_watcher",
        "config_schema_version": 1,
        "default_config": {"greeting": "hello", "tick_limit": 0, "tick_interval_seconds": 60},
        "worker_specs": [{"type": "hello_watcher", "interval_seconds": 60}],
        "knowledge_domains": [],
        "success_criteria": {},
    },
    # --- domain stubs (real behaviour lands in later phases) -------------
    {
        "name": "research",
        "template_version": 1,
        "description": "Continuous literature research on a topic (Phase B/D behaviour).",
        "config_schema_type": "generic",
        "default_config": {"topic": "", "depth": "high", "max_papers": 100, "alert_frequency": "daily"},
        "worker_specs": [],
        "knowledge_domains": ["research"],
        "success_criteria": {},
    },
    {
        # Real template as of Phase D (§D.6): a strict PaperTradingConfig + a PaperTradingWorker that
        # replays OHLCV feeds → indicators → DecisionEngine (policy-arbitrated) → virtual portfolio.
        # SIMULATION ONLY — NO real money, NO real broker (P10).
        "name": "paper_trading",
        "template_version": 2,
        "description": "Simulation-only paper trading (Phase D — Decision Engine flagship; NO real money — P10).",
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
        "success_criteria": {},
    },
    {
        "name": "job_hunting",
        "template_version": 1,
        "description": "Continuous job search against operator constraints (Phase C/D).",
        "config_schema_type": "generic",
        "default_config": {"locations": [], "min_salary": 0, "companies": [], "skills": []},
        "worker_specs": [],
        "knowledge_domains": ["personal", "career"],
        "success_criteria": {},
    },
    {
        "name": "patent_watch",
        "template_version": 1,
        "description": "Monitor new patents in an area (Phase B/D).",
        "config_schema_type": "generic",
        "default_config": {"queries": [], "sources": ["uspto", "google_patents", "wipo"]},
        "worker_specs": [],
        "knowledge_domains": ["research", "engineering"],
        "success_criteria": {},
    },
    {
        # Real template as of Phase B (§B.6): strict RepoWatcherConfig + a RepoWatcher worker
        # that re-ingests on schedule (Detect→Compare→Policy→Ingest), reusing B.1–B.5.
        "name": "repository_learning",
        "template_version": 2,
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
        "success_criteria": {},
    },
    {
        # Real template as of Phase C (§C.8): the permanent Owner Knowledge Mission — an
        # OwnerKnowledgeWorker that continuously reads the User Archive (code/docs/chats) into
        # global knowledge + experience and rebuilds the personal profile. Never completes.
        "name": "owner_knowledge",
        "template_version": 1,
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
        "success_criteria": {},
    },
    {
        "name": "technology_watch",
        "template_version": 1,
        "description": "Track breaking changes across chosen technologies (Phase B/D).",
        "config_schema_type": "generic",
        "default_config": {"technologies": [], "alert_frequency": "daily"},
        "worker_specs": [],
        "knowledge_domains": ["engineering"],
        "success_criteria": {},
    },
    {
        "name": "security_monitoring",
        "template_version": 1,
        "description": "Watch security advisories relevant to the stack (Phase B/D).",
        "config_schema_type": "generic",
        "default_config": {"components": [], "severity_floor": "high"},
        "worker_specs": [],
        "knowledge_domains": ["engineering", "security"],
        "success_criteria": {},
    },
]
