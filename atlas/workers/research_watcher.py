"""ResearchWatcher — continuous literature research mission worker (Phase D · §D.7).

Each tick drives the D-Core decision path over a configured topic:

    ResearchService.research → promote_research (Knowledge OS) → DecisionEngine.decide
    (ResearchDecisionRule: what to read next) → journal (P9) → notify on notable findings

The worker owns no knowledge (P11): it drives the research service + the shared engine and
journals what it did. Bounded + checkpointed: state carries the last topic fingerprint, seen
finding ids, and the last recommended source so an unchanged topic is a cheap no-op and the
loop resumes after a reboot. Never completes — a permanent watcher (like Owner Knowledge).
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from atlas.decision.contracts import ACTION_RECOMMEND, DecisionRequest
from atlas.jobs.workspace import JobWorkspace
from atlas.research.decision_rule import MISSION_TYPE_RESEARCH
from atlas.research.learn import promote_research
from atlas.workers.base import PersistentWorker, TickContext, TickResult

# Confidence ranks for alert_min_confidence filtering (higher = more confident).
_CONF_RANK = {"low": 1, "medium": 2, "high": 3, "": 0}


class ResearchWatcher(PersistentWorker):
    type = "research_watcher"
    VERSION = 1
    journal_ticks = True

    def __init__(
        self,
        *,
        research: Any,
        decision_engine: Any,
        knowledge: Any = None,
        learning: Any = None,
        events: Any = None,
        data_dir: str | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._research = research
        self._engine = decision_engine
        self._knowledge = knowledge
        self._learning = learning
        self._events = events
        self._data_dir = data_dir or "/tmp/atlas"
        self._logger = logger or logging.getLogger("atlas.workers.research_watcher")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        topic = str(cfg.get("topic") or "").strip()
        if not topic:
            return TickResult(state=state, note="")  # nothing configured yet — idle quietly

        force = any(bool(item.get("force")) for item in ctx.inputs)
        config_note = ""
        if ctx.config_version is not None and ctx.config_version != state.get("config_version"):
            config_note = f"config v{ctx.config_version} picked up; "
            state["config_version"] = ctx.config_version

        fingerprint = self._fingerprint(topic, cfg)
        if not force and fingerprint == state.get("topic_fingerprint"):
            state["ticks"] = int(state.get("ticks", 0)) + 1
            note = f"{config_note}no change (topic unchanged)".strip() if config_note else ""
            return TickResult(state=state, note=note)

        workspace = JobWorkspace.for_job(
            self._data_dir, f"mission-research-{ctx.mission_id}"
        ).ensure()

        result = self._research.research(
            topic,
            max_iterations=int(cfg.get("max_iterations") or 3),
            per_query=int(cfg.get("per_query") or 5) or None,
            workspace=workspace,
        )
        outcome = str(result.get("outcome") or "error")
        state["last_outcome"] = outcome
        state["ticks"] = int(state.get("ticks", 0)) + 1

        if outcome not in ("ok", "empty"):
            # unavailable / error — honest note; optionally notify so the operator can add capability.
            self._emit("ResearchUnavailable", {
                "mission_id": str(ctx.mission_id),
                "topic": topic,
                "outcome": outcome,
                "reason": result.get("reason"),
            })
            note = f"{config_note}research {outcome}: {result.get('reason') or 'see log'}".strip()
            return TickResult(state=state, note=note)

        # Promote into Knowledge OS (best-effort; never fails the tick).
        promote = promote_research(
            knowledge=self._knowledge,
            learning=self._learning,
            workspace=workspace,
            job_id=str(ctx.mission_id),
            objective=topic,
            graph=result.get("graph"),
            claims=self._claims_from(result),
            embed=bool(cfg.get("embed", False)),
        )
        state["last_promote"] = {
            "external_docs": promote.get("external_docs", 0),
            "research_docs": promote.get("research_docs", 0),
            "findings": promote.get("findings", 0),
        }

        candidates = list(result.get("recommendations") or [])
        decision = self._engine.decide(
            DecisionRequest(
                mission_id=ctx.mission_id,
                mission_type=MISSION_TYPE_RESEARCH,
                config_version=ctx.config_version,
                context={
                    "objective": topic,
                    "candidates": candidates,
                    "gaps": result.get("gaps") or {},
                    "findings_count": len(result.get("findings") or []),
                    "outcome": outcome,
                },
            )
        )
        state["last_decision_id"] = str(decision.id) if decision.id else None

        # Notable findings → notify (only newly seen, above alert floor).
        new_findings = self._notable_findings(
            result.get("findings") or [],
            seen=set(state.get("seen_finding_ids") or []),
            min_confidence=str(cfg.get("alert_min_confidence") or "medium"),
        )
        seen = list(state.get("seen_finding_ids") or [])
        for finding in new_findings:
            fid = str(finding.get("id") or finding.get("statement") or "")[:120]
            if fid and fid not in seen:
                seen.append(fid)
            self._emit("ResearchFinding", {
                "mission_id": str(ctx.mission_id),
                "decision_id": str(decision.id) if decision.id else None,
                "topic": topic,
                "finding": finding,
            })
        state["seen_finding_ids"] = seen[-200:]  # bound checkpoint size

        recommended = None
        if decision.action_kind == ACTION_RECOMMEND:
            payload = (decision.action or {}).get("payload") or {}
            if payload.get("kind") == "read_next":
                recommended = payload.get("source")
                state["last_recommended"] = recommended
                self._emit("ResearchRecommendation", {
                    "mission_id": str(ctx.mission_id),
                    "decision_id": str(decision.id) if decision.id else None,
                    "topic": topic,
                    "source": recommended,
                    "why": decision.why,
                })

        state["topic_fingerprint"] = fingerprint
        note = (
            f"{config_note}research {outcome}: "
            f"+{promote.get('external_docs', 0)} doc(s), "
            f"+{promote.get('research_docs', 0)} research, "
            f"+{promote.get('findings', 0)} finding(s); "
            f"{len(candidates)} candidate(s)"
            + (f"; next: {(recommended or {}).get('title', '')[:60]}" if recommended else "")
            + (f"; {len(new_findings)} notable" if new_findings else "")
        ).strip()
        return TickResult(state=state, note=note)

    # --- helpers --------------------------------------------------------
    @staticmethod
    def _fingerprint(topic: str, cfg: dict[str, Any]) -> str:
        key = "|".join([
            topic,
            str(cfg.get("max_iterations", 3)),
            str(cfg.get("max_documents", 12)),
            str(cfg.get("per_query", 5)),
        ])
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    @staticmethod
    def _claims_from(result: dict[str, Any]) -> list[dict[str, Any]] | None:
        claim = result.get("claim")
        if isinstance(claim, dict) and claim:
            return [claim]
        return None

    @staticmethod
    def _notable_findings(
        findings: list[dict[str, Any]], *, seen: set[str], min_confidence: str
    ) -> list[dict[str, Any]]:
        floor = _CONF_RANK.get(min_confidence.lower(), 0)
        out: list[dict[str, Any]] = []
        for f in findings:
            fid = str(f.get("id") or f.get("statement") or "")[:120]
            if fid and fid in seen:
                continue
            conf = str(f.get("confidence") or f.get("overall_confidence") or "").lower()
            if floor and _CONF_RANK.get(conf, 0) < floor:
                continue
            out.append(f)
        return out

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._events is None:
            return
        try:
            self._events.emit(event_type, payload, source=self.type)
        except Exception:  # noqa: BLE001 - telemetry must never break a tick
            self._logger.exception("failed to emit %s", event_type)
