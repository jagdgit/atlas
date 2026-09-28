"""OI-ICR0 — NO ADD / AVOID / quarantine capital safety."""

from __future__ import annotations

import json
from pathlib import Path

from atlas.investment.incumbent_capital import (
    REASON_ADD_BLOCKED_DUPLICATE_STATE,
    REASON_ADD_BLOCKED_NO_ACP,
    REASON_ADD_BLOCKED_QUARANTINE,
    REASON_ADD_BLOCKED_RESEARCH,
    REASON_BUY_BLOCKED_QUARANTINE,
    REASON_BUY_BLOCKED_RESEARCH,
    acp_path,
    allocation_state_hash,
    evaluate_icr0_buy,
    icr0_enabled,
)


_AVOID_AW = {
    "thesis": {
        "stance": "avoid",
        "summary": "PE rich vs fair; avoid new capital.",
        "id": "th-CIPLA.NS",
    }
}

_QUARANTINE_AW = {
    "thesis": {
        "stance": "WATCH",
        "summary": (
            "CIPLA is a branded hospital network. Occupancy, ARPOB, doctor "
            "retention and bed expansion ROIC drive returns."
        ),
        "id": "th-CIPLA.NS",
    }
}

_CLEAN_AW = {
    "thesis": {
        "stance": "BUY",
        "summary": (
            "Cipla India branded generics and respiratory franchise; "
            "US ANDA execution remains the swing factor."
        ),
        "id": "th-CIPLA.NS",
    }
}


def test_icr0_enabled_swing_default():
    assert icr0_enabled({}, "india_equity_learner") is True
    assert icr0_enabled({}, "india_fno_learner") is False
    assert icr0_enabled({}, "equity_intraday_learner") is False
    assert icr0_enabled({"icr0_enabled": False}, "india_equity_learner") is False


def test_icr0_avoid_blocks_new_buy_and_add():
    fresh = evaluate_icr0_buy(
        laboratory_id="india_equity_learner",
        symbol="CIPLA.NS",
        held=0.0,
        awareness=_AVOID_AW,
    )
    assert fresh["allowed"] is False
    assert fresh["reason_code"] == REASON_BUY_BLOCKED_RESEARCH

    add = evaluate_icr0_buy(
        laboratory_id="india_equity_learner",
        symbol="CIPLA.NS",
        held=15.0,
        awareness=_AVOID_AW,
    )
    assert add["allowed"] is False
    assert add["reason_code"] == REASON_ADD_BLOCKED_RESEARCH


def test_icr0_quarantine_blocks_buy_and_add():
    fresh = evaluate_icr0_buy(
        laboratory_id="india_equity_learner",
        symbol="CIPLA.NS",
        held=0.0,
        awareness=_QUARANTINE_AW,
    )
    assert fresh["allowed"] is False
    assert fresh["reason_code"] == REASON_BUY_BLOCKED_QUARANTINE

    add = evaluate_icr0_buy(
        laboratory_id="india_equity_learner",
        symbol="CIPLA.NS",
        held=15.0,
        awareness=_QUARANTINE_AW,
    )
    assert add["allowed"] is False
    assert add["reason_code"] == REASON_ADD_BLOCKED_QUARANTINE


def test_icr0_add_requires_acp_even_when_clean(tmp_path: Path):
    gate = evaluate_icr0_buy(
        laboratory_id="india_equity_learner",
        symbol="CIPLA.NS",
        held=15.0,
        awareness=_CLEAN_AW,
        data_dir=tmp_path,
    )
    assert gate["allowed"] is False
    assert gate["reason_code"] == REASON_ADD_BLOCKED_NO_ACP
    assert gate["state_hash"]


def test_icr0_add_allowed_with_acp_decision_add(tmp_path: Path):
    h = allocation_state_hash(
        laboratory_id="india_equity_learner",
        symbol="CIPLA.NS",
        held=15.0,
        stance="BUY",
        identity="VALID",
    )
    path = acp_path(tmp_path, "india_equity_learner", "CIPLA.NS", h)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "decision": "ADD",
                "state_hash": h,
                "version": "icr.1.test",
            }
        ),
        encoding="utf-8",
    )
    gate = evaluate_icr0_buy(
        laboratory_id="india_equity_learner",
        symbol="CIPLA.NS",
        held=15.0,
        awareness=_CLEAN_AW,
        data_dir=tmp_path,
        seen_state_hashes=set(),
    )
    assert gate["allowed"] is True
    assert gate["state_hash"] == h


def test_icr0_same_state_duplicate_add_blocked(tmp_path: Path):
    h = allocation_state_hash(
        laboratory_id="india_equity_learner",
        symbol="CIPLA.NS",
        held=15.0,
        stance="BUY",
        identity="VALID",
    )
    path = acp_path(tmp_path, "india_equity_learner", "CIPLA.NS", h)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"decision": "ADD", "state_hash": h}), encoding="utf-8")
    seen = {h}
    gate = evaluate_icr0_buy(
        laboratory_id="india_equity_learner",
        symbol="CIPLA.NS",
        held=15.0,
        awareness=_CLEAN_AW,
        data_dir=tmp_path,
        seen_state_hashes=seen,
    )
    assert gate["allowed"] is False
    assert gate["reason_code"] == REASON_ADD_BLOCKED_DUPLICATE_STATE


def test_icr0_fresh_buy_allowed_when_clean():
    gate = evaluate_icr0_buy(
        laboratory_id="india_equity_learner",
        symbol="CIPLA.NS",
        held=0.0,
        awareness=_CLEAN_AW,
    )
    assert gate["allowed"] is True
    assert gate["reason_code"] is None


def test_icr0_disabled_for_fno():
    gate = evaluate_icr0_buy(
        laboratory_id="india_fno_learner",
        symbol="NIFTY",
        held=50.0,
        awareness=_AVOID_AW,
    )
    assert gate["allowed"] is True
