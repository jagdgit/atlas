"""Python execution sandbox (Stage 2, S16, D6).

Atlas runs analysis code (e.g. a data-driven estimate) in an **isolated, resource-
limited** sandbox and feeds the computed result back into research as **L5 evidence**
(§5a.6). Design (D6 — *hybrid*): the executor is written against a small
``SandboxBackend`` interface; the default backend is a locked-down **subprocess**
(dedicated interpreter, `rlimit` CPU/memory/file caps, hard wall-clock timeout,
scratch-only working dir, stripped env, **network disabled by default**), and a
**Docker backend** can be swapped in via config later for stronger isolation — without
touching callers.

Every run returns a structured ``ExecutionResult`` (an *outcome*, never a raw crash),
so a job degrades honestly (R2/R3) instead of stalling.
"""

from __future__ import annotations

from atlas.sandbox.backends import (
    DockerBackend,
    SandboxBackend,
    SubprocessBackend,
    create_backend,
)
from atlas.sandbox.models import (
    OUTCOME_BLOCKED,
    OUTCOME_ERROR,
    OUTCOME_OK,
    OUTCOME_TIMEOUT,
    ExecutionResult,
)
from atlas.sandbox.service import PythonSandboxService

__all__ = [
    "ExecutionResult",
    "OUTCOME_OK",
    "OUTCOME_ERROR",
    "OUTCOME_TIMEOUT",
    "OUTCOME_BLOCKED",
    "SandboxBackend",
    "SubprocessBackend",
    "DockerBackend",
    "create_backend",
    "PythonSandboxService",
]
