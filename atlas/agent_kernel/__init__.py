"""Agent Kernel — persistent observe → investigate → verify → learn loop.

The kernel orchestrates work. It does not own market strategy, order placement,
evidence truth, or learning promotion. Cognitive Core is a tool it may call.
"""

from atlas.agent_kernel.kernel import AgentKernel
from atlas.agent_kernel.worker import AgentKernelWorker

__all__ = ["AgentKernel", "AgentKernelWorker"]
