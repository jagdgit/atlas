"""TechSecurityWatcher — shared Technology / Security watch worker (Phase D · §D.9).

One worker pattern behind two thin templates (``technology_watch``, ``security_monitoring``).
Each tick:

    Asset → AdvisoryFeedReader → advisories → DecisionEngine.decide
    (AdvisoryDecisionRule) → journal (P9) → notify

Recommend-only (P14): Atlas ranks and notifies; it never patches dependencies or remediates.
``mode`` in config selects the mission type / scoring bias (technology vs security).
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from atlas.decision.contracts import ACTION_RECOMMEND, DecisionRequest
from atlas.watch.decision_rule import MISSION_TYPE_SECURITY, MISSION_TYPE_TECHNOLOGY
from atlas.workers.base import PersistentWorker, TickContext, TickResult

ASSET_KIND_ADVISORY_FEED = "advisory_feed"

_MODE_TO_MISSION = {
    "technology": MISSION_TYPE_TECHNOLOGY,
    "tech": MISSION_TYPE_TECHNOLOGY,
    "security": MISSION_TYPE_SECURITY,
    "sec": MISSION_TYPE_SECURITY,
}


class TechSecurityWatcher(PersistentWorker):
    type = "tech_security_watcher"
    VERSION = 1
    journal_ticks = True

    def __init__(
        self,
        *,
        assets: Any,
        advisory_reader: Any,
        decision_engine: Any,
        events: Any = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._assets = assets
        self._reader = advisory_reader
        self._engine = decision_engine
        self._events = events
        self._logger = logger or logging.getLogger("atlas.workers.tech_security")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        sources = [str(s).strip() for s in (cfg.get("sources") or []) if str(s).strip()]
        if not sources:
            return TickResult(state=state, note="")

        force = any(bool(item.get("force")) for item in ctx.inputs)
        config_note = ""
        if ctx.config_version is not None and ctx.config_version != state.get("config_version"):
            config_note = f"config v{ctx.config_version} picked up; "
            state["config_version"] = ctx.config_version

        mode = str(cfg.get("mode") or "technology").lower()
        mission_type = _MODE_TO_MISSION.get(mode, MISSION_TYPE_TECHNOLOGY)
        focus = self._focus_terms(cfg)

        advisories, load_errors = self._load_all(sources)
        fingerprint = self._fingerprint(sources, advisories, cfg, mode)
        if not force and fingerprint == state.get("sources_fingerprint") and not load_errors:
            state["ticks"] = int(state.get("ticks", 0)) + 1
            note = f"{config_note}no change (advisories unchanged)".strip() if config_note else ""
            return TickResult(state=state, note=note)

        decision = self._engine.decide(
            DecisionRequest(
                mission_id=ctx.mission_id,
                mission_type=mission_type,
                config_version=ctx.config_version,
                context={
                    "advisories": advisories,
                    "focus": sorted(focus),
                    "severity_floor": cfg.get("severity_floor") or "medium",
                    "mode": "security" if mission_type == MISSION_TYPE_SECURITY else "technology",
                },
            )
        )
        state["last_decision_id"] = str(decision.id) if decision.id else None
        state["ticks"] = int(state.get("ticks", 0)) + 1
        state["sources_fingerprint"] = fingerprint
        state["last_advisory_count"] = len(advisories)
        state["mode"] = mode

        seen = list(state.get("seen_advisory_ids") or [])
        seen_set = set(seen)
        new_recs: list[dict[str, Any]] = []
        if decision.action_kind == ACTION_RECOMMEND:
            payload = (decision.action or {}).get("payload") or {}
            if payload.get("kind") == "recommend_advisory":
                advisory = payload.get("advisory") or {}
                aid = str(advisory.get("id") or "")
                if aid and aid not in seen_set:
                    new_recs.append(advisory)
                    seen.append(aid)
                    event_type = (
                        "SecurityAdvisoryRecommended"
                        if mission_type == MISSION_TYPE_SECURITY
                        else "TechnologyAdvisoryRecommended"
                    )
                    self._emit(event_type, {
                        "mission_id": str(ctx.mission_id),
                        "decision_id": str(decision.id) if decision.id else None,
                        "mode": mode,
                        "advisory": advisory,
                        "why": decision.why,
                    })

        state["seen_advisory_ids"] = seen[-500:]
        state["last_recommended"] = new_recs[0] if new_recs else state.get("last_recommended")

        note = (
            f"{config_note}{mode} watch: {len(advisories)} advisory(ies)"
            + (f", {load_errors} source error(s)" if load_errors else "")
            + (f"; recommended {new_recs[0].get('title', '')[:50]}" if new_recs else "; hold")
        ).strip()
        return TickResult(state=state, note=note)

    # --- helpers --------------------------------------------------------
    @staticmethod
    def _focus_terms(cfg: dict[str, Any]) -> set[str]:
        terms: set[str] = set()
        for key in ("focus", "technologies", "components"):
            for item in cfg.get(key) or []:
                t = str(item).strip().lower()
                if t:
                    terms.add(t)
        return terms

    def _load_all(self, sources: list[str]) -> tuple[list[dict[str, Any]], int]:
        advisories: list[dict[str, Any]] = []
        errors = 0
        seen: set[str] = set()
        for name in sources:
            try:
                for adv in self._load_source(name):
                    aid = str(adv.get("id") or "")
                    if aid and aid not in seen:
                        seen.add(aid)
                        advisories.append(adv)
            except Exception as exc:  # noqa: BLE001
                errors += 1
                self._logger.warning("advisory feed failed (%s): %s", name, exc)
        return advisories, errors

    def _load_source(self, asset_name: str) -> list[dict[str, Any]]:
        asset = self._assets.get_by_name(ASSET_KIND_ADVISORY_FEED, asset_name)
        if asset is None:
            raise FileNotFoundError(f"no advisory_feed asset named {asset_name!r}")
        artifact = self._reader.read(str(asset["id"]))
        if artifact.get("outcome") != "ok":
            raise RuntimeError(f"feed unreadable: {artifact.get('reason', 'unknown')}")
        return list(artifact.get("advisories") or [])

    @staticmethod
    def _fingerprint(
        sources: list[str], advisories: list[dict[str, Any]], cfg: dict[str, Any], mode: str
    ) -> str:
        ids = sorted(str(a.get("id") or "") for a in advisories)
        focus = sorted(
            str(x).lower()
            for key in ("focus", "technologies", "components")
            for x in (cfg.get(key) or [])
        )
        key = "|".join([
            mode,
            ",".join(sources),
            ",".join(ids),
            ",".join(focus),
            str(cfg.get("severity_floor") or "medium"),
        ])
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._events is None:
            return
        try:
            self._events.emit(event_type, payload, source=self.type)
        except Exception:  # noqa: BLE001
            self._logger.exception("failed to emit %s", event_type)
