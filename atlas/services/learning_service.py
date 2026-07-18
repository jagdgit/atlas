"""LearningService — the ``learning`` capability (S18b, D11/§5d + Stage 3B.5).

Continuous Learning is the third pillar: completed activities become durable,
*governed* knowledge. Two guarantees are enforced here, not just documented:

- **Atlas never silently learns.** Observing a completed job (or any source) only
  ever creates a **proposed** ``LearningEvent`` by default (``auto_apply`` off). A
  proposal must be **applied** to enter a store, and every proposal records *what*
  (summary), *why* (reason), and *from where* (origin) — it is explainable.
- **Learning is governed and reversible.** Applying attaches a policy
  (temporary/project/personal/verified) + Learning Level, and creates the store
  record; **reverting** flips the event to ``reverted`` and deactivates that record.

Stage 3B.5 extends Experience payloads (readers, paywalls, timings, strategies,
recommendations, component+version observations) and adds advice-only recall plus
a gated soft-bias path (apply → enable_bias → tiny retrieve boost). Soft bias never
auto-enables and never rewrites core behavior.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from atlas.learning.components import (
    REASONER_V1,
    RETRIEVAL_HYBRID,
    SOURCE_PREFIX,
    SYNTHESIZER_V1,
    component_observation,
    domain_from_url,
    reader_component_key,
    source_component_key,
)
from atlas.models.learning import (
    EVENT_APPLIED,
    EVENT_PROPOSED,
    EVENT_REVERTED,
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

# Tiny soft-bias magnitude after human enable (A3B.18 / A3B.25). Never filters/hides.
SOFT_BIAS_BOOST = 0.005


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
            result = getattr(job, "result", None) or detail.get("result") or {}
            if not isinstance(result, dict):
                result = {}
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
                payload=payload,
                bias_enabled=False,
            )
            ref_id = exp.id
            self._persist_component_observations(
                payload.get("component_observations") or [],
                source_job_id=event.source_id,
                experience_id=exp.id,
                event_id=event.id,
            )
        elif event.store in self._sinks:
            ref_id = self._sinks[event.store].apply(payload, policy=policy or event.policy)
        else:
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
                if hasattr(self._repo, "set_bias_enabled"):
                    self._repo.set_bias_enabled(event.ref_id, False)
            elif event.store in self._sinks:
                self._sinks[event.store].revert(event.ref_id)
        self._repo.set_event_status(event.id, EVENT_REVERTED, reviewed=True)
        reverted = self._repo.get_event(event.id)
        return {"event": reverted.as_dict() if reverted else None, "reverted": True}

    def _persist_component_observations(
        self,
        observations: list[Any],
        *,
        source_job_id: str | None,
        experience_id: str,
        event_id: str,
    ) -> None:
        if not hasattr(self._repo, "add_component_observation"):
            return
        for obs in observations:
            if not isinstance(obs, dict) or not obs.get("component_key"):
                continue
            try:
                self._repo.add_component_observation(
                    component_key=str(obs["component_key"]),
                    component_version=str(obs.get("component_version") or "1"),
                    corpus=obs.get("corpus"),
                    profile=obs.get("profile"),
                    metrics=obs.get("metrics") or {},
                    source_job_id=source_job_id,
                    experience_id=experience_id,
                    event_id=str(event_id),
                )
            except Exception:  # noqa: BLE001
                self._logger.debug("component observation persist failed", exc_info=True)

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
        for key in (
            "readers", "paywalls", "timings", "strategies", "recommendations",
            "component_observations", "domain", "provisional", "overall_confidence",
        ):
            if fields.get(key) is not None:
                payload[key] = fields[key]
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

    def advice_for(self, query: str, *, limit: int | None = None) -> dict[str, Any]:
        """Non-mutating planning/research advice from applied experiences (3B.5)."""
        hits = self.recall(query, limit=limit)
        lines: list[str] = []
        for hit in hits:
            title = (hit.get("title") or hit.get("problem") or "").strip()
            lessons = (hit.get("lessons") or "").strip()
            solution = (hit.get("solution") or "").strip()
            payload = hit.get("payload") or {}
            recs = payload.get("recommendations") if isinstance(payload, dict) else None
            bit = lessons or solution
            if not bit and isinstance(recs, list) and recs:
                bit = "; ".join(
                    str(r.get("title") or r.get("why") or r)
                    for r in recs[:3]
                    if r
                )
            if title or bit:
                lines.append(f"- {title}: {bit}".rstrip(": "))
        text = "\n".join(lines).strip()
        # Fold in accumulated *operational* source-reliability advice (§3B loop):
        # which publishers/domains have been reliably readable vs routinely blocked.
        # Advice-only — this never reorders acquisition automatically.
        operational = self.source_advice()
        combined = text
        if operational.get("advice"):
            block = "Source reliability (operational, advice-only):\n" + operational["advice"]
            combined = f"{text}\n\n{block}".strip() if text else block
        return {
            "query": query,
            "count": len(hits),
            "advice": combined,
            "experiences": hits,
            "operational": operational,
            "mutating": False,
        }

    def source_advice(self, *, min_attempts: int = 2, limit: int = 20) -> dict[str, Any]:
        """Ranked prefer/deprioritize advice from accumulated source outcomes (§3B loop).

        Aggregates ``source:{domain}`` component observations (which only exist for
        *applied* experiences — the human-approval gate) into per-domain acquisition
        success/failure, then recommends preferring reliably readable domains and
        deprioritizing routinely blocked/unreadable ones. Purely non-mutating: Atlas
        surfaces this so a human (or the informed planner) can act on it; it never
        silently changes acquisition order.
        """
        empty = {"count": 0, "prefer": [], "avoid": [], "advice": "", "mutating": False}
        if not hasattr(self._repo, "list_component_observations"):
            return empty
        agg: dict[str, dict[str, int]] = {}
        try:
            observations = self._repo.list_component_observations(limit=1000)
        except Exception:  # noqa: BLE001 - advice must never raise into research
            self._logger.debug("source_advice observation load failed", exc_info=True)
            return empty
        for obs in observations:
            key = getattr(obs, "component_key", "") or ""
            if not key.startswith(SOURCE_PREFIX):
                continue
            domain = key[len(SOURCE_PREFIX):]
            if not domain:
                continue
            metrics = getattr(obs, "metrics", None) or {}
            d = agg.setdefault(domain, {})
            for field in _SOURCE_STATUSES + ("total", "claims"):
                d[field] = d.get(field, 0) + int(metrics.get(field) or 0)
        prefer: list[dict[str, Any]] = []
        avoid: list[dict[str, Any]] = []
        for domain, d in agg.items():
            total = int(d.get("total", 0))
            if total < min_attempts:
                continue
            produced = int(d.get("ok", 0))
            readable = produced + int(d.get("no_claims", 0))
            failed = (
                int(d.get("blocked", 0))
                + int(d.get("read_failed", 0))
                + int(d.get("not_acquired", 0))
            )
            produce_rate = produced / total
            fail_rate = failed / total
            entry = {
                "domain": domain,
                "attempts": total,
                "produced_claims": produced,
                "readable": readable,
                "failed": failed,
                "claims": int(d.get("claims", 0)),
                "produce_rate": round(produce_rate, 3),
                "fail_rate": round(fail_rate, 3),
            }
            if produce_rate >= 0.5:
                entry["reason"] = f"produced claims in {produced}/{total} attempt(s)"
                prefer.append(entry)
            elif fail_rate >= 0.5:
                entry["reason"] = f"blocked/unreadable in {failed}/{total} attempt(s)"
                avoid.append(entry)
        prefer.sort(key=lambda e: (e["produce_rate"], e["attempts"]), reverse=True)
        avoid.sort(key=lambda e: (e["fail_rate"], e["attempts"]), reverse=True)
        prefer, avoid = prefer[:limit], avoid[:limit]
        lines = [f"- Prefer {e['domain']} — {e['reason']}." for e in prefer]
        lines += [
            f"- Deprioritize {e['domain']} — {e['reason']}; seek an open-access "
            "alternative."
            for e in avoid
        ]
        return {
            "count": len(agg),
            "prefer": prefer,
            "avoid": avoid,
            "advice": "\n".join(lines).strip(),
            "mutating": False,
        }

    def enable_bias(self, experience_id: str, *, enabled: bool = True) -> dict[str, Any]:
        """Explicit human gate for soft retrieve bias (D3B.12 / A3B.18)."""
        exp = self._repo.get_experience(experience_id)
        if exp is None:
            raise KeyError(f"no experience {experience_id}")
        if exp.status != "active":
            raise ValueError("bias can only be enabled on active experiences")
        if not hasattr(self._repo, "set_bias_enabled"):
            raise RuntimeError("repository does not support bias_enabled")
        self._repo.set_bias_enabled(experience_id, enabled)
        updated = self._repo.get_experience(experience_id)
        return {
            "experience": updated.as_dict() if updated else None,
            "bias_enabled": bool(enabled),
        }

    def soft_bias_terms(self, *, limit: int = 20) -> list[str]:
        """Terms from bias-enabled experiences for a tiny retrieve boost (never hide)."""
        if not hasattr(self._repo, "list_bias_enabled"):
            return []
        terms: list[str] = []
        for exp in self._repo.list_bias_enabled(limit=limit):
            payload = exp.payload or {}
            for key in ("title", "problem", "solution"):
                val = getattr(exp, key, "") or ""
                if val:
                    terms.append(str(val)[:80])
            for rec in payload.get("recommendations") or []:
                if isinstance(rec, dict):
                    t = rec.get("title") or rec.get("why") or ""
                    if t:
                        terms.append(str(t)[:80])
                elif rec:
                    terms.append(str(rec)[:80])
        seen: set[str] = set()
        out: list[str] = []
        for t in terms:
            low = t.lower().strip()
            if low and low not in seen:
                seen.add(low)
                out.append(t.strip())
        return out

    def list_component_observations(
        self, *, component_key: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        if not hasattr(self._repo, "list_component_observations"):
            return []
        return [
            o.as_dict()
            for o in self._repo.list_component_observations(
                component_key=component_key, limit=limit
            )
        ]

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
_CONFIDENCE_OK = {"HIGH", "MEDIUM"}
# Per-source pipeline-trace statuses aggregated into operational source experience.
_SOURCE_STATUSES = ("ok", "no_claims", "read_failed", "blocked", "not_acquired")


def _source_outcomes_from_trace(
    trace: list[dict[str, Any]] | None,
) -> dict[str, dict[str, int]]:
    """Aggregate a per-source pipeline trace into per-domain acquisition outcomes.

    ``{domain: {ok, no_claims, read_failed, blocked, not_acquired, total, claims}}``.
    This is the raw operational signal behind source-reliability advice (§3B loop).
    """
    out: dict[str, dict[str, int]] = {}
    for row in trace or []:
        if not isinstance(row, dict):
            continue
        domain = domain_from_url(row.get("url") or "")
        if not domain:
            continue
        agg = out.setdefault(domain, {s: 0 for s in _SOURCE_STATUSES})
        agg["total"] = agg.get("total", 0) + 1
        status = str(row.get("status") or "")
        if status in agg:
            agg[status] += 1
        agg["claims"] = agg.get("claims", 0) + (
            int(row.get("numeric_claims") or 0)
            + int(row.get("qualitative_claims") or 0)
            + int(row.get("inferred_claims") or 0)
        )
    return out


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

    research = _aggregate_research_extras(steps, result)
    solution = result.get("answer", "") or ""
    sections = result.get("report_sections") or {}
    lessons_bits = []
    if sections.get("limitations"):
        lessons_bits.append(f"Limitations: {sections['limitations']}")
    if sections.get("next_research"):
        lessons_bits.append(f"Next: {sections['next_research']}")
    tags = ["job", "experience"]
    confidence = (result.get("overall_confidence") or "").upper()
    if confidence and confidence not in _CONFIDENCE_OK:
        tags.append("provisional")

    readers = research.get("readers") or []
    paywalls = research.get("paywalls") or research.get("blocked") or []
    timings = research.get("timings") or {}
    strategies = research.get("strategies") or {}
    recommendations = research.get("recommendations") or []
    source_outcomes = _source_outcomes_from_trace(research.get("trace"))
    components = _component_observations_from_research(research, timings)

    return {
        "title": objective[:120],
        "problem": objective,
        "diagnosis": (sections.get("executive_summary") or result.get("summary") or ""),
        "actions": actions,
        "mistakes": "; ".join(mistakes),
        "solution": solution,
        "lessons": " ".join(lessons_bits),
        "tags": tags,
        "domain": "experience",
        "provisional": "provisional" in tags,
        "overall_confidence": confidence or None,
        "readers": readers,
        "paywalls": paywalls,
        "timings": timings,
        "strategies": strategies,
        "recommendations": recommendations,
        "source_outcomes": source_outcomes,
        "component_observations": components,
    }


def _aggregate_research_extras(
    steps: list[Any], result: dict[str, Any]
) -> dict[str, Any]:
    """Pull pipeline/blocked/recommendations/readers from job result + step extras."""
    extras: dict[str, Any] = {
        "pipeline": dict(result.get("pipeline") or {}),
        "blocked": list(result.get("blocked") or []),
        "recommendations": list(result.get("recommendations") or []),
        "readers": list(result.get("readers") or []),
        "usage": dict(result.get("usage") or {}),
    }
    for step in steps:
        step_result = getattr(step, "result", None) or {}
        if not isinstance(step_result, dict):
            continue
        if step_result.get("pipeline") and not extras["pipeline"]:
            extras["pipeline"] = dict(step_result["pipeline"])
        elif isinstance(step_result.get("pipeline"), dict):
            for k, v in step_result["pipeline"].items():
                extras["pipeline"].setdefault(k, v)
        for key in ("blocked", "recommendations", "readers"):
            vals = step_result.get(key)
            if isinstance(vals, list) and vals:
                if not extras[key]:
                    extras[key] = list(vals)
                else:
                    extras[key].extend(x for x in vals if x not in extras[key])
        usage = step_result.get("usage")
        if isinstance(usage, dict):
            for k, v in usage.items():
                extras["usage"].setdefault(k, v)
        docs = step_result.get("documents")
        if isinstance(docs, dict):
            for doc in docs.values():
                if isinstance(doc, dict) and doc.get("reader_id"):
                    rid = doc["reader_id"]
                    if rid not in extras["readers"]:
                        extras["readers"].append(rid)
        elif isinstance(docs, list):
            for doc in docs:
                if isinstance(doc, dict) and doc.get("reader_id"):
                    rid = doc["reader_id"]
                    if rid not in extras["readers"]:
                        extras["readers"].append(rid)

    usage = extras["usage"]
    timings = {
        k: usage[k]
        for k in (
            "research_elapsed_seconds",
            "verified_claims",
            "verified_claims_per_hour",
            "workspace_bytes",
            "documents_count",
            "documents_chars",
            "chars_read",
        )
        if k in usage
    }
    pipeline = extras["pipeline"]
    strategies = {
        k: pipeline[k]
        for k in (
            "rounds", "found", "acquired", "read", "extracted", "verified",
            "rejected", "findings", "patterns", "hypotheses", "blocked",
        )
        if k in pipeline
    }
    return {
        "readers": extras["readers"],
        "paywalls": extras["blocked"],
        "blocked": extras["blocked"],
        "timings": timings,
        "strategies": strategies,
        "recommendations": extras["recommendations"],
        "pipeline": pipeline,
        "trace": pipeline.get("trace") or [],
        "usage": usage,
    }


def _component_observations_from_research(
    research: dict[str, Any], timings: dict[str, Any]
) -> list[dict[str, Any]]:
    """Build A3B.17 component+version observation stubs from a research run."""
    out: list[dict[str, Any]] = []
    reader_counts: dict[str, int] = {}
    for rid in research.get("readers") or []:
        key = reader_component_key(str(rid))
        if key:
            reader_counts[key] = reader_counts.get(key, 0) + 1
    for key, count in reader_counts.items():
        out.append(
            component_observation(
                key,
                component_version="1",
                metrics={
                    "documents": count,
                    **{k: timings[k] for k in timings if k.startswith("documents")},
                },
            )
        )
    # Operational source-reliability observations (one per domain seen this run).
    for domain, agg in _source_outcomes_from_trace(research.get("trace")).items():
        key = source_component_key(domain)
        if key:
            out.append(
                component_observation(key, metrics=agg, profile="acquisition")
            )
    strategies = research.get("strategies") or {}
    if strategies:
        out.append(
            component_observation(
                RETRIEVAL_HYBRID,
                component_version="1",
                metrics={
                    "rounds": strategies.get("rounds"),
                    "acquired": strategies.get("acquired"),
                    "verified": strategies.get("verified"),
                },
                profile="research",
            )
        )
    if strategies.get("findings") is not None:
        out.append(
            component_observation(
                SYNTHESIZER_V1,
                component_version="1",
                metrics={"findings": strategies.get("findings")},
            )
        )
    if strategies.get("patterns") is not None or strategies.get("hypotheses") is not None:
        out.append(
            component_observation(
                REASONER_V1,
                component_version="1",
                metrics={
                    "patterns": strategies.get("patterns"),
                    "hypotheses": strategies.get("hypotheses"),
                },
            )
        )
    return out
