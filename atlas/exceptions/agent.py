"""Agent errors (run failed, no such agent)."""

from __future__ import annotations

from atlas.exceptions.base import AtlasError


class AgentError(AtlasError):
    """Any failure in the agent layer."""


class AgentNotFoundError(AgentError):
    """No agent is registered under the requested name."""


class AgentRunError(AgentError):
    """An agent run failed while executing."""
