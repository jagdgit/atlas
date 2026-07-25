"""Standardized post-decision feedback loops (OI-F4).

Convention: Recommendation → Outcome → Difference → Learning across missions.
Uses Experience OS + optional soft-bias — no new Feedback store.
"""

from __future__ import annotations

from typing import Any

from atlas.decision.knowledge import experience_id_from_result

DIFF_MATCHED = "matched"
DIFF_MISSED = "missed"
DIFF_PARTIAL = "partial"
DIFF_UNKNOWN = "unknown"

_DECISIVE = frozenset({DIFF_MATCHED, DIFF_MISSED})


def difference_label(expected: str, actual: str) -> str:
    """Classify expected recommendation vs reported outcome."""
    exp = str(expected or "").strip().lower()
    act = str(actual or "").strip().lower()
    if not exp and not act:
        return DIFF_UNKNOWN
    if not act or act in {"unknown", "pending", "n/a"}:
        return DIFF_UNKNOWN
    if act in {"matched", "applied", "accepted", "followed", "profit", "true", "yes"}:
        if exp in {"", act, "recommend", "recommended"}:
            return DIFF_MATCHED
        return DIFF_MATCHED if act == exp else DIFF_PARTIAL
    if act in {"missed", "ignored", "rejected", "stale", "loss", "false", "no"}:
        return DIFF_MISSED
    if exp and act and exp == act:
        return DIFF_MATCHED
    if exp and act:
        return DIFF_PARTIAL
    return DIFF_UNKNOWN


def should_enable_feedback_bias(difference: str) -> bool:
    return str(difference or "").lower() in _DECISIVE


def feedback_tags(
    mission_type: str,
    *,
    decision_id: str | None = None,
    difference: str | None = None,
    subject: str | None = None,
) -> list[str]:
    tags = [
        "feedback_loop",
        "post_decision",
        str(mission_type or "mission").strip().lower() or "mission",
        "experience_journal",
    ]
    if difference:
        tags.append(str(difference).lower())
    if subject:
        tags.append(str(subject).strip().lower())
    if decision_id:
        tags.append(f"decision:{decision_id}")
    return [t for t in tags if t]


def feedback_metadata(
    *,
    decision_id: str | None,
    mission_type: str,
    recommendation: str,
    outcome: str,
    difference: str,
    subject: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "feedback_loop": True,
        "decision_id": str(decision_id) if decision_id else None,
        "mission_type": str(mission_type),
        "recommendation": str(recommendation)[:500],
        "outcome": str(outcome)[:500],
        "difference": str(difference),
        "subject": subject,
    }
    if extra:
        meta.update(extra)
    return meta


def build_feedback_journal(
    *,
    title: str,
    recommendation: str,
    outcome: str,
    difference: str,
    observation: str = "",
    reasoning: str = "",
    reflection: str = "",
    lesson: str = "",
    domain: str = "general",
    mission_type: str = "mission",
    decision_id: str | None = None,
    subject: str | None = None,
    recommendations: list[Any] | None = None,
    metadata_extra: dict[str, Any] | None = None,
    tags_extra: list[str] | None = None,
) -> dict[str, Any]:
    """Build kwargs for ``ExperienceOS.journal`` / learning remember."""
    diff = str(difference or DIFF_UNKNOWN)
    if not reflection:
        reflection = {
            DIFF_MATCHED: "Outcome matched the recommendation — reinforce the decision path.",
            DIFF_MISSED: "Outcome diverged from the recommendation — review evidence and constraints.",
            DIFF_PARTIAL: "Outcome only partially aligned — capture nuance before generalizing.",
            DIFF_UNKNOWN: "Outcome inconclusive — do not overfit from this cycle.",
        }.get(diff, "Recorded post-decision feedback.")
    if not lesson:
        lesson = {
            DIFF_MATCHED: "Prefer similar recommendation patterns when evidence is comparable.",
            DIFF_MISSED: "Before similar recommends, re-check blockers and operator feedback.",
            DIFF_PARTIAL: "Split partial outcomes into what matched vs what missed next time.",
            DIFF_UNKNOWN: "Wait for a decisive outcome before enabling soft-bias.",
        }.get(diff, "Keep the Recommendation→Outcome→Difference→Learning cycle.")
    tags = feedback_tags(
        mission_type, decision_id=decision_id, difference=diff, subject=subject
    )
    if tags_extra:
        tags.extend(str(t) for t in tags_extra if t)
    meta = feedback_metadata(
        decision_id=decision_id,
        mission_type=mission_type,
        recommendation=recommendation,
        outcome=outcome,
        difference=diff,
        subject=subject,
        extra=metadata_extra,
    )
    return {
        "title": title,
        "observation": observation or f"Recommendation recorded for {subject or mission_type}",
        "reasoning": reasoning or "Operator/mission feedback on a prior recommendation",
        "decision": recommendation,
        "outcome": outcome,
        "reflection": f"Difference={diff}. {reflection}",
        "lesson": lesson,
        "domain": domain,
        "tags": tags,
        "recommendations": list(recommendations or []),
        "metadata": meta,
    }


def record_feedback_loop(
    *,
    experience_os: Any | None,
    learning: Any | None,
    journal_kwargs: dict[str, Any],
    enable_bias: bool,
    difference: str,
    logger: Any | None = None,
) -> dict[str, Any]:
    """Write the feedback journal and optionally enable Experience soft-bias."""
    if experience_os is None and learning is None:
        return {"ok": False, "error": "no_learning_backend"}

    result: dict[str, Any] | None = None
    if experience_os is not None:
        try:
            result = experience_os.journal(**journal_kwargs)
        except Exception as exc:  # noqa: BLE001
            if logger is not None:
                logger.warning("feedback journal failed: %s", exc)
            return {"ok": False, "error": str(exc)}
    elif learning is not None:
        try:
            meta = journal_kwargs.get("metadata") or {}
            problem = (
                f"Observation: {journal_kwargs.get('observation', '')}\n"
                f"Reasoning: {journal_kwargs.get('reasoning', '')}\n"
                f"Decision: {journal_kwargs.get('decision', '')}\n"
                f"Outcome: {journal_kwargs.get('outcome', '')}\n"
                f"Difference: {meta.get('difference', difference)}"
            )
            result = learning.remember_experience(
                title=journal_kwargs.get("title"),
                problem=problem,
                solution=f"Reflection: {journal_kwargs.get('reflection', '')}",
                lessons=f"Lesson: {journal_kwargs.get('lesson', '')}",
                domain=journal_kwargs.get("domain"),
                tags=journal_kwargs.get("tags"),
                recommendations=journal_kwargs.get("recommendations"),
                metadata=meta,
            )
        except Exception as exc:  # noqa: BLE001
            if logger is not None:
                logger.warning("feedback remember_experience failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    bias_enabled = False
    if (
        enable_bias
        and should_enable_feedback_bias(difference)
        and learning is not None
        and hasattr(learning, "enable_bias")
    ):
        exp_id = experience_id_from_result(result)
        if exp_id:
            try:
                learning.enable_bias(str(exp_id), enabled=True)
                bias_enabled = True
            except Exception as exc:  # noqa: BLE001
                if logger is not None:
                    logger.debug("feedback enable_bias skipped: %s", exc)

    return {
        "ok": True,
        "result": result,
        "difference": difference,
        "bias_enabled": bias_enabled,
        "experience_id": experience_id_from_result(result),
    }


def collect_outcome_feedback(
    inputs: list[dict[str, Any]] | None,
    cfg: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Pull outcome_feedback payloads from tick inputs and optional config seed list."""
    items: list[dict[str, Any]] = []
    for raw in inputs or []:
        if not isinstance(raw, dict):
            continue
        if raw.get("outcome_feedback") is True or isinstance(raw.get("outcome_feedback"), dict):
            payload = raw.get("outcome_feedback")
            if payload is True:
                items.append({k: v for k, v in raw.items() if k != "outcome_feedback"})
            elif isinstance(payload, dict):
                items.append(dict(payload))
        elif raw.get("kind") == "outcome_feedback":
            items.append(dict(raw))
    cfg = cfg if isinstance(cfg, dict) else {}
    seeded = cfg.get("outcome_feedback")
    if isinstance(seeded, list):
        for row in seeded:
            if isinstance(row, dict):
                items.append(dict(row))
    return items
