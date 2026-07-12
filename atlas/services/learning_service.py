"""LearningService — the ``learning`` capability (S18b, D11/§5d).

Continuous Learning is the third pillar: completed activities become durable,
*governed* knowledge. Two guarantees are enforced here, not just documented:

- **Atlas never silently learns.** Observing a completed job (or any source) only
  ever creates a **proposed** ``LearningEvent`` by default (``auto_apply`` off). A
  proposal must be **applied** to enter a store, and every proposal records *what*
  (summary), *why* (reason), and *from where* (origin) — it is explainable.
- **Learning is governed and reversible.** Applying attaches a policy
  (temporary/project/personal/verified) + Learning Level, and creates the store
  record; **reverting** flips the event to ``reverted`` and deactivates that record.

S18b lands the **Experience store** concretely (problem → diagnosis → actions →
mistakes → solution → lessons) and the governance ledger. Promotion into the other
stores (knowledge graph, code/architecture, generalized patterns → Learning Levels
L2–L5) is the Engineering-Intelligence work of S19; the ledger already models it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from atlas.models.learning import (
    EVENT_APPLIED,
    EVENT_PROPOSED,
    EVENT_REVERTED,
    EXP_ACTIVE,
    EXP_REVERTED,
    POLICIES,
    SOURCE_JOB,
    SOURCE_MANUAL,
    STORE_EXPERIENCE,
)
from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.config import LearningConfig
    from atlas.repositories.learning_repo import LearningRepository


class LearningService:
    name = "learning"

    def __init__(
        self,
        repo: "LearningRepository",
        config: "LearningConfig | None" = None,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repo = repo
        self._config = config
        self._enabled = getattr(config, "enabled", True)
        self._observe_jobs = getattr(config, "observe_jobs", True)
        self._auto_apply = getattr(config, "auto_apply", False)
        self._default_policy = getattr(config, "default_policy", "temporary")
        self._default_level = getattr(config, "default_level", 1)
        self._recall_k = getattr(config, "recall_k", 5)
        self._logger = logger or logging.getLogger("atlas.learning")
        # Store sinks (S19): a sink knows how to materialise/deactivate a record in a
        # non-Experience store (e.g. the Code store). Registering one is how "promotion
        # into the other stores" happens through this single governed ledger — the
        # schema stays fixed; S19+ "adds sinks, not schema".
        self._sinks: dict[str, Any] = {}

    def register_sink(self, store: str, sink: Any) -> None:
        """Attach a store sink with ``apply(payload) -> ref_id`` + ``revert(ref_id)``."""
        self._sinks[store] = sink

    # --- observing completed activity ----------------------------------
    def observe_job(self, detail: dict[str, Any]) -> dict[str, Any] | None:
        """Propose an Experience from a finished job (governed; propose-only default).

        Returns the created event dict, or ``None`` if learning/observation is off
        or there is nothing worth learning. Never raises into the caller (R2/R3).
        """
        if not self._enabled or not self._observe_jobs:
            return None
        try:
            job = detail.get("job")
            steps = detail.get("steps") or []
            objective = getattr(job, "objective", "") or ""
            job_id = getattr(job, "id", None)
            result = getattr(job, "result", {}) or {}
            candidate = _experience_from_job(objective, steps, result, job_id)
            if candidate is None:
                return None
            event = self._propose(
                SOURCE_JOB,
                STORE_EXPERIENCE,
                source_id=str(job_id) if job_id else None,
                summary=f"Experience from job: {objective[:120]}",
                reason="A completed job is a reusable problem→solution record (§5d).",
                origin=f"job {job_id}",
                payload=candidate,
            )
            return event
        except Exception:  # noqa: BLE001 - learning must never break a job
            self._logger.exception("observe_job failed")
            return None

    # --- proposals & governance ----------------------------------------
    def propose(
        self,
        source_type: str,
        store: str,
        *,
        summary: str,
        reason: str,
        origin: str,
        payload: dict[str, Any],
        source_id: str | None = None,
        policy: str | None = None,
        level: int | None = None,
        project: str | None = None,
        apply: bool = False,
    ) -> dict[str, Any]:
        """Public entry for other learners (e.g. Engineering Intelligence) to record a
        governed learning event. ``apply=True`` promotes it at once (an explicit act)."""
        return self._propose(
            source_type, store, source_id=source_id, summary=summary, reason=reason,
            origin=origin, payload=payload, policy=policy, level=level, project=project,
            force_apply=apply,
        )

    def _propose(
        self,
        source_type: str,
        store: str,
        *,
        source_id: str | None,
        summary: str,
        reason: str,
        origin: str,
        payload: dict[str, Any],
        policy: str | None = None,
        level: int | None = None,
        project: str | None = None,
        force_apply: bool = False,
    ) -> dict[str, Any]:
        event = self._repo.record_event(
            source_type,
            store,
            source_id=source_id,
            policy=policy or self._default_policy,
            level=level or self._default_level,
            status=EVENT_PROPOSED,
            summary=summary,
            reason=reason,
            origin=origin,
            project=project,
            metadata={"payload": payload},
        )
        if self._auto_apply or force_apply:
            return self.apply(event.id)
        return {"event": event.as_dict(), "applied": False}

    def apply(
        self,
        event_id: str,
        *,
        policy: str | None = None,
        level: int | None = None,
    ) -> dict[str, Any]:
        """Promote a proposed event into its target store (explicit, governed)."""
        event = self._repo.get_event(event_id)
        if event is None:
            raise KeyError(f"no learning event {event_id}")
        if event.status == EVENT_APPLIED:
            return {"event": event.as_dict(), "applied": True, "already": True}
        if policy is not None and policy not in POLICIES:
            raise ValueError(f"unknown policy '{policy}'")

        ref_id = None
        payload = (event.metadata or {}).get("payload", {})
        if event.store == STORE_EXPERIENCE:
            exp = self._repo.add_experience(
                title=payload.get("title", ""),
                problem=payload.get("problem", ""),
                diagnosis=payload.get("diagnosis", ""),
                actions=payload.get("actions", []),
                mistakes=payload.get("mistakes", ""),
                solution=payload.get("solution", ""),
                lessons=payload.get("lessons", ""),
                tags=payload.get("tags", []),
                source_job_id=event.source_id,
                policy=policy or event.policy,
            )
            ref_id = exp.id
        elif event.store in self._sinks:
            # A registered store sink (e.g. the S19 Code store) materialises the record
            # and returns its id, so promotion stays governed through this one ledger.
            ref_id = self._sinks[event.store].apply(payload, policy=policy or event.policy)
        else:
            # No concrete sink for this store yet; the ledger still records the applied
            # decision so it stays explainable/reversible.
            self._logger.info("applied learning to store '%s' (no sink)", event.store)

        self._repo.set_event_status(
            event.id, EVENT_APPLIED, policy=policy, level=level, ref_id=ref_id
        )
        applied = self._repo.get_event(event.id)
        return {"event": applied.as_dict() if applied else None, "applied": True}

    def revert(self, event_id: str) -> dict[str, Any]:
        """Undo a learning event and deactivate the record it created (reversible)."""
        event = self._repo.get_event(event_id)
        if event is None:
            raise KeyError(f"no learning event {event_id}")
        if event.status == EVENT_APPLIED and event.ref_id:
            if event.store == STORE_EXPERIENCE:
                self._repo.set_experience_status(event.ref_id, EXP_REVERTED)
            elif event.store in self._sinks:
                self._sinks[event.store].revert(event.ref_id)
        self._repo.set_event_status(event.id, EVENT_REVERTED, reviewed=True)
        reverted = self._repo.get_event(event.id)
        return {"event": reverted.as_dict() if reverted else None, "reverted": True}

    # --- introspection (explainable) -----------------------------------
    def list_events(
        self, *, status: str | None = None, store: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        return [e.as_dict() for e in self._repo.list_events(status=status, store=store, limit=limit)]

    def explain(self, event_id: str) -> dict[str, Any]:
        event = self._repo.get_event(event_id)
        if event is None:
            raise KeyError(f"no learning event {event_id}")
        data = event.as_dict()
        data["explanation"] = (
            f"Learned '{event.summary}' into the {event.store} store "
            f"({data['level_name']}, policy {event.policy}). Why: {event.reason} "
            f"From: {event.origin}. Status: {event.status} — reversible."
        )
        if event.store == STORE_EXPERIENCE and event.ref_id:
            exp = self._repo.get_experience(event.ref_id)
            data["record"] = exp.as_dict() if exp else None
        return data

    # --- the Experience store ------------------------------------------
    def remember_experience(self, **fields: Any) -> dict[str, Any]:
        """Manually record an Experience (source = manual), then apply it."""
        payload = {k: fields.get(k) for k in (
            "title", "problem", "diagnosis", "actions", "mistakes",
            "solution", "lessons", "tags",
        ) if fields.get(k) is not None}
        event = self._propose(
            SOURCE_MANUAL,
            STORE_EXPERIENCE,
            source_id=None,
            summary=f"Experience: {payload.get('title') or payload.get('problem', '')[:120]}",
            reason="Recorded manually by the user.",
            origin="manual",
            payload=payload,
            policy=fields.get("policy"),
        )
        # A manual "remember" is an explicit act → apply immediately if not already.
        if not event.get("applied"):
            return self.apply(event["event"]["id"], policy=fields.get("policy"))
        return event

    def list_experiences(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return [e.as_dict() for e in self._repo.list_experiences(limit=limit)]

    def recall(self, query: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        k = limit or self._recall_k
        query = (query or "").strip()
        if not query:
            return self.list_experiences(limit=k)
        return [e.as_dict() for e in self._repo.search_experiences(query, limit=k)]

    # --- lifecycle ------------------------------------------------------
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def health_check(self) -> HealthStatus:
        try:
            events = self._repo.count_events()
            proposed = self._repo.count_events(status=EVENT_PROPOSED)
            experiences = self._repo.count_experiences()
        except Exception as exc:  # noqa: BLE001 - health must never raise
            return HealthStatus.fail(f"learning store unreachable: {exc}")
        return HealthStatus.ok(
            f"{events} event(s), {proposed} proposed, {experiences} experience(s)",
            enabled=self._enabled,
            auto_apply=self._auto_apply,
        )


# --- experience extraction (pure helper) ---------------------------------
def _experience_from_job(
    objective: str,
    steps: list[Any],
    result: dict[str, Any],
    job_id: Any,
) -> dict[str, Any] | None:
    if not objective.strip():
        return None
    actions: list[str] = []
    mistakes: list[str] = []
    for s in steps:
        status = getattr(s, "status", "")
        intent = getattr(s, "intent", "")
        desc = getattr(s, "description", "") or intent
        if status == "done":
            actions.append(desc)
        elif status in {"failed", "blocked", "skipped"}:
            reason = getattr(s, "blocked_reason", None) or getattr(s, "error", None) or status
            mistakes.append(f"{desc}: {reason}")
    solution = result.get("answer", "") or ""
    sections = result.get("report_sections") or {}
    lessons_bits = []
    if sections.get("limitations"):
        lessons_bits.append(f"Limitations: {sections['limitations']}")
    if sections.get("next_research"):
        lessons_bits.append(f"Next: {sections['next_research']}")
    return {
        "title": objective[:120],
        "problem": objective,
        "diagnosis": (sections.get("executive_summary") or result.get("summary") or ""),
        "actions": actions,
        "mistakes": "; ".join(mistakes),
        "solution": solution,
        "lessons": " ".join(lessons_bits),
        "tags": ["job"],
    }
