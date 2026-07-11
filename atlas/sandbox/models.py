"""Sandbox execution result model.

A single, serialisable record of one run. The ``outcome`` is the honest, coarse
verdict a job (or the Verification Engine) reasons about:

- ``ok``       — the code ran and exited 0.
- ``error``    — the code ran but exited non-zero (exception/`sys.exit(n)`); see stderr.
- ``timeout``  — killed at the wall-clock limit.
- ``blocked``  — the sandbox itself was unavailable (backend missing/misconfigured);
                 R2/R3 — surface it, don't crash the job.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

OUTCOME_OK = "ok"
OUTCOME_ERROR = "error"
OUTCOME_TIMEOUT = "timeout"
OUTCOME_BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    outcome: str
    stdout: str = ""
    stderr: str = ""
    returncode: int | None = None
    duration_ms: int = 0
    timed_out: bool = False
    truncated: bool = False
    error: str | None = None
    # Optional structured result: parsed from ``result.json`` written by the code.
    result: Any = None
    # Files the run produced in its working dir (name → byte size).
    artifacts: dict[str, int] = field(default_factory=dict)
    backend: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome == OUTCOME_OK

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "ok": self.ok,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.returncode,
            "duration_ms": self.duration_ms,
            "timed_out": self.timed_out,
            "truncated": self.truncated,
            "error": self.error,
            "result": self.result,
            "artifacts": self.artifacts,
            "backend": self.backend,
        }
