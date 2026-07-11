"""Unified ``atlas`` command-line interface (ADR-0047).

Single entry point with subcommands, built on stdlib ``argparse`` (zero new deps,
consistent with ``atlas-db``). Commands call the kernel's services in-process via
the DI container, so they work without a running API server:

    atlas serve                 # run the REST API (uvicorn)
    atlas status                # bootstrap, health-check, print, exit
    atlas agents                # list registered agents
    atlas ask "question"        # ask an agent (default: rag)
    atlas search "query"        # semantic search over the knowledge base
    atlas ingest ./file.md      # ingest a file into the knowledge base
    atlas remember "fact"       # store a memory (working/episodic/semantic)
    atlas recall "query"        # semantic recall from memory
    atlas forget <id>           # delete a memory by id
    atlas plugins               # list loaded plugins
    atlas tools                 # list available tools
    atlas tool web.fetch --arg url=https://example.com   # invoke a tool

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

    p_tool = sub.add_parser("tool", help="invoke a tool by name")
    p_tool.add_argument("name")
    p_tool.add_argument(
        "--arg",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="tool argument as KEY=VALUE (repeatable)",
    )

    return parser


# --- command handlers (app injectable for testing) -----------------------
def cmd_serve(args: argparse.Namespace, app: "Application | None" = None) -> int:
    from atlas.api import serve

    serve(host=args.host, port=args.port)
    return 0


def cmd_status(args: argparse.Namespace, app: "Application | None" = None) -> int:
    app = app or build_application()
    app.start()
    try:
        report = app.health()
        for name, status in report.items():
            flag = "OK" if status.healthy else "FAIL"
            print(f"  [{flag}] {name}: {status.detail}")
        return 0 if app.healthy() else 1
    finally:
        app.stop()


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


_HANDLERS = {
    "serve": cmd_serve,
    "status": cmd_status,
    "agents": cmd_agents,
    "ask": cmd_ask,
    "search": cmd_search,
    "ingest": cmd_ingest,
    "remember": cmd_remember,
    "recall": cmd_recall,
    "forget": cmd_forget,
    "plugins": cmd_plugins,
    "tools": cmd_tools,
    "tool": cmd_tool,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return _HANDLERS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
