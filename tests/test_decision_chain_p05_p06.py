"""OI-DELI0 P0.5 / P0.6 — exit + overlay decision minting."""

from __future__ import annotations

import json
from pathlib import Path

from atlas.investment.decision_chain import (
    TRADE_CLASS_CONTROLLED_EXPERIMENT,
    mint_exit_decision,
    mint_overlay_buy_decision,
)
from atlas.investment.decision_packets import DecisionPacketStore
from atlas.investment.trade_lineage import (
    build_order_intent,
    resolve_open_entry_from_lineage,
    write_trade_lineage,
)


def test_p06_overlay_buy_has_parent_engine_and_controlled_class(tmp_path) -> None:
    store = DecisionPacketStore(data_dir=str(tmp_path))
    out = mint_overlay_buy_decision(
        store,
        symbol="NIFTY26OCT22550PE",
        portfolio_key="india_fno_learner",
        engine_decision_id="engine-hold-id",
        rationale="ATM PE adapter",
        price=264.5,
        quantity=65,
    )
    assert out["ok"] is True
    assert out["decision_id"]
    assert out["decision_id"] != "engine-hold-id"
    assert out["parent_decision_id"] == "engine-hold-id"
    assert out["trade_class"] == TRADE_CLASS_CONTROLLED_EXPERIMENT
    packet = store.get(out["decision_id"])
    assert packet is not None
    assert packet["action"] == "buy"
    assert packet["parent_decision_id"] == "engine-hold-id"
    assert packet["engine_decision_id"] == "engine-hold-id"
    assert packet["meta"]["trade_class"] == TRADE_CLASS_CONTROLLED_EXPERIMENT
    # Must not present engine HOLD as the buy's own identity
    assert packet["decision_id"] != packet["engine_decision_id"]


def test_p05_exit_decision_carries_reason(tmp_path) -> None:
    store = DecisionPacketStore(data_dir=str(tmp_path))
    out = mint_exit_decision(
        store,
        symbol="TRENT.NS",
        portfolio_key="india_equity_learner",
        exit_reason_code="eod_flatten",
        rationale="flat overnight",
        price=5000.0,
        quantity=1.0,
    )
    assert out["ok"] is True
    assert out["exit_reason_code"] == "eod_flatten"
    packet = store.get(out["decision_id"])
    assert packet["action"] == "sell"
    assert packet["meta"]["exit_reason_code"] == "eod_flatten"


def test_mint_without_store_is_safe() -> None:
    assert mint_exit_decision(None, symbol="X", portfolio_key="y", exit_reason_code="z")[
        "ok"
    ] is False
    assert mint_overlay_buy_decision(
        None, symbol="X", portfolio_key="y", engine_decision_id="e"
    )["ok"] is False


def test_resolve_open_entry_links_sell_to_buy(tmp_path: Path) -> None:
    lab = "india_fno_learner"
    sym = "NIFTY26OCT22500PE"
    buy_intent = build_order_intent(
        side="buy",
        symbol=sym,
        quantity=65,
        price=249.3,
        rationale_source="fno_overlay",
        engine_decision_id="engine-hold",
        engine_action="hold",
        overlay_decision_id="overlay-buy",
        overlay_used=True,
        laboratory_id=lab,
    )
    write_trade_lineage(
        tmp_path,
        trade={
            "id": "buy-fill",
            "symbol": sym,
            "side": "buy",
            "quantity": 65,
            "price": 249.3,
            "decision_id": "overlay-buy",
        },
        laboratory_id=lab,
        order_intent=buy_intent,
        entry_decision_id="overlay-buy",
        overlay_decision_id="overlay-buy",
        parent_decision_id="engine-hold",
    )
    resolved = resolve_open_entry_from_lineage(
        tmp_path, laboratory_id=lab, symbol=sym
    )
    assert resolved["entry_decision_id"] == "overlay-buy"
    assert resolved["parent_decision_id"] == "engine-hold"

    store = DecisionPacketStore(data_dir=str(tmp_path))
    minted = mint_exit_decision(
        store,
        symbol=sym,
        portfolio_key=lab,
        exit_reason_code="fno_lab_v1_experiment_close",
        parent_decision_id=resolved["entry_decision_id"],
        price=104.1,
        quantity=65,
    )
    sell_intent = build_order_intent(
        side="sell",
        symbol=sym,
        quantity=65,
        price=104.1,
        rationale_source="experiment_close",
        laboratory_id=lab,
        instrument_path="fno_lab_v1_experiment_close",
        overlay_decision_id=resolved["overlay_decision_id"],
    )
    out = write_trade_lineage(
        tmp_path,
        trade={
            "id": "sell-fill",
            "symbol": sym,
            "side": "sell",
            "quantity": 65,
            "price": 104.1,
            "decision_id": minted["decision_id"],
        },
        laboratory_id=lab,
        order_intent=sell_intent,
        entry_decision_id=resolved["entry_decision_id"],
        overlay_decision_id=resolved["overlay_decision_id"],
        parent_decision_id=resolved["parent_decision_id"],
        exit_decision_id=minted["decision_id"],
        exit_reason_code="fno_lab_v1_experiment_close",
    )
    assert out["ok"] is True
    assert out["lineage_incomplete"] is False
    assert out["integrity_issues"] == []
    # After sell, no open lot remains.
    assert (
        resolve_open_entry_from_lineage(tmp_path, laboratory_id=lab, symbol=sym)[
            "entry_decision_id"
        ]
        is None
    )
    day_files = list(
        (tmp_path / "investment" / "trade_lineage" / lab).glob("*.jsonl")
    )
    assert day_files
    rows = [
        json.loads(line)
        for line in day_files[0].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    sell = next(r for r in rows if r["side"] == "sell")
    assert sell["entry_decision_id"] == "overlay-buy"
    assert sell["exit_decision_id"] == minted["decision_id"]


def test_sell_without_entry_is_incomplete(tmp_path: Path) -> None:
    out = write_trade_lineage(
        tmp_path,
        trade={
            "id": "orphan-sell",
            "symbol": "TCS26OCT2200PE",
            "side": "sell",
            "quantity": 1,
            "price": 23.0,
        },
        laboratory_id="india_fno_learner",
        order_intent=build_order_intent(
            side="sell",
            symbol="TCS26OCT2200PE",
            quantity=1,
            rationale_source="experiment_close",
        ),
        exit_decision_id="exit-1",
        exit_reason_code="fno_lab_v1_experiment_close",
    )
    assert out["ok"] is True
    assert out["lineage_incomplete"] is True
    assert "missing_entry_decision_id" in out["integrity_issues"]
