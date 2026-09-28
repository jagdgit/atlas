"""OI-CU0 CU.B — learning story / prediction_absent / technical_only."""

from __future__ import annotations

from atlas.investment.decision_packets import build_packet
from atlas.investment.learning_objects import record_from_trade_close
from atlas.investment.learning_story import (
    STORY_KIND,
    build_learning_story,
    format_learning_story_lines,
    is_qualifying_close,
    stamp_packet_prediction,
    summarize_learning_stories,
)


def test_stamp_prediction_absent_when_empty():
    out = stamp_packet_prediction({}, action="hold")
    assert out["prediction_status"] == "prediction_absent"
    assert out.get("expected_return") is None


def test_stamp_prediction_stated_on_buy_action():
    out = stamp_packet_prediction({}, action="buy")
    assert out["prediction_status"] == "stated"
    assert out["expected_direction"] == "up"


def test_build_packet_stamps_prediction():
    pkt = build_packet(
        action="hold",
        symbol="CIPLA.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="engine_hold",
        reasons_for=["idle"],
    )
    assert pkt["expected"]["prediction_status"] == "prediction_absent"

    buy = build_packet(
        action="buy",
        symbol="ASTRAL.NS",
        portfolio_key="equity_intraday_learner",
        strategy_tag="sma_cross_rsi",
        reasons_for=["cross"],
        expected={"expected_return": 0.02},
        meta_extra={
            "decision_decomposition": {
                "lab_policy": "technical_only",
                "fundamental_thesis": "WATCH",
                "technical_signal": "BUY",
                "contradictions": ["technical_buy_vs_fundamental_watch"],
            }
        },
    )
    assert buy["expected"]["prediction_status"] == "stated"
    assert buy["expected"]["expected_return"] == 0.02


def test_qualifying_close_and_no_vanity():
    assert is_qualifying_close(event_kind="exit", trade={"side": "sell", "realized_pnl": -1})
    assert not is_qualifying_close(event_kind="outcome_check", action="hold")


def test_record_close_writes_story(tmp_path):
    pkt = build_packet(
        action="buy",
        symbol="ASTRAL.NS",
        portfolio_key="equity_intraday_learner",
        strategy_tag="sma_cross_rsi",
        reasons_for=["cross"],
        expected={"expected_return": 0.01, "expected_direction": "up"},
        meta_extra={
            "decision_decomposition": {
                "lab_policy": "technical_only",
                "fundamental_thesis": "WATCH",
                "technical_signal": "BUY",
                "contradictions": ["technical_buy_vs_fundamental_watch"],
            }
        },
    )
    # Persist packet so resolve can find it if needed
    day = pkt["ts_ist"]
    pdir = tmp_path / "investment" / "decisions" / "by_day" / "equity_intraday_learner"
    pdir.mkdir(parents=True)
    (pdir / f"{day}.jsonl").write_text(
        __import__("json").dumps(pkt) + "\n", encoding="utf-8"
    )

    trade = {
        "side": "sell",
        "quantity": 5,
        "price": 1540.0,
        "realized_pnl": -19.7,
        "id": "t-astral-1",
    }
    out = record_from_trade_close(
        tmp_path,
        symbol="ASTRAL.NS",
        trade=trade,
        laboratory_id="equity_intraday_learner",
        packet=pkt,
        strategy_tag="sma_cross_rsi",
    )
    assert out.get("ok") is True
    story = out.get("learning_story") or {}
    assert story.get("skipped") is False

    from atlas.investment.learning_objects import load_learning_events

    evs = load_learning_events(tmp_path, "equity_intraday_learner")
    stories = [e for e in evs if e.get("kind") == STORY_KIND]
    assert len(stories) == 1
    s = stories[0]
    assert s["prediction"]["status"] == "stated"
    assert s["cause"]["status"] in {"unknown_explicit", "attributed", "all_unknown"}
    assert s.get("contradiction_context", {}).get("decision_source") == "technical_only"
    assert "not silently rewrite" in (s.get("contradiction_context") or {}).get("rule") or s.get(
        "belief_note"
    )

    lines = format_learning_story_lines(evs)
    text = "\n".join(lines)
    assert "Learning stories" in text
    assert "ASTRAL" in text


def test_no_story_lines_when_no_closes():
    lines = format_learning_story_lines([])
    assert "no qualifying learning story today" in "\n".join(lines)
    assert summarize_learning_stories([]).get("stories") == 0
