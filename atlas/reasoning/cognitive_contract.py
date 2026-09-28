"""Cognitive Core contract v1 — one Core, two typed surfaces, explicit handoffs.

Core interprets. L2 influences. Auditor validates. Core does not own the
learning loop. Callers get a stable envelope; surface-specific fields live
in ``payload`` and are also flattened for legacy consumers.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

CONTRACT_VERSION = "cognitive.contract.v1"

REVIEWED = "REVIEWED"
UNREVIEWED = "UNREVIEWED"

# Influence provenance (L2 owns deltas; Core owns review_status).
INFLUENCE_SOURCE_DETERMINISTIC = "deterministic"
INFLUENCE_SOURCE_COGNITIVE_REVIEWED = "cognitive_reviewed"
INFLUENCE_SOURCE_COGNITIVE_UNREVIEWED = "cognitive_unreviewed"
INFLUENCE_SOURCE_POLICY = "policy"

EFFECT_TARGET_BUY_SCORE = "buy_score"
EFFECT_TARGET_EXIT_SCORE = "exit_score"
EFFECT_TARGET_RANKING = "ranking"
EFFECT_TARGET_UNKNOWN = "unknown"

EFFECT_DIR_POSITIVE = "positive"
EFFECT_DIR_NEGATIVE = "negative"
EFFECT_DIR_UNKNOWN = "unknown"


class CognitiveSurface(str, Enum):
    SCIENTIST = "scientist"
    DECIDE_RATIONALE = "decide_rationale"


def expected_effect(
    *,
    target: str = EFFECT_TARGET_UNKNOWN,
    direction: str = EFFECT_DIR_UNKNOWN,
    confidence: float | None = None,
) -> dict[str, Any]:
    """Semantic contract attached to a lesson (not hard-coded per lesson id)."""
    tgt = str(target or EFFECT_TARGET_UNKNOWN).strip().lower() or EFFECT_TARGET_UNKNOWN
    direction_s = (
        str(direction or EFFECT_DIR_UNKNOWN).strip().lower() or EFFECT_DIR_UNKNOWN
    )
    if direction_s not in {
        EFFECT_DIR_POSITIVE,
        EFFECT_DIR_NEGATIVE,
        EFFECT_DIR_UNKNOWN,
    }:
        direction_s = EFFECT_DIR_UNKNOWN
    out: dict[str, Any] = {"target": tgt, "direction": direction_s}
    if confidence is not None:
        try:
            out["confidence"] = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            pass
    return out


def lesson_expected_effect(lesson: dict[str, Any] | None) -> dict[str, Any]:
    """Resolve expected_effect from an explicit field, else infer from sign."""
    row = lesson if isinstance(lesson, dict) else {}
    raw = row.get("expected_effect")
    if isinstance(raw, dict) and raw.get("direction"):
        return expected_effect(
            target=str(raw.get("target") or EFFECT_TARGET_UNKNOWN),
            direction=str(raw.get("direction") or EFFECT_DIR_UNKNOWN),
            confidence=raw.get("confidence"),
        )
    try:
        sign = int(row.get("sign")) if row.get("sign") is not None else 0
    except (TypeError, ValueError):
        sign = 0
    if sign < 0:
        return expected_effect(
            target=EFFECT_TARGET_BUY_SCORE, direction=EFFECT_DIR_NEGATIVE
        )
    if sign > 0:
        return expected_effect(
            target=EFFECT_TARGET_BUY_SCORE, direction=EFFECT_DIR_POSITIVE
        )
    return expected_effect()


def provenance_from_claims(claims: list[Any] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for c in claims or []:
        if not isinstance(c, dict):
            continue
        for eid in c.get("evidence_ids") or c.get("citations") or []:
            s = str(eid).strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
    return out[:32]


def make_cognitive_result(
    *,
    surface: CognitiveSurface | str,
    review_status: str,
    skip_reason: str | None = None,
    claims: list[Any] | None = None,
    confidence: float | None = None,
    provenance: list[Any] | None = None,
    decision_id: str | None = None,
    laboratory_id: str | None = None,
    symbol: str | None = None,
    raw_llm_text: str | None = None,
    payload: dict[str, Any] | None = None,
    advice_only: bool = True,
    never_orders: bool = True,
    version: str | None = None,
    kind: str | None = None,
    honesty: str | None = None,
    llm: bool | None = None,
    **legacy: Any,
) -> dict[str, Any]:
    """Stable envelope + surface payload. Legacy flat keys preserved for callers."""
    surf = (
        surface.value
        if isinstance(surface, CognitiveSurface)
        else str(surface or "").strip()
    )
    claims_l = [c for c in (claims or []) if c][:16]
    prov = [str(x) for x in (provenance or []) if x][:32]
    if not prov:
        prov = provenance_from_claims(claims_l)
    pay = dict(payload) if isinstance(payload, dict) else {}
    out: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "surface": surf,
        "review_status": str(review_status or UNREVIEWED),
        "skip_reason": skip_reason,
        "claims": claims_l,
        "confidence": confidence,
        "provenance": prov,
        "decision_id": decision_id,
        "laboratory_id": laboratory_id,
        "symbol": symbol,
        "payload": pay,
        "advice_only": bool(advice_only),
        "never_orders": bool(never_orders),
    }
    if version:
        out["version"] = version
    if kind:
        out["kind"] = kind
    if honesty:
        out["honesty"] = honesty
    if llm is not None:
        out["llm"] = bool(llm)
    if raw_llm_text:
        out["raw_llm_text"] = str(raw_llm_text)[:2000]
    # Flatten payload + legacy for existing consumers (decide_rationale, ICR merge).
    for k, v in pay.items():
        out.setdefault(k, v)
    for k, v in legacy.items():
        if v is not None or k not in out:
            out[k] = v
    return out


def influence_event(
    *,
    lesson_id: str,
    bounded_delta: dict[str, float] | None = None,
    influence_source: str = INFLUENCE_SOURCE_DETERMINISTIC,
    cognitive_review_status: str | None = None,
) -> dict[str, Any]:
    """One L2 influence stamp — Core does not compute this."""
    src = str(influence_source or INFLUENCE_SOURCE_DETERMINISTIC)
    status = cognitive_review_status
    if status is None and src == INFLUENCE_SOURCE_COGNITIVE_REVIEWED:
        status = REVIEWED
    if status is None and src == INFLUENCE_SOURCE_COGNITIVE_UNREVIEWED:
        status = UNREVIEWED
    delta = dict(bounded_delta) if isinstance(bounded_delta, dict) else {}
    # Cognitive-derived influence without REVIEWED → zero (deterministic L2 untouched).
    if src == INFLUENCE_SOURCE_COGNITIVE_REVIEWED and status != REVIEWED:
        src = INFLUENCE_SOURCE_COGNITIVE_UNREVIEWED
        delta = {k: 0.0 for k in delta}
    elif src == INFLUENCE_SOURCE_COGNITIVE_UNREVIEWED:
        delta = {k: 0.0 for k in delta}
    return {
        "influence_source": src,
        "lesson_id": str(lesson_id or "")[:120],
        "cognitive_review_status": status,
        "bounded_delta": {
            "option": float(delta.get("option") or 0.0),
            "ranking": float(delta.get("ranking") or 0.0),
        },
    }


# Phrases that flip a negative buy_score lesson into buy support (fail).
_SUPPORTIVE_BUY_FLIP = (
    "supports the buy",
    "support the buy",
    "supportive of a buy",
    "supportive of buy",
    "supports buying",
    "supports a buy",
    "can support a buy",
    "can support buy",
    "positive for the buy",
    "reason to buy",
    "justifies buying",
    "justifies a buy",
)

_CAUTION_NEGATIONS = (
    "do not treat",
    "don't treat",
    "not to treat",
    "not a reason to buy",
    "never treat",
    "do not use",
    "contradicts using",
)


def text_claims_buy_support(text: str | None) -> bool:
    """True when prose treats a lesson as buy support (ignoring caution negations)."""
    blob = " ".join(str(text or "").lower().replace("_", " ").split())
    if not blob:
        return False
    if any(neg in blob for neg in _CAUTION_NEGATIONS) and "reason to buy" in blob:
        # "not a reason to buy" / "do not treat … as a reason to buy"
        if not any(
            flip in blob
            for flip in _SUPPORTIVE_BUY_FLIP
            if flip != "reason to buy"
        ):
            return False
    return any(flip in blob for flip in _SUPPORTIVE_BUY_FLIP)


def polarity_inverted_vs_expected_effect(
    text: str | None,
    *,
    lessons: list[dict[str, Any]] | None = None,
    lesson_refs: list[Any] | None = None,
) -> bool:
    """True when LLM text contradicts a lesson's expected_effect (buy_score negative).

    Lessons without expected_effect / direction=unknown → no assertion.
    """
    rows: list[dict[str, Any]] = []
    for item in lessons or []:
        if isinstance(item, dict):
            rows.append(item)
        elif item:
            rows.append({"id": str(item)})
    if not rows and lesson_refs:
        for ref in lesson_refs:
            if isinstance(ref, dict):
                rows.append(ref)
            elif ref:
                rows.append({"id": str(ref)})
    if not rows:
        return False

    blob = " ".join(str(text or "").lower().replace("_", " ").split())
    for row in rows:
        ee = lesson_expected_effect(row)
        if ee.get("direction") != EFFECT_DIR_NEGATIVE:
            continue
        tgt = str(ee.get("target") or "")
        if tgt not in {EFFECT_TARGET_BUY_SCORE, "buy", "option"}:
            continue
        lid = str(row.get("id") or "").lower()
        # Only assert when this lesson is in context (id mentioned or listed).
        in_context = True
        if lid and lesson_refs is not None:
            ref_ids = {
                str(x.get("id") if isinstance(x, dict) else x).lower()
                for x in (lesson_refs or [])
                if x
            }
            in_context = lid in ref_ids or lid in blob or lid.split("-")[0] in blob
        if not in_context:
            continue
        if text_claims_buy_support(text):
            return True
    return False
