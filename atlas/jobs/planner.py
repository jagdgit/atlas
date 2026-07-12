"""Job decomposition — objective → ordered steps (D2c, S12).

Two layers, honouring D2 (deterministic first, LLM decomposition for research):
1. **Deterministic fallback** — reuse the mode-agnostic `Planner` (D1). Always
   available, needs no model, and yields a single, sensible step.
2. **LLM decomposition (planner role)** — when an LLM is wired, ask the
   `planner`-role model (D7) to break a complex objective into multiple steps as a
   strict JSON array. Every proposed step is *validated* against the known intents
   and capability ids; invalid steps are dropped. If nothing valid comes back, we
   fall back to layer 1 — the LLM can only ever *improve* on the deterministic plan,
   never break it.

Output is a list of ``DecomposedStep`` (intent, capability, args, description,
depends_on) that ``JobService`` persists as ``job.steps``.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from atlas.capabilities import CAPABILITY_CATALOG
from atlas.planner.planner import Intent, Planner

if TYPE_CHECKING:
    from atlas.llm.service import LLMService

_VALID_INTENTS = {
    Intent.SMALLTALK,
    Intent.RECALL,
    Intent.REMEMBER,
    Intent.WEB_FETCH,
    Intent.WEB_SEARCH,
    Intent.SCHOLAR_SEARCH,
    Intent.YOUTUBE_TRANSCRIPT,
    Intent.RUN_PYTHON,
    Intent.GIT_STATUS,
    Intent.SQL_QUERY,
    Intent.OCR_IMAGE,
    Intent.MAIL_SEARCH,
    Intent.BROWSE_URL,
    Intent.RESEARCH,
    Intent.LIST_DOCUMENTS,
    Intent.INGEST_PATH,
    Intent.ASK_KNOWLEDGE,
    Intent.REACT,
}

_DECOMPOSE_SYSTEM = (
    "You are Atlas's job planner. Break the user's objective into an ordered list "
    "of concrete steps. Respond with ONLY a JSON array; each element is an object "
    "with keys: intent, capability, args (object), description, depends_on (integer "
    "index of a prerequisite step, or null). "
    "Allowed intents: smalltalk, recall, remember, web_fetch, web_search, "
    "scholar_search, youtube_transcript, run_python, git_status, sql_query, "
    "ocr_image, mail_search, browse_url, research, list_documents, ingest_path, "
    "ask_knowledge, react. Allowed capabilities: llm, memory, knowledge, web, search, "
    "scholar, transcript, python, git, sql, ocr, mail, browser, research, agent, "
    "document. "
    "Prefer 'react' for open-ended reasoning. Keep it to at most 6 steps. "
    "Do not include any prose outside the JSON array."
)

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


@dataclass(frozen=True)
class DecomposedStep:
    intent: str
    capability: str
    args: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    depends_on: int | None = None


class JobPlanner:
    def __init__(
        self,
        planner: Planner | None = None,
        llm: "LLMService | None" = None,
        *,
        max_steps: int = 6,
        research_first: bool = False,
        logger: logging.Logger | None = None,
    ) -> None:
        self._planner = planner or Planner()
        self._llm = llm
        self._max_steps = max_steps
        self._research_first = research_first
        self._logger = logger or logging.getLogger("atlas.jobs.planner")

    def decompose(self, objective: str) -> list[DecomposedStep]:
        objective = (objective or "").strip()
        if not objective:
            return [DecomposedStep(Intent.REACT, "agent", {"query": ""}, "Reason about the objective.")]

        steps = self._llm_decompose(objective) if self._llm is not None else []
        if not steps:
            steps = self._deterministic(objective)
        # The fast single-call `answer` fallback is a chat-responsiveness optimization
        # (RC/D3.12); a background job is for deep work, so a bare `answer` step is
        # promoted to the capable ReAct agent rather than a one-shot model reply.
        steps = self._promote_bare_answer(steps)
        # A job is for deep work: if the plan collapsed to a single open-ended
        # `react` step, the objective wasn't recognised as a concrete task, so run
        # the research loop (gather→verify→report with sources) instead of letting
        # the job answer from model memory with no evidence.
        if self._research_first and self._is_bare_react(steps):
            return [
                DecomposedStep(
                    Intent.RESEARCH,
                    "research",
                    {"objective": objective},
                    "Research the objective: gather evidence, verify, and report.",
                )
            ]
        return steps

    @staticmethod
    def _is_bare_react(steps: list[DecomposedStep]) -> bool:
        return len(steps) == 1 and steps[0].intent == Intent.REACT

    @staticmethod
    def _promote_bare_answer(steps: list[DecomposedStep]) -> list[DecomposedStep]:
        if len(steps) == 1 and steps[0].intent == Intent.ANSWER:
            return [
                DecomposedStep(
                    Intent.REACT,
                    "agent",
                    dict(steps[0].args),
                    "Reason and use tools to answer the objective.",
                )
            ]
        return steps

    # --- deterministic fallback ----------------------------------------
    def _deterministic(self, objective: str) -> list[DecomposedStep]:
        plan = self._planner.plan(objective)
        return [
            DecomposedStep(
                intent=s.intent,
                capability=s.capability,
                args=dict(s.args),
                description=s.description,
                depends_on=None,
            )
            for s in plan.steps
        ]

    # --- LLM decomposition ---------------------------------------------
    def _llm_decompose(self, objective: str) -> list[DecomposedStep]:
        from atlas.llm.provider import ChatMessage

        try:
            resp = self._llm.for_role("planner").chat(
                [
                    ChatMessage("system", _DECOMPOSE_SYSTEM),
                    ChatMessage("user", objective),
                ]
            )
            raw = (resp.text or "").strip()
        except Exception:  # noqa: BLE001 - LLM failure must fall back, never crash
            self._logger.exception("planner-role decomposition failed")
            return []

        parsed = self._parse(raw)
        return self._validate(parsed)

    @staticmethod
    def _parse(raw: str) -> list[dict[str, Any]]:
        if not raw:
            return []
        match = _JSON_ARRAY_RE.search(raw)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
        except (ValueError, TypeError):
            return []
        return data if isinstance(data, list) else []

    def _validate(self, items: list[dict[str, Any]]) -> list[DecomposedStep]:
        steps: list[DecomposedStep] = []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            intent = str(item.get("intent", "")).strip()
            if intent not in _VALID_INTENTS:
                continue
            capability = str(item.get("capability", "")).strip()
            if capability not in CAPABILITY_CATALOG:
                # Fall back to the capability the deterministic router would use.
                capability = "agent"
            args = item.get("args")
            if not isinstance(args, dict):
                args = {}
            depends_on = item.get("depends_on")
            if not isinstance(depends_on, int) or depends_on < 0 or depends_on >= i:
                depends_on = None
            steps.append(
                DecomposedStep(
                    intent=intent,
                    capability=capability,
                    args=args,
                    description=str(item.get("description", "")),
                    depends_on=depends_on,
                )
            )
            if len(steps) >= self._max_steps:
                break
        return steps
