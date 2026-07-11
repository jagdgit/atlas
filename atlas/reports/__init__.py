"""Report generation (Stage 2, S17, §5a.5).

The final stage of the research pipeline
(``Planner → Research → Verification Engine → Evidence Graph → **Report Generator**``):
turn *verified claims* into a **scientific-review-style report** — Executive Summary →
Answer → Confidence → Methodology → Evidence → References → Conflicting Views →
Limitations → Next Research — where every numeric answer carries its claim's calculated
confidence and supporting/contradicting sources.
"""

from __future__ import annotations

from atlas.reports.generator import REPORT_SECTIONS, ReportGenerator
from atlas.reports.service import ReportService

__all__ = ["ReportGenerator", "ReportService", "REPORT_SECTIONS"]
