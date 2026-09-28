"""FEA — Fundamental Evidence Acquisition (planner → Yahoo → provenance → UQ)."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.fundamental_evidence import (
    acquire_for_symbol,
    drain_uncertainty_queue,
    plan_symbol_acquisition,
    source_policy_table,
)
from atlas.investment.fundamentals import get_symbol, upsert_rows
from atlas.investment.uncertainty_queue import (
    STATUS_DONE,
    STATUS_PENDING,
    enqueue_from_unknowns,
    list_tasks,
)
from atlas.investment.yahoo_fundamentals import parse_quote_summary
from tests.test_laboratory_li2_providers import _fake_quote_summary


def test_source_policy_never_scrapes_screener_or_uses_zerodha_for_fcf():
    table = source_policy_table()
    fcf = table["metrics"]["fcf"]
    modes = {s["mode"] for s in fcf}
    assert "network" in modes
    assert "operator_only" in modes
    assert all(s.get("provider") != "zerodha" for s in fcf)
    pe = table["metrics"]["pe"]
    assert any(s.get("mode") == "operator_only" for s in pe)


def test_plan_stops_at_fcf_when_pe_present(tmp_path: Path):
    upsert_rows(
        tmp_path,
        [{"symbol": "WELCORP.NS", "pe": 43.17, "roe": 17.0, "debt_to_equity": 0.26}],
        program_id="market_intelligence",
        merge_screener=False,
    )
    plan = plan_symbol_acquisition(tmp_path, "WELCORP.NS")
    assert "pe" in plan["present"]
    assert "fcf" in plan["missing"]
    assert plan["complete"] is False
    assert plan["steps"][0]["field"] == "fcf"
    assert "nse_xbrl" in plan["steps"][0]["try_network"]
    assert "yahoo_fundamentals" in plan["steps"][0]["try_secondary"]
    assert "yahoo_fundamentals" not in plan["steps"][0]["try_network"]


def test_acquire_yahoo_fcf_reported_closes_uq(tmp_path: Path):
    enqueue_from_unknowns(
        tmp_path,
        laboratory_id="india_equity_learner",
        symbol="WELCORP.NS",
        unknowns=["fcf_missing", "pe_missing"],
    )

    def opener(url: str):
        return _fake_quote_summary(pe=43.0, fcf=1.2e10)

    out = acquire_for_symbol(
        tmp_path,
        "WELCORP.NS",
        laboratory_id="india_equity_learner",
        enabled=True,
        yahoo_secondary=True,
        opener=opener,
        push_to_ira=False,
        nse_enabled=False,
    )
    assert out["ok"] is True
    fields = {a["field"] for a in out.get("acquired") or []}
    assert "fcf" in fields
    assert "pe" in fields
    row = get_symbol(tmp_path, "WELCORP.NS") or {}
    assert row.get("fcf") == 1.2e10
    pending = list_tasks(tmp_path, "india_equity_learner", status=STATUS_PENDING)
    assert not any(
        t.get("symbol") == "WELCORP.NS" and t.get("unknown") == "fcf_missing"
        for t in pending
    )
    done = list_tasks(tmp_path, "india_equity_learner", status=STATUS_DONE)
    assert any(t.get("unknown") == "fcf_missing" for t in done)


def test_acquire_yahoo_fcf_derived_provenance():
    payload = {
        "quoteSummary": {
            "result": [
                {
                    "defaultKeyStatistics": {},
                    "financialData": {},  # no freeCashflow
                    "summaryDetail": {},
                    "price": {},
                    "cashflowStatementHistory": {
                        "cashflowStatements": [
                            {
                                "endDate": {"fmt": "2025-03-31"},
                                "totalCashFromOperatingActivities": {"raw": 3204.28},
                                "capitalExpenditures": {"raw": -3713.9},
                            }
                        ]
                    },
                }
            ]
        }
    }
    parsed = parse_quote_summary(payload, symbol="WELCORP.NS")
    assert parsed["fcf_value_type"] == "derived"
    assert abs(parsed["fields"]["fcf"] - (3204.28 - 3713.9)) < 1e-6
    fcf_ev = next(e for e in parsed["evidence"] if e["field"] == "fcf")
    assert fcf_ev["raw_ref"]["value_type"] == "derived"
    assert "operating_cash_flow" in (fcf_ev["raw_ref"].get("formula") or "")


def test_acquire_respects_yahoo_cooldown(tmp_path: Path, monkeypatch):
    from atlas.investment import yahoo_fundamentals as yf

    class _Gate:
        def status(self):
            return {"ready": False, "cooldown_remaining_s": 400.0}

    monkeypatch.setattr(yf, "get_yahoo_rate_gate", lambda _d: _Gate())
    out = acquire_for_symbol(
        tmp_path,
        "WELCORP.NS",
        enabled=True,
        yahoo_secondary=True,
        opener=lambda _u: _fake_quote_summary(),
        push_to_ira=False,
        nse_enabled=False,
    )
    assert out["reason"] == "yahoo_cooldown"
    assert not any(
        a.get("field") in {"pe", "fcf", "roe", "debt_to_equity"}
        for a in out.get("acquired") or []
    )


def test_drain_empty_queue(tmp_path: Path):
    out = drain_uncertainty_queue(tmp_path, laboratory_id="india_equity_learner")
    assert out["queued"] == 0
    assert out["acquired_n"] == 0


def test_fea_builtin_template_has_worker_spec():
    from atlas.missions.templates.builtins import BUILTIN_TEMPLATES

    tmpl = next(t for t in BUILTIN_TEMPLATES if t["name"] == "fundamental_evidence")
    types = [s["type"] for s in tmpl["worker_specs"]]
    assert "fundamental_evidence" in types
    assert tmpl["default_config"]["max_symbols"] == 6
    assert tmpl["default_config"]["nse_concurrency"] == 3
    assert tmpl["default_config"]["yahoo_secondary"] is False


def test_fea_worker_idle_without_data_dir():
    from atlas.workers.base import TickContext
    from atlas.workers.fundamental_evidence import FundamentalEvidenceWorker

    worker = FundamentalEvidenceWorker(data_dir=None, yahoo_enabled=False)
    result = worker.do_tick(
        TickContext(
            worker_id="fea-1",
            mission_id="m-fea",
            config={},
            config_version=1,
            state={},
        )
    )
    assert "data_dir not wired" in result.note


def test_yahoo_suppressed_on_normal_pe_fcf_path(tmp_path: Path):
    enqueue_from_unknowns(
        tmp_path,
        laboratory_id="india_equity_learner",
        symbol="WELCORP.NS",
        unknowns=["pe_missing", "fcf_missing"],
    )
    yahoo_hits = []

    def opener(url: str):
        yahoo_hits.append(url)
        return _fake_quote_summary(pe=43.0, fcf=1.2e10)

    out = acquire_for_symbol(
        tmp_path,
        "WELCORP.NS",
        laboratory_id="india_equity_learner",
        enabled=True,
        yahoo_secondary=False,
        opener=opener,
        push_to_ira=False,
        nse_enabled=False,
    )
    assert any(
        a.get("reason") == "yahoo_suppressed" for a in out.get("attempts") or []
    )
    fields = {a["field"] for a in out.get("acquired") or []}
    assert "pe" not in fields
    assert "fcf" not in fields
    assert yahoo_hits == []


def test_nse_unavailable_backs_off_and_skips_next_drain(tmp_path: Path):
    from datetime import datetime, timezone

    from atlas.investment.fundamental_evidence.dispatch import (
        plan_batch_acquisition,
        schedule_nse_retry,
    )

    enqueue_from_unknowns(
        tmp_path,
        laboratory_id="india_equity_learner",
        symbol="ABBOTINDIA.NS",
        unknowns=["pe_missing"],
    )
    stamp = schedule_nse_retry(
        tmp_path,
        laboratory_id="india_equity_learner",
        symbol="ABBOTINDIA.NS",
        reason="nse_unavailable",
        now=datetime(2026, 9, 19, 3, 0, tzinfo=timezone.utc),
    )
    assert stamp["fail_n"] == 1
    plan = plan_batch_acquisition(
        tmp_path,
        laboratory_id="india_equity_learner",
        now=datetime(2026, 9, 19, 3, 5, tzinfo=timezone.utc),
    )
    assert plan["due_n"] == 0
    assert plan["backing_off_n"] >= 1
    later = plan_batch_acquisition(
        tmp_path,
        laboratory_id="india_equity_learner",
        now=datetime(2026, 9, 19, 3, 25, tzinfo=timezone.utc),
    )
    assert later["due_n"] == 1
    assert later["due"][0]["symbol"] == "ABBOTINDIA.NS"


def test_priority_buy_beats_watch(tmp_path: Path):
    from atlas.investment.fundamental_evidence.dispatch import plan_batch_acquisition

    enqueue_from_unknowns(
        tmp_path,
        laboratory_id="india_equity_learner",
        symbol="WATCHCO.NS",
        unknowns=["pe_missing"],
    )
    enqueue_from_unknowns(
        tmp_path,
        laboratory_id="india_equity_learner",
        symbol="BUYCO.NS",
        unknowns=["pe_missing"],
    )
    plan = plan_batch_acquisition(
        tmp_path,
        laboratory_id="india_equity_learner",
        limit=1,
        holdings={"BUYCO.NS"},
        buy_blocked=set(),
        candidates=set(),
    )
    assert plan["due_n"] == 1
    assert plan["due"][0]["symbol"] == "BUYCO.NS"
    assert plan["due"][0]["priority_label"] == "P0_buy"


def test_hourly_includes_fea_ops(tmp_path: Path):
    from atlas.investment.reports import format_hourly_activity_report

    subject, body = format_hourly_activity_report(
        portfolio={"data_dir": str(tmp_path)},
        laboratory_id="india_equity_learner",
        hour=8,
        ist_date="2026-09-19",
    )
    assert "FUNDAMENTAL INTELLIGENCE" in body
    assert "queue depth" in body
    assert "Yahoo suppressed" in body
    assert "NSE success rate" in body


def test_fea_worker_tick_drains_pending_pe(tmp_path: Path):
    from atlas.workers.base import TickContext
    from atlas.workers.fundamental_evidence import FundamentalEvidenceWorker

    enqueue_from_unknowns(
        tmp_path,
        laboratory_id="india_equity_learner",
        symbol="YESBANK.NS",
        unknowns=["pe_missing"],
    )

    worker = FundamentalEvidenceWorker(data_dir=str(tmp_path), yahoo_enabled=False)
    result = worker.do_tick(
        TickContext(
            worker_id="fea-1",
            mission_id="m-fea",
            config={
                "data_dir": str(tmp_path),
                "yahoo_enabled": False,
                "portfolio_key": "india_equity_learner",
                "push_to_ira": False,
            },
            config_version=1,
            state={},
        )
    )
    last = result.state.get("last_acquire") or {}
    assert last.get("queued") == 1
    assert "yahoo_disabled" in result.note or last.get("queued") == 1


def test_q_only_instance_backs_off(tmp_path: Path):
    from atlas.investment.fundamental_evidence.dispatch import plan_batch_acquisition

    enqueue_from_unknowns(
        tmp_path,
        laboratory_id="india_equity_learner",
        symbol="ADANIPORTS.NS",
        unknowns=["pe_missing", "roe_missing"],
    )
    qxml = (
        Path(__file__).parent / "fixtures" / "nse_xbrl" / "quarterly_pat_only.xml"
    ).read_text(encoding="utf-8")
    out = acquire_for_symbol(
        tmp_path,
        "ADANIPORTS.NS",
        laboratory_id="india_equity_learner",
        enabled=False,
        push_to_ira=False,
        nse_xml_text=qxml,
        nse_price=100.0,
        evidence_as_of="2026-09-18",
        nse_available_at="2026-07-29",
    )
    assert out["reason"] == "instance_incomplete"
    pending = list_tasks(tmp_path, "india_equity_learner", status=STATUS_PENDING)
    assert any(t.get("last_nse_status") == "instance_incomplete" for t in pending)
    assert any(t.get("next_retry_at") for t in pending)
    from datetime import datetime, timezone

    plan = plan_batch_acquisition(
        tmp_path,
        laboratory_id="india_equity_learner",
        now=datetime(2026, 9, 19, 7, 50, tzinfo=timezone.utc),
    )
    assert plan["due_n"] == 0
    assert plan["backing_off_n"] >= 1
