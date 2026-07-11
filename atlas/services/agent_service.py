"""Agent service — kernel-managed registry and dispatcher for agents.

Holds the set of available agents and exposes a uniform way to run them, both
inline (``run``) and via the scheduler (``run_agent_task``, ADR-0034). Registering
an agent also records it in the ``agent.agents`` catalog on start, so the database
reflects what the running system can do.

The service is intentionally thin: per-agent behaviour (retrieval, generation,
run persistence) lives in the agents themselves. This service only wires them into
the kernel lifecycle and routes calls by name.
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from atlas.exceptions import AgentNotFoundError
from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.agents.base import Agent, AgentResult
    from atlas.repositories.agent_run_repo import AgentRunRepository


class AgentService:
    name = "agent"

    def __init__(
        self,
        agents: "list[Agent] | None" = None,
        run_repo: "AgentRunRepository | None" = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._agents: dict[str, "Agent"] = {}
        self._run_repo = run_repo
        self._logger = logger or logging.getLogger("atlas.agent")
        for agent in agents or []:
            self.register(agent)

    # --- registry -------------------------------------------------------
    def register(self, agent: "Agent") -> None:
        self._agents[agent.name] = agent

    def list(self) -> list[str]:
        return sorted(self._agents)

    def get(self, agent_name: str) -> "Agent":
        try:
            return self._agents[agent_name]
        except KeyError:
            raise AgentNotFoundError(
                f"no agent registered named '{agent_name}'", agent=agent_name
            ) from None

    # --- capability API -------------------------------------------------
    def run(self, agent_name: str, query: str, **options: Any) -> "AgentResult":
        return self.get(agent_name).run(query, **options)

    # --- Service lifecycle ---------------------------------------------
    def start(self) -> None:
        if self._run_repo is None:
            return
        # Record each agent in the catalog so the DB reflects capabilities.
        for agent in self._agents.values():
            try:
                self._run_repo.upsert_agent(
                    agent.name,
                    getattr(agent, "kind", agent.name),
                    description=getattr(agent, "description", None),
                    config=getattr(agent, "config_snapshot", lambda: {})(),
                )
            except Exception:  # noqa: BLE001 - catalog is best-effort, never fatal
                self._logger.exception("failed to register agent '%s'", agent.name)

    def stop(self) -> None:
        pass

    def health_check(self) -> HealthStatus:
        count = len(self._agents)
        detail = f"{count} agent(s): {', '.join(self.list()) or 'none'}"
        return HealthStatus(
            healthy=count > 0, detail=detail, data={"agents": self.list()}
        )

    # --- scheduler integration -----------------------------------------
    def run_agent_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Scheduler handler for task_type 'run_agent'.

        Payload: {"agent": <name>, "query": <text>, "options": {...}}.
        """
        agent_name = payload["agent"]
        query = payload["query"]
        options = payload.get("options") or {}
        result = self.run(agent_name, query, **options)
        return {"agent": agent_name, **result.as_dict()}
