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
    assert "decision_simulation" in phil["planned_split"]
    assert "market_observer" in phil["planned_split"]


def test_decision_simulation_philosophy_aliases_paper_trading():
    phil = philosophy_for("decision_simulation")
    assert phil["mission_kind"] == KIND_SIMULATION
    assert phil["compat_alias"] == "paper_trading"
    assert phil["lifecycle"]["decide"] == "active"


def test_market_stub_templates_have_philosophy():
    for name in (
        "market_observer",
        "company_intelligence",
        "news_intelligence",
        "event_research",
        "portfolio_ledger",
        "investment_mentor",
        "engineering_mentor",
        "personal_mentor",
    ):
        phil = philosophy_for(name)
        assert set(phil["lifecycle"]) == set(LIFECYCLE_STAGES)


def test_with_philosophy_preserves_existing_criteria():
    merged = with_philosophy({"metric": "sharpe"}, "research")
    assert merged["metric"] == "sharpe"
    assert merged["philosophy"]["mission_kind"] == "research"
