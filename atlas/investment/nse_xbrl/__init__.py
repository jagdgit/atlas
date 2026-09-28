"""NSE/XBRL vertical slice — FEA provider, not a second fundamentals product.

Connect: UQ → FEA → this provider → existing fundamentals store → PLC.A.
Does not scrape Screener HTML. Does not invent zeros. Does not loosen PLC.A.
"""

from __future__ import annotations

from atlas.investment.nse_xbrl.as_of import fact_usable_as_of
from atlas.investment.nse_xbrl.calculations import calculate_metrics, normalize_capex
from atlas.investment.nse_xbrl.coverage import SLICE_FIELDS, fundamentals_coverage
from atlas.investment.nse_xbrl.digest import format_fundamental_intelligence_section
from atlas.investment.nse_xbrl.filing_selection import select_canonical_filing
from atlas.investment.nse_xbrl.parser import parse_xbrl
from atlas.investment.nse_xbrl.provider import acquire_from_nse
from atlas.investment.nse_xbrl.replay import replay_hblpower_candidate

VERSION = "nse.xbrl.slice.v1"
SOURCE_NSE_XBRL = "nse_xbrl"

__all__ = [
    "SLICE_FIELDS",
    "SOURCE_NSE_XBRL",
    "VERSION",
    "acquire_from_nse",
    "calculate_metrics",
    "fact_usable_as_of",
    "format_fundamental_intelligence_section",
    "fundamentals_coverage",
    "normalize_capex",
    "parse_xbrl",
    "replay_hblpower_candidate",
    "select_canonical_filing",
]
