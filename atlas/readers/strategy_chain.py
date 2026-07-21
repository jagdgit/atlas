"""Reusable ordered strategy execution for Readers (Media Reader Family · M.2 / MD3).

Atlas increasingly needs:

    Capability
        ↓
    Strategy 1 → Strategy 2 → Strategy 3 → …
        ↓
    Outcome (+ strategies_tried[])

rather than a single brittle implementation. ``ReaderStrategyChain`` is that helper:
ordered callables, **first ``ok`` wins**, every attempt recorded. Media/YouTube is the
first production consumer; the same pattern is intended for documents, git, OCR, CAD
later (OI-M7) without inventing a new plane.

This module is intentionally **dependency-light** (no import of ``atlas.transcripts``) so
Readers can own the chain without circular imports. Callers map ``StrategyResult`` onto
domain records (e.g. ``AcquisitionAttempt``) themselves.

Strategies never raise into callers — exceptions become ``outcome=error`` attempts (R2/R3).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("atlas.readers.strategy_chain")

StrategyFn = Callable[[], "StrategyResult"]


@dataclass(frozen=True)
class StrategyResult:
    """Outcome of one named strategy. ``value`` is only meaningful when ``outcome == "ok"``."""

    name: str
    outcome: str
    reason: str | None = None
    reason_code: str = "unknown"
    bytes_read: int = 0
    value: Any = None

    @property
    def ok(self) -> bool:
        return self.outcome == "ok"

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "outcome": self.outcome,
            "reason": self.reason,
            "reason_code": self.reason_code,
            "bytes_read": int(self.bytes_read or 0),
            "ok": self.ok,
        }


@dataclass(frozen=True)
class ChainResult:
    """Full chain execution: optional winner + every attempt in order."""

    winner: StrategyResult | None
    tried: tuple[StrategyResult, ...]
    source_url: str = ""
    source_kind: str = "generic"
    suggested_next_capability: str | None = None

    @property
    def ok(self) -> bool:
        return self.winner is not None and self.winner.ok

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "winner": self.winner.as_dict() if self.winner else None,
            "strategies_tried": [r.as_dict() for r in self.tried],
            "source_url": self.source_url,
            "source_kind": self.source_kind,
            "suggested_next_capability": self.suggested_next_capability,
        }


class ReaderStrategyChain:
    """Execute named strategies in order; stop at the first ``ok``."""

    def __init__(self, *, logger_: logging.Logger | None = None) -> None:
        self._logger = logger_ or logger

    def execute(
        self,
        strategies: Sequence[tuple[str, StrategyFn]],
        *,
        source_url: str = "",
        source_kind: str = "generic",
        suggested_next_capability: str | None = None,
    ) -> ChainResult:
        tried: list[StrategyResult] = []
        for name, fn in strategies:
            try:
                result = fn()
            except Exception as exc:  # noqa: BLE001 - strategies must not abort the chain
                self._logger.exception("strategy %s raised", name)
                result = StrategyResult(
                    name=name,
                    outcome="error",
                    reason=str(exc),
                    reason_code="parse_error",
                )
            # Prefer the registry name so callers control the audit label.
            if result.name != name:
                result = StrategyResult(
                    name=name,
                    outcome=result.outcome,
                    reason=result.reason,
                    reason_code=result.reason_code,
                    bytes_read=result.bytes_read,
                    value=result.value,
                )
            tried.append(result)
            if result.ok:
                return ChainResult(
                    winner=result,
                    tried=tuple(tried),
                    source_url=source_url,
                    source_kind=source_kind,
                    suggested_next_capability=None,
                )
        return ChainResult(
            winner=None,
            tried=tuple(tried),
            source_url=source_url,
            source_kind=source_kind,
            suggested_next_capability=suggested_next_capability,
        )
