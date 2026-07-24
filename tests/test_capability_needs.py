"""Capability needs resolution (CAP.1 / OI-PA-CAP)."""

from __future__ import annotations

from atlas.capabilities.needs import (
    ALIASES,
    NEED_MARKET_READER,
    canonicalize,
    needs_for_mission,
)
from atlas.kernel.capabilities import CapabilityRegistry


def test_alias_and_check_needs():
    reg = CapabilityRegistry()
    reg.register(NEED_MARKET_READER, object(), kind="service", version="mi.3")
    reg.alias("MarketReader", NEED_MARKET_READER)
    assert reg.resolve_name("MarketReader") == NEED_MARKET_READER
    assert reg.has("MarketReader")
    report = reg.check_needs(["MarketReader", "speech_to_text"])
    assert report["ok"] is False
    assert NEED_MARKET_READER in [s["name"] for s in report["satisfied"]]
    assert "speech_to_text" in report["missing"]


def test_mission_needs_market_observer():
    needs = needs_for_mission("market_observer")
    assert NEED_MARKET_READER in needs
    assert "events" in needs


def test_canonicalize_aliases():
    assert canonicalize("MarketReader") == NEED_MARKET_READER
    assert canonicalize("speech") == "speech_to_text"


def test_provider_for_disabled():
    from atlas.exceptions import CapabilityMissingError

    reg = CapabilityRegistry()
    reg.register("x", object(), enabled=False)
    try:
        reg.provider_for("x")
        assert False, "expected CapabilityMissingError"
    except CapabilityMissingError:
        pass


def test_market_observer_gap_note():
    from atlas.workers.base import TickContext
    from atlas.workers.market_observer import MarketObserverWorker

    class _Reader:
        def observe(self, *a, **k):
            return []

    reg = CapabilityRegistry()
    # missing market_reader + events
    worker = MarketObserverWorker(market_reader=_Reader(), capabilities=reg)
    result = worker.do_tick(
        TickContext(worker_id="w", mission_id="m", config={}, config_version=1, state={})
    )
    assert "capability_gap" in result.note


def test_self_report_gaps_catalog_and_mission():
    """OI-F5 — registry self-report surfaces catalog + mission gaps (P15)."""
    from atlas.capabilities.contracts import CAPABILITY_CATALOG

    reg = CapabilityRegistry()
    reg.register(NEED_MARKET_READER, object(), kind="service", version="t")
    report = reg.self_report_gaps(include_missions=True)
    assert report["version"] == "f5.1"
    assert report["ok"] is False
    missing_ids = {g["missing_capability"] for g in report["catalog_gaps"]}
    # At least one catalog cap beyond market_reader should be missing
    assert any(cid != NEED_MARKET_READER for cid in missing_ids) or len(CAPABILITY_CATALOG) <= 1
    assert any(m["mission"] == "market_observer" for m in report["mission_gaps"])
    # events still missing for market_observer
    mo = next(m for m in report["mission_gaps"] if m["mission"] == "market_observer")
    assert "events" in mo["missing"]
    # With only market_reader, portfolio missions should also gap
    assert report["summary"]["missions_blocked"] >= 1


def test_self_report_gaps_ok_when_needs_met():
    reg = CapabilityRegistry()
    for name in ("market_reader", "events", "candidates", "jobs", "planning",
                 "portfolio", "mission_context", "policy_engine", "experience_os",
                 "portfolio_ledger", "learning", "company_data"):
        reg.register(name, object(), kind="service")
    # Don't include full catalog — ok refers to catalog+mission+unhealthy
    report = reg.self_report_gaps(include_missions=True)
    assert report["mission_gaps"] == []
    # catalog will still have gaps for unused catalog ids
    assert isinstance(report["catalog_gaps"], list)