"""OI-DELI0 P0.5 / P0.6 — exit and overlay decision minting.

P0.5: every sell path gets an exit decision id + durable trigger/reason.
P0.6: F&O overlay BUY gets its own decision; engine decision is parent;
trade class ``CONTROLLED_EXPERIMENT``. Does not change control behaviour.
"""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger("atlas.investment.decision_chain")

TRADE_CLASS_CONTROLLED_EXPERIMENT = "CONTROLLED_EXPERIMENT"
OVERLAY_STRATEGY_TAG = "fno_atm_overlay"


def _packet_id(saved: dict[str, Any] | None) -> str | None:
    if not isinstance(saved, dict):
        return None
    packet = saved.get("packet") if isinstance(saved.get("packet"), dict) else saved
    did = packet.get("decision_id") or packet.get("id")
    return str(did) if did else None


def mint_overlay_buy_decision(
    store: Any,
    *,
    symbol: str,
    portfolio_key: str,
    engine_decision_id: str | None,
    rationale: str | None = None,
    price: float | None = None,
    quantity: float | None = None,
    expected: dict[str, Any] | None = None,
    mission_id: Any = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """Mint the overlay's own BUY decision (engine = parent)."""
    log = logger or _log
    if store is None:
        return {"ok": False, "reason": "no_store"}
    try:
        saved = store.record(
            action="buy",
            symbol=symbol,
            portfolio_key=portfolio_key or "india_fno_learner",
            strategy_tag=OVERLAY_STRATEGY_TAG,
            mission_id=str(mission_id) if mission_id else None,
            parent_decision_id=str(engine_decision_id) if engine_decision_id else None,
            engine_decision_id=str(engine_decision_id) if engine_decision_id else None,
            reasons_for=[
                str(rationale or "F&O ATM overlay BUY — CONTROLLED_EXPERIMENT")
            ],
            expected=expected if isinstance(expected, dict) else None,
            prices={"mark": price, "intent": price} if price is not None else None,
            meta_extra={
                "trade_class": TRADE_CLASS_CONTROLLED_EXPERIMENT,
                "ownership": "fno_overlay",
                "quantity_intent": quantity,
                "engine_hold_not_buy_rationale": True,
            },
        )
        did = _packet_id(saved)
        return {
            "ok": bool(did),
            "decision_id": did,
            "parent_decision_id": str(engine_decision_id) if engine_decision_id else None,
            "trade_class": TRADE_CLASS_CONTROLLED_EXPERIMENT,
            "saved": saved,
        }
    except Exception as exc:  # noqa: BLE001
        log.exception("overlay buy decision mint failed")
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}


def mint_exit_decision(
    store: Any,
    *,
    symbol: str,
    portfolio_key: str,
    exit_reason_code: str,
    rationale: str | None = None,
    price: float | None = None,
    quantity: float | None = None,
    parent_decision_id: str | None = None,
    mission_id: Any = None,
    strategy_tag: str | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """Mint an exit decision for a sell path that would otherwise have null id."""
    log = logger or _log
    if store is None:
        return {"ok": False, "reason": "no_store"}
    code = str(exit_reason_code or "exit").strip() or "exit"
    try:
        saved = store.record(
            action="sell",
            symbol=symbol,
            portfolio_key=portfolio_key or "unknown",
            strategy_tag=str(strategy_tag or code),
            mission_id=str(mission_id) if mission_id else None,
            parent_decision_id=str(parent_decision_id) if parent_decision_id else None,
            reasons_for=[str(rationale or code)],
            prices={"mark": price, "intent": price} if price is not None else None,
            meta_extra={
                "exit_reason_code": code,
                "quantity_intent": quantity,
                "ownership": "exit_path",
            },
        )
        did = _packet_id(saved)
        return {
            "ok": bool(did),
            "decision_id": did,
            "exit_reason_code": code,
            "saved": saved,
        }
    except Exception as exc:  # noqa: BLE001
        log.exception("exit decision mint failed")
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
