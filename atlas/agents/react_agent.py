"""ReAct agent — reason + act over the ToolRegistry (ADR-0051).

A general assistant that solves tasks by iterating:

    reason -> emit a JSON action -> run a tool -> observe result -> repeat
    ... until it emits a final answer (or hits the iteration cap).

Tool selection is **prompt-based** (ADR-0051): the available tools (from the
kernel ToolRegistry, ADR-0050) are rendered into the system prompt, and the model
replies with exactly one JSON object per turn:

    {"thought": "...", "tool": "web.fetch", "args": {"url": "..."}}
    {"thought": "...", "final": "the answer"}

This is model-agnostic (works with qwen3:4b), fully testable with a fake LLM, and
needs no provider changes. Because other agents are registered as tools
(``agent.rag``, ADR-0052), this single loop also does multi-agent delegation.

Every run and step is persisted (ADR-0032) for observability. An optional
reflection pass reviews the draft answer before returning it.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from atlas.agents.base import AgentResult
from atlas.llm.provider import ChatMessage
from atlas.telemetry import get_metrics, start_span, timer

if TYPE_CHECKING:
    from atlas.kernel.tools import ToolRegistry
    from atlas.llm.service import LLMService
    from atlas.repositories.agent_run_repo import AgentRunRepository

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class ReActAgent:
    name = "assistant"
    kind = "react"
    description = "General assistant that reasons and uses tools (ReAct)."

    def __init__(
        self,
        llm: "LLMService",
        tools: "ToolRegistry",
        run_repo: "AgentRunRepository | None" = None,
        *,
        max_iterations: int = 6,
        reflection: bool = True,
        max_observation_chars: int = 2000,
        temperature: float = 0.0,
        think: bool = False,
        system_preamble: str = "You are Atlas, a capable assistant.",
        logger: logging.Logger | None = None,
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._run_repo = run_repo
        self._max_iterations = max_iterations
        self._reflection = reflection
        self._max_obs = max_observation_chars
        self._temperature = temperature
        self._think = think
        self._preamble = system_preamble
        self._logger = logger or logging.getLogger("atlas.agent.react")

    def config_snapshot(self) -> dict[str, Any]:
        return {
            "max_iterations": self._max_iterations,
            "reflection": self._reflection,
            "tools": self._tools.names(),
        }

    # --- capability API -------------------------------------------------
    def run(self, query: str, **options: Any) -> AgentResult:
        max_iter = int(options.get("max_iterations", self._max_iterations))
        reflect = bool(options.get("reflection", self._reflection))

        run_id = self._open_run(query, {"max_iterations": max_iter, "reflection": reflect})
        get_metrics().incr("agent.run", agent=self.name)
        tools_used: list[str] = []
        with start_span("agent.react.run", agent=self.name):
            try:
                messages = [
                    ChatMessage("system", self._system_prompt()),
                    ChatMessage("user", query),
                ]
                answer: str | None = None
                model: str | None = None
                ordinal = 0
                for i in range(max_iter):
                    response = self._chat(messages)
                    model = response.model
                    action = self._parse_action(response.text)
                    if action is None:
                        self._record_step(
                            run_id, ordinal, "parse_error", {"raw": response.text[:500]}
                        )
                        ordinal += 1
                        messages.append(ChatMessage("assistant", response.text))
                        messages.append(
                            ChatMessage(
                                "user",
                                "Reply with exactly ONE JSON object using the "
                                "specified format and nothing else.",
                            )
                        )
                        continue

                    if "final" in action:
                        answer = str(action["final"])
                        self._record_step(run_id, ordinal, "final", {"answer": answer[:500]})
                        ordinal += 1
                        break

                    tool = str(action.get("tool", ""))
                    args = action.get("args") or {}
                    if not isinstance(args, dict):
                        args = {}
                    observation = self._run_tool(tool, args)
                    tools_used.append(tool)
                    self._record_step(
                        run_id,
                        ordinal,
                        "act",
                        {
                            "thought": action.get("thought"),
                            "tool": tool,
                            "args": args,
                            "observation": observation[: self._max_obs],
                        },
                    )
                    ordinal += 1
                    messages.append(ChatMessage("assistant", response.text))
                    messages.append(ChatMessage("user", f"Observation: {observation}"))

                if answer is None:
                    answer = self._force_final(messages)
                    self._record_step(run_id, ordinal, "forced_final", {"answer": answer[:500]})
                    ordinal += 1

                if reflect and answer.strip():
                    answer = self._reflect(query, answer, run_id, ordinal)

                if not answer.strip():
                    answer = "I was unable to produce an answer."

                result = AgentResult(
                    answer=answer,
                    citations=[],
                    usage={
                        "model": model,
                        "iterations": ordinal,
                        "tools_used": tools_used,
                    },
                    run_id=run_id,
                )
                self._finish_run(run_id, result)
                return result
            except Exception as exc:  # noqa: BLE001 - record failure, then propagate
                get_metrics().incr("agent.run.failed", agent=self.name)
                if self._run_repo is not None and run_id is not None:
                    self._run_repo.fail_run(run_id, f"{type(exc).__name__}: {exc}")
                self._logger.exception("react run failed for query: %s", query)
                raise

    # --- prompt / parsing ----------------------------------------------
    def _system_prompt(self) -> str:
        catalog = self._tools.describe()
        if catalog:
            lines = []
            for t in catalog:
                params = ", ".join(t["params"].keys()) or "none"
                lines.append(f'- "{t["name"]}": {t["description"]} (args: {params})')
            tools_block = "\n".join(lines)
        else:
            tools_block = "(no tools available)"
        return (
            f"{self._preamble}\n\n"
            "You solve the user's request step by step. On EACH turn reply with "
            "EXACTLY ONE JSON object and nothing else.\n"
            'To use a tool: {"thought": "why", "tool": "<name>", "args": {..}}\n'
            'To answer:    {"thought": "why", "final": "<answer>"}\n\n'
            "After each tool call you will receive a line 'Observation: <result>'. "
            "Use observations to decide the next step. Prefer tools over guessing; "
            "when you have enough information, give the final answer.\n\n"
            f"Available tools:\n{tools_block}"
        )

    @staticmethod
    def _parse_action(text: str) -> dict[str, Any] | None:
        """Extract the single JSON action object from a model reply."""
        candidate = text.strip()
        fenced = _FENCE.search(candidate)
        if fenced:
            candidate = fenced.group(1).strip()
        obj = _try_json(candidate)
        if obj is None:
            start, end = candidate.find("{"), candidate.rfind("}")
            if start != -1 and end > start:
                obj = _try_json(candidate[start : end + 1])
        return obj if isinstance(obj, dict) else None

    def _run_tool(self, tool: str, args: dict[str, Any]) -> str:
        try:
            with timer("agent.react.tool", tool=tool):
                result = self._tools.invoke(tool, **args)
        except Exception as exc:  # noqa: BLE001 - surface as an observation, keep looping
            self._logger.info("tool %s failed: %s", tool, exc)
            return f"Error: {type(exc).__name__}: {exc}"
        return _stringify(result, self._max_obs)

    def _force_final(self, messages: list[ChatMessage]) -> str:
        messages.append(
            ChatMessage(
                "user",
                "You have reached the step limit. Provide your best final answer "
                'now as {"final": "<answer>"}.',
            )
        )
        response = self._chat(messages, think=False)
        action = self._parse_action(response.text)
        if action and "final" in action:
            return str(action["final"])
        return response.text.strip()

    def _reflect(self, query: str, answer: str, run_id: str | None, ordinal: int) -> str:
        messages = [
            ChatMessage(
                "system",
                "You are a reviewer. Improve the draft answer for correctness, "
                "completeness, and clarity. Return ONLY the improved answer text, "
                "with no preamble.",
            ),
            ChatMessage("user", f"Question: {query}\n\nDraft answer:\n{answer}"),
        ]
        try:
            with timer("agent.react.reflect"):
                revised = self._chat(messages, think=False).text.strip()
        except Exception:  # noqa: BLE001 - reflection is best-effort
            self._logger.exception("reflection failed")
            return answer
        final = revised or answer
        self._record_step(run_id, ordinal, "reflect", {"changed": final != answer})
        return final

    def _chat(self, messages: list[ChatMessage], *, think: bool | None = None, **extra: Any):
        use_think = self._think if think is None else think
        return self._llm.chat(
            messages, temperature=self._temperature, think=use_think, **extra
        )

    # --- run persistence (mirrors RagAgent) -----------------------------
    def _open_run(self, query: str, opts: dict[str, Any]) -> str | None:
        if self._run_repo is None:
            return None
        agent = self._run_repo.get_agent_by_name(self.name)
        row = self._run_repo.open_run(
            self.name,
            {"query": query, "options": opts},
            agent_id=agent["id"] if agent else None,
        )
        return str(row["id"])

    def _record_step(
        self, run_id: str | None, ordinal: int, kind: str, detail: dict[str, Any]
    ) -> None:
        if self._run_repo is None or run_id is None:
            return
        self._run_repo.add_step(run_id, ordinal, kind, detail)

    def _finish_run(self, run_id: str | None, result: AgentResult) -> None:
        if self._run_repo is None or run_id is None:
            return
        self._run_repo.finish_run(
            run_id, {"answer": result.answer, "usage": result.usage}
        )


def _try_json(text: str) -> Any:
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def _stringify(result: Any, limit: int) -> str:
    if isinstance(result, str):
        text = result
    else:
        try:
            text = json.dumps(result, default=str)
        except (TypeError, ValueError):
            text = str(result)
    return text if len(text) <= limit else text[: limit - 1] + "…"
