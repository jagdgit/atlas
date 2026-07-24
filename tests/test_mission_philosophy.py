"""Mission philosophy metadata (MP1)."""

from __future__ import annotations

from atlas.missions.philosophy import (
    KIND_SIMULATION,
    LIFECYCLE_STAGES,
    philosophy_for,
    with_philosophy,
)
from atlas.missions.templates.builtins import BUILTIN_TEMPLATES


def test_every_builtin_has_philosophy_block():
    names = {t["name"] for t in BUILTIN_TEMPLATES}
    for name in names:
        phil = philosophy_for(name)
        assert phil["mission_kind"]
        assert "never_stops" in phil
        assert set(phil["lifecycle"]) == set(LIFECYCLE_STAGES)


def test_builtins_seed_philosophy_into_success_criteria():
    by_name = {t["name"]: t for t in BUILTIN_TEMPLATES}
    paper = by_name["paper_trading"]
    phil = paper["success_criteria"]["philosophy"]
    assert phil["mission_kind"] == KIND_SIMULATION
    assert phil["never_stops"] is True
    assert phil["lifecycle"]["decide"] == "active"
    assert "market_watch" in phil["planned_split"]


def test_with_philosophy_preserves_existing_criteria():
    merged = with_philosophy({"metric": "sharpe"}, "research")
    assert merged["metric"] == "sharpe"
    assert merged["philosophy"]["mission_kind"] == "research"
