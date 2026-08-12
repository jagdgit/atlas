"""Judgment Month — hist bars, CWS, BRE.4 ChatMessage hermetic tests."""

from __future__ import annotations

import json

from atlas.investment.cognitive_work import (
    DEFAULT_QUOTA,
    format_cws_section,
    record_item,
    remaining,
    run_cws_pass,
)
from atlas.investment.historical_bars import (
    bootstrap_batch,
    needs_bootstrap,
)
from atlas.investment.morning_hypothesis import run_morning_hypothesis_batch
from atlas.investment.reports import format_hourly_activity_report
from atlas.llm.provider import ChatMessage, LLMResponse


def test_cws_quota_and_unknown_queue(tmp_path):
    lab = "india_equity_learner"
    doc = run_cws_pass(
        tmp_path,
        laboratory_id=lab,
        wsos=[{"symbol": "CIPLA.NS", "unknowns": ["fundamentals.fcf", "news"]}],
        open_symbols=["CIPLA.NS", "EICHERMOT.NS"],
    )
    assert doc["quota"]["belief_review"] == DEFAULT_QUOTA["belief_review"]
    assert sum(doc["completed"].values()) >= 1
    rem = remaining(doc)
    assert isinstance(rem, dict)
    lines = format_cws_section(doc)
    assert any("Cognitive Work" in x for x in lines)


def test_hist_bootstrap_skips_failed(tmp_path):
    from atlas.investment.historical_bars import save_progress

    save_progress(
        tmp_path,
        {
            "done": {},
            "failed": {
                "HBLPOWER.NS": {"status": "gap", "error": "404", "at": 1.0},
            },
        },
    )
    calls: list[str] = []

    def fetch(symbol, **kwargs):
        calls.append(symbol)
        from datetime import date, timedelta

        start = date(2016, 1, 1)
        return [
            {
                "date": (start + timedelta(days=i)).isoformat(),
                "close": 10.0 + i,
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "volume": 1,
            }
            for i in range(450)
        ]

    out = bootstrap_batch(
        tmp_path,
        ["HBLPOWER.NS", "TCS.NS"],
        fetch_bars=fetch,
        max_n=4,
        min_bars=400,
    )
    assert "HBLPOWER.NS" not in [c.upper() for c in calls]
    assert any(c.upper() == "TCS.NS" for c in calls)
    assert out["ok"] >= 1


def test_hist_bootstrap_persists(tmp_path):
    from datetime import date, timedelta

    start = date(2016, 1, 1)
    bars = [
        {
            "date": (start + timedelta(days=i)).isoformat(),
            "close": 100.0 + (i % 50),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "volume": 1000,
        }
        for i in range(450)
    ]

    def fetch(symbol, **kwargs):
        assert kwargs.get("range") == "10y"
        return bars

    assert needs_bootstrap(tmp_path, "NIFTY") is True
    out = bootstrap_batch(
        tmp_path,
        ["NIFTY"],
        fetch_bars=fetch,
        max_n=1,
        range_="10y",
        min_bars=400,
    )
    assert out["ok"] == 1
    assert needs_bootstrap(tmp_path, "NIFTY", min_bars=400) is False


def test_bre4_uses_chatmessage(tmp_path):
    from atlas.investment.world_state import empty_wso

    seen = {}

    class FakeLLM:
        def for_role(self, role):
            return self

        def lane_busy(self):
            return False

        def chat(self, messages, **options):
            seen["messages"] = messages
            assert all(isinstance(m, ChatMessage) for m in messages)
            return LLMResponse(
                text=json.dumps(
                    {
                        "hypotheses": [
                            {
                                "symbol": "EICHERMOT.NS",
                                "kind": "open_book",
                                "statement": "Need FCF evidence",
                                "falsifiers": ["FCF missing"],
                            }
                        ],
                        "evidence_needed": [
                            {
                                "symbol": "EICHERMOT.NS",
                                "unknown": "fcf",
                                "asks": ["import FCF"],
                            }
                        ],
                        "notes": "ok",
                    }
                ),
                model="test",
            )

    w = empty_wso(symbol="EICHERMOT.NS", laboratory_id="lab")
    w["unknowns"] = ["fcf", "news"]
    doc = run_morning_hypothesis_batch(
        tmp_path,
        laboratory_id="lab",
        wsos=[w],
        plan={"candidates": [{"symbol": "TCS.NS", "rank": 1}]},
        open_symbols={"EICHERMOT.NS"},
        llm=FakeLLM(),
        max_passes=3,
    )
    assert seen.get("messages")
    assert doc.get("status") == "done"
    assert doc.get("llm") is True


def test_hourly_format():
    subj, body = format_hourly_activity_report(
        portfolio={
            "cash": 15000,
            "equity": 50000,
            "day_pnl": -10,
            "total_pnl": 70,
            "positions": [{"symbol": "CIPLA.NS", "quantity": 1, "mark": 100, "unrealized_pnl": -1}],
            "cognitive_work": {
                "quota": DEFAULT_QUOTA,
                "completed": {"belief_review": 1},
                "items": [{"kind": "belief_review", "summary": "reviewed CIPLA"}],
            },
        },
        hour=14,
        ist_date="2026-08-11",
    )
    assert "14:00" in subj
    assert "Cognitive Work" in body or "belief_review" in body
