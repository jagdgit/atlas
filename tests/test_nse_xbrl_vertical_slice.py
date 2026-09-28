"""TRADE-LOOP0 NSE/XBRL vertical slice — connect UQ/FEA → calc → PLC.A."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.fundamental_evidence import acquire_for_symbol, plan_symbol_acquisition
from atlas.investment.fundamentals import get_symbol
from atlas.investment.nse_xbrl.as_of import fact_usable_as_of
from atlas.investment.nse_xbrl.calculations import calculate_metrics, normalize_capex
from atlas.investment.nse_xbrl.coverage import SLICE_FIELDS, fundamentals_coverage
from atlas.investment.nse_xbrl.filing_selection import select_canonical_filing
from atlas.investment.nse_xbrl.parser import parse_xbrl
from atlas.investment.nse_xbrl.replay import replay_hblpower_candidate
from atlas.investment.plc_buy_gates import evaluate_fundamental_sanity, sector_from_sources
from atlas.investment.reports import format_hourly_activity_report

FIXTURE = Path(__file__).parent / "fixtures" / "nse_xbrl" / "hblpower_consolidated.xml"
QONLY = Path(__file__).parent / "fixtures" / "nse_xbrl" / "quarterly_pat_only.xml"
LIAB = Path(__file__).parent / "fixtures" / "nse_xbrl" / "liabilities_not_debt.xml"
BAD = Path(__file__).parent / "fixtures" / "nse_xbrl" / "bad_non_numeric.xml"


def _xml(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_policy_nse_is_primary_network():
    from atlas.investment.fundamental_evidence import source_policy_table

    pe = source_policy_table()["metrics"]["pe"]
    nets = [s["provider"] for s in pe if s["mode"] == "network"]
    assert nets[0] == "nse_xbrl"
    assert "yahoo_fundamentals" not in nets
    seconds = [s["provider"] for s in pe if s["mode"] == "secondary"]
    assert "yahoo_fundamentals" in seconds
    assert all(s.get("provider") != "zerodha" for s in pe)


def test_parse_hblpower_fixture_calculates_all_ratios():
    parsed = parse_xbrl(_xml(FIXTURE), symbol="HBLPOWER", available_at="2026-05-15")
    assert parsed["ok"] is True
    calc = calculate_metrics(parsed["facts"], price=500.0, evidence_as_of="2026-09-18")
    pe = calc["metrics"]["pe"]
    assert pe["status"] == "VALID"
    assert pe["eps_basis"] == "TTM"
    assert abs(pe["value"] - 50.0) < 1e-6
    roe = calc["metrics"]["roe"]
    assert roe["status"] == "VALID"
    assert "beginning_equity" in roe["inputs"]
    de = calc["metrics"]["debt_to_equity"]
    assert de["status"] == "VALID"
    assert de["definition_id"] == "atlas.debt.total_borrowings.v1"
    assert abs(de["value"] - (300_000_000 / 2_200_000_000)) < 1e-9
    assert de["inputs"]["total_liabilities"] != de["inputs"]["total_debt"]
    fcf = calc["metrics"]["fcf"]
    assert fcf["status"] == "VALID"
    assert fcf["value"] < 0
    assert abs(fcf["value"] - (3204.28 - 3713.9)) < 1e-6


def test_pe_rejects_single_quarter_as_annual():
    parsed = parse_xbrl(_xml(QONLY), symbol="QONLY")
    calc = calculate_metrics(parsed["facts"], price=500.0, eps_fy_fallback=False)
    assert calc["metrics"]["pe"]["status"] == "UNKNOWN"
    assert "eps_quarterly_as_annual_rejected" in calc["unknown"] or calc["metrics"]["eps"]["status"] == "UNKNOWN"


def test_liabilities_are_not_debt():
    parsed = parse_xbrl(_xml(LIAB), symbol="LIABCO")
    calc = calculate_metrics(parsed["facts"])
    assert calc["metrics"]["debt_to_equity"]["status"] == "UNKNOWN"
    assert calc["metrics"]["debt_to_equity"]["reason"] == "total_liabilities_is_not_total_debt"


def test_malformed_xbrl_is_retry_not_zero():
    parsed = parse_xbrl("<<<<<<< not xml", symbol="HBLPOWER")
    assert parsed["ok"] is False
    assert parsed["status"] == "RETRY"
    assert parsed["facts"] == []
    parsed2 = parse_xbrl(_xml(BAD), symbol="BADCO")
    calc = calculate_metrics(parsed2.get("facts") or [])
    assert calc["metrics"]["pe"]["status"] == "UNKNOWN"


def test_look_ahead_excluded():
    fact = {
        "canonical_field": "NET_INCOME",
        "value": 1,
        "available_at": "2026-12-01",
    }
    chk = fact_usable_as_of(fact, evidence_as_of="2026-09-18")
    assert chk["ok"] is False
    assert chk["reason"] == "look_ahead"


def test_capex_normalize_then_one_formula():
    n = normalize_capex(-3713.9)
    assert n["capex_normalized"] == 3713.9
    assert n["normalization"] == "NEGATIVE_OUTFLOW_TO_POSITIVE"
    assert 3204.28 - n["capex_normalized"] < 0


def test_filing_selection_rejects_superseded_and_future():
    filings = [
        {
            "period_end": "2026-03-31",
            "scope": "CONSOLIDATED",
            "superseded": True,
            "available_at": "2026-05-01",
        },
        {
            "period_end": "2026-03-31",
            "scope": "CONSOLIDATED",
            "revision_n": 2,
            "available_at": "2026-05-15",
            "audited": "audited",
        },
        {
            "period_end": "2026-03-31",
            "scope": "CONSOLIDATED",
            "available_at": "2026-12-01",
            "revision_n": 9,
        },
    ]
    sel = select_canonical_filing(filings, evidence_as_of="2026-09-18")
    assert sel["ok"] is True
    assert sel["canonical"]["revision_n"] == 2
    reasons = {r["reject_reason"] for r in sel["rejected"]}
    assert "superseded" in reasons
    assert "available_after_evidence_as_of" in reasons


def test_fea_nse_hblpower_fills_plc_a_fields(tmp_path: Path):
    xml = _xml(FIXTURE)
    out = acquire_for_symbol(
        tmp_path,
        "HBLPOWER",
        laboratory_id="india_equity_learner",
        required_fields=list(SLICE_FIELDS),
        enabled=False,
        push_to_ira=False,
        nse_xml_text=xml,
        nse_price=500.0,
        evidence_as_of="2026-09-18",
        nse_available_at="2026-05-15",
    )
    fields = {a["field"] for a in out.get("acquired") or []}
    for need in SLICE_FIELDS:
        assert need in fields, need
    row = get_symbol(tmp_path, "HBLPOWER") or {}
    sector = sector_from_sources(fundamentals=row)
    plc = evaluate_fundamental_sanity(row, sector=sector)
    assert plc["ok"] is True, plc
    cov = fundamentals_coverage(
        fundamentals=row,
        identity={"sector_ok": True, "identity_ok": True, "sector": sector, "name": "HBL Power"},
    )
    assert cov["plc_a_complete"] is True
    assert cov["complete"] is True


def test_replay_is_not_a_fill(tmp_path: Path):
    result = replay_hblpower_candidate(
        tmp_path,
        xml_text=_xml(FIXTURE),
        price=500.0,
        evidence_as_of="2026-09-18",
    )
    assert result["not_a_fill"] is True
    assert result["isolated"] is True
    assert result["plc_a_before"]["ok"] is False
    assert "pe" in (result["plc_a_before"].get("missing") or [])
    assert result["plc_a_after"]["ok"] is True
    assert result["reevaluated"] is True
    assert result["before"]["plc_a"] == "INCOMPLETE"
    assert result["after"]["plc_a"] == "COMPLETE"
    ledger = tmp_path / "investment" / "paper"
    assert not ledger.exists() or not any(ledger.rglob("*fill*"))


def test_replay_does_not_use_live_complete_as_before(tmp_path: Path):
    from atlas.investment.fundamentals import upsert_rows

    upsert_rows(
        tmp_path,
        [
            {
                "symbol": "HBLPOWER",
                "pe": 25.86,
                "roe": 44.0,
                "debt_to_equity": 0.02,
                "fcf": 1.0,
                "sector": "Capital Goods",
                "name": "HBL Power",
            }
        ],
        source="nse_xbrl",
    )
    result = replay_hblpower_candidate(
        tmp_path,
        xml_text=_xml(FIXTURE),
        price=500.0,
    )
    assert result["plc_a_before"]["ok"] is False
    live = get_symbol(tmp_path, "HBLPOWER") or {}
    assert live.get("pe") == 25.86
    sandbox = tmp_path / "investment" / "trade_loop0" / "replay" / "sandbox"
    sand = get_symbol(sandbox, "HBLPOWER") or {}
    assert sand.get("pe") is not None
    assert sand.get("pe") != live.get("pe")


def test_replay_loads_stored_raw_xbrl(tmp_path: Path):
    from atlas.investment.nse_xbrl.raw_store import store_raw

    store_raw(
        tmp_path,
        symbol="HBLPOWER.NS",
        xml_text=_xml(FIXTURE),
        meta={"canonical": True, "role": "canonical", "available_at": "2026-05-15"},
    )
    result = replay_hblpower_candidate(tmp_path, xml_text=None, price=500.0)
    assert result["stored_raw_n"] == 1
    assert result["plc_a_after"]["ok"] is True
    assert result["reevaluated"] is True


def test_hourly_block_always_present(tmp_path: Path):
    subject, body = format_hourly_activity_report(
        portfolio={"data_dir": str(tmp_path)},
        laboratory_id="india_equity_learner",
        hour=8,
        ist_date="2026-09-19",
    )
    assert "FUNDAMENTAL INTELLIGENCE" in body
    assert "NSE XBRL success" in body
    assert "HBLPOWER" in body
    assert "queue depth" in body
    assert "Yahoo suppressed" in body


def test_yahoo_cooldown_still_allows_nse(tmp_path: Path, monkeypatch):
    from atlas.investment import yahoo_fundamentals as yf

    class _Gate:
        def status(self):
            return {"ready": False, "cooldown_remaining_s": 400.0, "consecutive_blocks": 3}

    monkeypatch.setattr(yf, "get_yahoo_rate_gate", lambda _d: _Gate())
    out = acquire_for_symbol(
        tmp_path,
        "HBLPOWER",
        enabled=True,
        push_to_ira=False,
        nse_xml_text=_xml(FIXTURE),
        nse_price=500.0,
        nse_available_at="2026-05-15",
        evidence_as_of="2026-09-18",
    )
    fields = {a["field"] for a in out.get("acquired") or []}
    assert "pe" in fields
    assert out["reason"] == "complete"


LIVE_FY26 = Path(__file__).parent / "fixtures" / "nse_xbrl" / "ifindas_fy26.xml"
LIVE_FY25 = Path(__file__).parent / "fixtures" / "nse_xbrl" / "ifindas_fy25.xml"


def test_live_taxonomy_does_not_treat_quarterly_eps_as_annual():
    parsed = parse_xbrl(_xml(LIVE_FY26), symbol="HBLPOWER", available_at="2026-05-24")
    assert parsed["ok"] is True
    names = {f["mapping_id"] for f in parsed["facts"]}
    assert "ProfitLossForPeriod" in names
    assert "DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations" in names
    calc = calculate_metrics(parsed["facts"], price=500.0, evidence_as_of="2026-09-18")
    pe = calc["metrics"]["pe"]
    assert pe["status"] == "VALID"
    assert pe["eps_basis"] == "FY"
    assert abs(pe["value"] - 50.0) < 1e-6
    assert calc["metrics"]["roe"]["status"] == "UNKNOWN"
    de = calc["metrics"]["debt_to_equity"]
    assert de["status"] == "VALID"
    assert abs(de["value"] - (300_000_000 / 2_200_000_000)) < 1e-9
    fcf = calc["metrics"]["fcf"]
    assert fcf["status"] == "VALID"
    assert abs(fcf["value"] - (3204.28 - 3713.9)) < 1e-6


def test_prior_year_equity_completes_roe():
    fy26 = parse_xbrl(_xml(LIVE_FY26), symbol="HBLPOWER", available_at="2026-05-24")
    fy25 = parse_xbrl(_xml(LIVE_FY25), symbol="HBLPOWER", available_at="2025-05-25")
    facts = list(fy26["facts"]) + list(fy25["facts"])
    calc = calculate_metrics(facts, price=500.0, evidence_as_of="2026-09-18")
    roe = calc["metrics"]["roe"]
    assert roe["status"] == "VALID"
    assert abs(roe["inputs"]["beginning_equity"] - 2_000_000_000) < 1e-6
    assert abs(roe["inputs"]["ending_equity"] - 2_200_000_000) < 1e-6
    assert calc["metrics"]["pe"]["eps_basis"] == "FY"
    assert abs(calc["metrics"]["pe"]["value"] - 50.0) < 1e-6


def test_fetch_uses_listed_nse_ticker_and_integrated_filings():
    from atlas.investment.nse_xbrl.identity import resolve_nse_code
    from atlas.investment.nse_xbrl.provider import acquire_from_nse, fetch_nse_xbrl

    assert resolve_nse_code("HBLPOWER") == "HBLENGINE"
    calls: list[str] = []

    def opener(url: str):
        calls.append(url)
        if "integrated-filing-results" in url:
            assert "HBLENGINE" in url
            assert "HBLPOWER" not in url
            body = {
                "data": [
                    {
                        "symbol": "HBLENGINE",
                        "consolidated": "Consolidated",
                        "audited": "Un-Audited",
                        "qe_Date": "30-JUN-2026",
                        "broadcast_Date": "08-Aug-2026 16:24:17",
                        "type": "Integrated Filing- Financials",
                        "xbrl": "https://nsearchives.example/q1.xml",
                    },
                    {
                        "symbol": "HBLENGINE",
                        "consolidated": "Consolidated",
                        "audited": "Audited",
                        "qe_Date": "31-MAR-2026",
                        "broadcast_Date": "24-May-2026 14:12:53",
                        "type": "Integrated Filing- Financials",
                        "xbrl": "https://nsearchives.example/fy26.xml",
                    },
                    {
                        "symbol": "HBLENGINE",
                        "consolidated": "Consolidated",
                        "audited": "Audited",
                        "qe_Date": "31-MAR-2025",
                        "broadcast_Date": "25-May-2025 11:41:54",
                        "type": "Integrated Filing- Financials",
                        "xbrl": "https://nsearchives.example/fy25.xml",
                    },
                    {
                        "symbol": "HBLENGINE",
                        "type": "Integrated Filing- Governance",
                        "xbrl": "https://nsearchives.example/gov.xml",
                    },
                ]
            }
            return 200, __import__("json").dumps(body).encode("utf-8")
        if url.endswith("fy26.xml"):
            return 200, _xml(LIVE_FY26).encode("utf-8")
        if url.endswith("fy25.xml"):
            return 200, _xml(LIVE_FY25).encode("utf-8")
        if "corporates-financial-results" in url:
            return 200, b'{"data":[]}'
        raise AssertionError(f"unexpected url {url}")

    fetched = fetch_nse_xbrl("HBLPOWER", opener=opener)
    assert fetched["ok"] is True
    assert fetched["nse_code"] == "HBLENGINE"
    urls = {d["url"] for d in fetched["documents"]}
    assert "https://nsearchives.example/fy26.xml" in urls
    assert "https://nsearchives.example/fy25.xml" in urls
    assert "https://nsearchives.example/q1.xml" not in urls
    assert "https://nsearchives.example/gov.xml" not in urls

    out = acquire_from_nse(
        None,
        "HBLPOWER",
        price=500.0,
        xml_text=None,
        opener=opener,
        push_store=False,
        evidence_as_of="2026-09-18",
    )
    fields = {a["field"] for a in out.get("acquired") or []}
    assert {"pe", "roe", "debt_to_equity", "fcf"} <= fields
    assert any("integrated-filing-results" in u for u in calls)


TATACHEM_SCOPE = Path(__file__).parent / "fixtures" / "nse_xbrl" / "tatachem_scope.xml"


def test_shareholder_roe_uses_attributable_pat_not_group_pat():
    parsed = parse_xbrl(_xml(TATACHEM_SCOPE), symbol="TATACHEM", available_at="2026-05-04")
    calc = calculate_metrics(parsed["facts"], price=689.0, evidence_as_of="2026-09-18")
    assert calc["metrics"]["pe"]["status"] == "UNKNOWN"
    assert calc["metrics"]["pe"]["reason"] == "non_positive_eps"
    roe = calc["metrics"]["roe"]
    assert roe["status"] == "VALID"
    assert roe["inputs"]["scope"] == "owners_of_parent"
    assert abs(roe["inputs"]["net_income"] - (-18_960_000_000)) < 1e-6
    assert abs(roe["value"] - ((-18_960_000_000 / 214_000_000_000) * 100.0)) < 1e-6
    de = calc["metrics"]["debt_to_equity"]
    assert de["status"] == "VALID"
    assert de["definition_id"] == "atlas.debt.total_borrowings.v1"
    assert de["inputs"]["mapping"] == "ifindas_borrowings_minus_leases"
    assert abs(de["value"] - (71_140_000_000 / 212_060_000_000)) < 1e-9
    fcf = calc["metrics"]["fcf"]
    assert abs(fcf["value"] - 640_000_000) < 1e-6


def test_roe_unknown_when_group_pat_mixed_with_parent_equity():
    parsed = parse_xbrl(_xml(TATACHEM_SCOPE), symbol="TATACHEM", available_at="2026-05-04")
    facts = [
        f
        for f in parsed["facts"]
        if f.get("canonical_field") != "NET_INCOME_OWNERS"
    ]
    calc = calculate_metrics(facts, price=689.0, evidence_as_of="2026-09-18")
    assert calc["metrics"]["roe"]["status"] == "UNKNOWN"
    assert calc["metrics"]["roe"]["reason"] == "scope_mismatch"
    assert any(c.get("conflict_type") == "SCOPE" for c in calc.get("conflicts") or [])


def test_ifindas_borrowings_without_lease_facts_emits_debt_definition():
    parsed = parse_xbrl(_xml(TATACHEM_SCOPE), symbol="TATACHEM", available_at="2026-05-04")
    facts = [
        f
        for f in parsed["facts"]
        if f.get("canonical_field") != "LEASE_LIABILITIES"
    ]
    calc = calculate_metrics(facts, price=689.0, evidence_as_of="2026-09-18")
    de = calc["metrics"]["debt_to_equity"]
    assert de["status"] == "VALID"
    assert de["inputs"]["leases_separable"] is False
    assert abs(de["value"] - (80_010_000_000 / 212_060_000_000)) < 1e-9
    assert any(c.get("conflict_type") == "DEBT_DEFINITION" for c in calc.get("conflicts") or [])


def test_debt_definition_conflict_persists_in_store(tmp_path: Path):
    from atlas.investment.fundamentals import get_symbol
    from atlas.investment.nse_xbrl.provider import acquire_from_nse

    out = acquire_from_nse(
        tmp_path,
        "HBLPOWER",
        xml_text=_xml(LIVE_FY26),
        price=500.0,
        evidence_as_of="2026-09-18",
        available_at="2026-05-24",
        push_store=True,
    )
    assert any(c.get("conflict_type") == "DEBT_DEFINITION" for c in out.get("conflicts") or [])
    row = get_symbol(tmp_path, "HBLPOWER") or {}
    stored = row.get("evidence_conflicts") or []
    assert any(
        (isinstance(c, dict) and c.get("conflict_type") == "DEBT_DEFINITION")
        or c == "DEBT_DEFINITION"
        for c in stored
    )
    acquire_from_nse(
        tmp_path,
        "HBLPOWER",
        xml_text=_xml(LIVE_FY26),
        price=500.0,
        evidence_as_of="2026-09-18",
        available_at="2026-05-24",
        push_store=True,
    )
    stored2 = (get_symbol(tmp_path, "HBLPOWER") or {}).get("evidence_conflicts") or []
    n_debt = sum(
        1
        for c in stored2
        if (isinstance(c, dict) and c.get("conflict_type") == "DEBT_DEFINITION")
        or c == "DEBT_DEFINITION"
    )
    assert n_debt == 1


def test_filing_selection_prefers_fy_over_later_quarter():
    filings = [
        {
            "period_end": "2026-06-30",
            "scope": "CONSOLIDATED",
            "audited": "Un-Audited",
            "available_at": "2026-08-08",
            "xbrl_url": "https://nsearchives.example/q1.xml",
        },
        {
            "period_end": "2026-03-31",
            "scope": "CONSOLIDATED",
            "audited": "Audited",
            "available_at": "2026-05-24",
            "xbrl_url": "https://nsearchives.example/fy26.xml",
        },
    ]
    sel = select_canonical_filing(filings, prefer_audited=True)
    assert sel["ok"] is True
    assert sel["canonical"]["period_end"] == "2026-03-31"


def test_stale_owners_pat_does_not_become_this_year_roe():
    fy26 = parse_xbrl(_xml(LIVE_FY26), symbol="HBLPOWER", available_at="2026-05-24")
    fy25 = parse_xbrl(_xml(LIVE_FY25), symbol="HBLPOWER", available_at="2025-05-25")
    facts = list(fy26["facts"]) + list(fy25["facts"])
    facts.append(
        {
            "canonical_field": "NET_INCOME_OWNERS",
            "mapping_id": "ProfitOrLossAttributableToOwnersOfParent",
            "value": 100_000_000.0,
            "period_end": "2025-03-31",
            "period_type": "FY",
            "scope": "CONSOLIDATED",
            "available_at": "2025-05-25",
        }
    )
    calc = calculate_metrics(facts, price=500.0, evidence_as_of="2026-09-18")
    roe = calc["metrics"]["roe"]
    assert roe["status"] == "VALID"
    assert str(roe["inputs"]["numerator_period"]) == "2026-03-31"
    assert abs(roe["inputs"]["net_income"] - 1_000_000_000.0) < 1e-6
    avg = (2_000_000_000.0 + 2_200_000_000.0) / 2.0
    assert abs(roe["value"] - ((1_000_000_000.0 / avg) * 100.0)) < 1e-6


def test_zero_borrowings_skips_debt_definition_noise():
    parsed = parse_xbrl(_xml(LIVE_FY26), symbol="HBLPOWER", available_at="2026-05-24")
    facts = []
    for f in parsed["facts"]:
        mid = str(f.get("mapping_id") or "")
        if mid in {"BorrowingsCurrent", "BorrowingsNoncurrent"}:
            facts.append({**f, "value": 0.0})
        else:
            facts.append(f)
    calc = calculate_metrics(facts, price=500.0, evidence_as_of="2026-09-18")
    de = calc["metrics"]["debt_to_equity"]
    assert de["status"] == "VALID"
    assert de["value"] == 0.0
    assert not any(c.get("conflict_type") == "DEBT_DEFINITION" for c in calc.get("conflicts") or [])


def test_fetch_annual_api_when_integrated_is_quarter_only():
    from atlas.investment.nse_xbrl.provider import fetch_nse_xbrl

    calls: list[str] = []

    def opener(url: str):
        calls.append(url)
        if "integrated-filing-results" in url:
            body = {
                "data": [
                    {
                        "symbol": "ADANIPORTS",
                        "consolidated": "Consolidated",
                        "audited": "Un-Audited",
                        "qe_Date": "30-JUN-2026",
                        "broadcast_Date": "29-Jul-2026",
                        "type": "Integrated Filing- Financials",
                        "xbrl": "https://nsearchives.example/q1.xml",
                    }
                ]
            }
            return 200, __import__("json").dumps(body).encode("utf-8")
        if "period=Annual" in url:
            body = {
                "data": [
                    {
                        "symbol": "ADANIPORTS",
                        "consolidated": "Consolidated",
                        "audited": "Audited",
                        "toDate": "31-MAR-2026",
                        "fromDate": "01-APR-2025",
                        "broadcast_Date": "06-May-2026",
                        "type": "Financial Results",
                        "xbrl": "https://nsearchives.example/fy26.xml",
                    },
                    {
                        "symbol": "ADANIPORTS",
                        "consolidated": "Consolidated",
                        "audited": "Audited",
                        "toDate": "31-MAR-2025",
                        "fromDate": "01-APR-2024",
                        "broadcast_Date": "07-May-2025",
                        "type": "Financial Results",
                        "xbrl": "https://nsearchives.example/fy25.xml",
                    },
                ]
            }
            return 200, __import__("json").dumps(body).encode("utf-8")
        if "period=Quarterly" in url:
            return 200, b'{"data":[]}'
        if url.endswith("fy26.xml"):
            return 200, _xml(LIVE_FY26).encode("utf-8")
        if url.endswith("fy25.xml"):
            return 200, _xml(LIVE_FY25).encode("utf-8")
        raise AssertionError(f"unexpected url {url}")

    fetched = fetch_nse_xbrl("ADANIPORTS", opener=opener)
    assert fetched["ok"] is True
    urls = {d["url"] for d in fetched["documents"]}
    assert "https://nsearchives.example/fy26.xml" in urls
    assert "https://nsearchives.example/fy25.xml" in urls
    assert "https://nsearchives.example/q1.xml" not in urls
    assert any("period=Annual" in u for u in calls)


def test_identity_patch_keeps_nse_source(tmp_path: Path):
    from atlas.investment.fundamental_evidence import acquire_for_symbol
    from atlas.investment.nse_xbrl.provider import acquire_from_nse

    acquire_from_nse(
        tmp_path,
        "HBLPOWER",
        xml_text=_xml(LIVE_FY26),
        price=500.0,
        evidence_as_of="2026-09-18",
        available_at="2026-05-24",
        push_store=True,
    )
    row = get_symbol(tmp_path, "HBLPOWER") or {}
    assert row.get("source") == "nse_xbrl"
    acquire_for_symbol(
        tmp_path,
        "HBLPOWER",
        nse_xml_text=_xml(LIVE_FY26),
        nse_price=500.0,
        nse_available_at="2026-05-24",
        evidence_as_of="2026-09-18",
        push_to_ira=False,
        enabled=False,
    )
    row = get_symbol(tmp_path, "HBLPOWER") or {}
    assert row.get("source") == "nse_xbrl"
    assert row.get("sector") == "Capital Goods"

