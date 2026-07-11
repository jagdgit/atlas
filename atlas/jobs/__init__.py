"""Job Engine (Stage 2, S12): persistent, concurrent, resumable jobs.

Built on the durable scheduler. A ``JobService`` decomposes an objective into
ordered steps and advances them one at a time via a self-re-enqueuing scheduler
task, so many jobs interleave (R1) while steps within a job stay sequential (v1).
``JobPlanner`` turns an objective into a plan (deterministic fallback + optional
planner-role LLM decomposition, D2c).
"""

from __future__ import annotations

from atlas.jobs.planner import DecomposedStep, JobPlanner
from atlas.jobs.service import JobService

__all__ = ["DecomposedStep", "JobPlanner", "JobService"]
