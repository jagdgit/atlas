"""SelfImprovementWatcher — hermetic eval → decide → gate → dashboard (Phase D · §D.10).

Each tick runs the Stage-3B hermetic baseline suite, compares against the previous
checkpoint + metric floors, asks the Decision Engine what to do next, journals the P9
record, notifies on regressions, and updates the ImprovementBoard for the Operations
Dashboard. Side-effecting fix proposals open the human-approval gate (P14).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from atlas.decision.contracts import ACTION_RECOMMEND, DecisionRequest
from atlas.eval.baseline import run_baseline_suite
from atlas.improvement.analyze import analyze_baseline, flatten_metrics
from atlas.improvement.decision_rule import MISSION_TYPE_SELF_IMPROVEMENT
from atlas.workers.base import PersistentWorker, TickContext, TickResult


class SelfImprovementWatcher(PersistentWorker):
    type = "self_improvement"
    VERSION = 1
    journal_ticks = True

    def __init__(
        self,
        *,
        decision_engine: Any,
        board: Any,
        events: Any = None,
        fixture_root: str | Path | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._engine = decision_engine
        self._board = board
        self._events = events
        self._default_root = Path(fixture_root) if fixture_root else None
        self._logger = logger or logging.getLogger("atlas.workers.self_improvement")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})

        force = any(bool(item.get("force")) for item in ctx.inputs)
        config_note = ""
        if ctx.config_version is not None and ctx.config_version != state.get("config_version"):
            config_note = f"config v{ctx.config_version} picked up; "
            state["config_version"] = ctx.config_version

        root = self._resolve_root(cfg)
        try:
            report = run_baseline_suite(root=root)
        except Exception as exc:  # noqa: BLE001 - honest failure, never crash the manager
            self._logger.warning("baseline suite failed: %s", exc)
            self._emit("SelfImprovementUnavailable", {
                "mission_id": str(ctx.mission_id),
                "reason": str(exc),
            })
            state["ticks"] = int(state.get("ticks", 0)) + 1
            return TickResult(
                state=state,
                note=f"{config_note}eval unavailable: {exc}".strip(),
            )

        metrics = flatten_metrics(report.sections)
        fingerprint = _fingerprint(metrics)
        if not force and fingerprint == state.get("metrics_fingerprint"):
            state["ticks"] = int(state.get("ticks", 0)) + 1
            note = f"{config_note}no change (metrics unchanged)".strip() if config_note else ""
            return TickResult(state=state, note=note)

        previous = dict(state.get("last_metrics") or {})
        floors = {
            str(k): float(v)
            for k, v in (cfg.get("metric_floors") or {}).items()
            if _is_number(v)
        }
        findings = analyze_baseline(
            metrics,
            previous=previous or None,
            floors=floors or None,
            regression_drop=float(cfg.get("regression_drop", 0.05) or 0.05),
        )

        decision = self._engine.decide(
            DecisionRequest(
                mission_id=ctx.mission_id,
                mission_type=MISSION_TYPE_SELF_IMPROVEMENT,
                config_version=ctx.config_version,
                context={
                    "findings": findings,
                    "metrics": metrics,
                    "gate_fixes": bool(cfg.get("gate_fixes", True)),
                    "milestone": report.milestone,
                },
            )
        )

        recommendation = None
        if decision.action_kind == ACTION_RECOMMEND:
            payload = (decision.action or {}).get("payload") or {}
            if payload.get("kind") in ("investigate", "propose_fix"):
                recommendation = {
                    "kind": payload.get("kind"),
                    "finding_id": payload.get("finding_id"),
                    "text": decision.action.get("key"),
                    "why": decision.why,
                    "payload": payload,
                    "requires_approval": decision.requires_approval,
                }

        self._board.record_run(
            metrics=metrics,
            findings=findings,
            decision_id=str(decision.id) if decision.id else None,
            recommendation=recommendation,
            milestone=report.milestone,
        )

        if findings:
            self._emit("SelfImprovementFinding", {
                "mission_id": str(ctx.mission_id),
                "decision_id": str(decision.id) if decision.id else None,
                "finding_count": len(findings),
                "findings": findings[:10],
            })
        if recommendation and recommendation.get("kind") == "propose_fix":
            self._emit("SelfImprovementRecommendation", {
                "mission_id": str(ctx.mission_id),
                "decision_id": str(decision.id) if decision.id else None,
                "recommendation": recommendation,
                "requires_approval": decision.requires_approval,
            })

        state["last_metrics"] = metrics
        state["metrics_fingerprint"] = fingerprint
        state["last_decision_id"] = str(decision.id) if decision.id else None
        state["last_finding_count"] = len(findings)
        state["ticks"] = int(state.get("ticks", 0)) + 1

        note = (
            f"{config_note}eval {report.milestone}: {len(metrics)} metric(s), "
            f"{len(findings)} finding(s)"
            + (
                f"; {recommendation['kind']} {recommendation.get('finding_id', '')}"
                if recommendation else "; hold"
            )
            + ("; gated" if decision.requires_approval else "")
        ).strip()
        return TickResult(state=state, note=note)

    def _resolve_root(self, cfg: dict[str, Any]) -> Path | None:
        override = str(cfg.get("fixture_root") or "").strip()
        if override:
            return Path(override)
        return self._default_root

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._events is None:
            return
        try:
            self._events.emit(event_type, payload, source=self.type)
        except Exception:  # noqa: BLE001
            self._logger.exception("failed to emit %s", event_type)


def _fingerprint(metrics: dict[str, float]) -> str:
    import hashlib
    parts = [f"{k}={metrics[k]:.6f}" for k in sorted(metrics)]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def _is_number(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False
