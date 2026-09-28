"""Decision Evidence Completeness Engine — data contract per lab."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.evidence_completeness import (
    ST_AVAILABLE,
    ST_MISSING,
    apply_completeness_to_uncertainty,
    build_candidate_evidence_packet,
    decision_data_contract,
    evaluate_evidence_completeness,
    format_why_not_evaluable,
    lab_completeness_rollup,
    persist_completeness,
)
from atlas.investment.uncertainty_queue import list_tasks


def test_swing_contract_from_lab_kind():
    c = decision_data_contract("india_equity_learner")
    assert c["lab_kind"] == "swing"
    assert "fcf" in c["required_keys"]
    assert "mos" in c["required_keys"]
    assert "live_ltp" not in c["required_keys"]


def test_intraday_contract_live_required():
    c = decision_data_contract("equity_intraday_learner")
    assert c["lab_kind"] == "intraday"
    assert "live_ltp" in c["required_keys"]
    assert "bars_intraday" in c["required_keys"]
    assert "fcf" not in c["required_keys"]


def test_welcorp_swing_not_evaluable_without_mos(tmp_path: Path):
    doc = evaluate_evidence_completeness(
        symbol="WELCORP.NS",
        laboratory_id="india_equity_learner",
        awareness={
            "thesis": {"stance": "WATCH"},
            "valuation": {"pe": 14.2},
            "brief": {"business": "Steel pipes"},
            "identity": {"identity": "NAMED"},
            "fundamentals": {"fcf": 2.4, "roe": 18.0, "debt_to_equity": 0.3},
        },
        market={"ltp": 812.5, "provider": "yahoo"},
    )
    assert doc["decision"] == "NOT_EVALUABLE"
    assert doc["decision_evaluable"] is False
    assert "mos" in doc["required_missing"]
    assert "mos" in doc["material_missing"]
    assert "fcf_missing" not in doc["acquisition_codes"]
    assert "mos_unknown" in doc["acquisition_codes"]
    why = format_why_not_evaluable(doc)
    assert "NOT_EVALUABLE" in why
    assert "mos" in why

    persist_completeness(tmp_path, doc)
    uq = apply_completeness_to_uncertainty(tmp_path, doc)
    assert uq["ok"] is True
    tasks = list_tasks(tmp_path, "india_equity_learner")
    assert any(t["unknown"] == "mos_unknown" for t in tasks)

    roll = lab_completeness_rollup(tmp_path, "india_equity_learner", as_of_ist=doc["as_of_ist"])
    assert roll["n"] == 1
    assert roll["not_evaluable_n"] == 1
    assert roll["avg_usable_evidence_pct"] is not None


def test_swing_complete_when_required_present():
    doc = evaluate_evidence_completeness(
        symbol="WELCORP.NS",
        laboratory_id="india_equity_learner",
        awareness={
            "thesis": {"stance": "OWN"},
            "valuation": {"pe": 14.2, "margin_of_safety_pct": 12.0},
            "brief": {"business": "Steel pipes"},
            "identity": {"identity": "NAMED"},
            "fundamentals": {"fcf": 2.4, "roe": 18.0, "debt_to_equity": 0.3},
        },
        market={"ltp": 812.5, "provider": "screener"},
    )
    assert doc["decision"] == "EVALUABLE"
    assert doc["decision_evaluable"] is True
    assert doc["required_missing"] == []
    assert "EVALUABLE" in format_why_not_evaluable(doc)


def test_intraday_missing_ltp_not_evaluable():
    doc = evaluate_evidence_completeness(
        symbol="CYIENT.NS",
        laboratory_id="equity_intraday_learner",
        market={"bars_ok": True, "technical": {"label": "up"}, "session": True},
    )
    assert doc["decision"] == "NOT_EVALUABLE"
    assert "live_ltp" in doc["required_missing"]


def test_intraday_complete_with_zerodha_plane():
    doc = evaluate_evidence_completeness(
        symbol="CYIENT.NS",
        laboratory_id="equity_intraday_learner",
        market={
            "ltp": 1850.0,
            "provider": "zerodha",
            "bars_ok": True,
            "technical": {"label": "up"},
            "session": True,
            "liquidity": "ok",
        },
    )
    assert doc["decision"] == "EVALUABLE"
    assert doc["market_data_plane"] == "zerodha_authoritative_market"


def test_fno_cash_equity_invalid():
    doc = evaluate_evidence_completeness(
        symbol="RELIANCE.NS",
        laboratory_id="india_fno_learner",
        market={
            "ltp": 1400.0,
            "provider": "zerodha",
            "bars_ok": True,
            "session": True,
            "instrument": {"asset_class": "equity"},
        },
    )
    assert doc["decision"] == "NOT_EVALUABLE"
    assert "cash_equity_excluded" in doc["invalid"] or "underlying" in doc["missing"]


def test_candidate_evidence_packet_shape():
    pkt = build_candidate_evidence_packet(
        symbol="WELCORP.NS",
        laboratory_id="india_equity_learner",
        awareness={"thesis": {"stance": "WATCH"}, "valuation": {"pe": 10}},
        market={"ltp": 100},
    )
    assert pkt["kind"] == "CANDIDATE_EVIDENCE_PACKET"
    assert "completeness" in pkt
    assert pkt["completeness"]["decision"] == "NOT_EVALUABLE"
    assert "why_not_evaluable" in pkt


def test_hydrate_from_fund_store_and_bars_does_not_invent_pe(tmp_path: Path):
    """Call sites that omit fundamentals= must still see durable store truth.

    Zerodha ≠ PE. Price from bars + ROE from fund store; PE/FCF/MoS stay missing.
    """
    from atlas.investment.bar_store import persist_symbol_bars
    from atlas.investment.fundamentals import upsert_rows

    upsert_rows(
        tmp_path,
        [
            {
                "symbol": "WELCORP.NS",
                "roe": 18.5,
                "debt_to_equity": 0.4,
                "sector": "Steel pipes",
                "source": "universe_seed",
            }
        ],
        program_id="market_intelligence",
        merge_screener=False,
    )
    persist_symbol_bars(
        tmp_path,
        "WELCORP.NS",
        [{"date": "2026-09-02", "open": 2500, "high": 2550, "low": 2480, "close": 2523.5, "volume": 1}],
        provider="test",
    )
    doc = evaluate_evidence_completeness(
        symbol="WELCORP.NS",
        laboratory_id="india_equity_learner",
        awareness={
            "thesis": {"stance": "WATCH"},
            "brief": {"business": "Steel pipes"},
            "identity": {"identity": "NAMED"},
        },
        market={},  # flat book — no LTP
        data_dir=tmp_path,
        program_id="market_intelligence",
    )
    assert "price_history" not in doc["required_missing"]
    assert "roe" not in doc["material_missing"]
    assert "debt" not in doc["material_missing"]
    # Still honestly incomplete without PE/FCF/MoS
    assert "pe" in doc["required_missing"]
    assert "fcf" in doc["required_missing"]
    assert "mos" in doc["required_missing"]
    assert doc["decision"] == "NOT_EVALUABLE"


def test_hydrate_does_not_override_explicit_fundamentals(tmp_path: Path):
    from atlas.investment.fundamentals import upsert_rows

    upsert_rows(
        tmp_path,
        [{"symbol": "AAA.NS", "pe": 99.0, "roe": 5.0}],
        program_id="market_intelligence",
        merge_screener=False,
    )
    doc = evaluate_evidence_completeness(
        symbol="AAA.NS",
        laboratory_id="india_equity_learner",
        awareness={
            "thesis": {"stance": "OWN"},
            "valuation": {"pe": 14.0, "margin_of_safety_pct": 20.0},
            "brief": {"business": "Widgets"},
            "identity": {"identity": "NAMED"},
        },
        market={"ltp": 100.0},
        fundamentals={"pe": 14.0, "fcf": 1.0, "roe": 20.0, "debt_to_equity": 0.2},
        data_dir=tmp_path,
    )
    pe_item = next(x for x in doc["items"] if x["key"] == "pe")
    assert pe_item["value"] == 14.0
    assert doc["decision"] == "EVALUABLE"


def test_item_statuses_not_null_alone():
    doc = evaluate_evidence_completeness(
        symbol="EICHERMOT.NS",
        laboratory_id="india_equity_learner",
        awareness={"fundamentals": {"fcf": None}, "valuation": {}},
        market={},
    )
    fcf = next(x for x in doc["items"] if x["key"] == "fcf")
    assert fcf["status"] == ST_MISSING
    assert fcf["required"] is True
    assert fcf["material"] is True
    price = next(x for x in doc["items"] if x["key"] == "price_history")
    assert price["status"] == ST_MISSING
