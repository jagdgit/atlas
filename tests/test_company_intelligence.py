"""Company Intelligence adapters + worker (MI.5)."""

from __future__ import annotations

import pytest

from atlas.decision.rules import CapabilityGap
from atlas.trading.company import (
    CompanyDataService,
    ConfigSeedCompanyAdapter,
    OfficialFilingAdapter,
    profile_from_dict,
)
from atlas.workers.base import TickContext
from atlas.workers.company_intelligence import CompanyIntelligenceWorker


_RELIANCE = {
    "symbol": "RELIANCE.NS",
    "name": "Reliance Industries",
    "sector": "Energy",
    "exchange": "NSE",
    "facts": [
        "Reliance Industries owns refining and petrochemicals businesses.",
        "Reliance Industries is a major Indian conglomerate.",
    ],
    "filings": [
        {"title": "Annual Report FY24", "kind": "annual", "as_of": "2024-03-31"},
    ],
    "ratios": {"pe": 25.0},
}


def test_profile_knowledge_text():
    profile = profile_from_dict(_RELIANCE)
    text = profile.knowledge_text()
    assert "Reliance Industries" in text
    assert "Energy" in text
    assert "Annual Report" in text


def test_config_seed_adapter():
    adapter = ConfigSeedCompanyAdapter([_RELIANCE])
    profile = adapter.fetch_company("reliance.ns")
    assert profile.name == "Reliance Industries"
    with pytest.raises(CapabilityGap):
        adapter.fetch_company("UNKNOWN.NS")


def test_official_adapter_missing_key():
    adapter = OfficialFilingAdapter("sec", api_key_env="ATLAS_TEST_SEC_NONE")
    with pytest.raises(CapabilityGap) as exc:
        adapter.fetch_company("AAPL")
    assert "ATLAS_TEST_SEC_NONE" in exc.value.detail


def test_company_data_service_fetch():
    svc = CompanyDataService()
    out = svc.fetch("RELIANCE.NS", companies=[_RELIANCE])
    assert out["provider"] == "config_seed"
    assert "refining" in out["knowledge_text"].lower()
    names = {p["name"] for p in svc.list_providers()}
    assert "sec" in names and "nse" in names


def test_company_intelligence_worker_emits():
    emitted: list[dict] = []

    class _Candidates:
        def emit(self, payload):
            emitted.append(payload)
            return {"id": str(len(emitted))}

        def consume_pending(self, *, limit=100):
            return []

    worker = CompanyIntelligenceWorker(
        company_data=CompanyDataService(),
        candidates=_Candidates(),
    )
    result = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={"companies": [_RELIANCE], "tickers": ["RELIANCE.NS"]},
            config_version=1,
            state={},
        )
    )
    assert result.state["last_emitted"] > 0
    assert any(p.get("claim_type") == "entity" for p in emitted)
    assert "RELIANCE" in result.note
    # Unchanged on second tick
    result2 = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={"companies": [_RELIANCE], "tickers": ["RELIANCE.NS"]},
            config_version=1,
            state=result.state,
        )
    )
    assert "unchanged" in result2.note
