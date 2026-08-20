"""OI-LINT0 Phase 6 — learning-first evening report."""

from __future__ import annotations

from atlas.investment.evening_learning_header import (
    BELOW_FOLD_MARKER,
    format_learning_first_header,
    format_process_metrics_below_fold,
    _packet_contradictions,
)
from atlas.investment.reports import format_evening_report, format_learned_today_section
from atlas.investment.session_notes import format_session_tick_histogram


def test_learning_first_header_order():
    lines, _, _ = format_learning_first_header(
        port={
            "portfolio_key": "india_equity_learner",
            "evolution": {"done_revisits": 1, "pending_revisits": 5, "revisits_due_today": 0},
            "evidence_delta": {"news": 2, "policy": 1},
            "curiosity_queue": {
                "items": [{"symbol": "CIPLA.NS", "unknown": "fcf", "status": "queued"}],
                "news_drain": {"resolved": 0, "unknown_explicit": 1},
            },
        },
        plan={"as_of": "2026-08-20", "phase": "learning"},
        decision_rows=[
            {
                "symbol": "CIPLA.NS",
                "action": "hold",
                "meta": {
                    "decision_decomposition": {
                        "contradictions": ["technical_buy_vs_fundamental_watch"],
                    }
                },
            }
        ],
        day_trades=[],
        buys=[],
        sells=[{"symbol": "X.NS", "quantity": 1, "price": 100, "realized_pnl": 5}],
        evo={"done_revisits": 1, "pending_revisits": 5, "revisits_due_today": 0},
        data_dir=None,
    )
    text = "\n".join(lines)
    assert text.index("Next ₹1") < text.index("Closed trades")
    assert text.index("Closed trades") < text.index("Contradictions")
    assert text.index("Contradictions") < text.index("Belief revisions")
    assert text.index("Belief revisions") < text.index("Research queue")
    assert text.index("Research queue") < text.index("LLM failures")
    assert text.index("LLM failures") < text.index("News & policy")
    assert text.index("News & policy") < text.index("Investigate tomorrow")
    assert "technical_buy_vs_fundamental_watch" in text
    assert "SELL X.NS" in text


def test_iq_below_fold_not_above_allocation():
    lines = format_learned_today_section(
        plan={"as_of": "2026-08-20", "phase": "learning"},
        portfolio={
            "portfolio_key": "india_equity_learner",
            "decisions": [{"action": "hold", "symbol": "CIPLA.NS"}],
            "process_proxies": {"process_score": 6.0},
            "meta_learning": {"intelligence_score": 17.5},
            "evolution": {"pending_revisits": 2, "done_revisits": 0},
            "fundamentals_coverage": {"symbols": 0, "with_pe": 0},
            "session_note": {"reason_counts": {"mark_only": 120, "strategy_hold": 3}},
        },
    )
    text = "\n".join(lines)
    assert BELOW_FOLD_MARKER in text
    assert text.index(BELOW_FOLD_MARKER) < text.index("Process score")
    assert text.index("Next ₹1") < text.index(BELOW_FOLD_MARKER)
    assert "Session tick histogram" in text
    assert "mark_only" in text


def test_evening_report_learning_before_morning_recap():
    _, body = format_evening_report(
        plan={"as_of": "2026-08-20", "summary": "x", "phase": "learning"},
        portfolio={
            "decisions": [{"action": "hold", "symbol": "CIPLA.NS"}],
            "evolution": {"pending_revisits": 1},
            "process_proxies": {"process_score": 5},
            "meta_learning": {"intelligence_score": 10},
        },
    )
    assert "WHAT ATLAS LEARNED TODAY" in body
    assert body.index("WHAT ATLAS LEARNED TODAY") < body.index("Morning plan recap")
    learned = body.split("Morning plan recap")[0]
    assert "Process score" not in learned or BELOW_FOLD_MARKER in learned


def test_packet_contradictions_from_decomposition():
    rows = _packet_contradictions(
        [
            {
                "symbol": "CIPLA.NS",
                "meta": {"decision_decomposition": {"contradictions": ["identity_quarantined"]}},
            }
        ]
    )
    assert any("identity_quarantined" in r for r in rows)


def test_tick_histogram_clock_last():
    lines = format_session_tick_histogram(
        {"reason_counts": {"mark_only": 50, "session_closed": 30, "switch_blocked": 2}}
    )
    text = "\n".join(lines)
    assert "mark_only" in text
    # Decision buckets before clock buckets (mark_only last among listed)
    assert text.index("Hold-vs-challenger") < text.index("mark_only")
