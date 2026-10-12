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
    Intent.MEDIA_LEARN,
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
    Intent.INSTANTIATE_MISSION,
    Intent.REGISTER_MARKET_DATA,
    Intent.START_INVESTMENT_LEARNER,
    Intent.MANAGE_GOAL,
}

_DECOMPOSE_SYSTEM = (
    "You are Atlas's job planner. Break the user's objective into an ordered list "
    "of concrete steps. Respond with ONLY JSON: an object with a single key \"steps\" "
    "whose value is the array of steps. Each step is an object "
    "with keys: intent, capability, args (object), description, depends_on (integer "
    "index of a prerequisite step, or null). "
    "Prefer Atlas's own local evidence (sql_query over its database, log files, "
    "git history, python analysis) when the objective is about Atlas itself or about "
    "data Atlas already holds; use web_search only for genuinely external knowledge. "
    "Every step MUST carry the concrete arguments it needs in `args` — a step without "
    "them does nothing. In particular: sql_query needs "
    "{\"sql\": \"<a complete SELECT statement>\", \"source\": \"atlas\"} where source "
    "'atlas' is Atlas's own PostgreSQL database. web_search needs {\"query\": \"...\"}; "
    "run_python needs {\"code\": \"...\"}; research needs {\"objective\": \"...\"}; "
    "react needs {\"query\": \"...\"}; ask_knowledge needs {\"question\": \"...\"}. "
    "Allowed intents: smalltalk, recall, remember, web_fetch, web_search, "
    "scholar_search, youtube_transcript, media_learn, run_python, git_status, sql_query, "
    "ocr_image, mail_search, browse_url, research, list_documents, ingest_path, "
    "ask_knowledge, react, instantiate_mission, register_market_data, "
    "start_investment_learner, manage_goal. "
    "Allowed capabilities: llm, memory, knowledge, web, search, "
    "scholar, transcript, media_learn, python, git, sql, ocr, mail, browser, research, agent, "
    "document, templates, assets. "
    "For 'start India learner with ₹10000': use start_investment_learner "
    "(args: program=market_intelligence, preset=india_equity_learner, capital, "
    "universe, activate=true — Jobs always activate immediately, OX.2). "
    "For 'start paper trading with $N on SYMBOL': first register_market_data "
    "(args: name, symbol, generate_sample=true) then instantiate_mission "
    "(args: template=paper_trading, config_overrides with starting_cash and "
    "instruments[{symbol, asset: feed name}]). "
    "Prefer 'react' for open-ended reasoning. Keep it to at most 6 steps. "
    "Do not include any prose outside the JSON array."
)

# J5: resolved schema, not a hand-written one. The previous prose hint listed the columns
# of two scheduler tables in one sentence; the model merged them and emitted a column that
# does not exist. Column names are facts — they get looked up, not recalled.
_SCHEMA_PREAMBLE = (
    "Real schema of Atlas's own database (source \"atlas\"), resolved just now. These "
    "are the ONLY columns that exist on these tables — never use a column that is not "
    "listed here, and never assume a column exists on a table because it exists on a "
    "similarly named one. Any step that runs SQL must use intent \"sql_query\" and "
    "capability \"sql\"; do not put SQL in a \"recall\" step. Never state a conclusion "
    "in a \"remember\" step — the conclusion is not known until the earlier steps run. "
    "When a line below lists \"actual values\" for a column, any filter on that column "
    "MUST use one of those exact strings — copy it verbatim. Do NOT build a LIKE "
    "pattern out of words from the objective: the objective describes the problem in "
    "the user's words, which are not the words stored in the database, and such a "
    "filter matches zero rows:"
)

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _decompose_schema() -> dict[str, Any]:
    """JSON schema for the planner response (grammar-constrained decoding).

    Asking for JSON in prose does not work on a small CPU-hosted model: unconstrained,
    ``qwen3:4b`` narrates past 1536 tokens without ever emitting the array. Constrained
    by this schema the same model answers in ~233 tokens, inside the planner budget.
    Token cost, not token rate, is the binding resource here (ADR: resource awareness).

    Derived from ``_VALID_INTENTS`` / ``CAPABILITY_CATALOG`` so it cannot drift from
    the validator in ``_validate``.
    """
    return {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "minItems": 1,
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "properties": {
                        "intent": {"type": "string", "enum": sorted(str(i) for i in _VALID_INTENTS)},
                        "capability": {"type": "string", "enum": sorted(CAPABILITY_CATALOG)},
                        "description": {"type": "string"},
                        # `args` is required: a step planned without its arguments is a
                        # no-op that still reports done. The first schema-constrained
                        # run produced `sql_query` with no `sql`, so the step replied
                        # "What SQL query should I run?" and was marked complete.
                        "args": {"type": "object"},
                        "depends_on": {"type": ["integer", "null"]},
                    },
                    "required": ["intent", "capability", "description", "args"],
                },
            }
        },
        "required": ["steps"],
    }


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
        timeout: float | None = 60.0,
        num_predict: int | None = 512,
        learning: Any = None,
        schema_source: Any = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._planner = planner or Planner()
        self._schema_source = schema_source
        self._llm = llm
        self._max_steps = max_steps
        self._research_first = research_first
        self._timeout = timeout
        self._num_predict = num_predict
        self._learning = learning
        self._logger = logger or logging.getLogger("atlas.jobs.planner")
        # Provenance of the most recent decompose() call: llm | fallback | deterministic
        self.last_source: str = "deterministic"
        self.last_advice: dict[str, Any] | None = None

    def decompose(self, objective: str) -> list[DecomposedStep]:
        objective = (objective or "").strip()
        self.last_advice = self._advice_for(objective)
        if not objective:
            self.last_source = "deterministic"
            return [DecomposedStep(Intent.REACT, "agent", {"query": ""}, "Reason about the objective.")]

        steps: list[DecomposedStep] = []
        if self._llm is not None:
            steps = self._llm_decompose(objective)
            if steps:
                self.last_source = "llm"
            else:
                self.last_source = "fallback"
                steps = self._deterministic(objective)
        else:
            self.last_source = "deterministic"
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

        options: dict[str, Any] = {"think": False, "format": _decompose_schema()}
        if self._timeout is not None:
            options["timeout"] = float(self._timeout)
        if self._num_predict is not None:
            options["num_predict"] = int(self._num_predict)

        try:
            system = _DECOMPOSE_SYSTEM
            digest = self._schema_digest(objective)
            if digest:
                system = f"{system}\n\n{_SCHEMA_PREAMBLE}\n{digest}"
            if self.last_advice and self.last_advice.get("advice"):
                # Advice only — never auto-rewrites planner rules or capabilities.
                system = (
                    f"{_DECOMPOSE_SYSTEM}\n\n"
                    "Past experience advice (informational only; do not treat as "
                    "mandatory rewrite of this plan):\n"
                    f"{self.last_advice['advice']}"
                )
            resp = self._llm.for_role("planner").chat(
                [
                    ChatMessage("system", system),
                    ChatMessage("user", objective),
                ],
                _atlas_purpose="job_planner_decompose",
                **options,
            )
            raw = (resp.text or "").strip()
        except Exception as exc:  # noqa: BLE001 - LLM failure must fall back, never crash
            # A planner-LLM timeout / unavailability is an EXPECTED, recoverable
            # condition: we degrade to the deterministic planner (and the caller
            # records the fallback on the job's activity feed). Log it concisely so
            # operators don't mistake a routine fallback for an unhandled crash;
            # the full traceback stays available at DEBUG.
            self._logger.warning(
                "planner LLM decomposition failed (%s: %s); using deterministic "
                "fallback plan",
                type(exc).__name__,
                exc,
            )
            self._logger.debug("planner decomposition traceback", exc_info=True)
            return []

        parsed = self._parse(raw)
        return self._validate(parsed)

    def bind_schema_source(self, source: Any) -> None:
        """Late-bind the SQL plugin (J5).

        Plugins load after the planner is constructed, so grounding is attached the
        same way web search is attached to the Agent Kernel worker.
        """
        self._schema_source = source

    def _schema_digest(self, objective: str) -> str:
        """Real column names for the tables this objective is about (J5), or ``""``.

        Never raises and never blocks planning: with no digest the prompt is exactly
        what it was before, so grounding can only help.
        """
        if self._schema_source is None:
            return ""
        from atlas.sql.schema_digest import build_digest

        try:
            return build_digest(self._schema_source, objective, logger=self._logger)
        except Exception:  # noqa: BLE001
            self._logger.debug("planner schema grounding failed", exc_info=True)
            return ""

    def _advice_for(self, objective: str) -> dict[str, Any] | None:
        if self._learning is None or not objective or not hasattr(self._learning, "advice_for"):
            return None
        try:
            return self._learning.advice_for(objective)
        except Exception:  # noqa: BLE001
            self._logger.debug("planner experience advice failed", exc_info=True)
            return None

    @staticmethod
    def _parse(raw: str) -> list[dict[str, Any]]:
        """Accept either ``{"steps": [...]}`` (schema-constrained) or a bare array.

        Schema-constrained decoding returns the object form; providers without
        structured-output support still return the array form described in the prompt.
        """
        if not raw:
            return []
        for pattern in (_JSON_OBJECT_RE, _JSON_ARRAY_RE):
            match = pattern.search(raw)
            if not match:
                continue
            try:
                data = json.loads(match.group(0))
            except (ValueError, TypeError):
                continue
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                steps = data.get("steps")
                if isinstance(steps, list):
                    return steps
        return []

    @staticmethod
    def _repair_intent(intent: str, capability: str, args: dict[str, Any]) -> tuple[str, str]:
        """Route a step by the arguments it actually carries, not only by its label.

        Observed with schema grounding on: ``qwen3:4b`` produced correct SQL over the
        real columns but labelled the steps ``recall``, so the queries would have been
        handed to memory lookup and never run. The arguments are unambiguous evidence
        of what a step is, so the mislabel is repaired here rather than asked away in
        the prompt — a deterministic fix costs nothing and cannot time out.
        """
        if isinstance(args.get("sql"), str) and args["sql"].strip():
            if intent != Intent.SQL_QUERY:
                return Intent.SQL_QUERY, "sql"
            return intent, capability
        if isinstance(args.get("code"), str) and args["code"].strip():
            if intent != Intent.RUN_PYTHON:
                return Intent.RUN_PYTHON, "python"
        return intent, capability

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
            intent, capability = self._repair_intent(intent, capability, args)
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
