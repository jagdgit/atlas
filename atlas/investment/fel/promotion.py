"""Promotion is a status, never a live V1 mutation (FEL.3 / D6)."""

from __future__ import annotations

from typing import Any

ALLOWED = frozenset({"never", "candidate", "paper_challenger"})
LIVE_CONTROL = "live_control"


def promotion_for(*, result: str, operator_level10: bool = False) -> str:
    """FEL never writes live_control. Level 10 is an operator act outside this module."""
    del operator_level10
    if result == "improve":
        return "candidate"
    if result == "conditional":
        return "candidate"
    return "never"


def assert_not_live(promotion: str) -> None:
    if promotion == LIVE_CONTROL:
        raise ValueError("FEL must not promote to live_control")
