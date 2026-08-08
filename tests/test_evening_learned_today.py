"""Evening learned-today section + process journal completeness fix."""

from __future__ import annotations

from atlas.investment.decision_packets import build_packet
from atlas.investment.process_proxies import detect_packet_flags
from atlas.investment.reports import format_evening_report, format_learned_today_section


def test_process_flags_see_real_completeness():
    pkt = build_packet(
        action="hold",
        symbol="INFY.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="engine_hold",
        reasons_for=["no actionable signal"],
        plan_link={"in_daily_plan": False},
        process_context={"gap_pct": None, "recent_losses": set()},
    )
    comp = float((pkt.get("meta") or {}).get("completeness") or 0)
    assert comp > 0.25
    flags = {f["proxy"] for f in ((pkt.get("meta") or {}).get("process_flags") or [])}
    assert "journal_incomplete" not in flags


def test_hold_with_reason_not_journal_incomplete_on_redetect():
    pkt = build_packet(
        action="hold",
        symbol="ITC.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="engine_hold",
        reasons_for=["no actionable signal"],
    )
    # Simulate re-detect path used by scorecard when flags missing
    flags = detect_packet_flags(
        {**pkt, "meta": pkt.get("meta")},
        plan=None,
        recent_losses=set(),
    )
    assert not any(f.get("proxy") == "journal_incomplete" for f in flags)


def test_learned_today_section_in_evening():
    pkt = build_packet(
        action="buy",
        symbol="CIPLA.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="sma_cross_rsi",
        reasons_for=["sma cross"],
        plan_link={"in_daily_plan": True, "rank": 3},
    )
    lines = format_learned_today_section(
        plan={
            "phase": "learning",
            "confidence": "very_low",
            "candidates": [{"symbol": "CIPLA.NS", "rank": 1}],
            "avoids": [{"symbol": "AXISBANK.NS"}],
        },
        portfolio={
            "decisions": [pkt],
            "recent_trades": [
                {"side": "buy", "symbol": "CIPLA.NS", "quantity": 1, "price": 1400, "ist_day_match": True}
            ],
            "positions": [
                {"symbol": "CIPLA.NS", "quantity": 1, "avg_price": 1400, "mark": 1477, "unrealized_pnl": 77}
            ],
            "kpis": {"sells_today": 0, "phase": "learning"},
            "evolution": {"pending_revisits": 16, "done_revisits": 0},
            "fundamentals_coverage": {
                "symbols": 0,
                "with_pe": 0,
                "learner_gaps": {"symbols_with_gaps": 5, "symbols_checked": 5},
            },
            "process_proxies": {"process_score": 6.0},
            "meta_learning": {"intelligence_score": 17.5},
            "observations": [{"id": "o1"}],
        },
    )
    text = "\n".join(lines)
    assert "WHAT ATLAS LEARNED TODAY" in text
    assert "Day learning grade:" in text
    assert "When Atlas sells" in text
    assert "CIPLA.NS" in text
    assert "Import PE/FCF" in text
    assert "Decision Evolution" in text

    _subj, body = format_evening_report(
        plan={"as_of": "2026-08-06", "summary": "x", "phase": "learning", "confidence": "very_low"},
        portfolio={
            "cash": 1,
            "decisions": [pkt],
            "fundamentals_coverage": {"symbols": 0, "with_pe": 0},
            "evolution": {"pending_revisits": 2, "done_revisits": 0},
        },
        decisions=[pkt],
    )
    assert "WHAT ATLAS LEARNED TODAY" in body
    assert body.index("WHAT ATLAS LEARNED TODAY") < body.index("Morning plan recap")
