"""OI-DELI0 P0.4 — trade lineage + order intent (shadow)."""

from __future__ import annotations

import json
from pathlib import Path

from atlas.investment.trade_lineage import (
    build_order_intent,
    content_hash,
    shadow_after_fill,
    write_trade_lineage,
)


def test_order_intent_never_uses_engine_hold_as_buy_source() -> None:
    intent = build_order_intent(
        side="buy",
        symbol="NIFTY26OCT22550PE",
        quantity=65,
        price=264.5,
        rationale_source="engine",
        rationale_text="engine HOLD",
        engine_decision_id="dec-hold",
        engine_action="hold",
        overlay_used=True,
    )
    assert intent["rationale_source"] == "fno_overlay"
    assert intent["engine_action"] == "hold"
    assert intent["order_intent_id"]
    assert intent["content_hash"] == content_hash(
        {k: v for k, v in intent.items() if k != "content_hash"}
    )


def test_hold_linked_as_entry_buy_is_flagged(tmp_path: Path) -> None:
    intent = build_order_intent(
        side="buy",
        symbol="NIFTY26OCT22550PE",
        quantity=65,
        price=264.5,
        rationale_source="fno_overlay",
        rationale_text="ATM PE adapter",
        engine_decision_id="dec-hold",
        engine_action="hold",
        overlay_used=True,
    )
    trade = {
        "id": "fill-1",
        "symbol": "NIFTY26OCT22550PE",
        "side": "buy",
        "quantity": 65,
        "price": 264.5,
        "decision_id": "dec-hold",
    }
    # Wrong: pass engine HOLD as entry_decision_id with no overlay id.
    out = write_trade_lineage(
        tmp_path,
        trade=trade,
        laboratory_id="india_fno_learner",
        order_intent=intent,
        entry_decision_id="dec-hold",
        overlay_decision_id=None,
        parent_decision_id=None,
    )
    assert out["ok"] is True
    assert out["lineage_incomplete"] is True
    # Demoted to parent; entry cleared
    day = out.get("path") and Path(out["path"])
    assert day and day.is_file()
    row = json.loads(day.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert row["parent_decision_id"] == "dec-hold"
    assert row["entry_decision_id"] is None
    assert "engine_hold_linked_as_entry_buy" in row["integrity_issues"] or row[
        "lineage_incomplete"
    ]


def test_missing_order_intent_is_explicit(tmp_path: Path) -> None:
    trade = {
        "id": "fill-2",
        "symbol": "TRENT.NS",
        "side": "buy",
        "quantity": 1,
        "price": 100.0,
        "decision_id": "dec-buy",
    }
    out = write_trade_lineage(
        tmp_path,
        trade=trade,
        laboratory_id="india_equity_learner",
        order_intent=None,
        entry_decision_id="dec-buy",
    )
    assert out["ok"] is True
    assert out["lineage_incomplete"] is True
    assert "missing_order_intent" in out["integrity_issues"]
    incomplete = (
        tmp_path
        / "investment"
        / "integrity"
        / "lineage_incomplete"
        / "india_equity_learner"
    )
    assert any(incomplete.glob("*.jsonl"))


def test_write_failure_does_not_raise(tmp_path: Path, monkeypatch) -> None:
    trade = {"id": "fill-3", "symbol": "X", "side": "buy", "quantity": 1, "price": 1}

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(
        "atlas.investment.trade_lineage._append_jsonl",
        boom,
    )
    out = write_trade_lineage(
        tmp_path,
        trade=trade,
        laboratory_id="lab",
        order_intent=build_order_intent(
            side="buy",
            symbol="X",
            quantity=1,
            rationale_source="engine",
            engine_action="buy",
        ),
        entry_decision_id="d1",
    )
    assert out["ok"] is False
    assert out["lineage_incomplete"] is True


def test_shadow_after_fill_never_raises(tmp_path: Path) -> None:
    out = shadow_after_fill(
        trade={"id": "f", "side": "sell", "symbol": "Y", "quantity": 1, "price": 2},
        data_dir=tmp_path,
        laboratory_id="lab",
        lineage_ctx=None,
    )
    assert out.get("lineage_incomplete") is True
    issues = out.get("integrity_issues") or []
    assert "missing_order_intent" in issues
    assert "missing_entry_decision_id" in issues
    assert "missing_exit_decision_id" in issues


def test_complete_buy_lineage_ok(tmp_path: Path) -> None:
    intent = build_order_intent(
        side="buy",
        symbol="TRENT.NS",
        quantity=2,
        price=5000.0,
        rationale_source="engine",
        rationale_text="SMA cross",
        engine_decision_id="dec-buy",
        engine_action="buy",
    )
    out = write_trade_lineage(
        tmp_path,
        trade={
            "id": "fill-ok",
            "symbol": "TRENT.NS",
            "side": "buy",
            "quantity": 2,
            "price": 5000.0,
            "decision_id": "dec-buy",
        },
        laboratory_id="india_equity_learner",
        order_intent=intent,
        entry_decision_id="dec-buy",
        prediction_id="pred-1",
        evidence_snapshot={"as_of": "2026-10-12T10:00:00+05:30", "spot": 5000},
    )
    assert out["ok"] is True
    assert out["lineage_incomplete"] is False
    assert out["integrity_issues"] == []
