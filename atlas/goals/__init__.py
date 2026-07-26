"""Durable Goals package (OX.3 / OX.4) — objectives first + progress narratives."""

from atlas.goals.progress import build_progress_report, format_progress_answer
from atlas.goals.service import GoalService
from atlas.repositories.goal_repo import (
    GOAL_STATUSES,
    GoalRepository,
    InMemoryGoalRepository,
)

__all__ = [
    "GOAL_STATUSES",
    "GoalRepository",
    "GoalService",
    "InMemoryGoalRepository",
    "build_progress_report",
    "format_progress_answer",
]
