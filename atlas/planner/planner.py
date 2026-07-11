"""Deterministic intent router (Planner v0, D2a).

A small, ordered set of regex rules maps a message to an ``Intent`` and extracts
its arguments. Order matters: more specific intents are checked before general
ones, and anything unmatched falls through to the ReAct strategy (open reasoning),
so the assistant never dead-ends.

The rules are data (``_RULES``): easy to read, extend, and unit-test. Each rule is
``(intent, capability, pattern, arg_builder)``. ``capability`` is the canonical
capability id the step needs (see ``atlas.capabilities``) — checked against the
CapabilityRegistry for the Capability Gap pre-flight (R2, S11).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from atlas.capabilities import (
    CAP_AGENT,
    CAP_KNOWLEDGE,
    CAP_LLM,
    CAP_MEMORY,
    CAP_PYTHON,
    CAP_SEARCH,
    CAP_WEB,
)


class Intent:
    SMALLTALK = "smalltalk"
    RECALL = "recall"
    REMEMBER = "remember"
    WEB_FETCH = "web_fetch"
    WEB_SEARCH = "web_search"
    RUN_PYTHON = "run_python"
    LIST_DOCUMENTS = "list_documents"
    INGEST_PATH = "ingest_path"
    ASK_KNOWLEDGE = "ask_knowledge"
    REACT = "react"  # fallback: open-ended reasoning via the ReAct strategy


@dataclass(frozen=True)
class PlanStep:
    intent: str
    capability: str  # coarse capability this step needs (for gap pre-flight, R2)
    args: dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "capability": self.capability,
            "args": self.args,
            "description": self.description,
        }


@dataclass(frozen=True)
class Plan:
    message: str
    steps: list[PlanStep] = field(default_factory=list)

    @property
    def intent(self) -> str:
        return self.steps[0].intent if self.steps else Intent.REACT

    @property
    def capabilities_required(self) -> list[str]:
        # Ordered, de-duplicated capabilities this plan needs (Gap pre-flight, R2).
        seen: dict[str, None] = {}
        for step in self.steps:
            seen.setdefault(step.capability, None)
        return list(seen)

    def as_dict(self) -> dict[str, Any]:
        return {
            "message": self.message,
            "intent": self.intent,
            "steps": [s.as_dict() for s in self.steps],
            "capabilities_required": self.capabilities_required,
        }


_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)
# A filesystem-ish token: optional ~/./ prefix, then a name with a known extension.
_PATH_RE = re.compile(
    r"(?:\"([^\"]+)\"|'([^']+)'|((?:~|\.{0,2}/)?[\w./\-]+\.(?:pdf|txt|md|markdown|"
    r"html?|docx?|pptx?|xlsx?|csv|tsv|json|py|rst)))",
    re.IGNORECASE,
)
_REMEMBER_PREFIX_RE = re.compile(
    r"^\s*(?:please\s+)?(?:remember|note|keep in mind|make a note)"
    r"(?:\s+(?:that|this))?[:,]?\s*",
    re.IGNORECASE,
)
_SEARCH_RE = re.compile(
    r"\bsearch (the web|online|for)\b"
    r"|\bgoogle\b"
    r"|\blook up\b"
    r"|\b(find|search) (sources|papers|articles|references|studies|info(?:rmation)?)\b",
    re.IGNORECASE,
)
_SEARCH_PREFIX_RE = re.compile(
    r"^\s*(?:please\s+)?(?:search(?:\s+the\s+web)?(?:\s+for)?|google|look\s+up|"
    r"find(?:\s+me)?)\s*[:,]?\s*",
    re.IGNORECASE,
)
# A fenced ```python code block, or an explicit "run this python …" instruction.
_PYTHON_FENCE_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_PYTHON_PREFIX_RE = re.compile(
    r"^\s*(?:please\s+)?(?:run|execute|eval(?:uate)?)\s+(?:this\s+)?"
    r"(?:python|py|code|script)\b[:,]?\s*",
    re.IGNORECASE,
)
_PYTHON_RE = re.compile(
    r"```(?:python|py)\b"
    r"|^\s*(?:please\s+)?(?:run|execute|eval(?:uate)?)\s+(?:this\s+)?"
    r"(?:python|py|code|script)\b",
    re.IGNORECASE,
)


def _url_args(message: str, _m: re.Match[str] | None) -> dict[str, Any]:
    match = _URL_RE.search(message)
    return {"url": match.group(0).rstrip(".,);") if match else None}


def _path_args(message: str, _m: re.Match[str] | None) -> dict[str, Any]:
    match = _PATH_RE.search(message)
    path = None
    if match:
        path = next((g for g in match.groups() if g), None)
    return {"path": path}


def _remember_args(message: str, _m: re.Match[str] | None) -> dict[str, Any]:
    content = _REMEMBER_PREFIX_RE.sub("", message).strip()
    return {"content": content or message.strip(), "kind": "semantic"}


def _query_args(message: str, _m: re.Match[str] | None) -> dict[str, Any]:
    return {"query": message.strip()}


def _search_args(message: str, _m: re.Match[str] | None) -> dict[str, Any]:
    query = _SEARCH_PREFIX_RE.sub("", message).strip()
    return {"query": query or message.strip()}


def _python_args(message: str, _m: re.Match[str] | None) -> dict[str, Any]:
    fence = _PYTHON_FENCE_RE.search(message)
    if fence:
        return {"code": fence.group(1).strip()}
    code = _PYTHON_PREFIX_RE.sub("", message).strip().strip("`").strip()
    return {"code": code}


ArgBuilder = Callable[[str, "re.Match[str] | None"], dict[str, Any]]

# (intent, capability, pattern, arg_builder) — evaluated in order.
_RULES: list[tuple[str, str, re.Pattern[str], ArgBuilder]] = [
    (
        Intent.SMALLTALK,
        CAP_LLM,
        re.compile(
            r"^\s*(hi|hello|hey|yo|hiya|greetings|thanks|thank you|thankyou|"
            r"good (morning|afternoon|evening|night))\b",
            re.IGNORECASE,
        ),
        _query_args,
    ),
    (
        Intent.RECALL,
        CAP_MEMORY,
        re.compile(
            r"\byou (remember|recall)\b"
            r"|\bwhat did i (tell|say)\b"
            r"|\bwhat do i (prefer|like|use)\b"
            r"|\bmy (preferences?|favou?rites?|settings?|choices?)\b"
            r"|\b(recall|remind me)\b",
            re.IGNORECASE,
        ),
        _query_args,
    ),
    (
        Intent.REMEMBER,
        CAP_MEMORY,
        re.compile(
            r"^\s*(please\s+)?remember\b"
            r"|\bremember that\b"
            r"|\b(note that|keep in mind|for the record|for future reference|make a note)\b"
            r"|^\s*(i (prefer|like|use|favou?r)|my \w+ is)\b",
            re.IGNORECASE,
        ),
        _remember_args,
    ),
    (
        Intent.RUN_PYTHON,
        CAP_PYTHON,
        _PYTHON_RE,
        _python_args,
    ),
    (
        Intent.WEB_FETCH,
        CAP_WEB,
        _URL_RE,
        _url_args,
    ),
    (
        Intent.WEB_SEARCH,
        CAP_SEARCH,
        _SEARCH_RE,
        _search_args,
    ),
    (
        Intent.LIST_DOCUMENTS,
        CAP_KNOWLEDGE,
        re.compile(
            r"\b(what|which|list|show|how many)\b[^?]{0,40}"
            r"\b(documents?|knowledge base|kb|files? do you)\b",
            re.IGNORECASE,
        ),
        _query_args,
    ),
    (
        Intent.INGEST_PATH,
        CAP_KNOWLEDGE,
        re.compile(
            r"^\s*(read|ingest|load|import|analys[ez]e?|process)\b"
            r"|\b[\w./~\-]+\.(pdf|txt|md|markdown|html?|docx?|pptx?|xlsx?|csv|tsv|json)\b",
            re.IGNORECASE,
        ),
        _path_args,
    ),
    (
        Intent.ASK_KNOWLEDGE,
        CAP_KNOWLEDGE,
        re.compile(
            r"\bwhat does it say\b"
            r"|\bwhat'?s in it\b"
            r"|\baccording to\b"
            r"|\bsummar(y|ize|ise)\b"
            r"|\b(the|this|that|it)\b[^?]{0,40}\b(document|doc|pdf|file|paper|report)\b"
            r"|\b(document|doc|pdf|file|paper|report|knowledge base)\b",
            re.IGNORECASE,
        ),
        _query_args,
    ),
]

_DESCRIPTIONS = {
    Intent.SMALLTALK: "Respond conversationally.",
    Intent.RECALL: "Recall relevant memories.",
    Intent.REMEMBER: "Store a fact in memory.",
    Intent.WEB_FETCH: "Fetch a web page.",
    Intent.WEB_SEARCH: "Search the web for sources.",
    Intent.RUN_PYTHON: "Run Python code in the sandbox.",
    Intent.LIST_DOCUMENTS: "List known documents.",
    Intent.INGEST_PATH: "Ingest a file into the knowledge base.",
    Intent.ASK_KNOWLEDGE: "Answer from the knowledge base (RAG).",
    Intent.REACT: "Reason and use tools to answer (ReAct).",
}


class Planner:
    """Deterministic message → Plan router (v0)."""

    def plan(self, message: str, *, context: Any = None) -> Plan:
        text = (message or "").strip()
        if not text:
            return Plan(
                message=message or "",
                steps=[self._step(Intent.SMALLTALK, CAP_LLM, {"query": ""})],
            )

        for intent, capability, pattern, build_args in _RULES:
            if pattern.search(text):
                return Plan(
                    message=text,
                    steps=[self._step(intent, capability, build_args(text, None))],
                )

        # Fallback: open-ended reasoning via the ReAct strategy (never dead-end).
        return Plan(
            message=text,
            steps=[self._step(Intent.REACT, CAP_AGENT, {"query": text})],
        )

    @staticmethod
    def _step(intent: str, capability: str, args: dict[str, Any]) -> PlanStep:
        return PlanStep(
            intent=intent,
            capability=capability,
            args=args,
            description=_DESCRIPTIONS.get(intent, ""),
        )
