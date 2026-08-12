"""OI-SELF-EXP — Experience → Belief closed loop (Phase 2).

Prediction / outcome / delta on Experience payloads; every learning experience
must link ``affected_beliefs`` or an honest ``no_belief_link_reason``.
"""

from __future__ import annotations

import logging
from typing import Any

VERSION = "self0.exp.v1"

_log = logging.getLogger("atlas.reasoning.experience_loop")


def validate_belief_link(
    *,
    affected_beliefs: list[Any] | None,
    no_belief_link_reason: str | None,
) -> dict[str, Any]:
    """Return {ok, error?}. Archive-without-inheritance is a failed learning event."""
    beliefs = [str(b).strip() for b in (affected_beliefs or []) if str(b).strip()]
    reason = (no_belief_link_reason or "").strip()
    if beliefs:
        return {"ok": True, "affected_beliefs": beliefs, "no_belief_link_reason": None}
    if reason:
        return {
            "ok": True,
            "affected_beliefs": [],
            "no_belief_link_reason": reason[:500],
        }
    return {
        "ok": False,
        "error": "belief_link_required",
        "detail": (
            "Learning experiences need affected_beliefs[] or "
            "no_belief_link_reason (honest archive)."
        ),
    }


def compute_delta(
    prediction: dict[str, Any] | None,
    outcome: dict[str, Any] | None,
) -> dict[str, Any]:
    """Deterministic delta sketch from prediction vs outcome dicts."""
    pred = prediction if isinstance(prediction, dict) else {}
    out = outcome if isinstance(outcome, dict) else {}
    delta: dict[str, Any] = {
        "version": VERSION,
        "matched_keys": [],
        "diverged_keys": [],
        "numeric": {},
        "label": "unknown",
    }
    for key in sorted(set(pred) | set(out)):
        pv, ov = pred.get(key), out.get(key)
        if isinstance(pv, (int, float)) and isinstance(ov, (int, float)):
            d = float(ov) - float(pv)
            delta["numeric"][key] = {
                "predicted": float(pv),
                "actual": float(ov),
                "diff": round(d, 6),
            }
            if abs(d) < 1e-9:
                delta["matched_keys"].append(key)
            else:
                delta["diverged_keys"].append(key)
        elif pv == ov and pv is not None:
            delta["matched_keys"].append(key)
        elif pv is not None and ov is not None:
            delta["diverged_keys"].append(key)
    if delta["diverged_keys"] and not delta["matched_keys"]:
        delta["label"] = "missed"
    elif delta["matched_keys"] and not delta["diverged_keys"]:
        delta["label"] = "matched"
    elif delta["matched_keys"] and delta["diverged_keys"]:
        delta["label"] = "partial"
    elif pred and not out:
        delta["label"] = "pending"
    return delta


def learning_metadata(
    *,
    prediction: dict[str, Any] | None = None,
    outcome_structured: dict[str, Any] | None = None,
    delta: dict[str, Any] | None = None,
    affected_beliefs: list[str] | None = None,
    no_belief_link_reason: str | None = None,
    decision_id: str | None = None,
    source: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pred = dict(prediction or {})
    out = dict(outcome_structured or {})
    dlt = delta if isinstance(delta, dict) else compute_delta(pred, out)
    link = validate_belief_link(
        affected_beliefs=affected_beliefs,
        no_belief_link_reason=no_belief_link_reason,
    )
    meta: dict[str, Any] = {
        "learning_loop": True,
        "learning_loop_version": VERSION,
        "prediction": pred,
        "outcome_structured": out,
        "delta": dlt,
        "affected_beliefs": list(link.get("affected_beliefs") or []),
        "no_belief_link_reason": link.get("no_belief_link_reason"),
        "belief_link_ok": bool(link.get("ok")),
    }
    if decision_id:
        meta["decision_id"] = str(decision_id)
    if source:
        meta["source"] = str(source)
    if extra:
        meta.update(extra)
    return meta


def journal_kwargs_from_packet_outcome(
    packet: dict[str, Any],
    *,
    outcome_structured: dict[str, Any],
    reflection: str = "",
    lesson: str = "",
    affected_beliefs: list[str] | None = None,
    no_belief_link_reason: str | None = None,
) -> dict[str, Any]:
    """Build ExperienceOS.journal kwargs from a Decision Packet + measured outcome."""
    sym = str(packet.get("symbol") or packet.get("payload", {}).get("symbol") or "?")
    action = str(packet.get("action") or "decide")
    expected = packet.get("expected") if isinstance(packet.get("expected"), dict) else {}
    if not expected and isinstance(packet.get("payload"), dict):
        expected = (
            packet["payload"].get("expected")
            if isinstance(packet["payload"].get("expected"), dict)
            else {}
        )
    prediction = {
        "action": action,
        "symbol": sym,
        **{k: expected[k] for k in list(expected)[:8]},
    }
    delta = compute_delta(prediction, outcome_structured)
    if not lesson:
        lesson = (
            f"Decision {action} on {sym} delta={delta.get('label')}: "
            "compare prediction vs outcome before generalizing."
        )
    if not reflection:
        reflection = (
            f"Predicted {prediction}; observed {outcome_structured}; "
            f"label={delta.get('label')}."
        )
    decision_id = str(
        packet.get("decision_id")
        or (packet.get("payload") or {}).get("decision_id")
        or ""
    ) or None
    return {
        "title": f"Learning loop: {action} {sym}",
        "observation": f"Packet freeze for {sym} action={action}",
        "reasoning": str(
            packet.get("thesis")
            or (packet.get("payload") or {}).get("thesis")
            or packet.get("why")
            or "Decide-time packet expectations"
        )[:800],
        "decision": f"{action} {sym}",
        "outcome": str(outcome_structured)[:800],
        "reflection": reflection,
        "lesson": lesson,
        "domain": "market",
        "tags": [
            "learning_loop",
            "decision_packet",
            "self0_exp",
            f"symbol:{sym.lower()}",
        ],
        "prediction": prediction,
        "outcome_structured": outcome_structured,
        "delta": delta,
        "affected_beliefs": list(affected_beliefs or []),
        "no_belief_link_reason": no_belief_link_reason,
        "metadata": {
            "decision_id": decision_id,
            "source": "decision_packet",
            "symbol": sym,
        },
    }


def ingest_experience_to_beliefs(
    reasoning: Any,
    *,
    lesson: str,
    domain: str,
    experience_id: str | None = None,
    affected_beliefs: list[str] | None = None,
    delta_label: str | None = None,
    evidence_summary: str = "",
    actor: str = "experience_loop",
) -> dict[str, Any]:
    """Strengthen existing beliefs or propose a candidate from an experience lesson.

    Advice-only — never mutates ranking/gates.
    """
    if reasoning is None:
        return {"ok": False, "error": "reasoning_unavailable"}
    lesson_text = (lesson or "").strip()
    if not lesson_text:
        return {"ok": False, "error": "empty_lesson"}

    actions: list[dict[str, Any]] = []
    ids = [str(b).strip() for b in (affected_beliefs or []) if str(b).strip()]
    summary = evidence_summary or f"experience:{experience_id or 'unknown'}"

    for bid in ids:
        try:
            before = reasoning.get_belief(bid, purpose="consult")
            if before is None:
                actions.append({"belief_id": bid, "action": "missing"})
                continue
            conf = float(before.get("confidence") or 0.5)
            label = (delta_label or "").lower()
            if label in {"matched", "beat"}:
                new_conf = min(0.95, conf + 0.03)
                status = None
            elif label in {"missed", "lost", "falsified"}:
                new_conf = max(0.1, conf - 0.05)
                status = "weakened" if new_conf < 0.55 else None
            else:
                new_conf = conf
                status = None
            out = reasoning.revise(
                bid,
                reason=f"Experience closed loop ({label or 'update'})",
                evidence_summary=summary[:500],
                new_confidence=new_conf,
                new_status=status,
                actor=actor,
            )
            actions.append(
                {
                    "belief_id": bid,
                    "action": "revised",
                    "revision_id": (out.get("revision") or {}).get("id"),
                    "confidence": new_conf,
                }
            )
        except Exception as exc:  # noqa: BLE001
            _log.debug("belief revise from experience failed: %s", exc)
            actions.append({"belief_id": bid, "action": "error", "error": str(exc)})

    candidate = None
    if not ids:
        # New generalization → candidate (not auto-active).
        try:
            candidate = reasoning.propose_candidate(
                statement=lesson_text[:500],
                domain=domain if domain in {
                    "market", "engineering", "personal", "cross"
                } else "cross",
                confidence=0.34,
                themes=["experience_loop", delta_label or "lesson"],
                open_questions=[
                    "Does this generalize beyond the source experience?"
                ],
                evidence_summary=summary[:500],
                origin="experience",
                actor=actor,
            )
            actions.append(
                {
                    "belief_id": candidate.get("id"),
                    "action": "candidate",
                    "status": "candidate",
                }
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "actions": actions}

    return {
        "ok": True,
        "version": VERSION,
        "actions": actions,
        "candidate": candidate,
        "influence_strength": "advice",
    }


def close_loop(
    *,
    experience_os: Any,
    reasoning: Any | None,
    journal_kwargs: dict[str, Any],
    ingest_beliefs: bool = True,
    actor: str = "experience_loop",
) -> dict[str, Any]:
    """Write learning experience then optionally ingest into Belief Core."""
    if experience_os is None:
        return {"ok": False, "error": "experience_os_unavailable"}
    out = experience_os.journal(**journal_kwargs)
    if not out.get("ok"):
        return {"ok": False, "stage": "journal", "journal": out}
    exp_id = None
    result = out.get("result") if isinstance(out.get("result"), dict) else {}
    for key in ("ref_id", "id"):
        event = result.get("event") if isinstance(result.get("event"), dict) else {}
        val = event.get(key) or result.get(key)
        if val:
            exp_id = str(val)
            break
    belief_out = None
    if ingest_beliefs and reasoning is not None:
        meta = (journal_kwargs.get("metadata") or {}) if isinstance(
            journal_kwargs.get("metadata"), dict
        ) else {}
        affected = list(
            journal_kwargs.get("affected_beliefs")
            or meta.get("affected_beliefs")
            or []
        )
        # If no link and no honest reason, journal should have failed already.
        if affected or journal_kwargs.get("no_belief_link_reason") or meta.get(
            "no_belief_link_reason"
        ):
            if affected or not (
                journal_kwargs.get("no_belief_link_reason")
                or meta.get("no_belief_link_reason")
            ):
                delta = journal_kwargs.get("delta") or meta.get("delta") or {}
                belief_out = ingest_experience_to_beliefs(
                    reasoning,
                    lesson=str(journal_kwargs.get("lesson") or ""),
                    domain=str(journal_kwargs.get("domain") or "cross"),
                    experience_id=exp_id,
                    affected_beliefs=affected or None,
                    delta_label=str(delta.get("label") or ""),
                    evidence_summary=(
                        f"experience {exp_id}: {journal_kwargs.get('title')}"
                    ),
                    actor=actor,
                )
            else:
                belief_out = {
                    "ok": True,
                    "skipped": "honest_archive",
                    "no_belief_link_reason": journal_kwargs.get(
                        "no_belief_link_reason"
                    )
                    or meta.get("no_belief_link_reason"),
                }
    return {
        "ok": True,
        "version": VERSION,
        "experience_id": exp_id,
        "journal": out,
        "belief_ingest": belief_out,
    }
