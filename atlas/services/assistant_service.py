"""Assistant service — the Chat-Mode orchestrator (Sprint 10).

Ties the spine together for one conversational turn:

    ensure session → persist user turn → plan (deterministic router)
      → pre-flight capability check (R2) → assemble context
      → dispatch the intent to a reused service → build a response
      → persist the assistant turn (with what it did) → return a ChatTurn

Every piece here is **mode-agnostic** (D1): the Planner and ToolExecutor used for a
synchronous chat turn are the exact objects the async Job Engine (S12) will drive.
Capability honesty (R2) is built in: if a required capability is unavailable, the
turn says so plainly instead of failing silently or fabricating a result.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from atlas.llm.provider import ChatMessage
from atlas.planner.planner import Intent, Plan, Planner
from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.conversation.service import ConversationContext, ConversationService
    from atlas.execution.executor import ToolExecutor
    from atlas.kernel.capabilities import CapabilityRegistry
    from atlas.kernel.tools import ToolRegistry
    from atlas.knowledge.service import KnowledgeService
    from atlas.llm.service import LLMService
    from atlas.services.agent_service import AgentService
    from atlas.services.memory_service import MemoryService

_SMALLTALK_SYSTEM = (
    "You are Atlas, a concise, friendly research and execution assistant. Reply "
    "briefly and helpfully. If the user greets or thanks you, respond in kind and "
    "offer to help."
)
# RC / D3.12: the fast fallback for general questions. One chat-model call, no
# tools — the path that keeps trivial questions from running the full ReAct loop.
_ANSWER_SYSTEM = (
    "You are Atlas, a knowledgeable, concise assistant. Answer the user's question "
    "directly using your own knowledge. Be clear and helpful; use short paragraphs "
    "or bullets when useful. If the answer genuinely depends on up-to-date or live "
    "information you can't be sure of, say so in one line and offer to research it. "
    "Do not invent specific facts, figures, or citations."
)
_WEB_SUMMARY_SYSTEM = (
    "You are Atlas. Summarize the fetched web page for the user in a few sentences, "
    "focusing on what answers their request. Do not invent details."
)


def _format_git(action: str, repo: str, data: dict[str, Any]) -> str:
    """Deterministic phrasing for a successful git result (no LLM needed)."""
    if action == "status":
        branch = data.get("branch") or "(detached)"
        if data.get("clean"):
            state = "clean"
        else:
            state = f"{len(data.get('changes') or [])} change(s)"
        ahead, behind = data.get("ahead", 0), data.get("behind", 0)
        tracking = ""
        if ahead or behind:
            tracking = f", ahead {ahead} / behind {behind}"
        lines = [f"On branch {branch} — working tree {state}{tracking}."]
        for ch in (data.get("changes") or [])[:20]:
            lines.append(f"  {ch.get('status'):>2} {ch.get('path')}")
        return "\n".join(lines)
    if action in ("log", "file_history"):
        commits = data.get("commits") or []
        if not commits:
            return "No commits found."
        head = "Recent commits" + (
            f" touching {data.get('path')}" if action == "file_history" else ""
        )
        lines = [f"{head}:"]
        for c in commits[:20]:
            lines.append(f"  {c.get('short')} {c.get('date')} {c.get('author')} — {c.get('subject')}")
        return "\n".join(lines)
    if action == "diff":
        stat = data.get("stat") or "(no changes)"
        return f"{data.get('files_changed', 0)} file(s) changed:\n{stat}"
    if action == "show":
        c = data.get("commit") or {}
        return (
            f"{c.get('short')} by {c.get('author')} on {c.get('date')}\n"
            f"{c.get('subject')}\n\n{data.get('stat') or ''}".strip()
        )
    if action == "branches":
        current = data.get("current")
        branches = data.get("branches") or []
        marked = [f"* {b}" if b == current else f"  {b}" for b in branches]
        return "Branches:\n" + "\n".join(marked)
    return f"git {action} on {repo}: {data}"


def _format_sql(data: dict[str, Any]) -> str:
    """Render a small result set as a compact text table (no LLM needed)."""
    columns = data.get("columns") or []
    rows = data.get("rows") or []
    if not rows:
        return "The query returned no rows."
    header = " | ".join(columns)
    lines = [header, "-" * len(header)]
    for row in rows[:20]:
        lines.append(" | ".join(str(row.get(c, "")) for c in columns))
    suffix = ""
    if data.get("truncated"):
        suffix = f"\n… (truncated; showing {min(len(rows), 20)} of many rows)"
    elif len(rows) > 20:
        suffix = f"\n… ({len(rows)} rows total; showing 20)"
    return f"{data.get('row_count', len(rows))} row(s):\n" + "\n".join(lines) + suffix


def _format_mail(data: dict[str, Any], query: str) -> str:
    """Render a mailbox search as a compact list of message summaries."""
    messages = data.get("messages") or []
    folder = data.get("folder", "INBOX")
    scope = f" matching {query!r}" if query else ""
    lines = [f"{len(messages)} message(s){scope} in {folder}:"]
    for m in messages[:20]:
        subject = m.get("subject") or "(no subject)"
        sender = m.get("from") or "(unknown sender)"
        date = m.get("date") or ""
        lines.append(f"  [{m.get('uid')}] {subject} — {sender}"
                     + (f"  ({date})" if date else ""))
    if len(messages) > 20:
        lines.append(f"  … ({len(messages)} total; showing 20)")
    return "\n".join(lines)


def _format_research(data: dict[str, Any]) -> str:
    """Render the research result: verdict + confidence + top sources + trail."""
    claim = data.get("claim") or {}
    report = data.get("report") or {}
    sections = report.get("sections") or {}
    confidence = claim.get("confidence", "UNVERIFIED")
    score = claim.get("confidence_score")
    conv = claim.get("convergence")
    stopped = data.get("stopped") or {}
    lines = [
        f"Research on: {data.get('objective')}",
        f"Confidence: {confidence}"
        + (f" (score {score}" if score is not None else "")
        + (f", convergence {conv:.0%})" if isinstance(conv, (int, float)) else
           ")" if score is not None else ""),
        f"Rounds: {data.get('iterations', 0)}; stopped because: "
        f"{'; '.join(stopped.get('reasons', [])) or 'n/a'}",
    ]
    summary = sections.get("executive_summary")
    if summary:
        lines += ["", summary if isinstance(summary, str) else str(summary)]
    sources = (data.get("graph") or {}).get("sources") or []
    if sources:
        lines += ["", f"Sources ({len(sources)}):"]
        for s in sources[:8]:
            lvl = s.get("level_name") or f"L{s.get('evidence_level', '?')}"
            lines.append(f"  - [{lvl}] {s.get('title') or s.get('id')}"
                         + (f" — {s.get('url')}" if s.get("url") else ""))
        if len(sources) > 8:
            lines.append(f"  … ({len(sources)} total; showing 8)")
    return "\n".join(lines)


def _research_citations(data: dict[str, Any]) -> list[dict[str, Any]]:
    sources = (data.get("graph") or {}).get("sources") or []
    return [
        {"source_id": s.get("id"), "title": s.get("title"), "url": s.get("url"),
         "evidence_level": s.get("evidence_level")}
        for s in sources
    ]


def _normalize_chat_citations(raw: list[Any] | None) -> list[dict[str, Any]]:
    """Map Belief Core / research / RAG cite dicts into ChatResponse CitationOut shape."""
    out: list[dict[str, Any]] = []
    for i, c in enumerate(raw or []):
        if not isinstance(c, dict):
            continue
        ctype = str(c.get("type") or "").lower()
        belief_id = str(c.get("belief_id") or "").strip()
        experience_id = str(c.get("experience_id") or "").strip()
        if ctype == "belief" or belief_id:
            bid = belief_id or str(c.get("id") or f"belief-{i}")
            snippet = str(
                c.get("snippet") or c.get("statement") or c.get("title") or ""
            ).strip()
            out.append(
                {
                    "index": int(c.get("index") if c.get("index") is not None else i),
                    "document_id": f"belief:{bid}",
                    "chunk_id": bid,
                    "similarity": float(c.get("similarity") if c.get("similarity") is not None else 1.0),
                    "snippet": snippet[:500] or f"belief {bid}",
                }
            )
            continue
        if ctype == "experience" or experience_id:
            eid = experience_id or str(c.get("id") or f"experience-{i}")
            snippet = str(
                c.get("snippet") or c.get("summary") or c.get("title") or ""
            ).strip()
            out.append(
                {
                    "index": int(c.get("index") if c.get("index") is not None else i),
                    "document_id": f"experience:{eid}",
                    "chunk_id": eid,
                    "similarity": float(c.get("similarity") if c.get("similarity") is not None else 1.0),
                    "snippet": snippet[:500] or f"experience {eid}",
                }
            )
            continue
        doc = str(
            c.get("document_id")
            or c.get("source_id")
            or c.get("url")
            or c.get("id")
            or f"src-{i}"
        )
        chunk = str(c.get("chunk_id") or c.get("id") or f"chunk-{i}")
        snippet = str(
            c.get("snippet") or c.get("title") or c.get("statement") or ""
        ).strip()
        try:
            sim = float(c.get("similarity") if c.get("similarity") is not None else 0.0)
        except (TypeError, ValueError):
            sim = 0.0
        out.append(
            {
                "index": int(c.get("index") if c.get("index") is not None else i),
                "document_id": doc,
                "chunk_id": chunk,
                "similarity": sim,
                "snippet": snippet[:500],
            }
        )
    return out


def _format_browse(data: dict[str, Any]) -> str:
    """Render a browsed page: title + a text preview + a few links."""
    title = data.get("title") or "(untitled)"
    final_url = data.get("final_url") or data.get("url")
    text = (data.get("text") or "").strip()
    preview = text[:1500] + ("…" if len(text) > 1500 else "")
    links = data.get("links") or []
    lines = [f"{title} — {final_url}",
             f"({data.get('chars', len(text))} chars rendered)", "", preview]
    if links:
        lines.append("")
        lines.append(f"Links ({len(links)} found):")
        lines.extend(f"  - {u}" for u in links[:10])
        if len(links) > 10:
            lines.append(f"  … ({len(links)} total; showing 10)")
    return "\n".join(lines)


@dataclass(frozen=True)
class ChatTurn:
    session_id: str
    answer: str
    intent: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    capability_gaps: list[dict[str, Any]] = field(default_factory=list)
    run_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "answer": self.answer,
            "intent": self.intent,
            "citations": _normalize_chat_citations(self.citations),
            "tool_calls": self.tool_calls,
            "capability_gaps": self.capability_gaps,
            "run_id": self.run_id,
        }


@dataclass
class _Outcome:
    answer: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    run_id: str | None = None
    blocked: bool = False
    blocked_reason: str | None = None
    # Optional step extras (e.g. research pipeline / usage) persisted on the job step.
    extras: dict[str, Any] = field(default_factory=dict)


class ResponseBuilder:
    """Composes natural-language replies, using the chat-role LLM where useful.

    Deterministic phrasing for structured results (lists, confirmations); the LLM
    for smalltalk and free-text summaries. Always degrades gracefully: if the LLM
    is unavailable the caller still gets a sensible, honest reply.
    """

    def __init__(self, llm: "LLMService", logger: logging.Logger | None = None) -> None:
        self._llm = llm
        self._logger = logger or logging.getLogger("atlas.assistant")

    def compose(
        self,
        system: str,
        user: str,
        *,
        context: "ConversationContext | None" = None,
        fallback: str = "",
        timeout: float | None = None,
        busy_preflight: bool = True,
    ) -> str:
        messages = [ChatMessage("system", system)]
        if context is not None:
            messages.extend(context.as_chat_messages())
        messages.append(ChatMessage("user", user))
        options: dict[str, Any] = {}
        if timeout is not None:
            options["timeout"] = timeout
        # PLC.F6 — fail fast when Ollama/LLM lane is saturated (<3s vs 60s hang)
        if busy_preflight:
            try:
                if hasattr(self._llm, "lane_busy") and self._llm.lane_busy():
                    return fallback or (
                        "Chat LLM is busy right now (inference lane saturated). "
                        "Try “market intelligence status” or “career intelligence status” "
                        "(no LLM), or ask me to research it as a background job."
                    )
            except Exception:  # noqa: BLE001
                pass
        try:
            return (
                self._llm.for_role("chat").chat(messages, **options).text.strip()
                or fallback
            )
        except Exception:  # noqa: BLE001 - never let composition crash a turn
            self._logger.exception("response composition failed")
            return fallback

    @staticmethod
    def explain(tool_calls: list[dict[str, Any]]) -> str:
        """A short, human explanation of what the turn did (acceptance: 'explain')."""
        actions = [tc.get("action") or tc.get("intent") for tc in tool_calls]
        actions = [a for a in actions if a]
        return f"(used: {', '.join(actions)})" if actions else ""


class AssistantService:
    name = "chat"

    def __init__(
        self,
        conversation: "ConversationService",
        planner: Planner,
        executor: "ToolExecutor",
        *,
        knowledge: "KnowledgeService | None" = None,
        memory: "MemoryService | None" = None,
        agent: "AgentService | None" = None,
        llm: "LLMService",
        tools: "ToolRegistry | None" = None,
        capabilities: "CapabilityRegistry | None" = None,
        web_tool: str = "web.fetch",
        search_tool: str = "web.search",
        scholar_tool: str = "scholar.search",
        youtube_tool: str = "youtube.transcript",
        python_tool: str = "python.run",
        git_tool_prefix: str = "git",
        sql_tool: str = "sql.query",
        ocr_tool: str = "ocr.image",
        mail_tool: str = "mail.search",
        browser_tool: str = "browser.open",
        research_tool: str = "research.run",
        search_limit: int = 5,
        list_limit: int = 25,
        interactive_timeout: float | None = None,
        templates: Any = None,
        assets: Any = None,
        media_learn: Any = None,
        programs: Any = None,
        planning: Any = None,
        goals: Any = None,
        reasoning: Any = None,
        experience_os: Any = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._conversation = conversation
        self._planner = planner
        self._executor = executor
        self._knowledge = knowledge
        self._memory = memory
        self._agent = agent
        self._llm = llm
        self._reasoning = reasoning
        self._experience_os = experience_os
        self._tools = tools
        self._capabilities = capabilities
        self._templates = templates
        self._assets = assets
        self._media_learn = media_learn
        self._programs = programs
        self._planning = planning
        self._goals = goals
        self._web_tool = web_tool
        self._search_tool = search_tool
        self._scholar_tool = scholar_tool
        self._youtube_tool = youtube_tool
        self._python_tool = python_tool
        self._git_tool_prefix = git_tool_prefix
        self._sql_tool = sql_tool
        self._ocr_tool = ocr_tool
        self._mail_tool = mail_tool
        self._browser_tool = browser_tool
        self._research_tool = research_tool
        self._search_limit = search_limit
        self._list_limit = list_limit
        self._interactive_timeout = interactive_timeout
        self._responder = ResponseBuilder(llm, logger)
        self._logger = logger or logging.getLogger("atlas.assistant")

    def bind_reasoning(self, reasoning: Any, *, experience_os: Any | None = None) -> None:
        """OI-SELF-ID — attach Belief Core / Living RAG for identity-first chat."""
        self._reasoning = reasoning
        if experience_os is not None:
            self._experience_os = experience_os

    def _identity_chat_answer(
        self,
        msg: str,
        context: Any,
        *,
        allow_llm: bool = True,
        benchmarks_only: bool = False,
    ) -> dict[str, Any] | None:
        """Return Living RAG / benchmark answer dict, or None to use legacy compose."""
        if self._reasoning is None:
            return None
        try:
            from atlas.reasoning.identity_chat import (
                answer_as_atlas,
                answer_belief_benchmark,
                detect_belief_benchmark,
            )

            if benchmarks_only or detect_belief_benchmark(msg):
                bench = answer_belief_benchmark(self._reasoning, msg)
                if bench is not None:
                    return {"version": "self0.identity_chat.v1", "mode": "benchmark", **bench}
                if benchmarks_only:
                    return None

            return answer_as_atlas(
                self._reasoning,
                msg,
                compose_fn=self._responder.compose if allow_llm else None,
                experience_os=self._experience_os,
                knowledge=self._knowledge,
                memory=self._memory,
                context=context,
                timeout=self._interactive_timeout,
                allow_llm=allow_llm,
            )
        except Exception:  # noqa: BLE001
            self._logger.debug("identity chat path failed", exc_info=True)
            return None

    def _outcome_from_identity(
        self,
        identity: dict[str, Any],
        *,
        intent: str,
        tool_calls: list[dict[str, Any]],
    ) -> "_Outcome | None":
        answer = str(identity.get("answer") or "").strip()
        if not answer and identity.get("mode") != "benchmark":
            return None
        if not answer:
            answer = "Belief Core returned no text for that query."
        tool_calls.append(
            {
                "intent": intent,
                "action": "identity_chat",
                "mode": identity.get("mode"),
                "capability": "reasoning",
                "bundle": identity.get("bundle_counts"),
            }
        )
        return _Outcome(
            answer=answer,
            citations=list(identity.get("citations") or []),
        )

    # --- capability API -------------------------------------------------
    def chat(self, message: str, *, session_id: str | None = None, **options: Any) -> ChatTurn:
        session = self._conversation.ensure_session(session_id)
        sid = session.id
        self._conversation.add_user_message(sid, message)

        plan = self._planner.plan(message)
        gaps = self._preflight_gaps(plan)
        context = self._conversation.build_context(sid, message)

        step = plan.steps[0]
        tool_calls: list[dict[str, Any]] = []

        # OI-SELF-ID — belief benchmarks never wait on Ollama / planner tools
        try:
            from atlas.reasoning.identity_chat import detect_belief_benchmark

            is_belief_q = detect_belief_benchmark(message) is not None
        except Exception:  # noqa: BLE001
            is_belief_q = False

        if gaps and not is_belief_q:
            outcome = _Outcome(answer=self._gap_answer(gaps))
        elif is_belief_q:
            identity = self._identity_chat_answer(
                message, context, allow_llm=False, benchmarks_only=True
            )
            if identity is not None:
                outcome = self._outcome_from_identity(
                    identity, intent="belief_benchmark", tool_calls=tool_calls
                )
            else:
                outcome = _Outcome(
                    answer=(
                        "Belief Core is not bound on this process (restart Atlas after "
                        "OI-SELF Phase 4). Try again, or call POST /v1/reasoning/why."
                    )
                )
            if outcome is None:
                outcome = _Outcome(
                    answer="Belief Core could not answer that why/mind-change query."
                )
        else:
            outcome = self._dispatch(step.intent, step.args, context, tool_calls)

        self._conversation.add_assistant_message(
            sid, outcome.answer, tool_calls=tool_calls
        )
        return ChatTurn(
            session_id=sid,
            answer=outcome.answer,
            intent="belief_benchmark" if is_belief_q else step.intent,
            citations=outcome.citations,
            tool_calls=tool_calls,
            capability_gaps=[] if is_belief_q else gaps,
            run_id=outcome.run_id,
        )

    # --- step execution (reused by the Job Engine, D1) -----------------
    def run_step(
        self,
        intent: str,
        args: dict[str, Any],
        *,
        context: "ConversationContext | None" = None,
        tool_calls: list[dict[str, Any]] | None = None,
        capability: str | None = None,
    ) -> _Outcome:
        """Execute one plan step and return a structured outcome.

        This is the exact dispatch a chat turn uses (D1), exposed so the async Job
        Engine (S12) drives job steps through the *same* code path. Runtime
        capability check (R2/R3): a step needing an unregistered capability is
        returned as ``blocked`` (needs the user to enable it) rather than failing
        silently — the job continues with other steps.
        """
        calls = tool_calls if tool_calls is not None else []
        cap = capability or ""
        if cap and not self._capability_available(cap):
            return _Outcome(
                answer=f"Blocked: this step needs the '{cap}' capability, which is "
                "not available.",
                blocked=True,
                blocked_reason=f"needs capability: {cap}",
            )
        return self._dispatch(intent, args, context, calls)

    # --- dispatch -------------------------------------------------------
    def _dispatch(
        self,
        intent: str,
        args: dict[str, Any],
        context: "ConversationContext",
        tool_calls: list[dict[str, Any]],
    ) -> _Outcome:
        handler = {
            Intent.SMALLTALK: self._do_smalltalk,
            Intent.REMEMBER: self._do_remember,
            Intent.RECALL: self._do_recall,
            Intent.LIST_DOCUMENTS: self._do_list_documents,
            Intent.INGEST_PATH: self._do_ingest,
            Intent.WEB_FETCH: self._do_web_fetch,
            Intent.WEB_SEARCH: self._do_web_search,
            Intent.SCHOLAR_SEARCH: self._do_scholar_search,
            Intent.YOUTUBE_TRANSCRIPT: self._do_youtube,
            Intent.MEDIA_LEARN: self._do_media_learn,
            Intent.VERIFY_KNOWLEDGE: self._do_verify_knowledge,
            Intent.RUN_PYTHON: self._do_run_python,
            Intent.GIT_STATUS: self._do_git,
            Intent.SQL_QUERY: self._do_sql,
            Intent.OCR_IMAGE: self._do_ocr,
            Intent.MAIL_SEARCH: self._do_mail,
            Intent.BROWSE_URL: self._do_browse,
            Intent.RESEARCH: self._do_research,
            Intent.ASK_KNOWLEDGE: self._do_ask_knowledge,
            Intent.ANSWER: self._do_answer,
            Intent.REACT: self._do_react,
            Intent.INSTANTIATE_MISSION: self._do_instantiate_mission,
            Intent.REGISTER_MARKET_DATA: self._do_register_market_data,
            Intent.START_INVESTMENT_LEARNER: self._do_start_investment_learner,
            Intent.MANAGE_GOAL: self._do_manage_goal,
            Intent.CAREER_STATUS: self._do_career_status,
            Intent.MARKET_STATUS: self._do_market_status,
        }.get(intent, self._do_react)
        return handler(args, context, tool_calls)

    def _do_smalltalk(self, args, context, tool_calls) -> _Outcome:
        msg = args.get("query", "")
        identity = self._identity_chat_answer(msg, context)
        if identity is not None:
            out = self._outcome_from_identity(
                identity, intent=Intent.SMALLTALK, tool_calls=tool_calls
            )
            if out is not None:
                return out
        answer = self._responder.compose(
            _SMALLTALK_SYSTEM, msg, context=context, fallback="Hello! How can I help?",
            timeout=self._interactive_timeout,
        )
        tool_calls.append({"intent": Intent.SMALLTALK, "action": "smalltalk"})
        return _Outcome(answer=answer)

    def _do_answer(self, args, context, tool_calls) -> _Outcome:
        """Fast fallback (RC/D3.12) — identity-first Living RAG when ReasoningService bound.

        This is the default route for open-ended messages the deterministic router
        doesn't map to a tool. With OI-SELF-ID, answers consult Atlas identity,
        goals, beliefs, experiences, then the chat model — not raw Qwen alone.
        When Ollama times out, Living RAG still returns Belief Core grounded text.
        """
        msg = args.get("query", "")
        identity = self._identity_chat_answer(msg, context, allow_llm=True)
        if identity is not None:
            out = self._outcome_from_identity(
                identity, intent=Intent.ANSWER, tool_calls=tool_calls
            )
            if out is not None:
                return out
        answer = self._responder.compose(
            _ANSWER_SYSTEM,
            msg,
            context=context,
            fallback=(
                "Chat LLM timed out (Ollama busy or slow — market workers + "
                "inference share this host). Try a Belief Core phrase without the "
                "LLM: “why do you believe capital preservation”, or a status "
                "phrase: “market intelligence status”, “career intelligence "
                "status”, “learner status”. Or ask me to research it as a "
                "background job."
            ),
            timeout=self._interactive_timeout,
        )
        tool_calls.append(
            {"intent": Intent.ANSWER, "action": "answer", "capability": "llm"}
        )
        return _Outcome(answer=answer)

    def _do_remember(self, args, context, tool_calls) -> _Outcome:
        content = (args.get("content") or "").strip()
        if not content:
            return _Outcome(answer="There's nothing for me to remember there.")
        item = self._memory.remember(
            content, kind=args.get("kind", "semantic"), scope=context.session_id
        )
        tool_calls.append(
            {
                "intent": Intent.REMEMBER,
                "action": "remember",
                "capability": "memory",
                "memory_id": item.id,
            }
        )
        return _Outcome(answer=f'Got it — I\'ll remember that: "{content}".')

    def _do_recall(self, args, context, tool_calls) -> _Outcome:
        query = args.get("query", "")
        results = self._memory.recall(
            query, scope=context.session_id, limit=self._list_limit
        )
        tool_calls.append(
            {
                "intent": Intent.RECALL,
                "action": "recall",
                "capability": "memory",
                "count": len(results),
            }
        )
        if not results:
            return _Outcome(
                answer="I don't have anything remembered about that yet."
            )
        lines = "\n".join(f"- {r.content}" for r in results)
        return _Outcome(answer=f"Here's what I remember:\n{lines}")

    def _do_list_documents(self, args, context, tool_calls) -> _Outcome:
        docs = self._knowledge.list_documents(limit=self._list_limit)
        tool_calls.append(
            {
                "intent": Intent.LIST_DOCUMENTS,
                "action": "list_documents",
                "capability": "knowledge",
                "count": len(docs),
            }
        )
        if not docs:
            return _Outcome(
                answer="My knowledge base is empty — I don't know about any documents yet."
            )
        lines = []
        for d in docs:
            label = d.title or d.uri or d.source
            lines.append(f"- {label} ({d.status})")
        return _Outcome(
            answer=f"I know about {len(docs)} document(s):\n" + "\n".join(lines)
        )

    def _do_ingest(self, args, context, tool_calls) -> _Outcome:
        from pathlib import Path

        from atlas.ingestion.extractors import content_type_for, extract

        path_str = args.get("path")
        if not path_str:
            return _Outcome(
                answer="Sure — which file should I read? Give me a path (e.g. "
                "/data/atlas_data/documents/report.pdf) and I'll ingest it."
            )
        path = Path(path_str).expanduser()
        if not path.is_file():
            # R3/Q3: not an error — the user needs to provide the file (e.g. drop it
            # in a watched folder), then resume. Block just this step.
            return _Outcome(
                answer=f"I couldn't find a file at '{path}'.",
                blocked=True,
                blocked_reason=f"needs file: {path}",
            )
        text = extract(path)
        if not text:
            return _Outcome(
                answer=f"I opened '{path.name}' but couldn't extract any text from it."
            )
        summary = self._knowledge.ingest_text(
            "chat",
            text,
            title=path.name,
            uri=str(path.resolve()),
            content_type=content_type_for(path),
            embed=True,
        )
        tool_calls.append(
            {
                "intent": Intent.INGEST_PATH,
                "action": "ingest",
                "capability": "knowledge",
                "document_id": summary["document_id"],
                "status": summary["status"],
            }
        )
        note = " (already in my knowledge base)" if summary["deduped"] else ""
        return _Outcome(
            answer=f"Ingested '{path.name}'{note}: {summary['chunks']} chunk(s), "
            f"status {summary['status']}. Ask me what it says."
        )

    def _do_web_fetch(self, args, context, tool_calls) -> _Outcome:
        url = args.get("url")
        if not url:
            return _Outcome(answer="Which URL should I fetch?")
        result = self._executor.execute(self._web_tool, {"url": url})
        tool_calls.append(
            {
                "intent": Intent.WEB_FETCH,
                "action": "web.fetch",
                "capability": "web",
                "ok": result.ok,
                "url": url,
            }
        )
        if not result.ok:
            return _Outcome(
                answer=f"I couldn't fetch {url}: {result.error}"
            )
        text = self._as_text(result.data)
        answer = self._responder.compose(
            _WEB_SUMMARY_SYSTEM,
            f"Request: summarize {url}\n\nPage content:\n{text[:4000]}",
            fallback=f"Fetched {url} ({len(text)} characters).",
        )
        return _Outcome(answer=answer)

    def _do_web_search(self, args, context, tool_calls) -> _Outcome:
        query = (args.get("query") or "").strip()
        if not query:
            return _Outcome(answer="What should I search the web for?")
        result = self._executor.execute(
            self._search_tool,
            {"query": query, "max_results": args.get("max_results", self._search_limit)},
        )
        data = result.data if isinstance(result.data, dict) else {}
        tool_calls.append(
            {
                "intent": Intent.WEB_SEARCH,
                "action": "web.search",
                "capability": "search",
                "ok": result.ok,
                "provider": data.get("provider"),
                "outcome": data.get("outcome"),
            }
        )
        if not result.ok:
            return _Outcome(answer=f"I couldn't search the web: {result.error}")
        outcome = data.get("outcome")
        results = data.get("results") or []
        if outcome != "ok":
            reason = data.get("reason") or outcome
            return _Outcome(
                answer=f"Web search was unavailable ({outcome}): {reason}. "
                "I couldn't gather sources for that."
            )
        if not results:
            return _Outcome(answer=f"I found no web results for '{query}'.")
        lines = [f"Top results for '{query}':"]
        for i, hit in enumerate(results, start=1):
            lines.append(f"{i}. {hit.get('title') or hit.get('url')} — {hit.get('url')}")
            snippet = (hit.get("snippet") or "").strip()
            if snippet:
                lines.append(f"   {snippet}")
        return _Outcome(answer="\n".join(lines))

    def _do_scholar_search(self, args, context, tool_calls) -> _Outcome:
        query = (args.get("query") or "").strip()
        if not query:
            return _Outcome(answer="What topic should I search academic sources for?")
        result = self._executor.execute(
            self._scholar_tool,
            {"query": query, "max_results": args.get("max_results", self._search_limit)},
        )
        data = result.data if isinstance(result.data, dict) else {}
        tool_calls.append(
            {
                "intent": Intent.SCHOLAR_SEARCH,
                "action": "scholar.search",
                "capability": "scholar",
                "ok": result.ok,
                "provider": data.get("provider"),
                "outcome": data.get("outcome"),
            }
        )
        if not result.ok:
            return _Outcome(answer=f"I couldn't search academic sources: {result.error}")
        outcome = data.get("outcome")
        papers = data.get("results") or []
        if outcome != "ok":
            reason = data.get("reason") or outcome
            return _Outcome(
                answer=f"Academic search was unavailable ({outcome}): {reason}. "
                "I couldn't gather papers for that."
            )
        if not papers:
            return _Outcome(answer=f"I found no academic papers for '{query}'.")
        lines = [f"Top papers for '{query}':"]
        for i, p in enumerate(papers, start=1):
            authors = ", ".join(p.get("authors", [])[:3])
            meta = " · ".join(
                bit for bit in (
                    authors,
                    str(p.get("year") or ""),
                    p.get("venue") or "",
                    p.get("level_name") or "",
                ) if bit
            )
            lines.append(f"{i}. {p.get('title')} ({meta})")
            if p.get("url"):
                lines.append(f"   {p['url']}")
        return _Outcome(answer="\n".join(lines))

    def _do_youtube(self, args, context, tool_calls) -> _Outcome:
        video = (args.get("video") or "").strip()
        if not video:
            return _Outcome(
                answer="Which YouTube video? Give me a link or an 11-character video id."
            )
        result = self._executor.execute(self._youtube_tool, {"video": video})
        data = result.data if isinstance(result.data, dict) else {}
        outcome = data.get("outcome")
        tool_calls.append(
            {
                "intent": Intent.YOUTUBE_TRANSCRIPT,
                "action": "youtube.transcript",
                "capability": "transcript",
                "ok": result.ok,
                "outcome": outcome,
                "reason_code": data.get("reason_code"),
                "bytes_read": data.get("bytes_read"),
                "acquisition": data.get("acquisition"),
            }
        )
        if not result.ok:
            return _Outcome(answer=f"I couldn't fetch that transcript: {result.error}")
        if outcome != "ok":
            summary = data.get("operator_summary") or ""
            if summary:
                return _Outcome(answer=summary)
            reason = data.get("reason") or outcome
            code = data.get("reason_code") or ""
            return _Outcome(
                answer=(
                    f"Acquisition failed before read ({outcome}"
                    + (f"/{code}" if code else "")
                    + f"): {reason}. No document was fabricated."
                )
            )
        text = (data.get("text") or "").strip()
        title = data.get("title") or data.get("video_id")
        summary = self._responder.compose(
            _WEB_SUMMARY_SYSTEM,
            f"Summarize this YouTube transcript ({title}):\n\n{text[:4000]}",
            fallback=f"Transcript of '{title}' ({len(text)} characters).",
        )
        return _Outcome(answer=summary)

    def _do_verify_knowledge(self, args, context, tool_calls) -> _Outcome:
        """KV.6 — verify claims learned from a media URL / asset via VerificationEngine."""
        del context
        params = {
            k: args.get(k)
            for k in (
                "source_url",
                "asset_id",
                "job_id",
                "finding_id",
                "limit",
                "enqueue_only",
                "gather",
                "max_gather_iterations",
            )
            if args.get(k) is not None
        }
        if not any(params.get(k) for k in ("source_url", "asset_id", "job_id", "finding_id")):
            return _Outcome(
                answer=(
                    "Which findings should I verify? Give a source URL "
                    "(e.g. the YouTube link), asset_id, job_id, or finding_id."
                )
            )
        if self._tools is None or not self._tools.has("knowledge.verify"):
            return _Outcome(
                answer="Blocked: knowledge.verify is not available.",
                blocked=True,
                blocked_reason="needs tool: knowledge.verify",
            )
        result = self._executor.execute("knowledge.verify", params)
        data = result.data if isinstance(result.data, dict) else {}
        tool_calls.append(
            {
                "intent": Intent.VERIFY_KNOWLEDGE,
                "action": "knowledge.verify",
                "ok": result.ok,
                "verification": data.get("verification") or "executed",
                "selected": data.get("selected"),
                "still_unverified": data.get("still_unverified"),
                "gather_requested": data.get("gather_requested"),
            }
        )
        if not result.ok:
            return _Outcome(
                answer=f"Verification failed: {result.error}",
                blocked=True,
                blocked_reason="knowledge.verify failed",
            )
        selected = int(data.get("selected") or 0)
        still = int(data.get("still_unverified") or 0)
        scored = int(data.get("promoted_or_scored") or 0)
        lines = [
            f"Verification ran on {selected} finding(s).",
            f"Scored (LOW/MEDIUM/HIGH): {scored}. Still UNVERIFIED/INSUFFICIENT: {still}.",
        ]
        if data.get("gather_requested"):
            lines.append("Gather (budget-capped Research search) was requested.")
        else:
            lines.append(
                "Single YouTube evidence alone does not promote to HIGH — "
                "say “with web search” to gather independent sources."
            )
        for row in (data.get("before_after") or [])[:8]:
            stmt = str(row.get("statement") or "")[:80]
            extra = ""
            if row.get("gather_added"):
                extra = f" (+{row.get('gather_added')} gathered)"
            trust_bit = ""
            if row.get("overall_trust") is not None:
                trust_bit = f"  overall_trust={row.get('overall_trust')}"
            lines.append(
                f"- {stmt}…  {row.get('confidence')} → {row.get('after_confidence')}"
                f"{extra}{trust_bit}"
            )
        return _Outcome(answer="\n".join(lines), extras={"verification": data})

    def _do_media_learn(self, args, context, tool_calls) -> _Outcome:
        source = (args.get("source") or args.get("video") or "").strip()
        if not source:
            return _Outcome(
                answer="Which media should I learn from? Give a YouTube URL or a local media path."
            )
        orch = self._media_learn
        if orch is None and self._tools is not None and self._tools.has("media.learn"):
            result = self._executor.execute("media.learn", {"source": source})
            data = result.data if isinstance(result.data, dict) else {}
            if not result.ok:
                return _Outcome(
                    answer=f"I couldn't learn from that media: {result.error}",
                    blocked=True,
                    blocked_reason="media.learn tool failed",
                )
        elif orch is not None:
            data = orch.learn(source, to_knowledge=True)
        else:
            return _Outcome(
                answer="Blocked: media.learn is not available.",
                blocked=True,
                blocked_reason="needs capability: media_learn",
            )

        strategies = data.get("strategies") or []
        tool_calls.append(
            {
                "intent": Intent.MEDIA_LEARN,
                "action": "media.learn",
                "capability": "media_learn",
                "ok": data.get("outcome") == "ok",
                "outcome": data.get("outcome"),
                "strategies": strategies,
                "acquisition": data.get("acquisition"),
                "orchestrator": data.get("orchestrator") or "media.learn",
            }
        )
        extras = {
            "strategies": strategies,
            "acquisition": data.get("acquisition"),
            "suggested_next_strategies": data.get("suggested_next_strategies") or [],
            "speech_to_text_status": data.get("speech_to_text_status"),
            "interactive_recovery": bool(data.get("interactive_recovery")),
            "waiting_for": data.get("waiting_for"),
            "readiness": data.get("readiness"),
            "stages": data.get("stages"),
            "knowledge_produced": int(data.get("knowledge_produced") or 0),
            "knowledge_breakdown": data.get("knowledge_breakdown"),
            "knowledge_preview": data.get("knowledge_preview"),
            "extraction_quality": data.get("extraction_quality"),
            "outcome": data.get("outcome"),
            "source": data.get("source") or source,
            "title": data.get("title"),
            "media": data.get("media"),
            "asset_id": (data.get("acquisition") or {}).get("asset_id")
            if isinstance(data.get("acquisition"), dict)
            else None,
            "asset_kind": (data.get("acquisition") or {}).get("asset_kind")
            if isinstance(data.get("acquisition"), dict)
            else None,
            "orchestrator": "media.learn",
        }

        if data.get("outcome") == "ok":
            text = (data.get("text") or "").strip()
            title = data.get("title") or source
            stages = data.get("stages") or {}
            breakdown = data.get("knowledge_breakdown") if isinstance(data.get("knowledge_breakdown"), dict) else {}
            meta_n = int(breakdown.get("metadata") or 0)
            tr_n = int(breakdown.get("transcript") or 0)
            speech_pending = str(stages.get("speech") or "") == "waiting" or (
                meta_n > 0 and tr_n == 0
            )
            if speech_pending and tr_n == 0:
                fallback = (
                    f"Metadata learned successfully from '{title}'. "
                    "Spoken content has not yet been learned because no transcript "
                    "or speech processing was available. "
                    f"Knowledge: metadata={meta_n or extras['knowledge_produced']}, "
                    f"transcript=0, concepts=0."
                )
            elif tr_n > 0:
                chunks = int(breakdown.get("transcript_chunks") or extras["knowledge_produced"])
                facts_n = int(breakdown.get("facts") or 0)
                claims_n = int(breakdown.get("claims") or 0)
                concepts_n = int(breakdown.get("concepts") or 0)
                entities_n = int(breakdown.get("entities") or 0)
                rel_n = int(breakdown.get("relationships") or 0)
                fallback = (
                    f"Spoken content learned from '{title}' "
                    f"(transcript={tr_n}, RAG chunks={chunks}, "
                    f"concepts={concepts_n}, entities={entities_n}, "
                    f"relationships={rel_n}, facts={facts_n}, claims={claims_n}, "
                    f"{len(text)} characters)."
                )
            else:
                fallback = (
                    f"Learning update for '{title}' "
                    f"(knowledge_produced={extras['knowledge_produced']}, "
                    f"{len(text)} characters)."
                )
            summary = self._responder.compose(
                _WEB_SUMMARY_SYSTEM,
                f"Summarize what was learned from this media ({title}):\n\n{text[:4000]}",
                fallback=fallback,
            )
            return _Outcome(answer=summary, extras=extras)

        summary = data.get("operator_summary") or (
            "Acquisition failed before read. No document was fabricated."
        )
        if data.get("interactive_recovery") or data.get("outcome") in (
            "blocked",
            "waiting",
        ):
            return _Outcome(
                answer=summary,
                blocked=True,
                blocked_reason=data.get("blocked_reason")
                or "interactive_recovery_required",
                extras=extras,
            )
        return _Outcome(answer=summary, extras=extras)

    def _do_run_python(self, args, context, tool_calls) -> _Outcome:
        code = (args.get("code") or "").strip()
        if not code:
            return _Outcome(answer="What Python code should I run?")
        result = self._executor.execute(self._python_tool, {"code": code})
        data = result.data if isinstance(result.data, dict) else {}
        outcome = data.get("outcome")
        tool_calls.append(
            {
                "intent": Intent.RUN_PYTHON,
                "action": "python.run",
                "capability": "python",
                "ok": result.ok,
                "outcome": outcome,
            }
        )
        if not result.ok:
            return _Outcome(answer=f"I couldn't run that code: {result.error}")
        if outcome == "blocked":
            return _Outcome(
                answer=f"The sandbox is unavailable: {data.get('error')}",
                blocked=True,
                blocked_reason=f"sandbox unavailable: {data.get('error')}",
            )
        if outcome == "timeout":
            return _Outcome(
                answer=f"The code timed out ({data.get('error')}). "
                "Try a smaller or faster computation."
            )
        stdout = (data.get("stdout") or "").strip()
        if outcome == "ok":
            body = stdout or "(the code produced no output)"
            res = data.get("result")
            tail = f"\n\nStructured result: {res}" if res is not None else ""
            return _Outcome(answer=f"Ran it successfully. Output:\n{body}{tail}")
        stderr = (data.get("stderr") or "").strip()
        detail = data.get("error") or (stderr.splitlines()[-1] if stderr else "error")
        return _Outcome(answer=f"The code raised an error: {detail}")

    def _do_git(self, args, context, tool_calls) -> _Outcome:
        action = (args.get("action") or "status").strip()
        repo = (args.get("repo") or ".").strip()
        tool = f"{self._git_tool_prefix}.{action}"
        params: dict[str, Any] = {"repo": repo}
        if action == "log":
            params["max_count"] = args.get("max_count")
        elif action == "diff":
            params["ref"] = args.get("ref")
        elif action == "show":
            params["ref"] = args.get("ref") or "HEAD"
        result = self._executor.execute(tool, params)
        data = result.data if isinstance(result.data, dict) else {}
        outcome = data.get("outcome")
        tool_calls.append(
            {
                "intent": Intent.GIT_STATUS,
                "action": tool,
                "capability": "git",
                "ok": result.ok,
                "outcome": outcome,
            }
        )
        if not result.ok:
            return _Outcome(answer=f"I couldn't run git: {result.error}")
        if outcome == "unavailable":
            return _Outcome(
                answer="Git isn't available here (the git binary isn't installed).",
                blocked=True,
                blocked_reason="git binary not found",
            )
        if outcome == "not_a_repo":
            return _Outcome(answer=f"'{repo}' isn't a git repository.")
        if outcome != "ok":
            return _Outcome(answer=f"git {action} failed: {data.get('reason')}")
        return _Outcome(answer=_format_git(action, repo, data))

    def _do_sql(self, args, context, tool_calls) -> _Outcome:
        sql = (args.get("sql") or "").strip()
        if not sql:
            return _Outcome(answer="What SQL query should I run?")
        result = self._executor.execute(
            self._sql_tool,
            {"sql": sql, "source": args.get("source"), "limit": args.get("limit")},
        )
        data = result.data if isinstance(result.data, dict) else {}
        outcome = data.get("outcome")
        tool_calls.append(
            {
                "intent": Intent.SQL_QUERY,
                "action": self._sql_tool,
                "capability": "sql",
                "ok": result.ok,
                "outcome": outcome,
            }
        )
        if not result.ok:
            return _Outcome(answer=f"I couldn't run that query: {result.error}")
        if outcome == "blocked":
            return _Outcome(
                answer=f"That query was refused: {data.get('reason')}. "
                "I only run read-only queries (SELECT/WITH/EXPLAIN)."
            )
        if outcome == "unavailable":
            return _Outcome(
                answer=f"I couldn't reach that database: {data.get('reason')}.",
                blocked=True,
                blocked_reason=f"database unavailable: {data.get('reason')}",
            )
        if outcome == "error":
            return _Outcome(answer=f"The query errored: {data.get('reason')}")
        return _Outcome(answer=_format_sql(data))

    def _do_ocr(self, args, context, tool_calls) -> _Outcome:
        path = (args.get("path") or "").strip()
        if not path:
            return _Outcome(answer="Which image should I read? Give me an image path.")
        result = self._executor.execute(
            self._ocr_tool, {"path": path, "lang": args.get("lang")}
        )
        data = result.data if isinstance(result.data, dict) else {}
        outcome = data.get("outcome")
        tool_calls.append(
            {
                "intent": Intent.OCR_IMAGE,
                "action": self._ocr_tool,
                "capability": "ocr",
                "ok": result.ok,
                "outcome": outcome,
            }
        )
        if not result.ok:
            return _Outcome(answer=f"I couldn't run OCR: {result.error}")
        if outcome == "unavailable":
            return _Outcome(
                answer=f"OCR isn't available here: {data.get('reason')}.",
                blocked=True,
                blocked_reason=f"ocr unavailable: {data.get('reason')}",
            )
        if outcome == "unsupported":
            return _Outcome(answer=f"I can't OCR that file: {data.get('reason')}.")
        if outcome == "error":
            return _Outcome(answer=f"OCR failed: {data.get('reason')}")
        if outcome == "empty":
            return _Outcome(answer=f"I found no readable text in {path}.")
        text = (data.get("text") or "").strip()
        return _Outcome(
            answer=f"Extracted {data.get('chars', len(text))} characters from {path}:\n\n{text}"
        )

    def _do_mail(self, args, context, tool_calls) -> _Outcome:
        query = (args.get("query") or "").strip()
        result = self._executor.execute(
            self._mail_tool, {"query": query, "folder": args.get("folder")}
        )
        data = result.data if isinstance(result.data, dict) else {}
        outcome = data.get("outcome")
        tool_calls.append(
            {
                "intent": Intent.MAIL_SEARCH,
                "action": self._mail_tool,
                "capability": "mail",
                "ok": result.ok,
                "outcome": outcome,
            }
        )
        if not result.ok:
            return _Outcome(answer=f"I couldn't search email: {result.error}")
        if outcome == "unauthorized":
            return _Outcome(
                answer=f"Email rejected the credentials: {data.get('reason')}.",
                blocked=True,
                blocked_reason=f"mail unauthorized: {data.get('reason')}",
            )
        if outcome == "unavailable":
            return _Outcome(
                answer=f"Email isn't available: {data.get('reason')}.",
                blocked=True,
                blocked_reason=f"mail unavailable: {data.get('reason')}",
            )
        if outcome == "error":
            return _Outcome(answer=f"The email search errored: {data.get('reason')}")
        if outcome == "empty":
            where = data.get("folder", "INBOX")
            scope = f" matching {query!r}" if query else ""
            return _Outcome(answer=f"No messages{scope} in {where}.")
        return _Outcome(answer=_format_mail(data, query))

    def _do_browse(self, args, context, tool_calls) -> _Outcome:
        url = (args.get("url") or "").strip()
        if not url:
            return _Outcome(answer="Which URL should I open in the browser?")
        result = self._executor.execute(self._browser_tool, {"url": url})
        data = result.data if isinstance(result.data, dict) else {}
        outcome = data.get("outcome")
        tool_calls.append(
            {
                "intent": Intent.BROWSE_URL,
                "action": self._browser_tool,
                "capability": "browser",
                "ok": result.ok,
                "outcome": outcome,
            }
        )
        if not result.ok:
            return _Outcome(answer=f"I couldn't open the browser: {result.error}")
        if outcome == "unavailable":
            return _Outcome(
                answer=f"The browser isn't available here: {data.get('reason')}.",
                blocked=True,
                blocked_reason=f"browser unavailable: {data.get('reason')}",
            )
        if outcome == "blocked":
            return _Outcome(
                answer=f"I didn't open {url}: {data.get('reason')}.",
                blocked=True,
                blocked_reason=f"browser blocked: {data.get('reason')}",
            )
        if outcome == "timeout":
            return _Outcome(answer=f"The page timed out: {data.get('reason')}")
        if outcome == "error":
            return _Outcome(answer=f"The browser errored: {data.get('reason')}")
        if outcome == "empty":
            return _Outcome(answer=f"I rendered {url} but found no text.")
        return _Outcome(answer=_format_browse(data))

    def _do_research(self, args, context, tool_calls) -> _Outcome:
        objective = (args.get("objective") or "").strip()
        if not objective:
            return _Outcome(answer="What would you like me to research?")
        payload: dict[str, Any] = {"objective": objective}
        if args.get("max_iterations") is not None:
            payload["max_iterations"] = args["max_iterations"]
        if args.get("resource_profile"):
            payload["resource_profile"] = str(args["resource_profile"]).strip().lower()
        # Stage 3 (C0/RL): jobs attach the live recorder + workspace on context so
        # the deep research loop streams phases into activity.jsonl and writes
        # claims/evidence into the job workspace (Step 5 fast-follow).
        if getattr(context, "activity", None) is not None:
            payload["activity"] = context.activity
        if getattr(context, "workspace", None) is not None:
            payload["workspace"] = context.workspace
        result = self._executor.execute(self._research_tool, payload)
        data = result.data if isinstance(result.data, dict) else {}
        outcome = data.get("outcome")
        tool_calls.append(
            {
                "intent": Intent.RESEARCH,
                "action": self._research_tool,
                "capability": "research",
                "ok": result.ok,
                "outcome": outcome,
            }
        )
        if not result.ok:
            return _Outcome(answer=f"I couldn't run the research loop: {result.error}")
        if outcome == "unavailable":
            return _Outcome(
                answer=f"I can't research that here: {data.get('reason')}.",
                blocked=True,
                blocked_reason=f"research unavailable: {data.get('reason')}",
            )
        if outcome == "error":
            return _Outcome(answer=f"The research loop errored: {data.get('reason')}")
        if outcome == "empty":
            return _Outcome(
                answer=f"I searched but gathered no usable evidence on {objective!r} "
                f"after {data.get('iterations', 0)} round(s)."
            )
        citations = _research_citations(data)
        extras: dict[str, Any] = {}
        if isinstance(data.get("pipeline"), dict):
            extras["pipeline"] = data["pipeline"]
        if isinstance(data.get("usage"), dict):
            extras["usage"] = data["usage"]
        return _Outcome(
            answer=_format_research(data), citations=citations, extras=extras
        )

    def _do_ask_knowledge(self, args, context, tool_calls) -> _Outcome:
        query = args.get("query", "")
        if self._agent is None:
            return _Outcome(answer="I can't answer from the knowledge base right now.")
        result = self._agent.run("rag", query)
        tool_calls.append(
            {
                "intent": Intent.ASK_KNOWLEDGE,
                "action": "rag",
                "capability": "knowledge",
                "run_id": result.run_id,
            }
        )
        answer = (result.answer or "").strip()
        citations = [c.as_dict() for c in result.citations]
        # PLC.F5 — never invent; empty RAG → honest gap
        if not answer or answer.lower() in {"", "i don't know", "unknown"}:
            if not citations:
                return _Outcome(
                    answer=(
                        f"I don't have durable knowledge findings for {query!r} yet. "
                        "Nothing invented. Ingest a document, run research, or ask "
                        "“market intelligence status” / “learner status” for store-backed facts."
                    ),
                    citations=[],
                    run_id=result.run_id,
                )
        return _Outcome(
            answer=answer,
            citations=citations,
            run_id=result.run_id,
        )

    def _do_instantiate_mission(self, args, context, tool_calls) -> _Outcome:
        """Create a mission from a template; optionally auto-register a sample OHLCV feed."""
        if self._templates is None:
            return _Outcome(
                answer="Mission templates are not available in this runtime.",
                blocked=True,
                blocked_reason="templates unavailable",
            )
        template = str(args.get("template") or "").strip()
        if not template:
            return _Outcome(answer="Which template should I instantiate?")
        overrides = dict(args.get("config_overrides") or {})
        auto_feed = bool(overrides.pop("_auto_sample_feed", False))
        feed_note = ""
        if auto_feed and self._assets is not None:
            from atlas.trading.sample_feed import register_market_feed

            instruments = list(overrides.get("instruments") or [])
            if not instruments:
                instruments = [{"symbol": "DEMO", "asset": ""}]
            fixed = []
            for inst in instruments:
                symbol = str(inst.get("symbol") or "DEMO").upper()
                asset_name = str(inst.get("asset") or "").strip() or f"{symbol.lower()}-feed"
                try:
                    info = register_market_feed(
                        self._assets,
                        name=asset_name,
                        symbol=symbol,
                        generate_sample=True,
                    )
                    fixed.append({"symbol": symbol, "asset": info["name"]})
                    feed_note += f" Registered sample market_data feed `{info['name']}` for {symbol}."
                except Exception as exc:  # noqa: BLE001
                    return _Outcome(
                        answer=f"Could not register market data for {symbol}: {exc}",
                        blocked=True,
                        blocked_reason=str(exc),
                    )
            overrides["instruments"] = fixed
        elif auto_feed and self._assets is None:
            return _Outcome(
                answer="Paper trading needs a market_data feed, but the asset store is unavailable.",
                blocked=True,
                blocked_reason="assets unavailable",
            )

        try:
            result = self._templates.instantiate(
                template,
                title=args.get("title"),
                objective=str(args.get("objective") or ""),
                config_overrides=overrides or None,
                activate=bool(args.get("activate", True)),
                autostart=bool(args.get("autostart", True)),
            )
        except Exception as exc:  # noqa: BLE001
            return _Outcome(
                answer=f"Could not instantiate mission '{template}': {exc}",
                blocked=True,
                blocked_reason=str(exc),
            )
        mission = result.get("mission")
        mid = getattr(mission, "id", None) or (mission.get("id") if isinstance(mission, dict) else None)
        title = getattr(mission, "title", None) or (mission.get("title") if isinstance(mission, dict) else template)
        tool_calls.append(
            {
                "intent": Intent.INSTANTIATE_MISSION,
                "action": "instantiate_mission",
                "template": template,
                "mission_id": str(mid) if mid else None,
                "config_overrides": overrides,
            }
        )
        cash = overrides.get("starting_cash")
        cash_bit = f" starting_cash={cash}" if cash is not None else ""
        return _Outcome(
            answer=(
                f"Instantiated mission `{title}` from template `{template}`"
                f" (id {mid}).{cash_bit}.{feed_note} "
                "Open Missions to watch the journal; send JSON live inputs like "
                '{"block_symbol": "SYM"} while it runs. '
                "No broker login — simulation only."
            ).strip(),
            extras={"mission_id": str(mid) if mid else None, "template": template},
        )

    def _do_register_market_data(self, args, context, tool_calls) -> _Outcome:
        if self._assets is None:
            return _Outcome(
                answer="Asset store is not available.",
                blocked=True,
                blocked_reason="assets unavailable",
            )
        from atlas.trading.sample_feed import register_market_feed

        name = str(args.get("name") or "").strip()
        symbol = str(args.get("symbol") or name or "DEMO").strip() or "DEMO"
        if not name:
            name = f"{symbol.lower()}-feed"
        data = None
        if args.get("content"):
            data = str(args["content"]).encode("utf-8")
        elif args.get("bars"):
            import json as _json

            data = _json.dumps(args["bars"]).encode("utf-8")
        try:
            info = register_market_feed(
                self._assets,
                name=name,
                symbol=symbol,
                data=data,
                filename=args.get("filename"),
                content_type=args.get("content_type"),
                generate_sample=bool(args.get("generate_sample", data is None)),
                sample_bars_n=int(args.get("sample_bars") or 60),
                sample_start=float(args.get("sample_start") or 100.0),
            )
        except Exception as exc:  # noqa: BLE001
            return _Outcome(
                answer=f"Could not register market data: {exc}",
                blocked=True,
                blocked_reason=str(exc),
            )
        tool_calls.append(
            {
                "intent": Intent.REGISTER_MARKET_DATA,
                "action": "register_market_data",
                **info,
            }
        )
        sample = " (deterministic sample fixture)" if info.get("generated_sample") else ""
        return _Outcome(
            answer=(
                f"Registered market_data asset `{info['name']}` for symbol {info['symbol']}"
                f"{sample}. Use instruments:[{{symbol:\"{info['symbol']}\", asset:\"{info['name']}\"}}] "
                "in a paper_trading mission config. No live broker credentials are required."
            ),
            extras=info,
        )

    def _do_start_investment_learner(self, args, context, tool_calls) -> _Outcome:
        """OX.1 / OX.2 — preview India learner plan (default) or activate immediately."""
        from atlas.planning.service import PlanningService

        program = str(args.get("program") or "market_intelligence").strip()
        preset = str(args.get("preset") or "india_equity_learner").strip()
        capital = float(args.get("capital") or 10000)
        universe = str(args.get("universe") or "NIFTY50").strip() or "NIFTY50"
        mode = str(args.get("mode") or "auto")
        broker = str(args.get("broker_profile") or "paper_demo")
        objective = str(args.get("objective") or "").strip() or None
        # OX.2: Chat defaults to preview; power-user / confirm / Jobs set activate.
        activate = bool(args.get("activate"))
        if args.get("preview") is True:
            activate = False
        if args.get("preview") is False:
            activate = True

        planner = self._planning if self._planning is not None else PlanningService()
        plan = planner.plan_program_start(
            preset=preset,
            program_id=program,
            capital=capital,
            universe=universe,
            mode=mode,
            broker_profile=broker,
            objective=objective,
            activate=activate,
        )

        member_overrides: dict[str, dict] = {}
        sim = {
            "starting_cash": capital,
            "universe_index": universe,
            "instruments": [],
            "feed_mode": "live",
            "live_provider": "yahoo",
            "market_session": "nse_equity",
            "program_id": program,
            "broker_profile": broker,
            "auto_max_instruments": 10,
        }
        member_overrides["decision_simulation"] = dict(sim)
        member_overrides["paper_trading"] = dict(sim)
        member_overrides["investment_universe"] = {
            "index": universe,
            "max_watchlist": 15,
            "mode": mode,
            "program_id": program,
        }
        member_overrides["portfolio_ledger"] = {
            "starting_cash": capital,
            "broker_profile": broker,
        }
        title_prefix = f"India ₹{int(capital):,} learner"

        if not activate:
            preview_members: list[dict] = []
            if self._programs is not None:
                try:
                    dry = self._programs.preview_start(
                        program,
                        title_prefix=title_prefix,
                        preset=preset,
                        member_overrides=member_overrides,
                    )
                    preview_members = list(dry.get("started") or [])
                except Exception as exc:  # noqa: BLE001
                    self._logger.debug("program preview_start skipped: %s", exc)
            tool_calls.append(
                {
                    "intent": Intent.START_INVESTMENT_LEARNER,
                    "action": "preview_program",
                    "program": program,
                    "preset": preset,
                    "capital": capital,
                    "universe": universe,
                    "activate": False,
                    "steps": len(plan.get("steps") or []),
                }
            )
            lines = [
                f"**Proposed plan — India cash-equity learner** "
                f"(₹{capital:,.0f}, {universe}, mode={mode})",
                "",
                "Steps Atlas will start:",
            ]
            for step in plan.get("steps") or []:
                lines.append(
                    f"{step.get('order')}. **{step.get('role')}** (`{step.get('template')}`) — "
                    f"{step.get('detail')}"
                )
            if preview_members:
                lines.append("")
                lines.append(
                    f"Would create {len(preview_members)} new mission(s); "
                    "already-present members are skipped."
                )
            lines.append("")
            for note in plan.get("notes") or []:
                lines.append(f"- {note}")
            lines.append("")
            lines.append(str(plan.get("confirm_hint") or ""))
            return _Outcome(
                answer="\n".join(lines).strip(),
                extras={
                    "program": program,
                    "preset": preset,
                    "plan": plan,
                    "would_start": preview_members,
                    "activate": False,
                },
            )

        if self._programs is None:
            return _Outcome(
                answer="Programs service is not available.",
                blocked=True,
                blocked_reason="programs unavailable",
            )
        try:
            result = self._programs.start(
                program,
                activate=True,
                title_prefix=title_prefix,
                preset=preset,
                member_overrides=member_overrides,
            )
        except Exception as exc:  # noqa: BLE001
            return _Outcome(
                answer=f"Could not start investment learner: {exc}",
                blocked=True,
                blocked_reason=str(exc),
            )
        started = result.get("started") or []
        skipped = result.get("skipped") or []
        goal_info: dict | None = None
        if self._goals is not None:
            try:
                goal_info = self._goals.ensure_for_learner(
                    objective_text=objective,
                    capital=capital,
                    universe=universe,
                    program_id=program,
                    portfolio_key=str(args.get("portfolio") or "india_equity_learner"),
                )
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("goal ensure_for_learner skipped: %s", exc)
        tool_calls.append(
            {
                "intent": Intent.START_INVESTMENT_LEARNER,
                "action": "start_program",
                "program": program,
                "preset": preset,
                "capital": capital,
                "universe": universe,
                "activate": True,
                "started": len(started),
                "skipped": len(skipped),
                "goal_id": (goal_info or {}).get("id"),
            }
        )
        roles = ", ".join(s.get("role") or s.get("template") for s in started) or "(none new)"
        goal_bit = ""
        if goal_info:
            goal_bit = f" Goal linked: “{goal_info.get('title')}”."
        return _Outcome(
            answer=(
                f"Started Market Intelligence as an India cash-equity learner "
                f"(₹{capital:,.0f}, {universe}, auto universe → Decision Simulation). "
                f"New missions: {roles}. "
                f"Skipped {len(skipped)} already-present/stub member(s)."
                f"{goal_bit} "
                "Open Programs → Market Intelligence to watch journals. "
                "Simulation only — no broker login."
            ),
            extras={
                "program": program,
                "preset": preset,
                "plan": plan,
                "started": started,
                "skipped": skipped,
                "activate": True,
                "goal": goal_info,
            },
        )

    def _do_career_status(self, args, context, tool_calls) -> _Outcome:
        """PLC.F — Career Intelligence status without waiting on Ollama."""
        lines: list[str] = [
            "Career Intelligence (CI.0–CI.5) — what Atlas has learned / can do so far:",
            "",
            "Shipped capabilities (not inventing job outcomes):",
            "· Observer one-step ingest (LinkedIn/export when you provide it)",
            "· Career Knowledge Graph + opportunity score",
            "· Career Research BATCH mode",
            "· Board adapters + honest CapabilityGaps when live HTTP isn’t wired",
            "· Learning plans from postings + gated-apply stub (recommend-only)",
            "",
        ]
        brief: dict[str, Any] | None = None
        try:
            from atlas.career.brief import build_morning_brief

            brief = build_morning_brief(include_jobs=False)
        except Exception as exc:  # noqa: BLE001
            lines.append(f"Brief unavailable right now: {type(exc).__name__}: {exc}"[:180])
            brief = None

        if isinstance(brief, dict):
            highlights = brief.get("highlights") or []
            watching = brief.get("watchlist") or {}
            n = int(watching.get("count") or 0) if isinstance(watching, dict) else 0
            lines.append(f"Watchlist items on disk: {n}")
            for h in (highlights or [])[:6]:
                lines.append(f"· {h}")
            market = brief.get("market") or {}
            skills = (market.get("skills") or [])[:5] if isinstance(market, dict) else []
            if skills:
                lines.append("Fixture market demand (sample feed — not live boards):")
                for s in skills:
                    lines.append(
                        f"  · {s.get('skill')}: {s.get('demand_pct')}%"
                    )
            honesty = brief.get("note")
            if honesty:
                lines.append(str(honesty)[:280])
            else:
                lines.append(
                    "Honesty: live board apply is gated; sample/fixture demand ≠ "
                    "your real market until you import a feed or enable boards."
                )

        lines.extend(
            [
                "",
                "Next useful operator moves:",
                "· Personal tab → career brief / watchlist",
                "· Import LinkedIn export or job feed when ready",
                "· GET /v1/personal/career/brief",
                "",
                "(This reply is deterministic — no chat LLM — so it works even when Ollama is busy.)",
            ]
        )
        wl_n = None
        if isinstance(brief, dict):
            wl_n = int((brief.get("watchlist") or {}).get("count") or 0)
        tool_calls.append(
            {
                "intent": Intent.CAREER_STATUS,
                "action": "status",
                "capability": "career_brief",
                "watchlist_n": wl_n,
            }
        )
        return _Outcome(answer="\n".join(lines))

    def _do_market_status(self, args, context, tool_calls) -> _Outcome:
        """PLC.F / UTS.G — Market Intelligence / coverage status (no Ollama)."""
        from atlas.investment.market_status_chat import (
            answer_market_allocation_question,
            build_market_intelligence_status,
        )

        data_dir = None
        try:
            from atlas.config import get_config

            data_dir = str(get_config().paths.data)
        except Exception:  # noqa: BLE001
            data_dir = None
        # Prefer specific UTS questions when the user asked them.
        msg = ""
        try:
            msg = str(
                (args or {}).get("message")
                or (args or {}).get("query")
                or (context or {}).get("message")
                or ""
            )
        except Exception:  # noqa: BLE001
            msg = ""
        special = answer_market_allocation_question(
            msg, data_dir=data_dir, laboratory_id="india_equity_learner"
        )
        if special and special.get("answer"):
            tool_calls.append(
                {
                    "intent": Intent.MARKET_STATUS,
                    "action": special.get("kind") or "allocation",
                    "capability": "market_status",
                }
            )
            return _Outcome(answer=str(special.get("answer") or ""), extras=special)

        doc = build_market_intelligence_status(data_dir=data_dir, goals=self._goals)
        tool_calls.append(
            {
                "intent": Intent.MARKET_STATUS,
                "action": "status",
                "capability": "market_status",
                "labs": doc.get("labs"),
                "research_n": doc.get("research_n"),
                "fundamentals_pe": doc.get("fundamentals_pe"),
            }
        )
        return _Outcome(answer=str(doc.get("answer") or ""), extras=doc)

    def _do_manage_goal(self, args, context, tool_calls) -> _Outcome:
        """OX.3 — create / list / status durable Goals (objectives first)."""
        if self._goals is None:
            return _Outcome(
                answer="Goals service is not available.",
                blocked=True,
                blocked_reason="goals unavailable",
            )
        action = str(args.get("action") or "status").strip().lower()
        title = str(args.get("title") or args.get("objective") or "").strip()
        query = str(args.get("query") or title).strip()

        if action == "create":
            if not title:
                return _Outcome(answer="What objective should I record as your Goal?")
            goal = self._goals.create(
                title,
                objective={"text": title, "intent": "operator"},
            )
            tool_calls.append(
                {
                    "intent": Intent.MANAGE_GOAL,
                    "action": "create",
                    "goal_id": goal.get("id"),
                }
            )
            return _Outcome(
                answer=(
                    f"Goal recorded (objective first): “{goal.get('title')}”. "
                    f"Status={goal.get('status')}. "
                    "Link a Program or Portfolio later — the Goal stands on its own. "
                    f"id={goal.get('id')}"
                ),
                extras={"goal": goal},
            )

        if action == "list":
            result = self._goals.list(status="active", limit=20)
            goals = result.get("goals") or []
            tool_calls.append(
                {"intent": Intent.MANAGE_GOAL, "action": "list", "count": len(goals)}
            )
            if not goals:
                return _Outcome(
                    answer="No active goals yet. Say “my goal is …” to create one."
                )
            lines = ["Active goals:"]
            for g in goals:
                links = []
                if g.get("program_id"):
                    links.append(f"program={g['program_id']}")
                if g.get("portfolio_key"):
                    links.append(f"portfolio={g['portfolio_key']}")
                link_s = f" ({', '.join(links)})" if links else " (no Program/Portfolio link yet)"
                lines.append(f"- {g.get('title')} [{g.get('status')}]{link_s}")
            return _Outcome(answer="\n".join(lines), extras=result)

        if action in {"pause", "complete"}:
            goal = self._goals.resolve(query)
            if not goal:
                return _Outcome(answer=f"I couldn't find a goal matching “{query}”.")
            new_status = "paused" if action == "pause" else "completed"
            updated = self._goals.update(goal["id"], status=new_status)
            tool_calls.append(
                {
                    "intent": Intent.MANAGE_GOAL,
                    "action": action,
                    "goal_id": goal.get("id"),
                }
            )
            return _Outcome(
                answer=f"Goal “{(updated or goal).get('title')}” → {new_status}.",
                extras={"goal": updated or goal},
            )

        # status / progress / resolve by objective text
        if action == "progress" or re.search(
            r"\b(progress|learner status|how(?:'s| is))\b",
            str(args.get("query") or "").lower(),
        ):
            report = self._goals.progress(query=query, persist=True)
            tool_calls.append(
                {
                    "intent": Intent.MANAGE_GOAL,
                    "action": "progress",
                    "goal_id": ((report.get("goal") or {}).get("id")),
                    "query": query,
                    "ok": report.get("ok"),
                }
            )
            return _Outcome(
                answer=str(report.get("answer") or report.get("narrative") or ""),
                extras=report,
            )

        goal = self._goals.resolve(query)
        tool_calls.append(
            {
                "intent": Intent.MANAGE_GOAL,
                "action": "status",
                "goal_id": (goal or {}).get("id"),
                "query": query,
            }
        )
        if not goal:
            return _Outcome(
                answer=(
                    f"No goal matched “{query}”. "
                    "Try “list goals” or “my goal is Beat NIFTY over 12 months”."
                )
            )
        # Prefer full OX.4 narrative when available
        report = self._goals.progress(goal_id=str(goal["id"]), persist=True)
        if report.get("ok"):
            return _Outcome(
                answer=str(report.get("answer") or report.get("narrative") or ""),
                extras=report,
            )
        prog = goal.get("program_id") or "(none)"
        book = goal.get("portfolio_key") or "(none)"
        progress = goal.get("progress") or {}
        note = progress.get("note") or "No progress narrative yet."
        return _Outcome(
            answer=(
                f"Goal: “{goal.get('title')}” [{goal.get('status')}]\n"
                f"Objective: {(goal.get('objective') or {}).get('text') or goal.get('title')}\n"
                f"Links: program={prog}, portfolio={book}\n"
                f"Progress: {note}"
            ),
            extras={"goal": goal},
        )

    def _do_react(self, args, context, tool_calls) -> _Outcome:
        query = args.get("query", "")
        if self._agent is None:
            return _Outcome(answer="I don't know how to handle that yet.")
        result = self._agent.run("assistant", query)
        tool_calls.append(
            {
                "intent": Intent.REACT,
                "action": "react",
                "capability": "agent",
                "run_id": result.run_id,
                "tools_used": result.usage.get("tools_used", []),
            }
        )
        return _Outcome(answer=result.answer, run_id=result.run_id)

    # --- capability honesty (R2) ---------------------------------------
    def _has_web_tool(self) -> bool:
        # Checked dynamically: plugin tools register after the service is built.
        return self._tools is not None and self._tools.has(self._web_tool)

    def _has_search_tool(self) -> bool:
        return self._tools is not None and self._tools.has(self._search_tool)

    def _has_python_tool(self) -> bool:
        return self._tools is not None and self._tools.has(self._python_tool)

    def _has_scholar_tool(self) -> bool:
        return self._tools is not None and self._tools.has(self._scholar_tool)

    def _has_youtube_tool(self) -> bool:
        return self._tools is not None and self._tools.has(self._youtube_tool)

    def _has_git_tool(self) -> bool:
        return self._tools is not None and self._tools.has(
            f"{self._git_tool_prefix}.status"
        )

    def _has_sql_tool(self) -> bool:
        return self._tools is not None and self._tools.has(self._sql_tool)

    def _has_ocr_tool(self) -> bool:
        return self._tools is not None and self._tools.has(self._ocr_tool)

    def _has_mail_tool(self) -> bool:
        return self._tools is not None and self._tools.has(self._mail_tool)

    def _has_browser_tool(self) -> bool:
        return self._tools is not None and self._tools.has(self._browser_tool)

    def _has_research_tool(self) -> bool:
        return self._tools is not None and self._tools.has(self._research_tool)

    def _capability_available(self, capability: str) -> bool:
        # Prefer the typed CapabilityRegistry (S11): it's the single source of truth
        # for what's registered, and it sees plugin capabilities registered after
        # this service is constructed (shared by reference).
        if not capability:
            return True
        if self._capabilities is not None:
            return self._capabilities.has(capability)
        # Fallback for callers that don't wire a registry (older tests): infer from
        # the injected dependencies.
        return {
            "llm": self._llm is not None,
            "memory": self._memory is not None,
            "knowledge": self._knowledge is not None,
            "agent": self._agent is not None,
            "web": self._has_web_tool(),
            "search": self._has_search_tool(),
            "scholar": self._has_scholar_tool(),
            "transcript": self._has_youtube_tool(),
            "python": self._has_python_tool(),
            "git": self._has_git_tool(),
            "sql": self._has_sql_tool(),
            "ocr": self._has_ocr_tool(),
            "mail": self._has_mail_tool(),
            "browser": self._has_browser_tool(),
            "research": self._has_research_tool(),
        }.get(capability, True)

    def _preflight_gaps(self, plan: Plan) -> list[dict[str, Any]]:
        from atlas.capabilities import CAPABILITY_CATALOG

        gaps: list[dict[str, Any]] = []
        for step in plan.steps:
            if self._capability_available(step.capability):
                continue
            spec = CAPABILITY_CATALOG.get(step.capability)
            gaps.append(
                {
                    "missing_capability": step.capability,
                    "needed_by_step": step.intent,
                    "reason": (
                        f"'{step.intent}' needs the '{step.capability}' capability, "
                        "which is not registered."
                    ),
                    "unlocks": (spec.unlocks if spec else step.description),
                    "since": (spec.since if spec else None),
                }
            )
        return gaps

    @staticmethod
    def _gap_answer(gaps: list[dict[str, Any]]) -> str:
        missing = ", ".join(g["missing_capability"] for g in gaps)
        return (
            "I can't do that yet — I'm missing the capability I'd need: "
            f"{missing}. I won't guess. Once that's added, I can handle this."
        )

    @staticmethod
    def _as_text(data: Any) -> str:
        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            for key in ("text", "content", "body"):
                if isinstance(data.get(key), str):
                    return data[key]
        return str(data)

    # --- Service lifecycle ---------------------------------------------
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def health_check(self) -> HealthStatus:
        ready = self._llm is not None and self._agent is not None
        return HealthStatus(
            healthy=ready,
            detail="chat orchestrator ready" if ready else "missing llm/agent",
            data={
                "web_tool": self._has_web_tool(),
                "web_capability": self._capability_available("web"),
            },
        )
