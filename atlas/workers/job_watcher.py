"""JobWatcher — continuous job-search mission worker (Phase D · §D.8).

Each tick drives the D-Core decision path over configured posting sources:

    Asset → JobPostingsReader → postings → DecisionEngine.decide
    (JobDecisionRule: match Personal + Policy + constraints) → journal (P9) → notify

Recommend-only (P14): Atlas ranks and notifies; it never applies to a job. The worker owns no
knowledge (P11). Bounded + checkpointed: state carries a sources fingerprint and seen posting
ids so an unchanged feed is a cheap no-op and the loop resumes after a reboot. Never completes.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from atlas.career.decision_rule import MISSION_TYPE_JOB_HUNTING
from atlas.decision.contracts import ACTION_RECOMMEND, DecisionRequest
from atlas.workers.base import PersistentWorker, TickContext, TickResult

ASSET_KIND_JOB_POSTINGS = "job_postings"


class JobWatcher(PersistentWorker):
    type = "job_watcher"
    VERSION = 1
    journal_ticks = True

    def __init__(
        self,
        *,
        assets: Any,
        postings_reader: Any,
        decision_engine: Any,
        personal: Any = None,
        events: Any = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._assets = assets
        self._reader = postings_reader
        self._engine = decision_engine
        self._personal = personal
        self._events = events
        self._logger = logger or logging.getLogger("atlas.workers.job_watcher")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        sources = [str(s).strip() for s in (cfg.get("sources") or []) if str(s).strip()]
        if not sources:
            return TickResult(state=state, note="")  # nothing configured — idle quietly

        force = any(bool(item.get("force")) for item in ctx.inputs)
        config_note = ""
        if ctx.config_version is not None and ctx.config_version != state.get("config_version"):
            config_note = f"config v{ctx.config_version} picked up; "
            state["config_version"] = ctx.config_version

        postings, load_errors = self._load_all(sources)
        fingerprint = self._fingerprint(sources, postings, cfg)
        if not force and fingerprint == state.get("sources_fingerprint") and not load_errors:
            state["ticks"] = int(state.get("ticks", 0)) + 1
            note = f"{config_note}no change (postings unchanged)".strip() if config_note else ""
            return TickResult(state=state, note=note)

        personal_skills = self._personal_skill_names(
            include_inferred=bool(cfg.get("include_inferred_skills", True))
        )

        decision = self._engine.decide(
            DecisionRequest(
                mission_id=ctx.mission_id,
                mission_type=MISSION_TYPE_JOB_HUNTING,
                config_version=ctx.config_version,
                context={
                    "postings": postings,
                    "locations": list(cfg.get("locations") or []),
                    "companies": list(cfg.get("companies") or []),
                    "skills": list(cfg.get("skills") or []),
                    "min_salary": cfg.get("min_salary", 0),
                    "min_skill_overlap": int(cfg.get("min_skill_overlap") or 0),
                    "personal_skills": sorted(personal_skills),
                    "include_inferred_skills": bool(cfg.get("include_inferred_skills", True)),
                },
            )
        )
        state["last_decision_id"] = str(decision.id) if decision.id else None
        state["ticks"] = int(state.get("ticks", 0)) + 1
        state["sources_fingerprint"] = fingerprint
        state["last_posting_count"] = len(postings)

        # Notify only on *new* top recommendations (seen-id checkpoint → reboot-safe).
        seen = list(state.get("seen_posting_ids") or [])
        seen_set = set(seen)
        new_recs: list[dict[str, Any]] = []
        if decision.action_kind == ACTION_RECOMMEND:
            payload = (decision.action or {}).get("payload") or {}
            if payload.get("kind") == "recommend_match":
                posting = payload.get("posting") or {}
                pid = str(posting.get("id") or "")
                if pid and pid not in seen_set:
                    new_recs.append(posting)
                    seen.append(pid)
                    self._emit("JobMatchRecommended", {
                        "mission_id": str(ctx.mission_id),
                        "decision_id": str(decision.id) if decision.id else None,
                        "posting": posting,
                        "why": decision.why,
                    })

        state["seen_posting_ids"] = seen[-500:]
        state["last_recommended"] = new_recs[0] if new_recs else state.get("last_recommended")

        note = (
            f"{config_note}job watch: {len(postings)} posting(s)"
            + (f", {load_errors} source error(s)" if load_errors else "")
            + (f"; recommended {new_recs[0].get('title', '')[:50]}" if new_recs else "; hold")
        ).strip()
        return TickResult(state=state, note=note)

    # --- helpers --------------------------------------------------------
    def _load_all(self, sources: list[str]) -> tuple[list[dict[str, Any]], int]:
        postings: list[dict[str, Any]] = []
        errors = 0
        seen_ids: set[str] = set()
        for name in sources:
            try:
                for p in self._load_source(name):
                    pid = str(p.get("id") or "")
                    if pid and pid not in seen_ids:
                        seen_ids.add(pid)
                        postings.append(p)
            except Exception as exc:  # noqa: BLE001 - a bad source must not stop the others
                errors += 1
                self._logger.warning("job postings source failed (%s): %s", name, exc)
        return postings, errors

    def _load_source(self, asset_name: str) -> list[dict[str, Any]]:
        asset = self._assets.get_by_name(ASSET_KIND_JOB_POSTINGS, asset_name)
        if asset is None:
            raise FileNotFoundError(f"no job_postings asset named {asset_name!r}")
        artifact = self._reader.read(str(asset["id"]))
        if artifact.get("outcome") != "ok":
            raise RuntimeError(f"postings unreadable: {artifact.get('reason', 'unknown')}")
        return list(artifact.get("postings") or [])

    def _personal_skill_names(self, *, include_inferred: bool) -> set[str]:
        if self._personal is None:
            return set()
        try:
            facts = self._personal.skills(include_inferred=include_inferred) or []
        except Exception as exc:  # noqa: BLE001 - personal is advisory for matching
            self._logger.warning("personal skills lookup failed: %s", exc)
            return set()
        names: set[str] = set()
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            value = fact.get("value")
            if isinstance(value, dict) and value.get("skill"):
                names.add(str(value["skill"]).strip().lower())
            if fact.get("key"):
                names.add(str(fact["key"]).strip().lower())
        return {n for n in names if n}

    @staticmethod
    def _fingerprint(sources: list[str], postings: list[dict[str, Any]], cfg: dict[str, Any]) -> str:
        ids = sorted(str(p.get("id") or "") for p in postings)
        key = "|".join([
            ",".join(sources),
            ",".join(ids),
            str(cfg.get("min_salary", 0)),
            ",".join(sorted(str(s) for s in (cfg.get("skills") or []))),
            ",".join(sorted(str(s) for s in (cfg.get("locations") or []))),
            ",".join(sorted(str(s) for s in (cfg.get("companies") or []))),
        ])
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._events is None:
            return
        try:
            self._events.emit(event_type, payload, source=self.type)
        except Exception:  # noqa: BLE001
            self._logger.exception("failed to emit %s", event_type)
