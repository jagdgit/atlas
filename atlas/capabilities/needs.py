"""Mission capability *needs* — declare what a mission requires (OI-PA-CAP / CAP.1).

Missions ask the Capability Registry for named needs (``market_reader``,
``speech_to_text``) instead of importing concrete adapters. Aliases map
operator/docs names (``MarketReader``) onto registered ids.
"""

from __future__ import annotations

# Canonical need ids (match CapabilityRegistry registration names where possible).
NEED_MARKET_READER = "market_reader"
NEED_COMPANY_DATA = "company_data"
NEED_PORTFOLIO = "portfolio"
NEED_PORTFOLIO_LEDGER = "portfolio_ledger"
NEED_MISSION_CONTEXT = "mission_context"
NEED_PLANNING = "planning"
NEED_POLICY_ENGINE = "policy_engine"
NEED_WORLD_MODELS = "world_models"
NEED_KNOWLEDGE_GRAPH = "knowledge_graph"
NEED_MEMORY_OS = "memory_os"
NEED_EXPERIENCE_OS = "experience_os"
NEED_EVENTS = "events"
NEED_JOBS = "jobs"
NEED_LEARNING = "learning"
NEED_CANDIDATES = "candidates"
NEED_SPEECH = "speech_to_text"
NEED_KNOWLEDGE = "knowledge"

# Docs / Program vocabulary → registry name
ALIASES: dict[str, str] = {
    "MarketReader": NEED_MARKET_READER,
    "marketreader": NEED_MARKET_READER,
    "CompanyData": NEED_COMPANY_DATA,
    "companydata": NEED_COMPANY_DATA,
    "PortfolioLedger": NEED_PORTFOLIO_LEDGER,
    "MissionContext": NEED_MISSION_CONTEXT,
    "MissionContextAPI": NEED_MISSION_CONTEXT,
    "PlanningOS": NEED_PLANNING,
    "PolicyEngine": NEED_POLICY_ENGINE,
    "WorldModels": NEED_WORLD_MODELS,
    "KnowledgeGraph": NEED_KNOWLEDGE_GRAPH,
    "MemoryOS": NEED_MEMORY_OS,
    "ExperienceOS": NEED_EXPERIENCE_OS,
    "SpeechToText": NEED_SPEECH,
    "speech": NEED_SPEECH,
}

# Built-in need sets for Market Intelligence members (declare, don't import).
MISSION_NEEDS: dict[str, tuple[str, ...]] = {
    "market_observer": (NEED_MARKET_READER, NEED_EVENTS),
    "company_intelligence": (NEED_COMPANY_DATA, NEED_CANDIDATES),
    "news_intelligence": (NEED_CANDIDATES,),
    "event_research": (NEED_JOBS, NEED_PLANNING),
    "decision_simulation": (NEED_PORTFOLIO, NEED_MISSION_CONTEXT, NEED_POLICY_ENGINE, NEED_EXPERIENCE_OS),
    "paper_trading": (NEED_PORTFOLIO, NEED_MISSION_CONTEXT, NEED_POLICY_ENGINE, NEED_EXPERIENCE_OS),
    "portfolio_ledger": (NEED_PORTFOLIO_LEDGER,),
    "investment_mentor": (NEED_LEARNING, NEED_EXPERIENCE_OS),
    "engineering_mentor": (NEED_LEARNING, NEED_EXPERIENCE_OS),
    "repository_learning": (NEED_KNOWLEDGE, NEED_LEARNING),
}


def canonicalize(name: str) -> str:
    raw = (name or "").strip()
    if not raw:
        return raw
    if raw in ALIASES:
        return ALIASES[raw]
    key = raw.lower().replace(" ", "").replace("-", "_")
    if key in ALIASES:
        return ALIASES[key]
    # MarketReader-style CamelCase → snake
    if raw[0].isupper() and raw in ALIASES:
        return ALIASES[raw]
    return key if "_" in key or key.islower() else raw


def needs_for_mission(template_or_worker: str) -> tuple[str, ...]:
    key = (template_or_worker or "").strip().lower()
    return MISSION_NEEDS.get(key, ())
