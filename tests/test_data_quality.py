"""Data quality envelope, capability recovery, and F&O pack gates."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from atlas.agent_kernel.kernel import AgentKernel
from atlas.investment.data_quality import (
    Q_BLOCKED,
    Q_CONFLICT,
    Q_INVALID,
    Q_PENDING,
    Q_STALE,
    Q_TRUSTED,
    Q_UNKNOWN,
    commit_record,
    current_capability,
    decision_may_consume,
    envelope,
    load_registry,
    note_capability_gap,
    reconcile_symbol_from_store,
)
from atlas.investment.fno_data_pack import (
    NOT_READY,
    READY,
    build_fno_data_pack,
    classify_tick_continuity,
    option_decision_permitted,
)
from atlas.investment.uncertainty_queue import list_tasks, make_acquisition_task, upsert_task

NOW = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
PERIOD = "2026-03-31"


def _pe(**overrides):
    base = dict(
        symbol="HBLPOWER.NS",
        metric="pe",
        value=25.0,
        unit="ratio",
        currency=None,
        period=PERIOD,
        period_end=PERIOD,
        period_type="FY",
        eps_basis="FY",
        as_of=PERIOD,
        price_as_of="2026-10-01",
        provider="nse_xbrl",
        source="NSE filing",
        evidence_id="ev-hbl-pe",
        components={"price": 100.0, "eps": 4.0, "eps_basis": "FY"},
        calculation_method="price_over_eps",
        now=NOW,
    )
    base.update(overrides)
    return envelope(**base)


def test_valid_fundamental_is_trusted():
    rec = _pe()
    assert rec["quality_status"] == Q_TRUSTED
    assert rec["validation_status"] == "PASSED"
    assert rec["usable"] is True
    assert decision_may_consume(rec) is True
    assert rec["value"] == 25.0


def test_invalid_fundamental_rejected():
    rec = _pe(components={"price": 100.0, "eps": 0.0, "eps_basis": "FY"}, value=25.0)
    assert rec["quality_status"] == Q_INVALID
    assert rec["usable"] is False
    assert decision_may_consume(rec) is False
    assert rec["value"] != 0


def test_stale_fundamental_not_decision_usable():
    rec = _pe(period="2020-03-31", period_end="2020-03-31", as_of="2020-03-31")
    assert rec["quality_status"] == Q_STALE
    assert rec["acquired"] is True
    assert rec["value"] == 25.0
    assert rec["usable"] is False
    assert decision_may_consume(rec) is False


def test_conflicting_providers_are_conflict(tmp_path: Path):
    first = commit_record(tmp_path, _pe(), now=NOW)
    assert first["current"]["quality_status"] == Q_TRUSTED
    other = _pe(
        provider="screener_export",
        source="screener",
        evidence_id="ev-other",
        value=40.0,
        components={"price": 160.0, "eps": 4.0, "eps_basis": "FY"},
    )
    second = commit_record(tmp_path, other, now=NOW)
    assert second["current"]["quality_status"] == Q_CONFLICT
    assert second["current"]["usable"] is False
    assert decision_may_consume(second["record"]) is False


def test_web_snippet_is_never_a_trusted_financial_value():
    rec = _pe(provider="duckduckgo", source="web_snippet", value=25.0)
    assert rec["value"] is None
    assert rec["quality_status"] == Q_BLOCKED
    assert rec["usable"] is False
    assert decision_may_consume(rec) is False


def test_old_gap_plus_new_acquisition_updates_current_only(tmp_path: Path):
    note_capability_gap(
        tmp_path,
        symbol="HBLPOWER.NS",
        metric="pe",
        reason="pe_missing",
        attempted=["local_market_store"],
        now=NOW - timedelta(days=1),
    )
    task = make_acquisition_task(
        laboratory_id="india_equity_learner",
        symbol="HBLPOWER.NS",
        unknown_code="pe_missing",
    )
    upsert_task(tmp_path, task)
    committed = commit_record(tmp_path, _pe(), now=NOW)
    current = current_capability(tmp_path, "HBLPOWER.NS", "pe")
    assert current["current_state"] == "DECISION_USABLE"
    assert current["quality_status"] == Q_TRUSTED
    assert current["acquired"] is True
    assert any(
        h.get("current_state") == "CAPABILITY_GAP" for h in current["history"]
    )
    audit = (tmp_path / "investment" / "data_quality" / "audit.jsonl").read_text()
    assert "capability_gap" in audit
    tasks = list_tasks(tmp_path, "india_equity_learner", status=None)
    row = next(t for t in tasks if t["unknown"] == "pe_missing")
    assert row["status"] == "DONE"
    assert row["history"]
    assert committed["ok"] is True


def test_historical_failure_remains_after_recovery(tmp_path: Path):
    note_capability_gap(
        tmp_path, symbol="ADANIENT.NS", metric="roe", reason="roe_missing", now=NOW
    )
    rec = envelope(
        symbol="ADANIENT.NS",
        metric="roe",
        value=0.2,
        period=PERIOD,
        period_end=PERIOD,
        period_type="FY",
        provider="nse_xbrl",
        source="NSE filing",
        evidence_id="ev-adanient-roe",
        components={"profit": 20.0, "equity": 100.0},
        now=NOW,
    )
    commit_record(tmp_path, rec, now=NOW)
    audit = (tmp_path / "investment" / "data_quality" / "audit.jsonl").read_text()
    assert "roe_missing" in audit
    current = current_capability(tmp_path, "ADANIENT.NS", "roe")
    assert current["usable"] is True
    assert current["history"][-1]["failure_reason"] == "roe_missing"


def test_kernel_retries_blocked_task_after_capability_recovery(tmp_path: Path):
    commit_record(tmp_path, _pe(), now=NOW)
    kernel = AgentKernel(tmp_path, laboratory_id="india_equity_learner")
    kernel.state["tasks"]["AK-pe"] = {
        "id": "AK-pe",
        "status": "CAPABILITY_GAP",
        "symbol": "HBLPOWER.NS",
        "objective": "Acquire evidence for pe on HBLPOWER.NS",
        "required": ["pe"],
        "missing_requirement": "pe",
        "domain": "investment",
        "priority_class": "P1",
        "score": 1,
        "evidence": {},
        "attempted_capabilities": ["local_market_store"],
        "failed": [],
        "plan": None,
        "constraints": {},
        "lineage": {},
        "deterministic_only": False,
        "interpretive": False,
    }
    kernel.cycle(mode="tick", max_investigations=1, allow_external=False, observations=[])
    task = kernel.task("AK-pe")
    assert task is not None
    assert task["status"] != "CAPABILITY_GAP"


def test_xbrl_calculation_releases_kernel_gap_only_when_trusted(tmp_path: Path):
    from atlas.investment.data_quality import release_blocked_kernel_tasks
    from atlas.investment.nse_xbrl.calculations import calculate_metrics
    from atlas.investment.nse_xbrl.parser import parse_xbrl
    from atlas.investment.nse_xbrl.provider import commit_stored_xbrl
    from atlas.investment.nse_xbrl.raw_store import store_raw

    xml = (
        Path(__file__).parent / "fixtures" / "nse_xbrl" / "hblpower_consolidated.xml"
    ).read_text(encoding="utf-8")
    stored = store_raw(
        tmp_path,
        symbol="HBLPOWER.NS",
        xml_text=xml,
        meta={
            "canonical": True,
            "available_at": "2026-05-15",
            "period_end": "2026-03-31",
            "scope": "CONSOLIDATED",
        },
    )
    parsed = parse_xbrl(xml, symbol="HBLPOWER.NS", available_at="2026-05-15")
    calc = calculate_metrics(parsed["facts"], evidence_as_of="2026-09-18")
    state = {
        "tasks": {
            "AK-pe": {
                "id": "AK-pe",
                "status": "BLOCKED",
                "symbol": "HBLPOWER.NS",
                "required": ["pe"],
                "missing_requirement": None,
                "status_history": [{"status": "CAPABILITY_GAP"}],
            },
            "AK-fcf": {
                "id": "AK-fcf",
                "status": "CAPABILITY_GAP",
                "symbol": "HBLPOWER.NS",
                "required": ["fcf"],
                "missing_requirement": "fcf",
            },
        }
    }
    first = commit_stored_xbrl(
        tmp_path,
        "HBLPOWER.NS",
        evidence_as_of="2026-09-18",
        now=NOW,
    )
    by_metric = {row["metric"]: row for row in first["metrics"]}
    assert by_metric["pe"]["quality_status"] == Q_UNKNOWN
    assert by_metric["pe"]["value"] is None
    assert by_metric["pe"]["reason"] == "price_or_eps_missing"
    fcf_calc = calc["metrics"]["fcf"]
    assert by_metric["fcf"]["quality_status"] == Q_TRUSTED
    assert by_metric["fcf"]["value"] == fcf_calc["value"]
    assert by_metric["fcf"]["formula"] == fcf_calc["formula"]
    assert by_metric["fcf"]["evidence_id"] == stored["raw_evidence_id"]
    assert by_metric["fcf"]["value"] != 0
    release_blocked_kernel_tasks(state, tmp_path)
    assert state["tasks"]["AK-pe"]["status"] == "BLOCKED"
    assert state["tasks"]["AK-fcf"]["status"] == "RETRY_SCHEDULED"
    assert state["tasks"]["AK-fcf"]["evidence_id"] == stored["raw_evidence_id"]

    priced = calculate_metrics(
        parsed["facts"], price=500.0, evidence_as_of="2026-09-18"
    )
    second = commit_stored_xbrl(
        tmp_path,
        "HBLPOWER.NS",
        price=500.0,
        price_as_of="2026-09-30",
        evidence_as_of="2026-09-18",
        now=NOW,
    )
    pe = next(row for row in second["metrics"] if row["metric"] == "pe")
    assert pe["quality_status"] == Q_TRUSTED
    assert pe["value"] == priced["metrics"]["pe"]["value"]
    assert pe["formula"] == priced["metrics"]["pe"]["formula"]
    assert abs(pe["value"] - 50.0) < 1e-6
    de = next(row for row in second["metrics"] if row["metric"] == "debt_to_equity")
    assert de["quality_status"] == Q_TRUSTED
    record = current_capability(tmp_path, "HBLPOWER.NS", "debt_to_equity")
    assert record["record"]["debt_definition"] == "total_borrowings"
    release_blocked_kernel_tasks(state, tmp_path)
    assert state["tasks"]["AK-pe"]["status"] == "RETRY_SCHEDULED"
    assert state["tasks"]["AK-pe"]["status_history"][-1]["status"] == "BLOCKED"


def test_trusted_release_drops_stale_failure_memory(tmp_path: Path):
    from atlas.investment.data_quality import release_blocked_kernel_tasks

    commit_record(
        tmp_path,
        envelope(
            symbol="HBLPOWER.NS",
            metric="debt_to_equity",
            value=0.02,
            period=PERIOD,
            period_end=PERIOD,
            provider="nse_xbrl",
            evidence_id="ev-debt",
            debt_definition="total_borrowings",
            components={"debt": 2.0, "equity": 100.0, "debt_definition": "total_borrowings"},
            now=NOW,
        ),
        now=NOW,
    )
    state = {
        "failure_memory": {
            "debt|local_market_store": {"error": "debt_missing", "generation": 0},
            "debt|knowledge_search": {"error": "debt_missing", "generation": 0},
            "pe|local_market_store": {"error": "pe_missing", "generation": 0},
        },
        "tasks": {
            "AK-de": {
                "id": "AK-de",
                "status": "CAPABILITY_GAP",
                "symbol": "HBLPOWER.NS",
                "required": ["debt"],
                "missing_requirement": "debt",
                "reason": "debt unavailable after the escalation ladder",
            }
        },
    }
    released = release_blocked_kernel_tasks(state, tmp_path)
    assert released == ["AK-de"]
    assert state["tasks"]["AK-de"]["status"] == "RETRY_SCHEDULED"
    assert "debt|local_market_store" not in state["failure_memory"]
    assert "debt|knowledge_search" not in state["failure_memory"]
    assert "pe|local_market_store" in state["failure_memory"]
    state["tasks"]["AK-de"]["status"] = "RETRY_SCHEDULED"
    state["tasks"]["AK-de"]["plan"] = {"steps": [{"id": "stale"}]}
    state["failure_memory"]["debt|local_market_store"] = {"error": "debt_missing", "generation": 0}
    again = release_blocked_kernel_tasks(state, tmp_path)
    assert again == []
    assert state["tasks"]["AK-de"]["status"] == "RETRY_SCHEDULED"
    assert state["tasks"]["AK-de"]["plan"] is None
    assert "debt|local_market_store" not in state["failure_memory"]


def test_store_reconcile_does_not_downgrade_a_trusted_xbrl_metric(tmp_path: Path):
    from atlas.investment.fundamentals import upsert_rows
    from atlas.investment.nse_xbrl.provider import commit_stored_xbrl
    from atlas.investment.nse_xbrl.raw_store import store_raw

    xml = (
        Path(__file__).parent / "fixtures" / "nse_xbrl" / "hblpower_consolidated.xml"
    ).read_text(encoding="utf-8")
    store_raw(
        tmp_path,
        symbol="HBLPOWER.NS",
        xml_text=xml,
        meta={"canonical": True, "available_at": "2026-05-15", "period_end": "2026-03-31"},
    )
    commit_stored_xbrl(
        tmp_path,
        "HBLPOWER.NS",
        price=500.0,
        price_as_of="2026-09-30",
        evidence_as_of="2026-09-18",
        now=NOW,
    )
    trusted = current_capability(tmp_path, "HBLPOWER.NS", "fcf")
    assert trusted["quality_status"] == Q_TRUSTED
    upsert_rows(
        tmp_path,
        [{"symbol": "HBLPOWER.NS", "fcf": trusted["value"], "as_of": PERIOD}],
        program_id="market_intelligence",
        source="universe_seed",
    )
    reconcile_symbol_from_store(tmp_path, symbol="HBLPOWER.NS", now=NOW)
    again = current_capability(tmp_path, "HBLPOWER.NS", "fcf")
    assert again["quality_status"] == Q_TRUSTED
    assert again["value"] == trusted["value"]
    assert again["evidence_id"] == trusted["evidence_id"]


def test_xbrl_unknown_debt_is_not_zero_and_kernel_stays_in_gap(tmp_path: Path):
    from atlas.investment.data_quality import release_blocked_kernel_tasks
    from atlas.investment.nse_xbrl.provider import commit_stored_xbrl
    from atlas.investment.nse_xbrl.raw_store import store_raw

    xml = (
        Path(__file__).parent / "fixtures" / "nse_xbrl" / "liabilities_not_debt.xml"
    ).read_text(encoding="utf-8")
    store_raw(
        tmp_path,
        symbol="LIABCO.NS",
        xml_text=xml,
        meta={"canonical": True, "available_at": "2026-05-15"},
    )
    saved = commit_stored_xbrl(tmp_path, "LIABCO.NS", now=NOW)
    debt = next(row for row in saved["metrics"] if row["metric"] == "debt_to_equity")
    assert debt["quality_status"] == Q_UNKNOWN
    assert debt["value"] is None
    assert debt["reason"] == "total_liabilities_is_not_total_debt"
    state = {
        "tasks": {
            "AK-de": {
                "id": "AK-de",
                "status": "CAPABILITY_GAP",
                "symbol": "LIABCO.NS",
                "required": ["debt_to_equity"],
                "missing_requirement": "debt_to_equity",
            }
        }
    }
    release_blocked_kernel_tasks(state, tmp_path)
    assert state["tasks"]["AK-de"]["status"] == "CAPABILITY_GAP"


def test_not_ready_pack_blocks_overlay_order(tmp_path: Path):
    from atlas.investment.fno_data_pack import (
        apply_pack_to_overlay,
        persist_fno_data_pack,
    )

    pack = build_fno_data_pack(
        underlying="COALINDIA",
        spot=None,
        session_ready=True,
        session_open=True,
        instrument_rows=[{"tradingsymbol": "X", "instrument_token": 1}],
        expiry="2026-10-27",
        now=NOW,
    )
    overlay = apply_pack_to_overlay(
        {"used": False, "fallback_l4": True, "kind": "buy", "qty": 16.0, "symbol": "COALINDIA"},
        pack,
    )
    assert pack["status"] == NOT_READY
    assert overlay["used"] is False
    assert overlay["fallback_l4"] is False
    assert overlay["kind"] is None
    assert overlay["qty"] == 0.0
    assert overlay["option_decision"]["decision"] is None
    path = persist_fno_data_pack(tmp_path, pack)
    assert path is not None
    saved = json.loads(Path(path).read_text(encoding="utf-8"))
    assert saved["status"] == NOT_READY
    assert saved["reason"] == "underlying_spot_unavailable"
    assert saved["live_orders"] is False


def test_live_underlier_quote_replaces_stale_bar():
    from atlas.investment.fno_data_pack import choose_underlier_spot

    fresh = NOW.isoformat()
    chosen = choose_underlier_spot(
        {
            "ok": True,
            "prices": {
                "AXISBANK": {"last": 1240.5, "as_of": fresh, "source": "zerodha"},
            },
        },
        bar_price=1228.2,
        bar_as_of="2026-09-30T18:30:00+00:00",
    )
    assert chosen["source"] == "live_ltp"
    assert chosen["price"] == 1240.5
    assert chosen["as_of"] == fresh
    pack = build_fno_data_pack(
        underlying="AXISBANK",
        spot=chosen["price"],
        spot_as_of=chosen["as_of"],
        spot_provider=chosen["provider"],
        instrument_rows=[{"tradingsymbol": "X", "instrument_token": 1}],
        expiry="2026-10-27",
        atm_strike=1240.0,
        ce={
            "ok": True,
            "tradingsymbol": "AXISBANK26OCT1240CE",
            "instrument_token": 1,
            "exchange": "NFO",
            "expiry": "2026-10-27",
            "strike": 1240.0,
            "instrument_type": "CE",
        },
        pe={
            "ok": True,
            "tradingsymbol": "AXISBANK26OCT1240PE",
            "instrument_token": 2,
            "exchange": "NFO",
            "expiry": "2026-10-27",
            "strike": 1240.0,
            "instrument_type": "PE",
        },
        ce_ltp=31.95,
        pe_ltp=28.8,
        ce_ltp_as_of=fresh,
        pe_ltp_as_of=fresh,
        session_open=True,
        session_ready=True,
        now=NOW,
    )
    assert pack["spot"]["status"] == "PASS"
    assert pack["atm"]["status"] == "PASS"
    assert pack["reason"] != "stale"


def test_missing_live_quote_keeps_the_bar_timestamp():
    from atlas.investment.fno_data_pack import choose_underlier_spot

    bar_as_of = "2026-09-30T18:30:00+00:00"
    chosen = choose_underlier_spot(
        {"ok": False, "error": "zerodha_session_required"},
        bar_price=1228.2,
        bar_as_of=bar_as_of,
    )
    assert chosen["source"] == "bar"
    assert chosen["as_of"] == bar_as_of
    assert chosen["price"] == 1228.2
    pack = build_fno_data_pack(
        underlying="AXISBANK",
        spot=chosen["price"],
        spot_as_of=chosen["as_of"],
        spot_provider=chosen["provider"],
        session_open=True,
        session_ready=True,
        now=NOW,
    )
    assert pack["spot"]["status"] == "STALE"
    assert pack["status"] == NOT_READY
    assert pack["reason"] == "stale"


def test_fno_ready_session_missing_spot_is_not_ready():
    pack = build_fno_data_pack(
        underlying="COALINDIA",
        spot=None,
        session_ready=True,
        session_open=True,
        instrument_rows=[{"tradingsymbol": "X", "instrument_token": 1}],
        expiry="2026-10-27",
        now=NOW,
    )
    assert pack["status"] == NOT_READY
    assert pack["spot"]["status"] == "MISSING"
    assert pack["atm"]["status"] == "NOT_COMPUTABLE"
    assert pack["ce"]["ltp"]["status"] == "NOT_REQUESTED"
    gate = option_decision_permitted(pack)
    assert gate["ok"] is False
    assert gate["decision"] is None


def _coal_instruments():
    return [
        {
            "ok": True,
            "tradingsymbol": "COALINDIA26OCT400CE",
            "instrument_type": "CE",
            "instrument_token": 11,
            "exchange": "NFO",
            "expiry": "2026-10-27",
            "strike": 400.0,
        },
        {
            "ok": True,
            "tradingsymbol": "COALINDIA26OCT400PE",
            "instrument_type": "PE",
            "instrument_token": 12,
            "exchange": "NFO",
            "expiry": "2026-10-27",
            "strike": 400.0,
        },
    ]


def test_valid_spot_invalid_instrument_not_ready():
    ce, pe = _coal_instruments()
    ce = {**ce, "instrument_token": None}
    pack = build_fno_data_pack(
        underlying="COALINDIA",
        spot=400.2,
        spot_as_of=NOW.isoformat(),
        instrument_rows=[{"tradingsymbol": "COALINDIA"}],
        expiry="2026-10-27",
        atm_strike=400.0,
        ce=ce,
        pe=pe,
        ce_ltp=10.0,
        pe_ltp=9.0,
        ce_ltp_as_of=NOW.isoformat(),
        pe_ltp_as_of=NOW.isoformat(),
        session_open=True,
        session_ready=True,
        now=NOW,
    )
    assert pack["status"] == NOT_READY
    assert option_decision_permitted(pack)["decision"] is None


def test_stale_option_ltp_not_ready():
    ce, pe = _coal_instruments()
    old = (NOW - timedelta(minutes=10)).isoformat()
    pack = build_fno_data_pack(
        underlying="COALINDIA",
        spot=400.2,
        spot_as_of=NOW.isoformat(),
        instrument_rows=[{"tradingsymbol": "COALINDIA"}],
        expiry="2026-10-27",
        atm_strike=400.0,
        ce=ce,
        pe=pe,
        ce_ltp=10.0,
        pe_ltp=9.0,
        ce_ltp_as_of=old,
        pe_ltp_as_of=NOW.isoformat(),
        session_open=True,
        session_ready=True,
        now=NOW,
    )
    assert pack["status"] == NOT_READY
    assert pack["ce"]["ltp"]["status"] == "STALE"
    assert option_decision_permitted(pack)["ok"] is False


def test_complete_pack_is_ready():
    ce, pe = _coal_instruments()
    pack = build_fno_data_pack(
        underlying="COALINDIA",
        spot=400.2,
        spot_as_of=NOW.isoformat(),
        spot_provider="zerodha",
        instrument_rows=[{"tradingsymbol": "COALINDIA", "instrument_token": 1}],
        expiry="2026-10-27",
        atm_strike=400.0,
        ce=ce,
        pe=pe,
        ce_ltp=10.0,
        pe_ltp=9.0,
        ce_ltp_as_of=NOW.isoformat(),
        pe_ltp_as_of=NOW.isoformat(),
        session_open=True,
        session_ready=True,
        now=NOW,
    )
    assert pack["status"] == READY
    gate = option_decision_permitted(pack)
    assert gate["ok"] is True
    assert gate["decision"]["live_orders"] is False
    assert gate["decision"]["atm"] == 400.0


def test_impossible_price_and_future_timestamp_rejected():
    ce, pe = _coal_instruments()
    future = (NOW + timedelta(hours=2)).isoformat()
    bad_px = build_fno_data_pack(
        underlying="COALINDIA",
        spot=-1,
        spot_as_of=NOW.isoformat(),
        instrument_rows=[{"tradingsymbol": "COALINDIA"}],
        expiry="2026-10-27",
        session_open=True,
        now=NOW,
    )
    assert bad_px["status"] == NOT_READY
    assert bad_px["spot"]["value"] is None
    future_pack = build_fno_data_pack(
        underlying="COALINDIA",
        spot=400.0,
        spot_as_of=future,
        instrument_rows=[{"tradingsymbol": "COALINDIA"}],
        expiry="2026-10-27",
        atm_strike=400.0,
        ce=ce,
        pe=pe,
        ce_ltp=10.0,
        pe_ltp=9.0,
        ce_ltp_as_of=NOW.isoformat(),
        pe_ltp_as_of=NOW.isoformat(),
        session_open=True,
        now=NOW,
    )
    assert future_pack["spot"]["reason"] == "timestamp_in_future"
    assert future_pack["status"] == NOT_READY


def test_duplicate_and_out_of_order_ticks():
    dup = classify_tick_continuity(
        [
            {"timestamp": NOW.isoformat(), "price": 10.0},
            {"timestamp": NOW.isoformat(), "price": 10.0},
        ]
    )
    assert dup["duplicates"] == 1
    ooo = classify_tick_continuity(
        [
            {"timestamp": NOW.isoformat(), "price": 10.0},
            {"timestamp": (NOW - timedelta(seconds=5)).isoformat(), "price": 11.0},
        ]
    )
    assert ooo["out_of_order"] == 1
    pack = build_fno_data_pack(
        underlying="COALINDIA",
        spot=400.0,
        spot_as_of=NOW.isoformat(),
        instrument_rows=[{"tradingsymbol": "X"}],
        expiry="2026-10-27",
        atm_strike=400.0,
        ce=_coal_instruments()[0],
        pe=_coal_instruments()[1],
        ce_ltp=10,
        pe_ltp=9,
        ce_ltp_as_of=NOW.isoformat(),
        pe_ltp_as_of=NOW.isoformat(),
        session_open=True,
        ticks=[
            {"timestamp": NOW.isoformat(), "price": 400.0},
            {"timestamp": (NOW - timedelta(seconds=1)).isoformat(), "price": 399.0},
        ],
        now=NOW,
    )
    assert pack["status"] == NOT_READY
    assert pack["ticks"]["out_of_order"] == 1


def test_capability_state_survives_reload(tmp_path: Path):
    commit_record(tmp_path, _pe(), now=NOW)
    again = load_registry(tmp_path)
    row = again["current"]["india_equity_learner|HBLPOWER.NS|pe"]
    assert row["quality_status"] == Q_TRUSTED
    assert row["evidence_id"] == "ev-hbl-pe"


def test_decision_layer_rejects_unusable_states():
    for rec in (
        _pe(value=None, components={}),
        _pe(period="2018-03-31", period_end="2018-03-31"),
        _pe(components={"price": 100.0, "eps": 0.0}, value=10.0),
        _pe(provider="duckduckgo", source="web_snippet"),
    ):
        assert decision_may_consume(rec) is False
    conflict = _pe()
    conflict["quality_status"] = Q_CONFLICT
    conflict["usable"] = False
    assert decision_may_consume(conflict) is False
    assert decision_may_consume({"quality_status": Q_UNKNOWN, "value": 1}) is False


def test_not_ready_pack_creates_no_trade_path():
    gate = option_decision_permitted(
        {"status": NOT_READY, "reason": "underlying_spot_unavailable", "reasons": ["spot"]}
    )
    assert gate["ok"] is False
    assert gate["decision"] is None
    assert gate["status"] == "DATA_QUALITY_FAILURE"


def test_failure_paths_do_not_invent_values():
    rec = _pe(provider="web_search", source="snippet", value=99.0)
    assert rec["value"] is None
    missing = build_fno_data_pack(underlying="COALINDIA", spot=None, now=NOW, session_ready=True)
    assert missing["spot"]["value"] is None
    assert missing["atm"]["strike"] is None
    debt = envelope(
        symbol="HBLPOWER.NS",
        metric="debt_to_equity",
        value=0.5,
        period=PERIOD,
        period_end=PERIOD,
        provider="nse_xbrl",
        evidence_id="ev-de",
        debt_definition="net_debt",
        components={
            "debt": 50.0,
            "equity": 100.0,
            "debt_definition": "net_debt",
            "substituted_from": "total_borrowings",
        },
        now=NOW,
    )
    assert debt["quality_status"] == Q_INVALID
    assert debt["usable"] is False


def test_store_presence_is_not_trusted(tmp_path: Path):
    from atlas.investment.fundamentals import upsert_rows

    upsert_rows(
        tmp_path,
        [
            {
                "symbol": "HBLPOWER.NS",
                "pe": 25.859,
                "roe": 44.08,
                "debt_to_equity": 0.02,
                "fcf": 6293200000.0,
                "source": "universe_seed",
                "as_of": "2026-10-01",
                "eps_basis": "FY",
            }
        ],
        program_id="market_intelligence",
        merge_screener=False,
    )
    out = reconcile_symbol_from_store(
        tmp_path, symbol="HBLPOWER.NS", now=NOW
    )
    pe = current_capability(tmp_path, "HBLPOWER.NS", "pe")
    assert out["ok"] is True
    assert pe["acquired"] is True
    assert pe["quality_status"] == Q_PENDING
    assert pe["usable"] is False
    assert pe["tradable"] is False
    assert decision_may_consume(pe.get("record")) is False


def _store_hbl(tmp_path: Path) -> None:
    from atlas.investment.fundamentals import upsert_rows

    upsert_rows(
        tmp_path,
        [
            {
                "symbol": "HBLPOWER.NS",
                "pe": 25.859,
                "roe": 44.08,
                "debt_to_equity": 0.02,
                "fcf": 6293200000.0,
                "source": "universe_seed",
                "as_of": "2026-10-01",
                "eps_basis": "FY",
            }
        ],
        program_id="market_intelligence",
        merge_screener=False,
    )


def test_pending_store_value_is_not_queued_as_missing(tmp_path: Path):
    from atlas.investment.uncertainty_queue import enqueue_from_unknowns

    _store_hbl(tmp_path)
    task = make_acquisition_task(
        laboratory_id="india_equity_learner",
        symbol="HBLPOWER.NS",
        unknown_code="pe_missing",
    )
    upsert_task(tmp_path, task)
    reconcile_symbol_from_store(tmp_path, symbol="HBLPOWER.NS", now=NOW)
    pe = current_capability(tmp_path, "HBLPOWER.NS", "pe")
    assert pe["quality_status"] == Q_PENDING
    assert pe["acquired"] is True
    assert pe["usable"] is False
    assert pe["tradable"] is False
    assert pe["value"] == 25.859
    pending = list_tasks(tmp_path, "india_equity_learner", status="PENDING")
    assert not any(t.get("unknown") == "pe_missing" for t in pending)
    held = next(
        t
        for t in list_tasks(tmp_path, "india_equity_learner", status=None)
        if t.get("unknown") == "pe_missing"
    )
    assert held["status"] == "PENDING_VALIDATION"
    again = enqueue_from_unknowns(
        tmp_path,
        laboratory_id="india_equity_learner",
        symbol="HBLPOWER.NS",
        unknowns=["pe_missing"],
    )
    assert held["id"] not in again["created_ids"]
    assert "pe_missing" in again["skipped"]
    still = next(
        t
        for t in list_tasks(tmp_path, "india_equity_learner", status=None)
        if t.get("id") == held["id"]
    )
    assert still["status"] == "PENDING_VALIDATION"


def test_trusted_pe_is_not_an_open_missing_task(tmp_path: Path):
    task = make_acquisition_task(
        laboratory_id="india_equity_learner",
        symbol="HBLPOWER.NS",
        unknown_code="pe_missing",
    )
    upsert_task(tmp_path, task)
    commit_record(tmp_path, _pe(), now=NOW)
    pe = current_capability(tmp_path, "HBLPOWER.NS", "pe")
    assert pe["quality_status"] == Q_TRUSTED
    assert pe["usable"] is True
    assert pe["tradable"] is True
    assert decision_may_consume(pe.get("record")) is True
    pending = list_tasks(tmp_path, "india_equity_learner", status="PENDING")
    assert not any(t.get("unknown") == "pe_missing" for t in pending)
    row = next(
        t
        for t in list_tasks(tmp_path, "india_equity_learner", status=None)
        if t.get("unknown") == "pe_missing"
    )
    assert row["status"] == "DONE"


def test_unknown_registry_may_keep_an_acquisition_task(tmp_path: Path):
    from atlas.investment.uncertainty_queue import enqueue_from_unknowns
    from atlas.investment.data_quality import blocks_missing_code

    noted = note_capability_gap(
        tmp_path, symbol="TATACHEM.NS", metric="pe", reason="pe_missing", now=NOW
    )
    row = noted["current"]
    assert row["quality_status"] == Q_UNKNOWN
    assert row["acquired"] is False
    assert row["value"] is None
    assert row["value"] != 0
    assert row["tradable"] is False
    assert blocks_missing_code(tmp_path, "india_equity_learner", "TATACHEM.NS", "pe_missing")
    created = enqueue_from_unknowns(
        tmp_path,
        laboratory_id="india_equity_learner",
        symbol="TATACHEM.NS",
        unknowns=["pe_missing"],
    )
    assert created["created_ids"]
    pending = list_tasks(tmp_path, "india_equity_learner", status="PENDING")
    assert any(t.get("unknown") == "pe_missing" and t.get("symbol") == "TATACHEM.NS" for t in pending)


def test_conflict_is_not_usable_or_tradable(tmp_path: Path):
    task = make_acquisition_task(
        laboratory_id="india_equity_learner",
        symbol="HBLPOWER.NS",
        unknown_code="pe_missing",
    )
    upsert_task(tmp_path, task)
    commit_record(tmp_path, _pe(), now=NOW)
    other = _pe(
        provider="screener_export",
        source="screener",
        evidence_id="ev-other",
        value=40.0,
        components={"price": 160.0, "eps": 4.0, "eps_basis": "FY"},
    )
    second = commit_record(tmp_path, other, now=NOW)
    assert second["current"]["quality_status"] == Q_CONFLICT
    assert second["current"]["usable"] is False
    assert second["current"]["tradable"] is False
    assert decision_may_consume(second["record"]) is False
    assert second["current"]["value"] not in (0, None)
    row = next(
        t
        for t in list_tasks(tmp_path, "india_equity_learner", status=None)
        if t.get("unknown") == "pe_missing"
    )
    assert row["status"] == "CONFLICT"
    assert not any(
        t.get("unknown") == "pe_missing"
        for t in list_tasks(tmp_path, "india_equity_learner", status="PENDING")
    )


def test_pending_keeps_historical_gap_and_kernel_does_not_call_it_missing(tmp_path: Path):
    from atlas.agent_kernel.local_evidence import lookup_local
    from atlas.agent_kernel.safety import FORBIDDEN_CAPABILITIES
    from atlas.investment.data_quality import align_kernel_fundamental_tasks

    note_capability_gap(
        tmp_path,
        symbol="HBLPOWER.NS",
        metric="pe",
        reason="pe_missing",
        attempted=["local_market_store"],
        now=NOW - timedelta(days=1),
    )
    _store_hbl(tmp_path)
    reconcile_symbol_from_store(tmp_path, symbol="HBLPOWER.NS", now=NOW)
    ignored = note_capability_gap(
        tmp_path,
        symbol="HBLPOWER.NS",
        metric="pe",
        reason="pe_missing",
        now=NOW,
    )
    assert ignored["ignored"] is True
    pe = current_capability(tmp_path, "HBLPOWER.NS", "pe")
    assert pe["quality_status"] == Q_PENDING
    assert any(h.get("current_state") == "CAPABILITY_GAP" for h in pe["history"])
    audit = (tmp_path / "investment" / "data_quality" / "audit.jsonl").read_text()
    assert "capability_gap" in audit
    assert "gap_ignored_current_state" in audit
    looked = lookup_local(
        tmp_path,
        symbol="HBLPOWER.NS",
        requirement="pe",
        laboratory_id="india_equity_learner",
    )
    assert looked["quality_hold"] is True
    assert looked["quality"] == Q_PENDING
    assert looked["missing"] is None
    assert looked["tradable"] is False
    assert looked.get("evidence") is None
    kernel = AgentKernel(tmp_path, laboratory_id="india_equity_learner")
    kernel.state["tasks"]["AK-pe"] = {
        "id": "AK-pe",
        "status": "CAPABILITY_GAP",
        "symbol": "HBLPOWER.NS",
        "objective": "Acquire evidence for pe_missing on HBLPOWER.NS",
        "required": ["pe"],
        "missing_requirement": "pe",
        "domain": "investment",
        "priority_class": "P1",
        "score": 1,
        "evidence": {},
        "attempted_capabilities": ["local_market_store"],
        "failed": ["local_market_store:pe_not_available"],
        "plan": None,
        "constraints": {},
        "lineage": {},
    }
    changed = align_kernel_fundamental_tasks(
        kernel.state, tmp_path, laboratory_id="india_equity_learner"
    )
    task = kernel.state["tasks"]["AK-pe"]
    assert changed == ["AK-pe"]
    assert task["status"] == "BLOCKED"
    assert task["missing_requirement"] is None
    assert task["registry_state"] == Q_PENDING
    assert task["tradable"] is False
    assert task["usable"] is False
    assert task["status_history"][-1]["status"] == "CAPABILITY_GAP"
    assert "place_order" not in task["attempted_capabilities"]
    assert "place_order" in FORBIDDEN_CAPABILITIES


def test_plc_a_result_ignores_pending_registry(tmp_path: Path):
    from atlas.investment.plc_buy_gates import evaluate_fundamental_sanity

    fundamentals = {
        "pe": None,
        "fcf": None,
        "roe": None,
        "debt_to_equity": None,
    }
    before = evaluate_fundamental_sanity(fundamentals, sector=None)
    _store_hbl(tmp_path)
    reconcile_symbol_from_store(tmp_path, symbol="HBLPOWER.NS", now=NOW)
    after = evaluate_fundamental_sanity(fundamentals, sector=None)
    assert after == before
    assert current_capability(tmp_path, "HBLPOWER.NS", "pe")["tradable"] is False
