"""ReportService — the ``reports`` capability (S17).

Two entry points:
- ``report(objective, graph, budget?)`` — the research pipeline: verify a serialised
  Evidence Graph (via the Verification Engine), then render the §5a.5 report from the
  *verified* claims. Used by ``POST /v1/report`` / ``atlas report``.
- ``render(objective, ...)`` — render a report directly from already-verified claims or
  a gathered answer + sources (no verification). Used by the Job Engine on finalize to
  attach a structured report to a job's result.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from atlas.reports.generator import ReportGenerator
from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.verification.service import VerificationService


class ReportService:
    name = "reports"

    def __init__(
        self,
        verification: "VerificationService | None" = None,
        generator: ReportGenerator | None = None,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._verification = verification
        self._generator = generator or ReportGenerator()
        self._logger = logger or logging.getLogger("atlas.reports")

    def report(
        self,
        objective: str,
        graph: dict[str, Any],
        *,
        budget: dict[str, Any] | None = None,
        notes: str = "",
        findings: list[dict[str, Any]] | None = None,
        reasoning: dict[str, Any] | None = None,
        pipeline: dict[str, Any] | None = None,
        termination: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._verification is None:
            # No engine wired: render from the (assumed pre-verified) claims as-is.
            verified = {
                "claims": graph.get("claims", []),
                "sources": graph.get("sources", []),
                "budget": budget or {},
            }
        else:
            # Acquire-stop: skip verification — there is nothing to verify (RH2/RH3).
            if termination and str(termination.get("stage") or "") == "acquire":
                verified = {
                    "claims": [],
                    "sources": graph.get("sources", []),
                    "budget": budget or {},
                    "skipped": "acquisition_failed",
                }
            else:
                verified = self._verification.verify(graph, budget)
        report = self._generator.generate(
            objective,
            claims=verified["claims"],
            findings=findings,
            sources=verified.get("sources", []),
            notes=notes,
            reasoning=reasoning,
            pipeline=pipeline,
            termination=termination,
        )
        return {"report": report, "verification": verified}

    def render(
        self,
        objective: str,
        *,
        claims: list[dict[str, Any]] | None = None,
        findings: list[dict[str, Any]] | None = None,
        sources: list[dict[str, Any]] | None = None,
        answer: str = "",
        notes: str = "",
        reasoning: dict[str, Any] | None = None,
        pipeline: dict[str, Any] | None = None,
        termination: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._generator.generate(
            objective,
            claims=claims,
            findings=findings,
            sources=sources,
            answer=answer,
            notes=notes,
            reasoning=reasoning,
            pipeline=pipeline,
            termination=termination,
        )

    # --- lifecycle ------------------------------------------------------
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def health_check(self) -> HealthStatus:
        return HealthStatus.ok(
            "report generator ready",
            verification=self._verification is not None,
        )
