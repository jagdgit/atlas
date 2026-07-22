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
    CAP_BROWSER,
    CAP_GIT,
    CAP_KNOWLEDGE,
    CAP_LLM,
    CAP_MAIL,
    CAP_MEDIA_LEARN,
    CAP_MEMORY,
    CAP_OCR,
    CAP_PYTHON,
    CAP_RESEARCH,
    CAP_SCHOLAR,
    CAP_SEARCH,
    CAP_SQL,
    CAP_TRANSCRIPT,
    CAP_WEB,
)


class Intent:
    SMALLTALK = "smalltalk"
    RECALL = "recall"
    REMEMBER = "remember"
    WEB_FETCH = "web_fetch"
    WEB_SEARCH = "web_search"
    SCHOLAR_SEARCH = "scholar_search"
    YOUTUBE_TRANSCRIPT = "youtube_transcript"
    MEDIA_LEARN = "media_learn"
    RUN_PYTHON = "run_python"
    GIT_STATUS = "git_status"
    SQL_QUERY = "sql_query"
    OCR_IMAGE = "ocr_image"
    MAIL_SEARCH = "mail_search"
    BROWSE_URL = "browse_url"
    RESEARCH = "research"
    LIST_DOCUMENTS = "list_documents"
    INGEST_PATH = "ingest_path"
    ASK_KNOWLEDGE = "ask_knowledge"
    ANSWER = "answer"  # fast fallback: a single chat-model call, no tools (RC/D3.12)
    REACT = "react"  # escalation: open-ended reasoning + tools via the ReAct strategy
    INSTANTIATE_MISSION = "instantiate_mission"
    REGISTER_MARKET_DATA = "register_market_data"


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
# Academic search: arXiv/Scholar mentions, or "find papers/studies on …" phrasing.
_SCHOLAR_RE = re.compile(
    r"\barxiv\b|\bgoogle scholar\b|\bsemantic scholar\b|\bpeer[- ]reviewed\b"
    r"|\bacademic (?:papers?|sources?|literature)\b|\bliterature review\b"
    r"|\b(?:find|search|look up|get|fetch)\b[^?]{0,30}"
    r"\b(?:papers?|studies|publications?|journal articles?)\b"
    r"|\b(?:papers?|studies|research)\s+(?:on|about)\b",
    re.IGNORECASE,
)
_SCHOLAR_PREFIX_RE = re.compile(
    r"^\s*(?:please\s+)?(?:find|search|look\s+up|get|fetch)\s+(?:me\s+)?(?:some\s+)?"
    r"(?:recent\s+)?(?:"
    r"(?:papers?|studies|research|publications?|academic\s+\w+|literature)"
    r"|(?:on\s+)?(?:arxiv|semantic\s+scholar|google\s+scholar|scholar)"
    r")\s*(?:on|about|for|regarding)?\s*[:,]?\s*",
    re.IGNORECASE,
)
# A YouTube URL, or an explicit "transcript/transcribe" request.
_YOUTUBE_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtube\.com/(?:watch\?[^\s]*v=|shorts/|embed/|v/)"
    r"|youtu\.be/)[\w\-]{11}[^\s<>\"')]*",
    re.IGNORECASE,
)
# Caption-only: explicit transcript/subtitle language (not "learn from video").
_YOUTUBE_TRANSCRIPT_RE = re.compile(
    r"\b(?:transcript|transcribe|subtitles?|captions?)\b",
    re.IGNORECASE,
)
# Learn-from-media: bare YouTube URL, learn/summarize/ingest + video, or local media file.
_MEDIA_LEARN_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtube\.com/(?:watch\?[^\s]*v=|shorts/|embed/|v/)"
    r"|youtu\.be/)[\w\-]{11}"
    r"|\b(?:learn|ingest|understand|summarize|summarise)\b.{0,60}\b"
    r"(?:video|youtube|talk|lecture|podcast|media|recording)\b"
    r"|\b(?:video|youtube|talk|lecture|podcast|media|recording)\b.{0,60}\b"
    r"(?:learn|ingest|understand|summarize|summarise)\b"
    r"|\b[\w./~\-]+\.(?:mp4|mp3|wav|m4a|webm|mkv|vtt|srt)\b",
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
# Explicit git inspection request: "git status/log/diff/branches" or "recent commits".
_GIT_RE = re.compile(
    r"\bgit\s+(?:status|log|diff|show|branch(?:es)?|history)\b"
    r"|\b(?:recent\s+commits?|commit\s+history|git\s+history|"
    r"uncommitted\s+changes|working\s+tree\s+changes?)\b",
    re.IGNORECASE,
)
# A directory-ish path token (quoted, or starting with ~ / . / /), for the repo arg.
_GIT_DIR_RE = re.compile(
    r"(?:\"([^\"]+)\"|'([^']+)'|((?:~|\.{1,2})?/[\w./\-]+))"
)
# A fenced ```sql block, or an explicit "run/query … sql/database" instruction, or a
# bare SELECT/WITH statement.
_SQL_FENCE_RE = re.compile(r"```sql\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_SQL_PREFIX_RE = re.compile(
    r"^\s*(?:please\s+)?(?:run|execute|query)\s+(?:this\s+)?"
    r"(?:sql|query|the\s+database|database|db)\b[:,]?\s*",
    re.IGNORECASE,
)
_SQL_RE = re.compile(
    r"```sql\b"
    r"|^\s*(?:please\s+)?(?:run|execute|query)\s+(?:this\s+)?"
    r"(?:sql|query|the\s+database|database|db)\b"
    r"|^\s*(?:select|with)\b[\s\S]*\bfrom\b"
    r"|\bquery\s+the\s+(?:database|db|table)\b",
    re.IGNORECASE,
)
# A database source token: a quoted path or a *.db / *.sqlite file.
_SQL_SOURCE_RE = re.compile(
    r"(?:\"([^\"]+\.(?:db|sqlite3?|s3db))\"|'([^']+\.(?:db|sqlite3?|s3db))'"
    r"|([\w./\-]+\.(?:db|sqlite3?|s3db)))",
    re.IGNORECASE,
)
# An image path token (quoted or bare) with a known raster suffix.
_IMAGE_RE = re.compile(
    r"(?:\"([^\"]+\.(?:png|jpe?g|gif|bmp|tiff?|webp))\""
    r"|'([^']+\.(?:png|jpe?g|gif|bmp|tiff?|webp))'"
    r"|([\w./\-]+\.(?:png|jpe?g|gif|bmp|tiff?|webp)))",
    re.IGNORECASE,
)
# An explicit OCR request, or an image path paired with a "read/extract text" verb.
_OCR_RE = re.compile(
    r"\bocr\b"
    r"|\b(?:extract|read|get|pull|transcribe)\b[^.?!]{0,40}"
    r"\b(?:text|words?|writing)\b[^.?!]{0,40}"
    r"\b(?:image|photo|picture|screenshot|scan|png|jpe?g)\b"
    r"|\b[\w./\-]+\.(?:png|jpe?g|gif|bmp|tiff?|webp)\b",
    re.IGNORECASE,
)
# A read-only email request: "inbox"/"mailbox", or a read verb near "email(s)", or an
# email paired with from/about/subject. We never *send* — this routes to read-only search.
_MAIL_RE = re.compile(
    r"\b(?:inbox|mailbox)\b"
    r"|\b(?:check|search|find|read|show|list|any|recent|latest|unread|scan)\b"
    r"[^.?!]{0,30}\be-?mails?\b"
    r"|\be-?mails?\b[^.?!]{0,30}\b(?:from|about|regarding|subject|containing)\b",
    re.IGNORECASE,
)
# Query text: a quoted phrase, or whatever follows for/about/regarding/… .
_MAIL_QUERY_RE = re.compile(
    r"(?:\"([^\"]+)\"|'([^']+)'"
    r"|\b(?:for|about|regarding|containing|mentioning|with subject|from)\s+(.+))",
    re.IGNORECASE,
)
# An optional named folder (a trailing "in <Folder>").
_MAIL_FOLDER_RE = re.compile(
    r"\bin\s+(?:the\s+)?(?:folder\s+)?"
    r"(INBOX|Sent|Drafts|Trash|Spam|Junk|Archive|All\s?Mail|[A-Z][\w/]*)\b",
)
# An autonomous research request: a research verb, or "what does the evidence say".
_RESEARCH_RE = re.compile(
    r"^\s*(?:please\s+)?(?:do\s+(?:a|an)\s+)?"
    r"(?:deep[\s-]?dive|research|investigate|gather\s+evidence|find\s+evidence)\b"
    r"|\bwhat\s+does\s+the\s+(?:evidence|research|literature)\s+say\b"
    r"|\bresearch\s+(?:whether|if|how|why|what|the\s+topic)\b",
    re.IGNORECASE,
)
_RESEARCH_PREFIX_RE = re.compile(
    r"^\s*(?:please\s+)?(?:do\s+(?:a|an)\s+)?(?:deep[\s-]?dive|research|investigate|"
    r"look\s+into|gather\s+evidence|find\s+evidence|find\s+out)\b"
    r"\s*(?:on|about|into|for|regarding|whether|if|the\s+topic\s+of)?\s*[:,-]?\s*"
    r"|^\s*what\s+does\s+the\s+(?:evidence|research|literature)\s+say\s+(?:about|on)?\s*",
    re.IGNORECASE,
)
# An explicit request to render/screenshot a page in a headless browser. Requires a URL
# to be present (lookahead) so it only wins over plain web_fetch on deliberate escalation.
_BROWSE_RE = re.compile(
    r"(?=.*https?://)"
    r"(?:\b(?:browse|browser|render(?:ed|s)?|headless|screenshot|screen[- ]?grab)\b"
    r"|\bopen\b[^.?!]{0,20}\bin\b[^.?!]{0,15}\bbrowser\b"
    r"|\bjavascript[- ]?(?:rendered|heavy)\b"
    r"|\bdynamic(?:ally)?\b[^.?!]{0,20}\b(?:page|site|content|rendered|loaded)\b)",
    re.IGNORECASE | re.DOTALL,
)
# RC / D3.12: when an unmatched (open-ended) message reaches the fallback, only
# escalate to the (slow, multi-call) ReAct agent if it plainly needs *current data*
# or a tool/action. Everything else is a general question the chat model can answer
# in a single call — which is what keeps trivial chat fast instead of timing out.
_ESCALATE_RE = re.compile(
    r"\b(?:latest|newest|current(?:ly)?|today|tonight|as of|"
    r"up[- ]?to[- ]?date|recent(?:ly)?|breaking|live)\b"
    r"|\bright now\b|\bthis (?:week|month|year|morning|evening)\b"
    r"|\b(?:news|headlines?)\b"
    r"|\b(?:price|cost|value|rate|quote)\s+(?:of|for)\b"
    r"|\bstock price\b|\bexchange rate\b|\bweather\b|\bforecast\b"
    r"|\b(?:download|scrape|crawl|monitor|fetch|browse)\b",
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


def _scholar_args(message: str, _m: re.Match[str] | None) -> dict[str, Any]:
    query = _SCHOLAR_PREFIX_RE.sub("", message).strip()
    query = re.sub(
        r"\b(?:on|in|from)\s+(?:arxiv|semantic\s+scholar|google\s+scholar|scholar)\b",
        "",
        query,
        flags=re.IGNORECASE,
    ).strip()
    return {"query": query or message.strip()}


def _youtube_args(message: str, _m: re.Match[str] | None) -> dict[str, Any]:
    match = _YOUTUBE_URL_RE.search(message)
    if match:
        video = match.group(0).rstrip(".,);")
    else:
        token = re.search(r"\b[A-Za-z0-9_-]{11}\b", message)
        video = token.group(0) if token else ""
    return {"video": video}


def _media_learn_args(message: str, _m: re.Match[str] | None) -> dict[str, Any]:
    match = _YOUTUBE_URL_RE.search(message)
    if match:
        return {"source": match.group(0).rstrip(".,);")}
    media_file = re.search(
        r"((?:~|\.{0,2}/)?[\w./\-]+\.(?:mp4|mp3|wav|m4a|webm|mkv|vtt|srt))",
        message,
        re.IGNORECASE,
    )
    if media_file:
        return {"source": media_file.group(1)}
    # Same fallback as youtube args for bare 11-char ids in learn phrasing.
    token = re.search(r"\b[A-Za-z0-9_-]{11}\b", message)
    return {"source": token.group(0) if token else ""}


def _python_args(message: str, _m: re.Match[str] | None) -> dict[str, Any]:
    fence = _PYTHON_FENCE_RE.search(message)
    if fence:
        return {"code": fence.group(1).strip()}
    code = _PYTHON_PREFIX_RE.sub("", message).strip().strip("`").strip()
    return {"code": code}


def _git_args(message: str, _m: re.Match[str] | None) -> dict[str, Any]:
    low = message.lower()
    if re.search(r"\b(log|commits?|history)\b", low):
        action = "log"
    elif "diff" in low or "uncommitted" in low or "working tree" in low:
        action = "diff"
    elif "branch" in low:
        action = "branches"
    elif "show" in low:
        action = "show"
    else:
        action = "status"
    repo = "."
    match = _GIT_DIR_RE.search(message)
    if match:
        repo = next((g for g in match.groups() if g), ".")
    return {"action": action, "repo": repo}


def _sql_args(message: str, _m: re.Match[str] | None) -> dict[str, Any]:
    source = None
    src = _SQL_SOURCE_RE.search(message)
    if src:
        source = next((g for g in src.groups() if g), None)
    fence = _SQL_FENCE_RE.search(message)
    if fence:
        return {"sql": fence.group(1).strip(), "source": source}
    body = _SQL_PREFIX_RE.sub("", message).strip().strip("`").strip()
    # If the message *is* a bare SELECT/WITH, keep it as-is.
    if re.match(r"^\s*(?:select|with)\b", message, re.IGNORECASE):
        body = message.strip()
    # Drop a trailing "on/from/in <source.db>" mention so it doesn't pollute the SQL.
    if source:
        body = re.sub(
            r"\b(?:on|from|in|against|using)\s+['\"]?[\w./\-]+\.(?:db|sqlite3?|s3db)['\"]?\s*$",
            "",
            body,
            flags=re.IGNORECASE,
        ).strip()
    return {"sql": body, "source": source}


def _ocr_args(message: str, _m: re.Match[str] | None) -> dict[str, Any]:
    match = _IMAGE_RE.search(message)
    path = None
    if match:
        path = next((g for g in match.groups() if g), None)
    return {"path": path}


def _mail_args(message: str, _m: re.Match[str] | None) -> dict[str, Any]:
    folder = None
    fmatch = _MAIL_FOLDER_RE.search(message)
    if fmatch:
        folder = fmatch.group(1).strip()
    query = ""
    qmatch = _MAIL_QUERY_RE.search(message)
    if qmatch:
        query = next((g for g in qmatch.groups() if g), "") or ""
        # Trim a trailing "in <folder>" that leaked into the query tail.
        query = re.sub(r"\s+in\s+(?:the\s+)?(?:folder\s+)?\S+\s*$", "", query).strip()
        query = query.rstrip("?.! ").strip().strip("\"'").strip()
    return {"query": query, "folder": folder}


def _browse_args(message: str, _m: re.Match[str] | None) -> dict[str, Any]:
    match = _URL_RE.search(message)
    url = match.group(0).rstrip(".,);") if match else None
    action = "screenshot" if re.search(
        r"\bscreenshot|screen[- ]?grab\b", message, re.IGNORECASE
    ) else "open"
    return {"url": url, "action": action}


def _research_args(message: str, _m: re.Match[str] | None) -> dict[str, Any]:
    objective = _RESEARCH_PREFIX_RE.sub("", message).strip(" :,-").strip()
    return {"objective": objective or message.strip()}


_TEMPLATE_ALIASES = {
    "paper trading": "paper_trading",
    "paper-trading": "paper_trading",
    "paper_trading": "paper_trading",
    "research": "research",
    "job hunting": "job_hunting",
    "job search": "job_hunting",
    "job_hunting": "job_hunting",
    "repository learning": "repository_learning",
    "repo learning": "repository_learning",
    "repository_learning": "repository_learning",
    "owner knowledge": "owner_knowledge",
    "technology watch": "technology_watch",
    "security monitoring": "security_monitoring",
    "self improvement": "self_improvement",
    "hello watcher": "hello_watcher",
    "hello": "hello_watcher",
}


def _instantiate_mission_args(message: str, _m: re.Match[str] | None) -> dict[str, Any]:
    """Extract template + common paper-trading overrides from natural language."""
    text = message.strip()
    low = text.lower()
    template = "paper_trading"
    for alias, name in sorted(_TEMPLATE_ALIASES.items(), key=lambda kv: -len(kv[0])):
        if alias in low:
            template = name
            break

    overrides: dict[str, Any] = {}
    cash = re.search(
        r"(?:\$|₹|rs\.?\s*)?\s*(\d[\d,]*(?:\.\d+)?)\s*(?:k|thousand)?\s*"
        r"(?:(?:starting|virtual|paper)?\s*(?:cash|capital|budget|dollars?))?"
        r"|(?:starting|with|assume)\s+(?:\$|₹)?\s*(\d[\d,]*(?:\.\d+)?)",
        low,
        re.IGNORECASE,
    )
    if cash:
        raw = (cash.group(1) or cash.group(2) or "").replace(",", "")
        try:
            val = float(raw)
            if "k" in (cash.group(0) or "").lower() and val < 1000:
                val *= 1000
            if val > 0:
                overrides["starting_cash"] = val
        except ValueError:
            pass

    sym = re.search(
        r"\b(?:symbol|ticker|instrument|stock)\s*[:=]?\s*([A-Za-z][A-Za-z0-9.\-]{0,11})\b"
        r"|\bon\s+([A-Z]{1,6})\b",
        text,
    )
    symbol = None
    if sym:
        symbol = next((g for g in sym.groups() if g), None)
    if symbol:
        overrides["instruments"] = [{"symbol": symbol.upper(), "asset": ""}]
        overrides["_auto_sample_feed"] = True

    if template == "paper_trading" and "_auto_sample_feed" not in overrides:
        overrides["_auto_sample_feed"] = True
        overrides.setdefault("instruments", [{"symbol": "DEMO", "asset": ""}])

    return {
        "template": template,
        "title": None,
        "objective": text[:300],
        "config_overrides": overrides,
        "activate": True,
    }


def _register_market_data_args(message: str, _m: re.Match[str] | None) -> dict[str, Any]:
    text = message.strip()
    sym = re.search(
        r"\b(?:symbol|ticker)\s*[:=]?\s*([A-Za-z][A-Za-z0-9.\-]{0,11})\b",
        text,
        re.IGNORECASE,
    )
    if not sym:
        sym = re.search(r"\bfor\s+([A-Z]{1,6})\b", text)
    symbol = (sym.group(1) if sym else "DEMO").upper()
    if symbol in {"SYMBOL", "TICKER", "FOR", "NAME", "ASSET", "SAMPLE", "FEED"}:
        sym2 = re.search(r"\b([A-Z]{2,6})\b", text)
        symbol = (sym2.group(1) if sym2 else "DEMO")
    name_m = re.search(r"\b(?:name|asset)\s*[:=]?\s*([A-Za-z0-9_\-]+)\b", text, re.IGNORECASE)
    name = name_m.group(1) if name_m else f"{symbol.lower()}-feed"
    if name.lower() in {"symbol", "ticker", "name", "asset"}:
        name = f"{symbol.lower()}-feed"
    return {
        "name": name,
        "symbol": symbol,
        "generate_sample": True,
    }


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
        Intent.INSTANTIATE_MISSION,
        "templates",
        re.compile(
            r"\b(start|create|instantiate|spin\s*up|launch|set\s*up)\b.{0,40}"
            r"\b(mission|paper\s*trad(?:e|ing)|job\s*hunt(?:ing)?|research\s*watcher|"
            r"repo(?:sitory)?\s*learn(?:ing)?|hello\s*watcher)\b"
            r"|\bpaper\s*trad(?:e|ing)\b.{0,40}\b(mission|with|\$|\d)",
            re.IGNORECASE,
        ),
        _instantiate_mission_args,
    ),
    (
        Intent.REGISTER_MARKET_DATA,
        "assets",
        re.compile(
            r"\b(register|upload|add|create)\b.{0,40}"
            r"\b(market\s*data|ohlcv|price\s*feed|trading\s*feed)\b"
            r"|\b(sample|fixture|demo)\b.{0,20}\b(market\s*data|ohlcv|feed)\b",
            re.IGNORECASE,
        ),
        _register_market_data_args,
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
        Intent.GIT_STATUS,
        CAP_GIT,
        _GIT_RE,
        _git_args,
    ),
    (
        Intent.SQL_QUERY,
        CAP_SQL,
        _SQL_RE,
        _sql_args,
    ),
    (
        Intent.OCR_IMAGE,
        CAP_OCR,
        _OCR_RE,
        _ocr_args,
    ),
    (
        Intent.MAIL_SEARCH,
        CAP_MAIL,
        _MAIL_RE,
        _mail_args,
    ),
    (
        Intent.YOUTUBE_TRANSCRIPT,
        CAP_TRANSCRIPT,
        _YOUTUBE_TRANSCRIPT_RE,
        _youtube_args,
    ),
    (
        Intent.MEDIA_LEARN,
        CAP_MEDIA_LEARN,
        _MEDIA_LEARN_RE,
        _media_learn_args,
    ),
    (
        Intent.RESEARCH,
        CAP_RESEARCH,
        _RESEARCH_RE,
        _research_args,
    ),
    (
        Intent.BROWSE_URL,
        CAP_BROWSER,
        _BROWSE_RE,
        _browse_args,
    ),
    (
        Intent.WEB_FETCH,
        CAP_WEB,
        _URL_RE,
        _url_args,
    ),
    (
        Intent.SCHOLAR_SEARCH,
        CAP_SCHOLAR,
        _SCHOLAR_RE,
        _scholar_args,
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
    Intent.SCHOLAR_SEARCH: "Search academic sources (arXiv, Semantic Scholar).",
    Intent.YOUTUBE_TRANSCRIPT: "Fetch a YouTube video transcript.",
    Intent.MEDIA_LEARN: "Learn from media.",
    Intent.RUN_PYTHON: "Run Python code in the sandbox.",
    Intent.GIT_STATUS: "Inspect a local git repository (read-only).",
    Intent.SQL_QUERY: "Run a read-only SQL query on a local database.",
    Intent.OCR_IMAGE: "Extract text from an image via OCR.",
    Intent.MAIL_SEARCH: "Search a mailbox (read-only) for messages.",
    Intent.BROWSE_URL: "Render a URL in a headless browser (read-only).",
    Intent.RESEARCH: "Run an autonomous gather→verify→decide research loop.",
    Intent.LIST_DOCUMENTS: "List known documents.",
    Intent.INGEST_PATH: "Ingest a file into the knowledge base.",
    Intent.ASK_KNOWLEDGE: "Answer from the knowledge base (RAG).",
    Intent.ANSWER: "Answer the question directly (fast, single model call).",
    Intent.REACT: "Reason and use tools to answer (ReAct).",
    Intent.INSTANTIATE_MISSION: "Instantiate a mission from a template (with config overrides).",
    Intent.REGISTER_MARKET_DATA: "Register a market_data OHLCV feed asset (fixture/sample).",
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

        # Fallback (RC/D3.12): a general question gets a fast single-call answer;
        # only messages that plainly need current data or a tool escalate to ReAct,
        # so simple chat stays responsive instead of running the full agent loop.
        if _ESCALATE_RE.search(text):
            return Plan(
                message=text,
                steps=[self._step(Intent.REACT, CAP_AGENT, {"query": text})],
            )
        return Plan(
            message=text,
            steps=[self._step(Intent.ANSWER, CAP_LLM, {"query": text})],
        )

    @staticmethod
    def _step(intent: str, capability: str, args: dict[str, Any]) -> PlanStep:
        return PlanStep(
            intent=intent,
            capability=capability,
            args=args,
            description=_DESCRIPTIONS.get(intent, ""),
        )
