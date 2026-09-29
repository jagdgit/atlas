"""Persistent worker that ticks the Agent Kernel.

Advice, research, and observation only. Market gates stay in the trading workers.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.agent_kernel.kernel import AgentKernel
from atlas.agent_kernel.safety import scope_allowed
from atlas.workers.base import PersistentWorker, TickContext, TickResult


class AgentKernelWorker(PersistentWorker):
    type = "agent_kernel"
    VERSION = 1

    def __init__(
        self,
        *,
        data_dir: str,
        experience_os: Any = None,
        activity_journal: Any = None,
        job_planner: Any = None,
        llm: Any = None,
        enabled: bool = True,
        allow_external: bool = True,
        logger: logging.Logger | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._experience_os = experience_os
        self._journal = activity_journal
        self._planner = job_planner
        self._llm = llm
        self._enabled = bool(enabled)
        self._allow_external = bool(allow_external)
        self._web: Any = None
        self._logger = logger or logging.getLogger("atlas.workers.agent_kernel")
        self._kernel: AgentKernel | None = None

    def bind_web_search(self, client: Any) -> None:
        """Attach Atlas's existing search plugin. Does not build a second client."""
        self._web = client
        if self._kernel is not None:
            self._kernel.bind_web_search(client)

    def kernel(self) -> AgentKernel:
        if self._kernel is None:
            self._kernel = AgentKernel(
                self._data_dir,
                experience_os=self._experience_os,
                activity_journal=self._journal,
                job_planner=self._planner,
                llm=self._llm,
                web_search=self._web,
                logger=self._logger,
            )
        return self._kernel

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = dict(ctx.config or {})
        state = dict(ctx.state or {})
        state["ticks"] = int(state.get("ticks") or 0) + 1
        enabled = bool(cfg.get("enabled", self._enabled))
        if not enabled:
            state["enabled"] = False
            return TickResult(state=state, note="agent kernel disabled")
        scope = str(cfg.get("action_scope") or "advice_research_observation")
        if not scope_allowed(scope):
            state["refused_scope"] = scope
            return TickResult(
                state=state,
                note=f"refused action_scope {scope}; autonomous loop stays advice/research/observation",
            )
        mode = str(cfg.get("mode") or "tick")
        # Process config is the operator switch. A stale mission document that
        # still says false must not turn external search back off.
        if self._allow_external:
            allow_external = True
        else:
            allow_external = bool(cfg.get("allow_external", False))
        try:
            report = self.kernel().cycle(
                mode=mode,
                laboratory_id=str(cfg.get("laboratory_id") or "india_equity_learner"),
                allow_external=allow_external,
                max_investigations=int(cfg.get("max_investigations_per_tick") or 1),
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("agent kernel tick failed: %s", exc)
            state["last_error"] = str(exc)[:300]
            return TickResult(state=state, note=f"agent kernel tick failed: {exc}")
        state["enabled"] = True
        state["action_scope"] = scope
        state["last_mode"] = report.get("mode")
        state["last_ran"] = list(report.get("ran") or [])
        state["last_note"] = report.get("note")
        return TickResult(state=state, note=str(report.get("note") or "agent kernel tick"))
