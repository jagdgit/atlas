"""Execution layer (Sprint 10).

The ToolExecutor wraps the kernel ``ToolRegistry`` with the safety a planner/job
needs: argument validation against the tool's signature, bounded retries on
transient failures, and a structured ``ToolResult`` (never a raw exception). This
is mode-agnostic (D1): a chat turn runs a tool inline; a job step (S12) will run
the *same* executor over the *same* registry. The ``evidence`` field on a result
is the seam the Verification Engine (S15) later hooks into.
"""

from __future__ import annotations

from atlas.execution.executor import ToolExecutor, ToolResult

__all__ = ["ToolExecutor", "ToolResult"]
