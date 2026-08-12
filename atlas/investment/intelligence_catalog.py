"""Investment Intelligence operator catalog — capabilities, sites, methodology.

Served to the web UI so the operator can review what Atlas uses and extend it.
Static description + live hooks (providers, universes, failures) assembled at request time.
"""

from __future__ import annotations

from typing import Any


VERSION = "iip.catalog.1"


def methodology() -> dict[str, Any]:
    return {
        "product": "Investment Intelligence Platform",
        "house": "Market Intelligence Program (not a new OS)",
        "pipeline": [
            "Macro Theme Engine",
            "Universe Manager",
            "Discovery Engine (screen + hypothesis)",
            "Research Worker / IRA",
            "Market Knowledge Graph",
            "Investment Scoring",
            "Portfolio Optimizer",
            "Paper Trading (simulation)",
            "Thesis Tracker / Learning",
        ],
        "principles": [
            "P10 — simulation fills only (no live broker orders)",
            "Evidence before eloquence — never invent fundamentals",
            "Coverage ≠ confidence ≠ research quality ≠ investment confidence",
            "MVR satisfied ≠ buy; high research confidence can still mean low investment confidence",
            "No ToS HTML scraping as a dependency (Screener via export; TradingView non-primary)",
            "Host-first (IR-RO11) — discovery/research are background and memory-gated",
            "CapabilityGap honesty when a web source is down or disabled",
        ],
        "research": {
            "agent": "Investing Research Agent (IRA)",
            "dossier": [
                "Thesis",
                "Business quality",
                "Moat / risks",
                "Management",
                "Valuation / MoS",
                "Technical structure",
                "Policy / theme impact",
                "News",
                "Evidence ladder",
                "Watch items",
            ],
            "gates": [
                "Research gate (MVR / thesis / MoS soft for learner)",
                "Portfolio gate (cash, concentration, persona)",
                "Session hours (NSE cash)",
            ],
            "horizons": [
                "trading",
                "swing",
                "position",
                "long_term",
                "structural",
                "speculative",
            ],
            "dual_confidence": {
                "research_confidence": "How well do we understand the company/theme?",
                "investment_confidence": "How attractive is owning it now?",
            },
        },
        "ship_order": [
            "IIP.1 Universe Manager",
            "IIP.2 Themes + Discovery",
            "IIP.3 Fundamentals import",
            "IIP.4 Document research",
            "IIP.5 Market Knowledge Graph",
            "IIP.6 Scoring",
            "IIP.7 Portfolio optimizer",
            "IIP.8 Thesis Tracker",
            "IIP.9 News/policy feeds & vendors",
        ],
        "plan_doc": "docs/INVESTMENT_INTELLIGENCE_PLATFORM_PLAN.md",
    }


def websites_and_sources() -> list[dict[str, Any]]:
    """Declared external / internal sources (honest status)."""
    return [
        {
            "id": "yahoo_finance",
            "name": "Yahoo Finance chart API",
            "url": "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            "purpose": "Live / delayed OHLCV for .NS symbols",
            "status": "primary_live",
            "needs": "market.yahoo_enabled=true + network",
            "operator_help": "If failures appear, check Wi‑Fi and yahoo_enabled; empty bars often mean outage or symbol mismatch.",
        },
        {
            "id": "alphavantage",
            "name": "Alpha Vantage",
            "url": "https://www.alphavantage.co/query",
            "purpose": "Alternate OHLCV",
            "status": "wired_needs_key",
            "needs": "ATLAS_ALPHAVANTAGE_API_KEY",
            "operator_help": "Set API key in .env / atlas.env then restart Atlas.",
        },
        {
            "id": "polygon",
            "name": "Polygon.io",
            "url": "https://api.polygon.io/",
            "purpose": "Alternate OHLCV aggregates",
            "status": "wired_needs_key",
            "needs": "ATLAS_POLYGON_API_KEY",
            "operator_help": "Set API key then restart Atlas.",
        },
        {
            "id": "stooq",
            "name": "Stooq daily history",
            "url": "https://stooq.com/",
            "purpose": "Free daily OHLCV history fallback (NSE → .in mapping)",
            "status": "available",
            "needs": "provider=stooq + network",
            "operator_help": "Select stooq as MarketReader provider; SYMBOL.NS maps to symbol.in.",
        },
        {
            "id": "rss_allowlist",
            "name": "RSS / Atom allow-list",
            "url": None,
            "purpose": "Official news/policy feeds only (PIB/SEBI/etc. when verified)",
            "status": "operator_enable",
            "needs": (
                "E1: learner overrides enable pib_press; SEBI/RBI stay off until verified"
            ),
            "operator_help": (
                "DEFAULT_ALLOWLIST stays disabled. Mission rss_enable=['pib_press'] "
                "(XML verified 2026-08-10). HTML pages are refused (no scrape)."
            ),
        },
        {
            "id": "nse_bse",
            "name": "NSE / BSE adapters",
            "url": None,
            "purpose": "Official exchange feeds (planned)",
            "status": "skeleton_tos_gated",
            "needs": "ToS-safe client + keys",
            "operator_help": "Not live yet — CapabilityGap until licensed path exists.",
        },
        {
            "id": "asset_replay",
            "name": "Local market_data assets",
            "url": None,
            "purpose": "Hermetic replay for tests / backtests",
            "status": "available",
            "needs": "Registered market_data asset",
            "operator_help": "Developer path — not the India learner default.",
        },
        {
            "id": "screener_export",
            "name": "Screener.in (operator export)",
            "url": "https://www.screener.in/",
            "purpose": "Fundamentals convenience (ROE, ROCE, debt, …)",
            "status": "operator_import",
            "needs": "CSV/JSON export or drop folder → POST /v1/market/fundamentals/import",
            "operator_help": (
                "Do not scrape HTML. Export CSV from Screener, paste on Invest intel, "
                "or drop files into data/imports/fundamentals/. See docs/SCREENER_FUNDAMENTALS_IMPORT.md."
            ),
        },
        {
            "id": "company_documents",
            "name": "Company documents (AR / quarterly / deck)",
            "url": None,
            "purpose": "Operator-uploaded PDFs → guidance/risk/KPI claims on IRA dossiers",
            "status": "operator_import",
            "needs": "PDF/TXT path or drop folder → POST /v1/market/company-documents/import",
            "operator_help": (
                "Name files SYMBOL__kind__period.pdf (e.g. INFY__annual__FY25.pdf). "
                "See docs/COMPANY_DOCUMENTS_IMPORT.md. No scrape."
            ),
        },
        {
            "id": "tradingview",
            "name": "TradingView",
            "url": "https://www.tradingview.com/",
            "purpose": "Chart links only (GET /v1/market/chart-links/{symbol})",
            "status": "non_primary",
            "needs": None,
            "operator_help": "Never the primary price feed; technicals computed locally from OHLCV.",
        },
        {
            "id": "duckduckgo",
            "name": "DuckDuckGo HTML search",
            "url": "https://html.duckduckgo.com/html/",
            "purpose": "General web search capability",
            "status": "available_search",
            "needs": "network",
            "operator_help": "Not a dedicated stock terminal.",
        },
        {
            "id": "gov_catalog",
            "name": "Atlas India policy catalog",
            "url": None,
            "purpose": "Budget / PLI / sector nudges (hermetic + operator + optional policy RSS)",
            "status": "hermetic_plus_operator_rss",
            "needs": "Optional operator items; enable policy RSS via news-feeds fetch into_policy",
            "operator_help": (
                "Add policy via Government Intelligence or POST /v1/market/news-feeds/fetch "
                "with into_policy=true after enabling verified RSS ids."
            ),
        },
        {
            "id": "operator_snapshots",
            "name": "Operator research snapshots",
            "url": None,
            "purpose": "Fundamentals / filings / management evidence",
            "status": "available",
            "needs": "POST research snapshot / filings / management pack",
            "operator_help": "Highest-leverage way to improve research quality today.",
        },
        {
            "id": "smtp",
            "name": "SMTP (investor email)",
            "url": None,
            "purpose": "Morning / evening / trade / weekly reports",
            "status": "configured_via_env",
            "needs": "ATLAS_EMAIL_* + ATLAS_INVESTOR_REPORT_TO",
            "operator_help": "Failures to send are retried; day not marked sent on SMTP fail.",
        },
    ]


def capabilities_matrix() -> list[dict[str, Any]]:
    return [
        {
            "id": "universe_manager",
            "name": "Universe Manager",
            "status": "iip1_shipping",
            "description": "Multi-index / theme membership; caps on active research set",
        },
        {
            "id": "theme_engine",
            "name": "Macro Theme Engine",
            "status": "shipping_iip2",
            "description": "Hypotheses → beneficiary supply chains before screening",
        },
        {
            "id": "discovery",
            "name": "Discovery Engine",
            "status": "shipping_iip2",
            "description": "1000→40→10 interesting candidates with why + horizon",
        },
        {
            "id": "ira",
            "name": "Investing Research Agent",
            "status": "shipped",
            "description": "Dossiers, MVR, MoS, evidence ladder, research gate",
        },
        {
            "id": "paper_trading",
            "name": "Decision Simulation / paper ledger",
            "status": "shipped",
            "description": "Sim buys/sells, fees, emails, session hours",
        },
        {
            "id": "fundamentals_import",
            "name": "Fundamentals import",
            "status": "shipping",
            "description": (
                "Screener/CSV/JSON → durable store + screener snapshot + ranking/discovery; "
                "optional push_to_ira for dossier ladder"
            ),
        },
        {
            "id": "company_documents",
            "name": "Company document research",
            "status": "shipping",
            "description": (
                "AR/quarterly/deck/transcript PDF → extract claims → IRA dossier evidence"
            ),
        },
        {
            "id": "mkg",
            "name": "Market Knowledge Graph",
            "status": "shipping",
            "description": (
                "Theme↔company↔policy edges; why-own / who-benefits queries; "
                "dossier neighborhood (hermetic seed, no invented supply chains)"
            ),
        },
        {
            "id": "investment_scoring",
            "name": "Investment Scoring",
            "status": "shipping",
            "description": (
                "Multi-axis score + research vs investment confidence; "
                "high research + low investment → watch"
            ),
        },
        {
            "id": "portfolio_optimizer",
            "name": "Portfolio Optimizer",
            "status": "shipping",
            "description": (
                "Pre-trade gates: concentration, cash, persona, max names, "
                "investment confidence; MoS/horizon sizing"
            ),
        },
        {
            "id": "thesis_tracker",
            "name": "Thesis Tracker",
            "status": "shipping",
            "description": (
                "Hypothesis → assumptions → decision → outcome → lessons; "
                "N≥20 closed paper outcomes unlock discovery/scoring prior shifts"
            ),
        },
        {
            "id": "news_policy_vendors",
            "name": "News / policy RSS + vendors",
            "status": "shipping",
            "description": (
                "RSS allow-list (no scrape), policy RSS → gov catalog, "
                "Stooq history adapter, TradingView chart links"
            ),
        },
        {
            "id": "feed_failure_log",
            "name": "Web data failure log",
            "status": "shipping",
            "description": "Durable record when Yahoo/other fetches fail — operator triage",
        },
    ]


def how_to_help_atlas() -> list[str]:
    return [
        "Keep Atlas online (systemd + Wi‑Fi); check Feed failures on this page after market hours.",
        "If Yahoo fails: restore internet; confirm market.yahoo_enabled; restart atlas.service.",
        "Add ATLAS_POLYGON_API_KEY or ATLAS_ALPHAVANTAGE_API_KEY for alternate price feeds; try provider=stooq for free history.",
        "Post operator research snapshots / filing refs for names you care about (Market → Research).",
        "Enable additional universes (NEXT50 / Midcap) when you want broader discovery (IIP.1).",
        "Import Screener CSV/JSON on Invest intel (Fundamentals) or drop into data/imports/fundamentals/ — no HTML scraping.",
        "Upload annual/quarterly PDFs on Invest intel (Documents) or drop SYMBOL__kind__period.pdf into data/imports/company_documents/.",
        "Ask ‘Why own X?’ on Invest intel MKG or Research dossier — answers cite labeled theme/policy edges only.",
        "Review Thesis Tracker on Invest intel after sim sells — tag assumption failures so priors compound (N≥20).",
        "Enable verified official RSS ids on Invest intel (News feeds) — HTML pages are refused.",
        "Add government policy items when Budget/PLI news lands (Government Intelligence inputs).",
    ]


def catalog_skeleton() -> dict[str, Any]:
    return {
        "version": VERSION,
        "methodology": methodology(),
        "sources": websites_and_sources(),
        "capabilities": capabilities_matrix(),
        "how_to_help": how_to_help_atlas(),
    }
