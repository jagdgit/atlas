"""LOOP0 L3 — outcome_check + genealogical belief candidates.

Revisit already exists. This slice writes a durable causal chain:

    decision → expected direction → observed direction → thesis change
    → optional belief *candidate* (never auto-active).

Thin evidence yields an explicit skip, not a slogan.
"""

from __future__ import annotations

import logging
from typing import Any

VERSION = "loop0.l3.outcome_revision.v1"
INFLUENCE = "advice_only"
THIN_MOVE_PCT = 1.0
MATERIAL_MISS_PCT = 2.0
FALSIFIER_DROP_PCT = 8.0

_log = logging.getLogger("atlas.reasoning.outcome_revision")

_HORIZON = {
    "day1": "1d",
    "day3": "3d",
    "week1": "7d",
    "7d": "7d",
    "day14": "14d",
    "month1": "30d",
    "30d": "30d",
    "quarter": "90d",
    "90d": "90d",
    "exit": "exit",
    "open_book": "session",
}


def _f(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sign_direction(pct: float | None, *, deadband: float = THIN_MOVE_PCT) -> str:
    if pct is None:
        return "unknown"
    if pct > deadband:
        return "up"
    if pct < -deadband:
        return "down"
    return "flat"


def _expected_direction(packet: dict[str, Any]) -> str:
    action = str(packet.get("action") or "").strip().lower()
    expected = packet.get("expected") if isinstance(packet.get("expected"), dict) else {}
    er = _f(expected.get("expected_return"))
    band = str(expected.get("return_band") or expected.get("vs_index") or "").lower()
    if er is not None:
        if er > 0.002:
            return "up"
        if er < -0.002:
            return "down"
        return "flat"
    if "outperform" in band or band in {"up", "long", "positive"}:
        return "up"
    if "underperform" in band or band in {"down", "short", "negative"}:
        return "down"
    if action == "buy":
        return "up"
    if action in {"sell", "reduce"}:
        return "down"
    return "unknown"


def _thesis_change(what: dict[str, Any], *, direction_match: str) -> str:
    early = str(what.get("early_vs_wrong") or "")
    status = str(what.get("thesis_status") or "").lower()
    improved = what.get("thesis_improved")
    if early in {"thesis_weakening"} or status in {"weakening", "broken", "falsified"}:
        return "weaken"
    if direction_match == "missed":
        return "weaken"
    if improved is True or direction_match == "matched":
        if status in {"strengthening", "intact", "confirmed"}:
            return "strengthen"
        if improved is True:
            return "strengthen"
        return "unchanged" if direction_match != "matched" else "strengthen"
    if improved is False:
        return "weaken"
    return "unchanged"


def _falsifier_status(packet: dict[str, Any], what: dict[str, Any], *, price_chg: float | None) -> str:
    expected = packet.get("expected") if isinstance(packet.get("expected"), dict) else {}
    falsifiers = list(expected.get("falsifiers") or [])
    status = str(what.get("thesis_status") or "").lower()
    if status in {"falsified", "broken"}:
        return "triggered"
    action = str(packet.get("action") or "").lower()
    if action == "buy" and price_chg is not None and price_chg <= -FALSIFIER_DROP_PCT:
        return "triggered"
    if falsifiers:
        return "open"
    return "not_applicable"


def _horizon(checkpoint: str) -> str:
    cp = str(checkpoint or "").strip().lower()
    return _HORIZON.get(cp, cp or "unspecified")


def _evidence_ids(packet: dict[str, Any], what: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for oid in packet.get("observation_ids") or []:
        if oid and str(oid) not in ids:
            ids.append(str(oid))
    for oid in what.get("new_observation_ids") or []:
        if oid and str(oid) not in ids:
            ids.append(str(oid))
    for oid in what.get("open_book_pack_ids") or []:
        if oid and str(oid) not in ids:
            ids.append(str(oid))
    return ids[:24]


def _confidence_before(packet: dict[str, Any]) -> float:
    conf = packet.get("confidence_breakdown") if isinstance(packet.get("confidence_breakdown"), dict) else {}
    v = _f(conf.get("overall"))
    if v is not None:
        return max(0.0, min(1.0, v if v <= 1.0 else v / 100.0))
    expected = packet.get("expected") if isinstance(packet.get("expected"), dict) else {}
    v = _f(expected.get("opportunity_confidence"))
    if v is not None:
        return max(0.0, min(1.0, v))
    bc = packet.get("belief_context") if isinstance(packet.get("belief_context"), dict) else {}
    beliefs = bc.get("beliefs") if isinstance(bc.get("beliefs"), list) else []
    if beliefs and isinstance(beliefs[0], dict):
        v = _f(beliefs[0].get("confidence"))
        if v is not None:
            return max(0.0, min(1.0, v))
    return 0.35


def build_outcome_check(
    packet: dict[str, Any] | None,
    what_changed: dict[str, Any] | None,
    *,
    checkpoint: str = "",
    source_experience_id: str | None = None,
) -> dict[str, Any]:
    """Pure outcome_check. Always emitted; never silent."""
    packet = packet if isinstance(packet, dict) else {}
    what = what_changed if isinstance(what_changed, dict) else {}
    price_chg = _f(what.get("price_change_pct"))
    rs = _f(what.get("rs_vs_nifty") if what.get("rs_vs_nifty") is not None else what.get("sector_rel_pct"))
    expected = _expected_direction(packet)
    observed = _sign_direction(price_chg)
    vs_nifty = "unknown"
    if rs is not None:
        vs_nifty = "outperform" if rs > 0.5 else ("underperform" if rs < -0.5 else "inline")

    if expected == "unknown" or observed == "unknown":
        direction_match = "unknown"
    elif expected == "flat":
        direction_match = "matched" if observed == "flat" else "missed"
    elif expected == observed:
        direction_match = "matched"
    elif observed == "flat":
        direction_match = "inconclusive"
    else:
        direction_match = "missed"

    thesis_change = _thesis_change(what, direction_match=direction_match)
    before = _confidence_before(packet)
    if thesis_change == "strengthen" and direction_match == "matched":
        after = min(0.95, round(before + 0.03, 4))
    elif thesis_change == "weaken" or direction_match == "missed":
        after = max(0.10, round(before - 0.05, 4))
    else:
        after = before

    entry = _f((packet.get("prices") or {}).get("fill_price") if isinstance(packet.get("prices"), dict) else None)
    if entry is None:
        entry = _f((packet.get("prices") or {}).get("mark") if isinstance(packet.get("prices"), dict) else None)
    mark_now = _f(what.get("mark_now"))
    new_obs = int(what.get("new_observation_count") or 0)
    thin = (entry is None or mark_now is None or price_chg is None) and new_obs <= 0
    if price_chg is not None and abs(price_chg) < THIN_MOVE_PCT and new_obs <= 0:
        thin = True

    falsifier = _falsifier_status(packet, what, price_chg=price_chg)
    evidence_ids = _evidence_ids(packet, what)
    contradiction_ids: list[str] = []
    if direction_match == "missed" or thesis_change == "weaken":
        contradiction_ids = list(what.get("new_observation_ids") or [])[:8]

    hypothesis = (
        f"{packet.get('action') or 'hold'} {packet.get('symbol') or '?'} "
        f"expected {expected}"
        + (
            f" (E[R]={packet.get('expected', {}).get('expected_return')})"
            if isinstance(packet.get("expected"), dict)
            and packet["expected"].get("expected_return") is not None
            else ""
        )
    )
    reason = (
        f"At {_horizon(checkpoint)}: expected {expected}, observed {observed} "
        f"({price_chg:+.2f}% vs entry)" if price_chg is not None else
        f"At {_horizon(checkpoint)}: expected {expected}, observed {observed} (mark missing)"
    )
    reason += f"; thesis {thesis_change}; direction {direction_match}."

    skip_candidate = None
    write_candidate = False
    if thin:
        skip_candidate = "no candidate: evidence too thin"
    elif falsifier == "triggered" or direction_match == "missed" or thesis_change == "weaken":
        write_candidate = True
    else:
        skip_candidate = "thesis held / unchanged; no candidate"

    return {
        "version": VERSION,
        "source_decision_id": packet.get("decision_id"),
        "source_experience_id": source_experience_id,
        "symbol": packet.get("symbol"),
        "action": packet.get("action"),
        "checkpoint": checkpoint or None,
        "outcome_horizon": _horizon(checkpoint),
        "hypothesis": hypothesis[:300],
        "expected_direction": expected,
        "observed_direction": observed,
        "observed_vs_nifty": vs_nifty,
        "direction_match": direction_match,
        "thesis_change": thesis_change,
        "price_change_pct": price_chg,
        "rs_vs_nifty": rs,
        "entry_price": entry,
        "mark_now": mark_now,
        "evidence_ids": evidence_ids,
        "contradiction_ids": contradiction_ids,
        "confidence_before": before,
        "confidence_after_candidate": after,
        "falsifier_status": falsifier,
        "thin_evidence": thin,
        "write_candidate": write_candidate,
        "skip_candidate": skip_candidate,
        "reason": reason[:400],
        "influence": INFLUENCE,
        "er_model": (
            (packet.get("expected") or {}).get("er_model")
            if isinstance(packet.get("expected"), dict)
            else None
        ),
    }


def belief_candidate_payload(outcome_check: dict[str, Any]) -> dict[str, Any] | None:
    """Genealogy blob for a candidate. None when skip_candidate is set."""
    oc = outcome_check if isinstance(outcome_check, dict) else {}
    if oc.get("thin_evidence") or not oc.get("write_candidate"):
        return None
    statement = (
        f"{oc.get('symbol') or 'name'} thesis {oc.get('thesis_change')} at "
        f"{oc.get('outcome_horizon')}: expected {oc.get('expected_direction')}, "
        f"observed {oc.get('observed_direction')} "
        f"(direction {oc.get('direction_match')}). {oc.get('reason')}"
    )
    return {
        "source_decision_id": oc.get("source_decision_id"),
        "source_experience_id": oc.get("source_experience_id"),
        "hypothesis": oc.get("hypothesis"),
        "expected_direction": oc.get("expected_direction"),
        "observed_direction": oc.get("observed_direction"),
        "evidence_ids": list(oc.get("evidence_ids") or []),
        "contradiction_ids": list(oc.get("contradiction_ids") or []),
        "outcome_horizon": oc.get("outcome_horizon"),
        "confidence_before": oc.get("confidence_before"),
        "confidence_after_candidate": oc.get("confidence_after_candidate"),
        "reason": oc.get("reason"),
        "falsifier_status": oc.get("falsifier_status"),
        "statement": statement[:500],
        "domain": "market",
        "status": "candidate",
        "influence": INFLUENCE,
        "version": VERSION,
    }


def record_belief_candidate(
    reasoning: Any | None,
    outcome_check: dict[str, Any],
    *,
    actor: str = "outcome_loop",
) -> dict[str, Any]:
    """Write a Belief Core *candidate*. Never promotes. Advice-only."""
    payload = belief_candidate_payload(outcome_check)
    if payload is None:
        return {
            "ok": True,
            "wrote": False,
            "skip_reason": outcome_check.get("skip_candidate")
            or "no candidate: evidence too thin",
            "outcome_check": outcome_check,
            "influence": INFLUENCE,
        }
    if reasoning is None:
        return {
            "ok": True,
            "wrote": False,
            "skip_reason": "ReasoningService not bound — candidate recorded locally only",
            "belief_candidate": payload,
            "outcome_check": outcome_check,
            "influence": INFLUENCE,
        }
    try:
        cand = reasoning.propose_candidate(
            statement=payload["statement"],
            domain="market",
            confidence=float(payload.get("confidence_after_candidate") or 0.34),
            themes=["outcome_loop", str(payload.get("thesis_change") or "revise")],
            open_questions=[
                "Does this generalize beyond the source decision?",
                f"Falsifier status: {payload.get('falsifier_status')}",
            ],
            evidence_summary=(
                f"genealogy decision={payload.get('source_decision_id')} "
                f"horizon={payload.get('outcome_horizon')} "
                f"expected={payload.get('expected_direction')} "
                f"observed={payload.get('observed_direction')}"
            )[:500],
            origin="experience",
            actor=actor,
            metadata={"genealogy": payload, "loop0": "l3", "influence": INFLUENCE},
        )
        payload["belief_id"] = cand.get("id")
        payload["belief_status"] = cand.get("status") or "candidate"
        return {
            "ok": True,
            "wrote": True,
            "belief_candidate": payload,
            "belief": cand,
            "outcome_check": outcome_check,
            "influence": INFLUENCE,
        }
    except TypeError:
        # Older propose_candidate without metadata=.
        cand = reasoning.propose_candidate(
            statement=payload["statement"],
            domain="market",
            confidence=float(payload.get("confidence_after_candidate") or 0.34),
            themes=["outcome_loop"],
            evidence_summary=str(payload.get("reason") or "")[:500],
            origin="experience",
            actor=actor,
        )
        payload["belief_id"] = cand.get("id")
        return {
            "ok": True,
            "wrote": True,
            "belief_candidate": payload,
            "belief": cand,
            "outcome_check": outcome_check,
            "influence": INFLUENCE,
        }
    except Exception as exc:  # noqa: BLE001
        _log.debug("belief candidate write failed: %s", exc)
        return {
            "ok": False,
            "wrote": False,
            "error": str(exc),
            "belief_candidate": payload,
            "outcome_check": outcome_check,
            "influence": INFLUENCE,
        }
