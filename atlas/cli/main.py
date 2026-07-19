"""Unified ``atlas`` command-line interface (ADR-0047).

Single entry point with subcommands, built on stdlib ``argparse`` (zero new deps,
consistent with ``atlas-db``). Commands call the kernel's services in-process via
the DI container, so they work without a running API server:

    atlas serve                 # run the REST API + web console at /ui (uvicorn)
    atlas status                # bootstrap, health-check, print, exit
    atlas doctor [--offline]    # preflight: validate config + probe deps (no workers)
    atlas chat ["message"]      # chat with the assistant (REPL if no message)
    atlas jobs                  # list jobs
    atlas job start "objective" # create + run an async job (Job Engine)
    atlas job show <id>         # show a job's steps and progress
    atlas job resume <id>       # re-run a job's blocked steps
    atlas job cancel <id>       # cancel a job
    atlas formats               # list document formats the reader supports
    atlas websearch "query"     # search the web (SearchCapability)
    atlas download <url>        # download a URL to the downloads dir
    atlas scholar "query"       # search academic sources (arXiv/Semantic Scholar, S18a)
    atlas youtube <url|id>      # fetch a YouTube transcript (S18a)
    atlas code map ./repo       # map a repo (langs/deps/frameworks/entry points)
    atlas code parse ./f.py     # parse one file into symbols/imports/calls
    atlas code symbols ./repo -q Foo   # search code symbols
    atlas code graph ./repo     # import + cross-file call graph
    atlas code patterns ./repo  # mine recurring engineering patterns
    atlas python "print(2+2)"   # run Python in the sandbox (S16)
    atlas verify graph.json     # verify claims (Verification Engine, S15)
    atlas report graph.json     # scientific-review report from claims (S17)
    atlas jobs --blocked        # list job steps awaiting you (HITL queue, R3)
    atlas agents                # list registered agents
    atlas ask "question"        # ask an agent (default: rag)
    atlas search "query"        # semantic search over the knowledge base
    atlas ingest ./file.md      # ingest a file into the knowledge base
    atlas remember "fact"       # store a memory (working/episodic/semantic)
    atlas recall "query"        # semantic recall from memory
    atlas forget <id>           # delete a memory by id
    atlas plugins               # list loaded plugins
    atlas tools                 # list available tools
    atlas capabilities          # list capabilities (provided + missing, R2)
    atlas tool web.fetch --arg url=https://example.com   # invoke a tool
    atlas backup                # run an on-demand database backup (pg_dump)

One-shot commands (agents/ask/search/ingest) resolve services from the container
without starting the full lifecycle, so they don't spin up worker threads.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from atlas.kernel import build_application

if TYPE_CHECKING:
    from atlas.kernel.application import Application


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="atlas", description="Atlas — a personal AI Operating System"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="run the REST API server")
    p_serve.add_argument("--host", default=None, help="bind host (default: config)")
    p_serve.add_argument("--port", type=int, default=None, help="bind port")

    sub.add_parser("status", help="bootstrap, run health checks, print status, exit")

    p_doctor = sub.add_parser(
        "doctor", help="preflight: validate config + probe dependencies (no workers)"
    )
    p_doctor.add_argument(
        "--offline", action="store_true",
        help="config checks only; skip database/LLM probes",
    )

    p_chat = sub.add_parser(
        "chat", help="chat with the assistant (interactive REPL or one-shot)"
    )
    p_chat.add_argument(
        "message", nargs="?", default=None, help="one-shot message; omit for a REPL"
    )
    p_chat.add_argument("--session", default=None, help="session id to continue")

    sub.add_parser("agents", help="list registered agents")

    p_ask = sub.add_parser("ask", help="ask an agent a question")
    p_ask.add_argument("query")
    p_ask.add_argument("--agent", default="rag", help="agent name (default: rag)")
    p_ask.add_argument("--k", type=int, default=None, help="chunks to retrieve")

    p_search = sub.add_parser("search", help="semantic search over the knowledge base")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=5)

    p_ingest = sub.add_parser("ingest", help="ingest a file into the knowledge base")
    p_ingest.add_argument("path", help="path to a .txt/.md/.pdf/.html file")

    p_remember = sub.add_parser("remember", help="store a memory")
    p_remember.add_argument("content")
    p_remember.add_argument(
        "--kind",
        default="semantic",
        choices=["working", "episodic", "semantic"],
        help="memory kind (default: semantic)",
    )
    p_remember.add_argument("--scope", default="global", help="scope (default: global)")
    p_remember.add_argument("--importance", type=float, default=0.0)
    p_remember.add_argument(
        "--ttl", type=int, default=None, help="expire after N seconds"
    )

    p_recall = sub.add_parser("recall", help="semantic recall from memory")
    p_recall.add_argument("query")
    p_recall.add_argument("--limit", type=int, default=5)
    p_recall.add_argument(
        "--kind", default=None, choices=["working", "episodic", "semantic"]
    )
    p_recall.add_argument("--scope", default=None)

    p_forget = sub.add_parser("forget", help="delete a memory by id")
    p_forget.add_argument("id")

    sub.add_parser("plugins", help="list loaded plugins")
    sub.add_parser("tools", help="list available tools")
    sub.add_parser(
        "capabilities", help="list capabilities (provided + missing, honest per R2)"
    )

    p_tool = sub.add_parser("tool", help="invoke a tool by name")
    p_tool.add_argument("name")
    p_tool.add_argument(
        "--arg",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="tool argument as KEY=VALUE (repeatable)",
    )

    p_jobs = sub.add_parser("jobs", help="list jobs")
    p_jobs.add_argument("--status", default=None, help="filter by status")
    p_jobs.add_argument("--limit", type=int, default=50)
    p_jobs.add_argument(
        "--blocked", action="store_true", help="list blocked steps awaiting you (HITL)"
    )

    p_job = sub.add_parser("job", help="manage a job (start/show/resume/cancel)")
    p_job.add_argument(
        "action", choices=["start", "show", "resume", "cancel"], help="what to do"
    )
    p_job.add_argument(
        "target", help="objective (for start) or job id (show/resume/cancel)"
    )
    p_job.add_argument("--session", default=None, help="session id to link (start)")

    sub.add_parser("formats", help="list document formats the reader can extract")

    p_ws = sub.add_parser("websearch", help="search the web (SearchCapability)")
    p_ws.add_argument("query", help="search query")
    p_ws.add_argument("--limit", type=int, default=5, help="max results")

    p_dl = sub.add_parser("download", help="download a URL to the downloads dir")
    p_dl.add_argument("url", help="absolute http(s) URL")
    p_dl.add_argument("--filename", default=None, help="output filename (sanitised)")

    p_sch = sub.add_parser("scholar", help="search academic sources (arXiv, Semantic Scholar)")
    p_sch.add_argument("query", help="search query")
    p_sch.add_argument("--limit", type=int, default=5, help="max papers")

    p_yt = sub.add_parser("youtube", help="fetch a YouTube video transcript")
    p_yt.add_argument("video", help="YouTube URL or 11-char video id")
    p_yt.add_argument("--full", action="store_true", help="print the full transcript text")

    p_code = sub.add_parser("code", help="code understanding (CodeCapability)")
    p_code.add_argument(
        "action",
        choices=["parse", "map", "symbols", "graph", "patterns", "explain"],
    )
    p_code.add_argument("target", help="file path (parse/explain) or repo root")
    p_code.add_argument("-q", "--query", default="", help="symbol name filter")
    p_code.add_argument("--kind", default=None, help="symbol kind filter")
    p_code.add_argument("--lang", default=None, help="language filter")
    p_code.add_argument("--question", default=None, help="question for `explain`")

    p_py = sub.add_parser("python", help="run Python in the sandbox (S16)")
    p_py.add_argument("code", nargs="?", default=None, help="Python source to run")
    p_py.add_argument("-f", "--file", default=None, help="run a .py file instead")
    p_py.add_argument("--timeout", type=float, default=None, help="wall-clock seconds")

    p_git = sub.add_parser("git", help="read-only local git inspection (S20a)")
    p_git.add_argument(
        "action",
        choices=["status", "log", "diff", "show", "branches", "file_history"],
    )
    p_git.add_argument("repo", nargs="?", default=".", help="repository path")
    p_git.add_argument("--ref", default=None, help="commit/range (diff/show)")
    p_git.add_argument("--path", default=None, help="file path (file_history)")
    p_git.add_argument("--max", type=int, default=None, dest="max_count",
                       help="max commits (log/file_history)")

    p_sql = sub.add_parser("sql", help="read-only SQL over a local database (S20b)")
    p_sql.add_argument("action", choices=["query", "tables", "schema"])
    p_sql.add_argument("target", nargs="?", default=None,
                       help="SQL text (query) or table name (schema)")
    p_sql.add_argument("--source", default=None, help="db file under the sandbox root")
    p_sql.add_argument("--limit", type=int, default=None, help="max rows (query)")

    p_ocr = sub.add_parser("ocr", help="extract text from an image via OCR (S20c)")
    p_ocr.add_argument("path", help="image path under the OCR sandbox root")
    p_ocr.add_argument("--lang", default=None, help="tesseract language (default eng)")

    p_mail = sub.add_parser("mail", help="read-only email over IMAP (S20d)")
    p_mail.add_argument("action", choices=["search", "folders", "message"])
    p_mail.add_argument("target", nargs="?", default=None,
                        help="search query, or message uid (message)")
    p_mail.add_argument("--folder", default=None, help="mailbox/folder (default INBOX)")
    p_mail.add_argument("--limit", type=int, default=None, help="max messages (search)")

    p_browser = sub.add_parser("browser", help="headless browser render (S20e)")
    p_browser.add_argument("url", help="http(s) URL to render")
    p_browser.add_argument("--screenshot", default=None,
                           help="save a PNG to this path under the sandbox root")

    p_research = sub.add_parser("research", help="autonomous research loop (S21)")
    p_research.add_argument("objective", help="the research question or topic")
    p_research.add_argument("--max-iterations", type=int, default=None,
                            help="cap on search rounds")

    p_report = sub.add_parser(
        "report", help="generate a scientific-review report from a JSON evidence graph"
    )
    p_report.add_argument(
        "path", help="JSON file: {objective, claims:[...], sources?, budget?, notes?}"
    )

    p_verify = sub.add_parser(
        "verify", help="verify claims from a JSON evidence graph (Verification Engine)"
    )
    p_verify.add_argument(
        "path", help="path to a JSON file: {claims: [...], sources?: [...], budget?: {...}}"
    )

    p_learn = sub.add_parser(
        "learn", help="continuous learning: review/apply/revert/recall (S18b)"
    )
    p_learn.add_argument(
        "action",
        choices=[
            "events", "show", "apply", "revert", "experiences", "recall",
            "advice", "sources", "components", "bias",
        ],
        help="events|show|apply|revert|experiences|recall|advice|sources|components|bias",
    )
    p_learn.add_argument("target", nargs="?", help="event/experience id, or a recall query")
    p_learn.add_argument("--status", help="filter events by status")
    p_learn.add_argument("--store", help="filter events by store")
    p_learn.add_argument("--policy", help="policy when applying (temporary|project|personal|verified)")
    p_learn.add_argument("--level", type=int, help="Learning Level (1-5) when applying")
    p_learn.add_argument("--limit", type=int, default=20)
    p_learn.add_argument(
        "--disable",
        action="store_true",
        help="for bias action: disable soft bias (default is enable)",
    )

    p_intel = sub.add_parser(
        "intel", help="engineering intelligence: learn repos, generalize, recommend (S19)"
    )
    p_intel.add_argument(
        "action",
        choices=["learn", "repos", "search", "connections", "generalize",
                 "patterns", "recommend", "profile"],
        help="learn <path>|repos|search <q>|connections|generalize|patterns|"
             "recommend [context]|profile",
    )
    p_intel.add_argument("target", nargs="?", help="repo path, query, or context")
    p_intel.add_argument("--policy", help="policy for learned repo (default: project)")
    p_intel.add_argument("--limit", type=int, default=20)

    sub.add_parser(
        "coverage",
        help="knowledge coverage map: per-domain coverage %% + understanding %% (C.4)",
    )

    p_policy = sub.add_parser(
        "policy", help="operator policy rules that influence retrieval/advice (C.5)"
    )
    p_policy.add_argument(
        "action",
        choices=["set", "list", "show", "enable", "disable", "revert", "events"],
        help="set <subject>|list|show <id>|enable <id>|disable <id>|revert <event_id>|events [id]",
    )
    p_policy.add_argument("target", nargs="?", help="subject (set) | rule/event id")
    p_policy.add_argument(
        "--rule", choices=["prefer", "avoid", "trust", "distrust"], default="prefer"
    )
    p_policy.add_argument("--scope", default="global")
    p_policy.add_argument("--strength", type=float, default=1.0)
    p_policy.add_argument("--by", help="created_by (provenance)")
    p_policy.add_argument("--limit", type=int, default=50)

    sub.add_parser("backup", help="run an on-demand database backup (pg_dump)")

    return parser


# --- command handlers (app injectable for testing) -----------------------
def cmd_serve(args: argparse.Namespace, app: "Application | None" = None) -> int:
    from atlas.api import serve

    serve(host=args.host, port=args.port)
    return 0


_STATUS_FLAG = {"ok": "OK", "degraded": "WARN", "failed": "FAIL"}


def cmd_status(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    app.start()
    try:
        report = app.health()
        for name, status in report.items():
            flag = _STATUS_FLAG.get(status.level, "OK")
            print(f"  [{flag:4}] {name}: {status.detail}")
        summary = app.status()
        counts = summary["severity_counts"]
        print(
            f"\nAtlas {summary['version']} — "
            f"{counts['ok']} ok, {counts['degraded']} degraded, "
            f"{counts['failed']} failed "
            f"(uptime {summary['uptime_seconds']}s)"
        )
        return 0 if app.healthy() else 1
    finally:
        app.stop()


_DOCTOR_FLAG = {"ok": "OK", "warn": "WARN", "fail": "FAIL"}


def cmd_doctor(args: argparse.Namespace, app: "Application | None" = None) -> int:
    from atlas.config import get_config
    from atlas.kernel.preflight import CHECK_FAIL, check_config, probe_dependencies, worst_status

    cfg = get_config()
    checks = check_config(cfg)
    if not args.offline:
        try:
            app = app or build_application()
            checks.extend(probe_dependencies(app))
        except Exception as exc:  # noqa: BLE001 - report, don't crash the doctor
            print(f"  [FAIL] bootstrap: could not build application: {exc}",
                  file=sys.stderr)
            return 1
    for check in checks:
        flag = _DOCTOR_FLAG.get(check.status, "OK")
        print(f"  [{flag:4}] {check.name}: {check.detail}")
    overall = worst_status(checks)
    print(f"\npreflight: {overall.upper()}"
          + (" (offline — dependencies not probed)" if args.offline else ""))
    return 1 if overall == CHECK_FAIL else 0


def cmd_chat(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    assistant = app.container.resolve("chat")

    if args.message:
        turn = assistant.chat(args.message, session_id=args.session)
        print(turn.answer)
        return 0

    print("Atlas chat — type 'exit' or press Ctrl-D to quit.")
    session_id = args.session
    while True:
        try:
            line = input("you> ").strip()
        except EOFError:
            print()
            break
        if not line:
            continue
        if line.lower() in {"exit", "quit", ":q"}:
            break
        turn = assistant.chat(line, session_id=session_id)
        session_id = turn.session_id
        print(f"atlas> {turn.answer}")
    return 0


def cmd_agents(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    agent_service = app.container.resolve("agent")
    names = agent_service.list()
    if not names:
        print("(no agents registered)")
    for name in names:
        print(name)
    return 0


def cmd_ask(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    agent_service = app.container.resolve("agent")
    options = {}
    if args.k is not None:
        options["k"] = args.k
    result = agent_service.run(args.agent, args.query, **options)
    print(result.answer)
    return 0


def cmd_search(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    knowledge = app.container.resolve("knowledge")
    results = knowledge.search(args.query, limit=args.limit)
    if not results:
        print("(no results)")
    for r in results:
        preview = " ".join(r.content.split())[:100]
        print(f"[{r.similarity:.3f}] {r.document_id} #{r.ordinal}: {preview}")
    return 0


def cmd_ingest(args: argparse.Namespace, app: "Application | None" = None) -> int:
    from atlas.ingestion.extractors import content_type_for, extract

    path = Path(args.path)
    if not path.is_file():
        print(f"error: not a file: {path}", file=sys.stderr)
        return 1
    text = extract(path)
    if not text:
        print(f"error: no extractable text in {path}", file=sys.stderr)
        return 1
    app = app or build_application()
    knowledge = app.container.resolve("knowledge")
    summary = knowledge.ingest_text(
        "cli",
        text,
        title=path.name,
        uri=str(path.resolve()),
        content_type=content_type_for(path),
        embed=True,
    )
    print(
        f"ingested {path.name}: document={summary['document_id']} "
        f"status={summary['status']} chunks={summary['chunks']} "
        f"deduped={summary['deduped']}"
    )
    return 0


def cmd_remember(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    memory = app.container.resolve("memory")
    item = memory.remember(
        args.content,
        kind=args.kind,
        scope=args.scope,
        importance=args.importance,
        ttl_seconds=args.ttl,
    )
    print(f"remembered {item.kind} memory {item.id} (scope={item.scope})")
    return 0


def cmd_recall(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    memory = app.container.resolve("memory")
    results = memory.recall(
        args.query, limit=args.limit, kind=args.kind, scope=args.scope
    )
    if not results:
        print("(no memories)")
    for r in results:
        preview = " ".join(r.content.split())[:100]
        sim = f"{r.similarity:.3f}" if r.similarity is not None else "  -  "
        print(f"[{sim}] {r.kind} {r.id}: {preview}")
    return 0


def cmd_forget(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    memory = app.container.resolve("memory")
    ok = memory.forget(args.id)
    print("forgotten" if ok else "(not found)")
    return 0 if ok else 1


def cmd_plugins(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    manager = app.container.resolve("plugins")
    infos = manager.describe()
    if not infos:
        print("(no plugins loaded)")
    for info in infos:
        print(f"{info['name']} {info['version']}")
    return 0


def cmd_tools(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    tools = app.tools.describe()
    if not tools:
        print("(no tools registered)")
    for tool in tools:
        print(f"{tool['name']}: {tool['description']}")
    return 0


def cmd_capabilities(args: argparse.Namespace, app: "Application | None" = None) -> int:
    from atlas.capabilities import describe_capabilities

    app = app or build_application()
    rows = describe_capabilities(app.capabilities)
    for row in rows:
        flag = "ok " if row["provided"] else "-- "
        contract = row.get("contract") or ""
        suffix = f" [{contract}]" if contract else ""
        print(f"  [{flag}] {row['id']}{suffix}: {row['summary']}")
        if not row["provided"] and row.get("unlocks"):
            print(f"          unlocks: {row['unlocks']} (since {row.get('since')})")
    return 0


def cmd_tool(args: argparse.Namespace, app: "Application | None" = None) -> int:
    import json

    kwargs = {}
    for pair in args.arg:
        if "=" not in pair:
            print(f"error: --arg must be KEY=VALUE, got {pair!r}", file=sys.stderr)
            return 1
        key, value = pair.split("=", 1)
        kwargs[key] = value
    app = app or build_application()
    result = app.invoke_tool(args.name, **kwargs)
    if isinstance(result, (dict, list)):
        print(json.dumps(result, indent=2, default=str))
    else:
        print(result)
    return 0


def _print_job_detail(detail) -> None:
    job = detail["job"]
    prog = detail["progress"]
    print(f"job {job.id} [{job.status}] — {job.objective}")
    print(
        f"  progress: {prog.get('done', 0)}/{prog.get('total', 0)} done, "
        f"{prog.get('blocked', 0)} blocked, {prog.get('failed', 0)} failed"
    )
    for step in detail["steps"]:
        line = f"  #{step.ordinal} [{step.status}] {step.intent} ({step.capability})"
        if step.blocked_reason:
            line += f" — needs: {step.blocked_reason}"
        print(line)


def cmd_jobs(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    jobs = app.container.resolve("jobs")
    if getattr(args, "blocked", False):
        blocked = jobs.list_blocked(limit=args.limit)
        if not blocked:
            print("(nothing blocked — no jobs are waiting on you)")
        for b in blocked:
            print(f"{b['job_id']} step {b['ordinal']} [{b['capability']}] "
                  f"needs: {b['needs']}  — {b['objective']}")
        return 0
    rows = jobs.list_jobs(status=args.status, limit=args.limit)
    if not rows:
        print("(no jobs)")
    for job in rows:
        print(f"{job.id} [{job.status}] {job.objective}")
    return 0


def cmd_job(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    jobs = app.container.resolve("jobs")
    if args.action == "start":
        detail = jobs.create_job(args.target, session_id=args.session)
        print(f"started job {detail['job'].id}")
        _print_job_detail(detail)
        return 0
    try:
        if args.action == "show":
            detail = jobs.job_detail(args.target)
        elif args.action == "resume":
            detail = jobs.resume_job(args.target)
        else:  # cancel
            detail = jobs.cancel_job(args.target)
    except KeyError:
        print(f"error: no job {args.target}", file=sys.stderr)
        return 1
    _print_job_detail(detail)
    return 0


def cmd_formats(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    documents = app.container.resolve("documents")
    print("document formats: " + ", ".join(documents.supported()))
    return 0


def cmd_websearch(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    result = app.invoke_tool("web.search", query=args.query, max_results=args.limit)
    outcome = result.get("outcome")
    if outcome != "ok":
        print(
            f"search {outcome}: {result.get('reason') or 'no results'}",
            file=sys.stderr,
        )
        return 1
    results = result.get("results", [])
    if not results:
        print(f"no results for {args.query!r}")
        return 0
    for i, hit in enumerate(results, start=1):
        print(f"{i}. {hit.get('title') or hit.get('url')}")
        print(f"   {hit.get('url')}")
        if hit.get("snippet"):
            print(f"   {hit['snippet']}")
    return 0


def cmd_download(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    result = app.invoke_tool("web.download", url=args.url, filename=args.filename)
    print(f"downloaded {result['bytes']} bytes -> {result['path']}")
    return 0


def cmd_scholar(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    result = app.invoke_tool("scholar.search", query=args.query, max_results=args.limit)
    outcome = result.get("outcome")
    if outcome != "ok":
        print(f"scholar {outcome}: {result.get('reason') or 'no results'}", file=sys.stderr)
        return 1
    papers = result.get("results", [])
    if not papers:
        print(f"no papers for {args.query!r}")
        return 0
    for i, p in enumerate(papers, start=1):
        authors = ", ".join(p.get("authors", [])[:3])
        meta = " · ".join(
            b for b in (authors, str(p.get("year") or ""), p.get("venue") or "",
                        p.get("level_name") or "") if b
        )
        print(f"{i}. {p.get('title')} ({meta})")
        if p.get("url"):
            print(f"   {p['url']}")
    return 0


def cmd_youtube(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    result = app.invoke_tool("youtube.transcript", video=args.video)
    outcome = result.get("outcome")
    if outcome != "ok":
        print(f"transcript {outcome}: {result.get('reason') or 'unavailable'}", file=sys.stderr)
        return 1
    title = result.get("title") or result.get("video_id")
    text = result.get("text", "")
    print(f"# {title}  [{result.get('language')}]  ({len(text)} chars)")
    print(text if args.full else (text[:1000] + ("…" if len(text) > 1000 else "")))
    return 0


def cmd_code(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    code = app.container.resolve("code")
    action = args.action
    if action == "parse":
        fp = code.parse(args.target)
        print(f"{fp['path']} ({fp['lang']}, {fp['loc']} loc, outcome={fp['outcome']})")
        for sym in fp["symbols"]:
            indent = "  " if sym["parent"] else ""
            print(f"{indent}{sym['kind']} {sym['signature'] or sym['name']} "
                  f"(L{sym['start_line']}-{sym['end_line']})")
        return 0
    if action == "map":
        m = code.repo_map(args.target)
        print(f"root: {m['root']}")
        print(f"files: {m['file_count']}  loc: {m['total_loc']}")
        print(f"languages: {m['languages']}")
        print(f"frameworks: {', '.join(m['frameworks']) or '-'}")
        print(f"entry points: {', '.join(m['entry_points']) or '-'}")
        for mgr, deps in m["dependencies"].items():
            print(f"deps[{mgr}]: {', '.join(deps[:20])}")
        return 0
    if action == "symbols":
        hits = code.search_symbols(
            args.query, root=args.target, kind=args.kind, lang=args.lang
        )
        if not hits:
            print("no matching symbols")
            return 0
        for s in hits:
            print(f"{s['kind']:8} {s['qualname']:40} {s['file']}:{s['start_line']}")
        return 0
    if action == "graph":
        g = code.graph(args.target)
        print(f"import edges: {g['import_edge_count']} "
              f"(external imports: {g['external_imports']})")
        print(f"call edges: {g['call_edge_count']} "
              f"(unresolved: {g['unresolved_calls']})")
        for src, dst in g["import_edges"][:40]:
            print(f"  import {src} -> {dst}")
        for caller, callee in g["call_edges"][:40]:
            print(f"  call   {caller} -> {callee}")
        return 0
    if action == "patterns":
        pats = code.patterns(args.target)
        if not pats:
            print("no patterns detected")
            return 0
        for p in pats:
            print(f"[{p['confidence']:.2f}] {p['name']}: {p['description']}")
            for ev in p["evidence"]:
                print(f"        - {ev}")
        return 0
    if action == "explain":
        result = code.explain(args.target, args.question)
        print(result["outline"])
        if result["explanation"]:
            print("\n" + result["explanation"])
        return 0
    return 1


def cmd_python(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    sandbox = app.container.resolve("python")
    if args.file:
        result = sandbox.run_file(args.file, timeout=args.timeout)
    elif args.code:
        result = sandbox.run(args.code, timeout=args.timeout)
    else:
        print("provide code or --file")
        return 2
    print(
        f"outcome: {result['outcome']}  "
        f"({result['duration_ms']} ms, backend={result['backend']})"
    )
    stdout = result.get("stdout") or ""
    if stdout:
        print(stdout, end="" if stdout.endswith("\n") else "\n")
    if result["outcome"] != "ok":
        stderr = (result.get("stderr") or "").strip()
        if stderr:
            print(stderr)
        if result.get("error"):
            print(f"error: {result['error']}")
    if result.get("result") is not None:
        print(f"result: {result['result']}")
    return 0 if result["outcome"] == "ok" else 1


def cmd_git(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    action = args.action
    if action == "log":
        result = app.invoke_tool("git.log", repo=args.repo, max_count=args.max_count)
    elif action == "diff":
        result = app.invoke_tool("git.diff", repo=args.repo, ref=args.ref)
    elif action == "show":
        result = app.invoke_tool("git.show", repo=args.repo, ref=args.ref or "HEAD")
    elif action == "branches":
        result = app.invoke_tool("git.branches", repo=args.repo)
    elif action == "file_history":
        result = app.invoke_tool(
            "git.file_history", repo=args.repo, path=args.path or "",
            max_count=args.max_count,
        )
    else:
        result = app.invoke_tool("git.status", repo=args.repo)

    outcome = result.get("outcome")
    if outcome != "ok":
        print(f"git {action} {outcome}: {result.get('reason') or ''}", file=sys.stderr)
        return 1
    if action == "status":
        print(f"branch {result.get('branch')}  "
              f"ahead {result.get('ahead')} / behind {result.get('behind')}  "
              f"{'clean' if result.get('clean') else 'dirty'}")
        for ch in result.get("changes", []):
            print(f"  {ch['status']:>2} {ch['path']}")
    elif action in ("log", "file_history"):
        for c in result.get("commits", []):
            print(f"{c['short']} {c['date']} {c['author']} — {c['subject']}")
    elif action == "diff":
        print(f"{result.get('files_changed', 0)} file(s) changed")
        if result.get("stat"):
            print(result["stat"])
    elif action == "show":
        c = result.get("commit", {})
        print(f"{c.get('short')} {c.get('date')} {c.get('author')} — {c.get('subject')}")
        if result.get("stat"):
            print(result["stat"])
    elif action == "branches":
        for b in result.get("branches", []):
            print(("* " if b == result.get("current") else "  ") + b)
    return 0


def cmd_sql(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    action = args.action
    if action == "tables":
        result = app.invoke_tool("sql.tables", source=args.source)
    elif action == "schema":
        if not args.target:
            print("provide a table name", file=sys.stderr)
            return 2
        result = app.invoke_tool("sql.schema", table=args.target, source=args.source)
    else:
        if not args.target:
            print("provide a SQL query", file=sys.stderr)
            return 2
        result = app.invoke_tool(
            "sql.query", sql=args.target, source=args.source, limit=args.limit
        )

    outcome = result.get("outcome")
    if outcome in ("unavailable", "blocked", "error"):
        print(f"sql {action} {outcome}: {result.get('reason') or ''}", file=sys.stderr)
        return 1
    if action == "tables":
        for t in result.get("tables", []):
            print(t)
    elif action == "schema":
        for c in result.get("columns", []):
            pk = " PK" if c.get("pk") else ""
            null = "" if c.get("notnull") else " NULL"
            print(f"{c['name']} {c['type']}{null}{pk}")
    else:
        columns = result.get("columns", [])
        rows = result.get("rows", [])
        if columns:
            print(" | ".join(columns))
        for row in rows:
            print(" | ".join(str(row.get(c, "")) for c in columns))
        print(f"({result.get('row_count', len(rows))} row(s)"
              f"{', truncated' if result.get('truncated') else ''})")
    return 0


def cmd_ocr(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    result = app.invoke_tool("ocr.image", path=args.path, lang=args.lang)
    outcome = result.get("outcome")
    if outcome not in ("ok", "empty"):
        print(f"ocr {outcome}: {result.get('reason') or ''}", file=sys.stderr)
        return 1
    if outcome == "empty":
        print("(no readable text found)")
        return 0
    print(f"# {args.path}  [{result.get('lang')}, {result.get('chars')} chars]")
    print(result.get("text", ""))
    return 0


def cmd_mail(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    if args.action == "folders":
        result = app.invoke_tool("mail.folders")
    elif args.action == "message":
        if not args.target:
            print("mail message: a uid is required", file=sys.stderr)
            return 2
        result = app.invoke_tool("mail.message", uid=args.target, folder=args.folder)
    else:
        result = app.invoke_tool(
            "mail.search", query=args.target or "", folder=args.folder, limit=args.limit
        )
    outcome = result.get("outcome")
    if outcome not in ("ok", "empty"):
        print(f"mail {outcome}: {result.get('reason') or ''}", file=sys.stderr)
        return 1
    if args.action == "folders":
        for name in result.get("folders", []):
            print(name)
    elif args.action == "message":
        msg = result.get("message") or {}
        if not msg:
            print("(no such message)")
            return 0
        print(f"From:    {msg.get('from')}")
        print(f"To:      {msg.get('to')}")
        print(f"Date:    {msg.get('date')}")
        print(f"Subject: {msg.get('subject')}")
        print()
        print(msg.get("body", ""))
    else:
        messages = result.get("messages", [])
        if not messages:
            print("(no messages)")
            return 0
        for m in messages:
            print(f"[{m.get('uid')}] {m.get('subject') or '(no subject)'}"
                  f" — {m.get('from') or ''}  {m.get('date') or ''}")
    return 0


def cmd_browser(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    if args.screenshot:
        result = app.invoke_tool("browser.screenshot", url=args.url, path=args.screenshot)
    else:
        result = app.invoke_tool("browser.open", url=args.url)
    outcome = result.get("outcome")
    if outcome not in ("ok", "empty"):
        print(f"browser {outcome}: {result.get('reason') or ''}", file=sys.stderr)
        return 1
    if args.screenshot:
        print(f"saved screenshot: {result.get('path')}")
        return 0
    if outcome == "empty":
        print(f"(rendered {args.url} but found no text)")
        return 0
    print(f"# {result.get('title')} — {result.get('final_url')}"
          f"  [{result.get('chars')} chars]")
    print(result.get("text", ""))
    links = result.get("links", [])
    if links:
        print(f"\nLinks ({len(links)}):")
        for u in links[:20]:
            print(f"  - {u}")
    return 0


def cmd_research(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    result = app.invoke_tool(
        "research.run", objective=args.objective, max_iterations=args.max_iterations
    )
    outcome = result.get("outcome")
    if outcome not in ("ok",):
        print(f"research {outcome}: {result.get('reason') or ''}", file=sys.stderr)
        return 1
    claim = result.get("claim") or {}
    stopped = result.get("stopped") or {}
    print(f"# Research: {result.get('objective')}")
    print(f"confidence: {claim.get('confidence')} "
          f"(score {claim.get('confidence_score')}, "
          f"convergence {claim.get('convergence')})")
    print(f"rounds: {result.get('iterations')}; "
          f"stopped: {'; '.join(stopped.get('reasons', [])) or 'n/a'}")
    report = result.get("report") or {}
    if report.get("markdown"):
        print()
        print(report["markdown"])
    return 0


def cmd_report(args: argparse.Namespace, app: "Application | None" = None) -> int:
    import json
    from pathlib import Path

    data = json.loads(Path(args.path).read_text(encoding="utf-8"))
    app = app or build_application()
    reports = app.container.resolve("reports")
    result = reports.report(
        data.get("objective", ""),
        {"claims": data.get("claims", []), "sources": data.get("sources", [])},
        budget=data.get("budget"),
        notes=data.get("notes", ""),
    )
    print(result["report"]["markdown"])
    return 0


def cmd_verify(args: argparse.Namespace, app: "Application | None" = None) -> int:
    import json
    from pathlib import Path

    data = json.loads(Path(args.path).read_text(encoding="utf-8"))
    app = app or build_application()
    verification = app.container.resolve("verification")
    result = verification.verify(
        {"claims": data.get("claims", []), "sources": data.get("sources", [])},
        budget=data.get("budget"),
    )
    for claim in result["claims"]:
        conv = claim["convergence"]
        conv_str = f"{conv:.0%}" if conv is not None else "n/a"
        print(f"[{claim['confidence']}] {claim['statement']}")
        print(f"    convergence={conv_str}  score={claim['confidence_score']}  "
              f"support={len(claim['supporting_sources'])}  "
              f"contra={len(claim['contradicting_sources'])}")
        for step in claim["reasoning_trace"]:
            print(f"    · {step}")
        decision = claim["budget_decision"]
        print(f"    budget → {decision['decision']}: {'; '.join(decision['reasons'])}")
    return 0


def cmd_learn(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    learning = app.container.resolve("learning")
    action = args.action

    if action == "events":
        events = learning.list_events(
            status=args.status, store=args.store, limit=args.limit
        )
        if not events:
            print("no learning events")
            return 0
        for e in events:
            print(f"[{e['status']}] {e['id']}  {e['store']}/{e['level_name']}  "
                  f"({e['policy']})  {e['summary']}")
        return 0

    if action == "show":
        if not args.target:
            print("usage: atlas learn show <event_id>")
            return 2
        try:
            data = learning.explain(args.target)
        except KeyError:
            print("event not found")
            return 1
        print(data.get("explanation", ""))
        return 0

    if action == "apply":
        if not args.target:
            print("usage: atlas learn apply <event_id>")
            return 2
        try:
            result = learning.apply(args.target, policy=args.policy, level=args.level)
        except KeyError:
            print("event not found")
            return 1
        except ValueError as exc:
            print(str(exc))
            return 2
        print(f"applied: {result['event']['id']} → {result['event']['store']}")
        return 0

    if action == "revert":
        if not args.target:
            print("usage: atlas learn revert <event_id>")
            return 2
        try:
            learning.revert(args.target)
        except KeyError:
            print("event not found")
            return 1
        print(f"reverted: {args.target}")
        return 0

    if action == "experiences":
        for x in learning.list_experiences(limit=args.limit):
            print(f"{x['id']}  ({x['policy']})  {x['title'] or x['problem'][:80]}")
        return 0

    if action == "recall":
        query = args.target or ""
        for x in learning.recall(query, limit=args.limit):
            print(f"{x['id']}  {x['title'] or x['problem'][:80]}")
            if x.get("lessons"):
                print(f"    lessons: {x['lessons']}")
        return 0

    if action == "advice":
        query = args.target or ""
        data = learning.advice_for(query, limit=args.limit)
        print(f"advice ({data['count']} hit(s), mutating={data['mutating']}):")
        print(data.get("advice") or "(none)")
        return 0

    if action == "sources":
        data = learning.source_advice(limit=args.limit)
        print(
            f"source reliability advice ({data['count']} domain(s), "
            f"mutating={data['mutating']}):"
        )
        print(
            data.get("advice")
            or "(none yet — apply some research experiences first)"
        )
        return 0

    if action == "components":
        for o in learning.list_component_observations(
            component_key=args.target, limit=args.limit
        ):
            print(
                f"{o['component_key']}@{o['component_version']}  "
                f"job={o.get('source_job_id') or '-'}  metrics={o.get('metrics')}"
            )
        return 0

    if action == "bias":
        if not args.target:
            print("usage: atlas learn bias <experience_id> [--enable|--disable]")
            return 2
        try:
            result = learning.enable_bias(
                args.target, enabled=not bool(getattr(args, "disable", False))
            )
        except KeyError:
            print("experience not found")
            return 1
        except ValueError as exc:
            print(str(exc))
            return 1
        print(
            f"bias_enabled={result.get('bias_enabled')} for "
            f"{(result.get('experience') or {}).get('id', args.target)}"
        )
        return 0

    return 2


def cmd_intel(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    intel = app.container.resolve("intelligence")
    action = args.action

    if action == "learn":
        if not args.target:
            print("usage: atlas intel learn <repo_path>")
            return 2
        result = intel.learn_repository(args.target, policy=args.policy)
        if result.get("outcome") != "ok":
            print(f"error: {result.get('reason')}")
            return 1
        repo = result.get("repository") or {}
        print(f"learned {repo.get('name', args.target)}: "
              f"{repo.get('file_count', 0)} files, {repo.get('symbol_count', 0)} symbols")
        print(f"  {repo.get('summary', '')}")
        return 0

    if action == "repos":
        repos = intel.list_repositories(limit=args.limit)
        if not repos:
            print("no repositories learned yet")
            return 0
        for r in repos:
            print(f"{r['id']}  {r['name']}  ({r['file_count']} files) "
                  f"{', '.join(r['frameworks'][:3])}")
        return 0

    if action == "search":
        out = intel.search(args.target or "", limit=args.limit)
        for r in out["repositories"]:
            print(f"{r['name']}  {', '.join(r['frameworks'][:3])}")
        for e in out["connections"]:
            print(f"  ~ {e['a']} <-> {e['b']}: {', '.join(e['shared_frameworks'] or e['shared_languages'])}")
        return 0

    if action == "connections":
        for e in intel.connections()["connections"]:
            print(f"{e['a']} <-> {e['b']}: {', '.join(e['shared_frameworks'] or e['shared_languages'])}")
        return 0

    if action == "generalize":
        out = intel.generalize()
        if out.get("outcome") != "ok":
            print(f"need at least {out.get('min_repos')} repos "
                  f"(have {out.get('total_repos')})")
            return 0
        for p in out["patterns"]:
            print(f"{p['prevalence']:.0%}  {p['name']} ({p['category']}) "
                  f"— {p['repo_count']}/{p['total_repos']}")
        return 0

    if action == "patterns":
        for p in intel.patterns(limit=args.limit):
            print(f"{p['prevalence']:.0%}  {p['name']} ({p['category']})")
        return 0

    if action == "recommend":
        out = intel.recommend(args.target or "", limit=args.limit)
        if not out["recommendations"]:
            print("no recommendations yet — learn and generalize some repos first")
            return 0
        for r in out["recommendations"]:
            print(f"- {r['recommendation']}")
        return 0

    if action == "profile":
        p = intel.profile()
        print(p["summary"])
        print(f"  repositories: {p['repositories']}")
        print(f"  languages: {', '.join(p['languages'])}")
        print(f"  frameworks: {', '.join(p['frameworks'])}")
        return 0

    return 2


def cmd_coverage(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    summary = app.container.resolve("coverage").summary()
    domains = summary.get("domains") or []
    if not domains:
        print("no coverage recorded yet — ingest documents or learn a repository first")
        return 0
    overall = summary.get("overall") or {}
    print(f"{'domain':<16} {'coverage':>10} {'understanding':>14}")
    for d in domains:
        print(f"{d['domain']:<16} {d['coverage_pct']:>9.1f}% {d['understanding_pct']:>13.1f}%")
    print(f"{'overall':<16} {overall.get('coverage_pct', 0.0):>9.1f}% "
          f"{overall.get('understanding_pct', 0.0):>13.1f}%")
    return 0


def cmd_policy(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    policy = app.container.resolve("policy")
    action = args.action

    if action == "set":
        if not args.target:
            print("usage: atlas policy set <subject> --rule prefer|avoid|trust|distrust")
            return 2
        row = policy.create_rule(
            args.target, args.rule, scope=args.scope, strength=args.strength, created_by=args.by
        )
        print(f"{row['id']}  {row['rule']} '{row['subject']}' "
              f"(scope={row['scope']}, strength={row['strength']}, enabled={row['enabled']})")
        return 0

    if action == "list":
        rules = policy.list_rules(limit=args.limit)
        if not rules:
            print("no policy rules yet")
            return 0
        for r in rules:
            state = "on " if r["enabled"] else "off"
            print(f"{r['id']}  [{state}] {r['rule']:<8} '{r['subject']}' "
                  f"scope={r['scope']} strength={r['strength']}")
        return 0

    if action == "show":
        if not args.target:
            print("usage: atlas policy show <rule_id>")
            return 2
        r = policy.get_rule(args.target)
        if r is None:
            print("policy rule not found")
            return 1
        for key, val in r.items():
            print(f"{key}: {val}")
        return 0

    if action in ("enable", "disable"):
        if not args.target:
            print(f"usage: atlas policy {action} <rule_id>")
            return 2
        try:
            r = policy.set_enabled(args.target, action == "enable")
        except KeyError:
            print("policy rule not found")
            return 1
        print(f"{r['id']}  enabled={r['enabled']}")
        return 0

    if action == "revert":
        if not args.target:
            print("usage: atlas policy revert <event_id>")
            return 2
        try:
            policy.revert(args.target)
        except KeyError:
            print("policy event not found")
            return 1
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print("reverted")
        return 0

    if action == "events":
        events = policy.list_events(rule_id=args.target, limit=args.limit)
        if not events:
            print("no policy events")
            return 0
        for e in events:
            print(f"{e['created_at']}  {e['action']:<9} rule={e['rule_id']}")
        return 0

    return 2


def cmd_backup(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    backup = app.container.resolve("backup")
    path = backup.backup()
    print(f"backup written to {path}")
    return 0


_HANDLERS = {
    "serve": cmd_serve,
    "status": cmd_status,
    "doctor": cmd_doctor,
    "chat": cmd_chat,
    "agents": cmd_agents,
    "ask": cmd_ask,
    "search": cmd_search,
    "ingest": cmd_ingest,
    "remember": cmd_remember,
    "recall": cmd_recall,
    "forget": cmd_forget,
    "plugins": cmd_plugins,
    "tools": cmd_tools,
    "capabilities": cmd_capabilities,
    "tool": cmd_tool,
    "coverage": cmd_coverage,
    "policy": cmd_policy,
    "jobs": cmd_jobs,
    "job": cmd_job,
    "formats": cmd_formats,
    "websearch": cmd_websearch,
    "download": cmd_download,
    "scholar": cmd_scholar,
    "youtube": cmd_youtube,
    "code": cmd_code,
    "python": cmd_python,
    "git": cmd_git,
    "sql": cmd_sql,
    "ocr": cmd_ocr,
    "mail": cmd_mail,
    "browser": cmd_browser,
    "research": cmd_research,
    "report": cmd_report,
    "verify": cmd_verify,
    "learn": cmd_learn,
    "intel": cmd_intel,
    "backup": cmd_backup,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return _HANDLERS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
