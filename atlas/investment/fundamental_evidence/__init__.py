"""Fundamental Evidence Acquisition — planner → multi-source fetch → validate → store.

Not a Screener HTML scraper. NSE/XBRL is the normal network path; Yahoo is
secondary/cross-check only; operator Screener import remains first-class;
MoS stays IRA-only. Does not authorize trades or loosen swing gates.
"""

from __future__ import annotations

from atlas.investment.fundamental_evidence.planner import plan_symbol_acquisition
from atlas.investment.fundamental_evidence.dispatch import (
    plan_batch_acquisition,
    schedule_nse_retry,
)
from atlas.investment.fundamental_evidence.policy import (
    ACQUIRABLE_FIELDS,
    CODE_TO_FIELD,
    FIELD_TO_UQ_CODE,
    metric_source_policy,
    source_policy_table,
)
from atlas.investment.fundamental_evidence.runner import (
    acquire_for_symbol,
    drain_uncertainty_queue,
)

__all__ = [
    "ACQUIRABLE_FIELDS",
    "CODE_TO_FIELD",
    "FIELD_TO_UQ_CODE",
    "acquire_for_symbol",
    "drain_uncertainty_queue",
    "metric_source_policy",
    "plan_batch_acquisition",
    "plan_symbol_acquisition",
    "schedule_nse_retry",
    "source_policy_table",
]
