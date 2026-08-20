"""OI-STAB0 D4 — session honesty + readiness."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from atlas.activity import ActivityJournal, InMemoryActivityRepository, bind_journal
from atlas.investment.session_notes import classify_action, merge_day_notes
from atlas.investment.session_readiness import evaluate_equity_session
from atlas.reasoning.day_activity import build_day_activity_brief


def test_classify_yahoo_cooldown():
    assert classify_action("RELIANCE.NS: yahoo_cooldown deferred") == "yahoo_cooldown"
    assert classify_action("TCS.NS: mark_only @ 100") == "mark_only"


def test_classify_loop0_decision_idle():
    assert (
        classify_action("CIPLA.NS: switch_review hold (switch_blocked_missing_er)")
        == "switch_blocked"
    )
    assert (
        classify_action("BAJFINANCE.NS: plc_a_hold (fundamentals_incomplete:debt_to_equity)")
        == "plc_a_hold"
    )
    assert (
        classify_action("CIPLA.NS: portfolio_hold (concentration_name:8.8%>0%) [alt]")
        == "portfolio_hold"
    )
    assert classify_action("next_alt: skipped (fno_no_cash_alts)") == "fno_no_cash_alts"
    assert classify_action("NIFTY: margin (insufficient margin: need ~1; cash=0)") == "margin"


def test_format_no_fill_leads_with_decisions():
    from atlas.investment.session_notes import format_no_fill_reasons

    lines = format_no_fill_reasons(
        {
            "reason_counts": {
                "session_closed": 2000,
                "mark_only": 1900,
                "switch_blocked": 2,
                "plc_a_hold": 4,
            }
        }
    )
    joined = "\n".join(lines)
    assert "PLC.A" in joined
    assert joined.index("PLC.A") < joined.index("clock:")


def test_day_brief_includes_why_idle(tmp_path: Path):
    day = "2026-08-12"
    merge_day_notes(
        tmp_path,
        portfolio_key="india_equity_learner",
        ist_date=day,
        reason_counts={"session_closed": 5, "strategy_hold": 2},
        samples=["TCS.NS: session_closed (after_close) mark @ 10"],
        extra={
            "valuation_basis": "mixed (1/2 market, rest avg cost)",
            "marks_pct": 50.0,
            "session_open": False,
        },
    )
    repo = InMemoryActivityRepository()
    j = ActivityJournal(repo)
    bind_journal(j)
    try:
        j.record(
            domain="market",
            worker="paper_trading",
            action="paper_tick",
            summary="Paper tick on india_equity_learner: +0 buy",
            result="completed",
            ts=datetime(2026, 8, 12, 15, 30, tzinfo=ZoneInfo("Asia/Kolkata")),
        )
        brief = build_day_activity_brief(
            data_dir=tmp_path, day=day, journal=j, reasoning=None
        )
        ans = brief["answer"].lower()
        assert "why i did" in ans or "did not act" in ans
        assert "valuation" in ans or "mixed" in ans
        assert "belief core" in ans
    finally:
        bind_journal(None)


def test_fno_lab_paused_env(monkeypatch):
    from atlas.investment.session_readiness import fno_lab_paused

    monkeypatch.delenv("ATLAS_STAB0_PAUSE_FNO", raising=False)
    assert fno_lab_paused() is False
    monkeypatch.setenv("ATLAS_STAB0_PAUSE_FNO", "1")
    assert fno_lab_paused() is True
    monkeypatch.setenv("ATLAS_STAB0_PAUSE_FNO", "0")
    assert fno_lab_paused() is False


def test_session_readiness_incomplete_without_data(tmp_path: Path):
    out = evaluate_equity_session(tmp_path, day="2026-08-12")
    assert out["version"].startswith("stab0")
    assert out["success_metric"] == "observe_and_explain"
    assert out["status"] in {"incomplete", "fail", "pass"}
    keys = {g["key"] for g in out["gates"]}
    assert "activity_journal" in keys
    assert "yahoo_429" in keys


def test_session_readiness_pass_with_journal_and_clean_soak(tmp_path: Path):
    day = "2026-08-12"
    repo = InMemoryActivityRepository()
    j = ActivityJournal(repo)
    bind_journal(j)
    try:
        j.record(
            domain="market",
            worker="investor_mailer",
            action="send_evening",
            summary="Sent evening report",
            ts=datetime(2026, 8, 12, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
        )
        merge_day_notes(
            tmp_path,
            portfolio_key="india_equity_learner",
            ist_date=day,
            reason_counts={"session_closed": 3},
            extra={
                "valuation_basis": "latest daily market bars",
                "marks_pct": 100.0,
                "feed_gap_days": 0,
            },
        )
        audit = tmp_path / "investment" / "yahoo_request_audit.jsonl"
        audit.parent.mkdir(parents=True, exist_ok=True)
        audit.write_text(
            json.dumps(
                {
                    "ts": f"{day}T10:00:00+05:30",
                    "url_class": "durable_bar_store",
                    "status": 200,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        out = evaluate_equity_session(tmp_path, day=day)
        assert out["counts"]["required"] >= 1
        # journal + marks + yahoo present → should pass required gates
        assert out["status"] in {"pass", "incomplete"}
        by = {g["key"]: g for g in out["gates"]}
        assert by["activity_journal"]["ok"] is True
        assert by["yahoo_429"]["ok"] is True
        assert by["marks_valuation"]["ok"] is True
    finally:
        bind_journal(None)


def test_session_readiness_weekend_calendar_gap_passes_when_marks_fresh(tmp_path: Path):
    day = "2026-08-17"
    repo = InMemoryActivityRepository()
    j = ActivityJournal(repo)
    bind_journal(j)
    try:
        j.record(
            domain="market",
            worker="paper_trading",
            action="paper_tick",
            summary="tick",
            ts=datetime(2026, 8, 17, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
        )
        merge_day_notes(
            tmp_path,
            portfolio_key="india_equity_learner",
            ist_date=day,
            reason_counts={"session_closed": 3, "switch_blocked": 2},
            extra={
                "valuation_basis": "latest daily market bars",
                "marks_pct": 100.0,
                "feed_gap_days": 4.0,
            },
        )
        class _RS:
            def consultation_metrics(self):
                return {"day_ist": day, "total": 3, "by_domain": {"market": 3}}

        out = evaluate_equity_session(tmp_path, day=day, reasoning=_RS())
        by = {g["key"]: g for g in out["gates"]}
        assert by["feed_gap"]["ok"] is True
        assert "session-fresh" in by["feed_gap"]["detail"]
        assert by["belief_consults_tracked"]["detail"] == "consultations_today=3"
    finally:
        bind_journal(None)


def test_merge_day_notes_rotates_samples_when_cap_full(tmp_path: Path):
    day = "2026-08-17"
    filled = [f"SYM{i}.NS: session_closed (after_close) mark @ {i}" for i in range(40)]
    merge_day_notes(
        tmp_path,
        portfolio_key="india_equity_learner",
        ist_date=day,
        reason_counts={"session_closed": 40},
        samples=filled,
    )
    merge_day_notes(
        tmp_path,
        portfolio_key="india_equity_learner",
        ist_date=day,
        reason_counts={"switch_blocked": 2, "session_closed": 10},
        samples=[
            filled[-1],
            "CIPLA.NS: switch_review hold (switch_blocked_plc_a)",
            "EICHERMOT.NS: switch_review hold (switch_blocked_plc_a)",
        ],
    )
    notes = json.loads(
        (tmp_path / "market" / "session_notes" / "india_equity_learner" / f"{day}.json").read_text()
    )
    samples = notes["samples"]
    assert len(samples) == 40
    assert "CIPLA.NS: switch_review hold (switch_blocked_plc_a)" in samples
    assert samples[-1].startswith("EICHERMOT.NS: switch_review")
    assert filled[0] not in samples


def test_samples_for_notes_keeps_switch_review_when_clock_dominates():
    from atlas.investment.session_notes import samples_for_notes

    clock = [f"SYM{i}.NS: session_closed (after_close) mark @ {i}" for i in range(20)]
    decisions = [
        "CIPLA.NS: switch_review hold (switch_blocked_plc_a)",
        "EICHERMOT.NS: switch_review hold (switch_blocked_plc_a)",
    ]
    out = samples_for_notes(clock + decisions, cap=12)
    assert "CIPLA.NS: switch_review hold (switch_blocked_plc_a)" in out
    assert out[-1].startswith("EICHERMOT.NS: switch_review")
    assert len(out) <= 12
