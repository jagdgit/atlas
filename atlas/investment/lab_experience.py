"""OI-LAB-LOOP0 Step 5 — one lab experience contract, including blocked_buy.

L10: lab · ts · instrument · state · features · action · entry/exit · P&L ·
costs · reward · regime · strategy version.

L24: a technical BUY stopped by a gate is a ``blocked_buy`` experience — not a
trade outcome and not a reward. Step 6 attaches outcome/reward to round-trips
only. Do not dump these into pgvector. Do not mutate SMA/RSI from one close.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

VERSION = "lab.loop0.experience.v1"
REWARD_VERSION = "lab.loop0.reward.v1"
LIFECYCLE_CREATED = "CREATED"
LIFECYCLE_OUTCOME = "OUTCOME"
LIFECYCLE_REWARD = "REWARD"
ACTION_BLOCKED_BUY = "blocked_buy"
ACTION_ROUND_TRIP = "round_trip"
KIND_EXPERIENCE = "EXPERIENCE"
_IST = ZoneInfo("Asia/Kolkata")

# Technical BUY converted to HOLD by a gate (not engine_hold / eod_flatten).
BLOCKED_BUY_TAGS = frozenset(
    {
        "plc_a_hold",
        "fundamentals_incomplete",
        "thesis_trigger_missing",
        "lab_policy_hold",
        "research_forced_hold",
        "research_hold",
        "pack_block",
        "policy_block",
        "add_blocked_icr0",
    }
)

STRATEGY_VERSION = "sma_cross_rsi.v1"


def ist_today() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def is_blocked_buy_tag(strategy_tag: str | None) -> bool:
    tag = str(strategy_tag or "").strip().lower()
    if tag in BLOCKED_BUY_TAGS:
        return True
    if tag.startswith("plc_a") or tag.startswith("fundamentals_"):
        return True
    if tag.startswith("add_blocked") or tag.startswith("buy_blocked"):
        return True
    return False


def _f(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fingerprint(
    *,
    laboratory_id: str,
    symbol: str,
    strategy_tag: str,
    reason: str,
    as_of_ist: str | None = None,
) -> str:
    raw = "|".join(
        [
            str(laboratory_id or ""),
            str(symbol or "").upper(),
            str(strategy_tag or "").lower(),
            str(reason or "").lower()[:160],
            as_of_ist or ist_today(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _lab_meta(laboratory_id: str, cfg: dict[str, Any] | None) -> dict[str, Any]:
    cfg = cfg if isinstance(cfg, dict) else {}
    kind = "unconstrained"
    contract = "unconstrained"
    try:
        from atlas.investment.lab_contracts import lab_kind, strategy_contract

        kind = lab_kind(laboratory_id, cfg=cfg)
        contract = strategy_contract(kind)
    except Exception:  # noqa: BLE001
        pass
    return {"lab_kind": kind, "strategy_contract": contract}


def _features(indicators: dict[str, Any] | None) -> dict[str, Any]:
    ind = indicators if isinstance(indicators, dict) else {}
    out: dict[str, Any] = {}
    for key in ("rsi", "sma_fast", "sma_slow"):
        val = _f(ind.get(key))
        if val is not None:
            out[key] = val
    for key in ("sma_fast_n", "sma_slow_n"):
        if ind.get(key) is not None:
            out[key] = ind.get(key)
    if ind.get("signal"):
        out["signal"] = ind.get("signal")
    return out


def build_blocked_buy_experience(
    *,
    laboratory_id: str,
    symbol: str,
    strategy_tag: str,
    reason: str,
    reasons_against: list[str] | None = None,
    indicators: dict[str, Any] | None = None,
    instrument: dict[str, Any] | None = None,
    gate: dict[str, Any] | None = None,
    price: float | None = None,
    cfg: dict[str, Any] | None = None,
    as_of_ist: str | None = None,
    decision_id: str | None = None,
) -> dict[str, Any]:
    """L10 row for a gated technical BUY. P&L / costs / reward stay null."""
    day = as_of_ist or ist_today()
    lab = _lab_meta(laboratory_id, cfg)
    inst = instrument if isinstance(instrument, dict) else {}
    gate_doc = dict(gate) if isinstance(gate, dict) else {}
    against = [str(x) for x in (reasons_against or []) if x][:8]
    if reason and reason not in against:
        against = [reason] + against
    tag = str(strategy_tag or "blocked_buy")
    fp = fingerprint(
        laboratory_id=laboratory_id,
        symbol=symbol,
        strategy_tag=tag,
        reason=reason,
        as_of_ist=day,
    )
    extras: dict[str, Any] = {}
    if inst.get("intraday_tape"):
        extras["intraday_tape"] = inst.get("intraday_tape")
    if inst.get("fno_contract"):
        extras["fno_contract"] = inst.get("fno_contract")
    return {
        "version": VERSION,
        "kind": KIND_EXPERIENCE,
        "experience_id": str(uuid4()),
        "event_kind": ACTION_BLOCKED_BUY,
        "lifecycle": LIFECYCLE_CREATED,
        "experience_type": ACTION_BLOCKED_BUY,
        "laboratory_id": laboratory_id,
        "as_of_ist": day,
        "instrument": {
            "symbol": str(symbol or "").upper(),
            "asset_class": inst.get("asset_class"),
            "nfo_tradingsymbol": inst.get("nfo_tradingsymbol"),
        },
        "state": {
            **lab,
            "gate": tag,
            "gate_detail": gate_doc or None,
            "mark": _f(price),
            "live_provider": str((cfg or {}).get("live_provider") or "") or None,
        },
        "features": _features(indicators),
        "action": ACTION_BLOCKED_BUY,
        "entry": None,
        "exit": None,
        "pnl": None,
        "costs": None,
        "reward": None,
        "regime": None,
        "strategy_version": STRATEGY_VERSION,
        "decision": {
            "intended_action": "buy",
            "recorded_action": "hold",
            "strategy_tag": tag,
            "decision_id": decision_id,
            "reasons_against": against,
        },
        "lab_fields": extras or None,
        "fingerprint": fp,
        "not_a_trade": True,
        "honesty": (
            "blocked_buy captures a technical BUY the lab did not take. "
            "Not a P&L outcome. Reward is Step 6. Not vector memory."
        ),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


def already_recorded(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    fingerprint_s: str,
    as_of_ist: str | None = None,
) -> bool:
    try:
        from atlas.investment.learning_objects import load_learning_events
    except Exception:  # noqa: BLE001
        return False
    for row in load_learning_events(
        data_dir, laboratory_id, as_of_ist=as_of_ist or ist_today(), limit=400
    ):
        if str(row.get("fingerprint") or "") == fingerprint_s:
            return True
    return False


def record_blocked_buy(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    symbol: str,
    strategy_tag: str,
    reason: str,
    reasons_against: list[str] | None = None,
    indicators: dict[str, Any] | None = None,
    instrument: dict[str, Any] | None = None,
    gate: dict[str, Any] | None = None,
    price: float | None = None,
    cfg: dict[str, Any] | None = None,
    as_of_ist: str | None = None,
    decision_id: str | None = None,
) -> dict[str, Any]:
    """Persist one blocked_buy per lab+symbol+gate+reason+IST day."""
    if not is_blocked_buy_tag(strategy_tag):
        return {"ok": False, "reason": "not_blocked_buy_tag"}
    day = as_of_ist or ist_today()
    fp = fingerprint(
        laboratory_id=laboratory_id,
        symbol=symbol,
        strategy_tag=strategy_tag,
        reason=reason,
        as_of_ist=day,
    )
    if already_recorded(
        data_dir, laboratory_id=laboratory_id, fingerprint_s=fp, as_of_ist=day
    ):
        return {"ok": True, "skipped": True, "reason": "duplicate_blocked_buy_same_day", "fingerprint": fp}
    exp = build_blocked_buy_experience(
        laboratory_id=laboratory_id,
        symbol=symbol,
        strategy_tag=strategy_tag,
        reason=reason,
        reasons_against=reasons_against,
        indicators=indicators,
        instrument=instrument,
        gate=gate,
        price=price,
        cfg=cfg,
        as_of_ist=day,
        decision_id=decision_id,
    )
    from atlas.investment.learning_objects import record_learning_event

    out = record_learning_event(data_dir, exp)
    out["fingerprint"] = fp
    out["skipped"] = False
    return out


def round_trip_fingerprint(
    *,
    laboratory_id: str,
    symbol: str,
    trade_id: str | None,
    quantity: float | None,
    price: float | None,
    pnl: float | None,
    as_of_ist: str | None = None,
) -> str:
    if trade_id:
        raw = "|".join([str(laboratory_id or ""), "round_trip", str(trade_id)])
    else:
        raw = "|".join(
            [
                str(laboratory_id or ""),
                "round_trip",
                str(symbol or "").upper(),
                str(quantity or ""),
                str(price or ""),
                str(pnl or ""),
                as_of_ist or ist_today(),
            ]
        )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def compute_round_trip_outcome(
    trade: dict[str, Any] | None,
    *,
    packet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Book P&L on a close. Does not invent a second FIFO truth."""
    tr = trade if isinstance(trade, dict) else {}
    pkt = packet if isinstance(packet, dict) else {}
    meta = pkt.get("meta") if isinstance(pkt.get("meta"), dict) else {}
    qty = _f(tr.get("quantity") or tr.get("qty"))
    exit_px = _f(tr.get("price") or tr.get("fill_price") or tr.get("sell_price"))
    fee = _f(tr.get("fee")) or 0.0
    pnl = _f(tr.get("realized_pnl"))
    entry_px = _f(
        tr.get("buy_price")
        or tr.get("avg_price")
        or tr.get("entry_price")
        or meta.get("entry_price")
        or meta.get("avg_price")
    )
    if entry_px is None and pnl is not None and qty and qty > 0 and exit_px is not None:
        # Ledger identity: realized = (exit - avg) * qty - sell_fee
        entry_px = round(exit_px - (pnl + fee) / qty, 6)
    notional = None
    if qty and (entry_px or exit_px):
        notional = round(qty * float(entry_px if entry_px is not None else exit_px), 4)
    fees_doc = tr.get("fees") if isinstance(tr.get("fees"), dict) else None
    return {
        "version": VERSION,
        "realized_pnl": pnl,
        "quantity": qty,
        "entry_price": entry_px,
        "exit_price": exit_px,
        "fee": fee,
        "fees": fees_doc,
        "notional": notional,
        "trade_id": tr.get("id") or tr.get("trade_id") or tr.get("sell_trade_id"),
        "buy_trade_id": tr.get("buy_trade_id"),
        "unmatched_buy": bool(tr.get("unmatched_buy")) or entry_px is None,
        "entry_at": tr.get("bought_at") or tr.get("opened_at") or meta.get("entry_at"),
        "exit_at": tr.get("sold_at") or tr.get("created_at") or tr.get("closed_at"),
        "honesty": (
            "Outcome is the simulation book's realized_pnl on the sell. "
            "Entry is avg-cost identity, not a second P&L model."
        ),
    }


def compute_reward(
    outcome: dict[str, Any] | None = None,
    *,
    experience_type: str | None = None,
    not_a_trade: bool = False,
) -> dict[str, Any] | None:
    """Deterministic paper reward. None for blocked_buy / non-trades. Not RL."""
    kind = str(experience_type or "").strip().lower()
    if not_a_trade or kind == ACTION_BLOCKED_BUY:
        return None
    oc = outcome if isinstance(outcome, dict) else {}
    pnl = _f(oc.get("realized_pnl"))
    notional = _f(oc.get("notional"))
    if pnl is None:
        return {
            "version": REWARD_VERSION,
            "schema": "net_paper_pnl_inr",
            "status": "unknown",
            "value": None,
            "return_pct": None,
            "sign": "unknown",
            "mutates_strategy": False,
            "honesty": (
                "No book realized_pnl on this close — reward not inventable. "
                "Not RL. A single close does not change SMA/RSI."
            ),
        }
    ret = None
    if notional and abs(notional) > 1e-12:
        ret = round(100.0 * pnl / notional, 4)
    if pnl > 1e-9:
        sign = "positive"
    elif pnl < -1e-9:
        sign = "negative"
    else:
        sign = "flat"
    return {
        "version": REWARD_VERSION,
        "schema": "net_paper_pnl_inr",
        "status": "computed",
        "value": round(pnl, 4),
        "return_pct": ret,
        "sign": sign,
        "components": {
            "realized_pnl": round(pnl, 4),
            "fee": oc.get("fee"),
            "notional": notional,
            "quantity": oc.get("quantity"),
        },
        "mutates_strategy": False,
        "honesty": (
            "Reward is book realized P&L after the recorded sell fee. "
            "Not RL. A single close does not change SMA/RSI."
        ),
    }


def attach_round_trip_l10(
    exp: dict[str, Any],
    *,
    laboratory_id: str,
    symbol: str,
    trade: dict[str, Any] | None = None,
    packet: dict[str, Any] | None = None,
    indicators: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    as_of_ist: str | None = None,
) -> dict[str, Any]:
    """Fill L10 outcome + reward on a close EXPERIENCE. Does not mutate strategy."""
    row = dict(exp) if isinstance(exp, dict) else {}
    pkt = packet if isinstance(packet, dict) else {}
    tr = trade if isinstance(trade, dict) else {}
    meta = pkt.get("meta") if isinstance(pkt.get("meta"), dict) else {}
    inst: dict[str, Any] = {}
    if isinstance(meta.get("instrument"), dict):
        inst = meta["instrument"]
    elif isinstance(tr.get("instrument"), dict):
        inst = tr["instrument"]
    snap = pkt.get("market_snapshot") if isinstance(pkt.get("market_snapshot"), dict) else {}
    oc = compute_round_trip_outcome(tr, packet=pkt)
    reward = compute_reward(oc, experience_type=ACTION_ROUND_TRIP)
    lab = _lab_meta(laboratory_id, cfg)
    feats = _features(indicators)
    if not feats:
        feats = _features(
            meta.get("indicators") if isinstance(meta.get("indicators"), dict) else None
        )
    extras: dict[str, Any] = {}
    tape = inst.get("intraday_tape") or snap.get("intraday_tape") or meta.get("intraday_tape")
    if tape:
        extras["intraday_tape"] = tape
    fut = inst.get("fno_contract") or meta.get("fno_contract")
    if fut:
        extras["fno_contract"] = fut
    # Lab v1 experiment attribution + Core stamp (must survive into EXPERIENCE).
    fno_att = pkt.get("fno_lab_v1") if isinstance(pkt.get("fno_lab_v1"), dict) else None
    if fno_att:
        extras["fno_lab_v1"] = fno_att
        if fno_att.get("option_contract") and not extras.get("fno_contract"):
            extras["fno_contract"] = {
                "tradingsymbol": fno_att.get("option_contract"),
                "instrument_type": fno_att.get("option_type"),
                "underlying": fno_att.get("underlying"),
                "experiment_family": fno_att.get("experiment_family"),
            }
    cog = pkt.get("cognitive") if isinstance(pkt.get("cognitive"), dict) else None
    if cog is None and isinstance(fno_att, dict):
        cog = fno_att.get("cognitive") if isinstance(fno_att.get("cognitive"), dict) else None
    if cog:
        extras["cognitive"] = cog
        extras["cognitive_review"] = cog.get("cognitive_review") or "UNREVIEWED"
    elif fno_att and fno_att.get("cognitive_review"):
        extras["cognitive_review"] = fno_att.get("cognitive_review")
    if pkt.get("mark_source"):
        extras["mark_source"] = pkt.get("mark_source")
    if pkt.get("exit_reason"):
        extras["exit_reason"] = pkt.get("exit_reason")
    if isinstance(pkt.get("entry_prediction"), dict):
        extras["entry_prediction"] = pkt["entry_prediction"]
    if isinstance(pkt.get("expected"), dict) and pkt["expected"].get("prediction_status"):
        extras["expected"] = pkt["expected"]
    lineage = pkt.get("evidence_lineage") if isinstance(pkt.get("evidence_lineage"), dict) else None
    if lineage is None:
        try:
            from atlas.investment.evidence_lineage import build_evidence_lineage

            lineage = build_evidence_lineage(
                decision_id=str(pkt.get("decision_id") or pkt.get("id") or "") or None,
                prediction=pkt.get("expected") if isinstance(pkt.get("expected"), dict) else None,
                observation_ids=list(pkt.get("observation_ids") or []),
                market_snapshot=snap or None,
            )
        except Exception:  # noqa: BLE001
            lineage = None
    fp = round_trip_fingerprint(
        laboratory_id=laboratory_id,
        symbol=symbol,
        trade_id=str(oc.get("trade_id") or "") or None,
        quantity=oc.get("quantity"),
        price=oc.get("exit_price"),
        pnl=oc.get("realized_pnl"),
        as_of_ist=as_of_ist or str(row.get("as_of_ist") or "") or ist_today(),
    )
    lifecycle = (
        LIFECYCLE_REWARD
        if reward and reward.get("status") == "computed"
        else LIFECYCLE_OUTCOME
    )
    row["experience_type"] = ACTION_ROUND_TRIP
    row["lifecycle"] = lifecycle
    row["instrument"] = {
        "symbol": str(symbol or "").upper(),
        "asset_class": inst.get("asset_class"),
        "nfo_tradingsymbol": inst.get("nfo_tradingsymbol"),
    }
    row["state"] = {
        **lab,
        "live_provider": str((cfg or {}).get("live_provider") or meta.get("live_provider") or "")
        or None,
        "unmatched_buy": oc.get("unmatched_buy"),
    }
    row["features"] = feats
    row["action"] = str(tr.get("side") or pkt.get("action") or "sell").lower()
    row["entry"] = (
        {
            "price": oc.get("entry_price"),
            "at": oc.get("entry_at"),
            "trade_id": oc.get("buy_trade_id"),
        }
        if oc.get("entry_price") is not None or oc.get("entry_at")
        else None
    )
    row["exit"] = {
        "price": oc.get("exit_price"),
        "at": str(oc.get("exit_at") or ""),
        "trade_id": oc.get("trade_id"),
    }
    row["pnl"] = oc.get("realized_pnl")
    row["costs"] = {
        "fee": oc.get("fee"),
        "fees": oc.get("fees"),
        "notional": oc.get("notional"),
    }
    row["reward"] = reward
    row["regime"] = meta.get("regime") or snap.get("regime")
    row["strategy_version"] = STRATEGY_VERSION
    row["lab_fields"] = extras or None
    row["evidence_lineage"] = lineage
    row["fingerprint"] = fp
    row["not_a_trade"] = False
    row["honesty"] = (
        "Round-trip close writes OUTCOME+REWARD on the existing EXPERIENCE row. "
        "Reward is book P&L. blocked_buy is not rewarded. Not vector memory. Not RL."
    )
    return row
