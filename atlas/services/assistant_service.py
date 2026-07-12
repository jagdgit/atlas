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
            "citations": self.citations,
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
    ) -> str:
        messages = [ChatMessage("system", system)]
        if context is not None:
            messages.extend(context.as_chat_messages())
        messages.append(ChatMessage("user", user))
        try:
            return self._llm.for_role("chat").chat(messages).text.strip() or fallback
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
        search_limit: int = 5,
        list_limit: int = 25,
        logger: logging.Logger | None = None,
    ) -> None:
        self._conversation = conversation
        self._planner = planner
        self._executor = executor
        self._knowledge = knowledge
        self._memory = memory
        self._agent = agent
        self._llm = llm
        self._tools = tools
        self._capabilities = capabilities
        self._web_tool = web_tool
        self._search_tool = search_tool
        self._scholar_tool = scholar_tool
        self._youtube_tool = youtube_tool
        self._python_tool = python_tool
        self._git_tool_prefix = git_tool_prefix
        self._sql_tool = sql_tool
        self._ocr_tool = ocr_tool
        self._mail_tool = mail_tool
        self._search_limit = search_limit
        self._list_limit = list_limit
        self._responder = ResponseBuilder(llm, logger)
        self._logger = logger or logging.getLogger("atlas.assistant")

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

        if gaps:
            outcome = _Outcome(answer=self._gap_answer(gaps))
        else:
            outcome = self._dispatch(step.intent, step.args, context, tool_calls)

        self._conversation.add_assistant_message(
            sid, outcome.answer, tool_calls=tool_calls
        )
        return ChatTurn(
            session_id=sid,
            answer=outcome.answer,
            intent=step.intent,
            citations=outcome.citations,
            tool_calls=tool_calls,
            capability_gaps=gaps,
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
            Intent.RUN_PYTHON: self._do_run_python,
            Intent.GIT_STATUS: self._do_git,
            Intent.SQL_QUERY: self._do_sql,
            Intent.OCR_IMAGE: self._do_ocr,
            Intent.MAIL_SEARCH: self._do_mail,
            Intent.ASK_KNOWLEDGE: self._do_ask_knowledge,
            Intent.REACT: self._do_react,
        }.get(intent, self._do_react)
        return handler(args, context, tool_calls)

    def _do_smalltalk(self, args, context, tool_calls) -> _Outcome:
        msg = args.get("query", "")
        answer = self._responder.compose(
            _SMALLTALK_SYSTEM, msg, context=context, fallback="Hello! How can I help?"
        )
        tool_calls.append({"intent": Intent.SMALLTALK, "action": "smalltalk"})
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
            }
        )
        if not result.ok:
            return _Outcome(answer=f"I couldn't fetch that transcript: {result.error}")
        if outcome != "ok":
            reason = data.get("reason") or outcome
            return _Outcome(
                answer=f"No transcript available ({outcome}): {reason}."
            )
        text = (data.get("text") or "").strip()
        title = data.get("title") or data.get("video_id")
        summary = self._responder.compose(
            _WEB_SUMMARY_SYSTEM,
            f"Summarize this YouTube transcript ({title}):\n\n{text[:4000]}",
            fallback=f"Transcript of '{title}' ({len(text)} characters).",
        )
        return _Outcome(answer=summary)

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
        return _Outcome(
            answer=result.answer,
            citations=[c.as_dict() for c in result.citations],
            run_id=result.run_id,
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

    def _capability_available(self, capability: str) -> bool:
        # Prefer the typed CapabilityRegistry (S11): it's the single source of truth
        # for what's registered, and it sees plugin capabilities registered after
        # this service is constructed (shared by reference).
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
