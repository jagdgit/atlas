"""ToolExecutor + ToolResult — validated, retrying tool invocation.

``ToolExecutor.execute`` is the single choke point for running a tool:

    validate args (against the callable's signature)
      -> invoke via the ToolRegistry
      -> retry transient failures (bounded, small backoff)
      -> return a structured ToolResult (ok/data/error/evidence/timing)

It never raises for an ordinary tool failure — the failure is *data* on the
result, so a planner/job can decide what to do (surface a Capability Gap per R2,
mark a step blocked/skipped per R3, or try another capability). Only genuinely
exceptional misuse (e.g. a non-dict args) is a programming error.
"""

from __future__ import annotations

import inspect
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from atlas.exceptions import ToolNotFoundError

if TYPE_CHECKING:
    from atlas.kernel.tools import ToolRegistry


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    tool: str
    data: Any = None
    error: str | None = None
    error_kind: str | None = None  # exception/type name, for gap classification (R2)
    evidence: list[dict[str, Any]] = field(default_factory=list)  # seam for S15
    elapsed_ms: float = 0.0
    attempts: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "tool": self.tool,
            "data": self.data,
            "error": self.error,
            "error_kind": self.error_kind,
            "evidence": self.evidence,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "attempts": self.attempts,
        }


class ToolExecutor:
    def __init__(
        self,
        tools: "ToolRegistry",
        *,
        max_retries: int = 2,
        retry_base: float = 0.1,
        logger: logging.Logger | None = None,
    ) -> None:
        self._tools = tools
        self._max_retries = max_retries
        self._retry_base = retry_base
        self._logger = logger or logging.getLogger("atlas.execution")

    def execute(
        self,
        tool: str,
        args: dict[str, Any] | None = None,
        *,
        retries: int | None = None,
    ) -> ToolResult:
        args = dict(args or {})
        started = time.perf_counter()

        # 1. Tool must exist. A missing tool is a capability gap (R2), not a crash.
        if not self._tools.has(tool):
            return ToolResult(
                ok=False,
                tool=tool,
                error=f"no tool registered named '{tool}'",
                error_kind="ToolNotFoundError",
                elapsed_ms=self._ms(started),
            )

        registered = self._tools.get(tool)

        # 2. Validate args against the callable's signature (deterministic → no retry).
        problem = self._validate_args(registered.func, args)
        if problem is not None:
            return ToolResult(
                ok=False,
                tool=tool,
                error=problem,
                error_kind="ArgumentError",
                elapsed_ms=self._ms(started),
            )

        # 3. Invoke with bounded retries on transient failures.
        max_attempts = (self._max_retries if retries is None else retries) + 1
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                data = registered.invoke(**args)
                return ToolResult(
                    ok=True,
                    tool=tool,
                    data=data,
                    elapsed_ms=self._ms(started),
                    attempts=attempt,
                )
            except ToolNotFoundError as exc:  # non-retryable gap
                return ToolResult(
                    ok=False,
                    tool=tool,
                    error=str(exc),
                    error_kind="ToolNotFoundError",
                    elapsed_ms=self._ms(started),
                    attempts=attempt,
                )
            except Exception as exc:  # noqa: BLE001 - surface as data, not a crash
                last_error = exc
                self._logger.info(
                    "tool '%s' failed (attempt %d/%d): %s",
                    tool,
                    attempt,
                    max_attempts,
                    exc,
                )
                if attempt < max_attempts:
                    time.sleep(self._retry_base * (2 ** (attempt - 1)))

        return ToolResult(
            ok=False,
            tool=tool,
            error=f"{type(last_error).__name__}: {last_error}",
            error_kind=type(last_error).__name__ if last_error else "Error",
            elapsed_ms=self._ms(started),
            attempts=max_attempts,
        )

    # --- internals ------------------------------------------------------
    @staticmethod
    def _validate_args(func: Any, args: dict[str, Any]) -> str | None:
        """Return an error string if ``args`` don't fit ``func``'s signature.

        Best-effort: if the signature can't be introspected, skip validation and
        let the call proceed (the invocation still surfaces failures as data).
        """
        try:
            sig = inspect.signature(func)
        except (TypeError, ValueError):
            return None

        params = sig.parameters.values()
        accepts_kwargs = any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in params
        )
        accepted = {
            p.name
            for p in params
            if p.kind
            in (
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            )
        }
        if not accepts_kwargs:
            unexpected = set(args) - accepted
            if unexpected:
                return (
                    f"unexpected argument(s): {', '.join(sorted(unexpected))}; "
                    f"accepts: {', '.join(sorted(accepted)) or 'none'}"
                )
        required = {
            p.name
            for p in params
            if p.default is inspect.Parameter.empty
            and p.kind
            in (
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            )
        }
        missing = required - set(args)
        if missing:
            return f"missing required argument(s): {', '.join(sorted(missing))}"
        return None

    @staticmethod
    def _ms(started: float) -> float:
        return (time.perf_counter() - started) * 1000.0
