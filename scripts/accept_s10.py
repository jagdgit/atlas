"""Sprint 10 Chat-Mode acceptance: the five §3 interactions in one session.

Runs against real services (DB + Ollama). Builds the application without starting
worker threads, resolves the chat orchestrator, and drives one conversation.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from atlas.kernel import build_application


def main() -> int:
    app = build_application()
    chat = app.container.resolve("chat")

    # A document to ingest for turns 2 & 3.
    tmp = Path(tempfile.mkdtemp(prefix="atlas_accept_"))
    doc = tmp / "atlas_overview.md"
    doc.write_text(
        "# Atlas Overview\n\n"
        "Atlas is a personal AI research and execution system. It runs locally, "
        "stores knowledge in PostgreSQL with pgvector, and uses Ollama for local "
        "language models. Its guiding principle is determinism over speed.\n",
        encoding="utf-8",
    )

    turns = [
        "What documents do you know about?",
        f"Read this file: {doc}",
        "What does it say?",
        "Remember that I prefer PostgreSQL over Milvus.",
        "What do you remember about my preferences?",
    ]

    session_id = None
    for i, message in enumerate(turns, 1):
        turn = chat.chat(message, session_id=session_id)
        session_id = turn.session_id
        print(f"\n=== Turn {i} ===")
        print(f"you>   {message}")
        print(f"atlas> {turn.answer}")
        print(f"       [intent={turn.intent} gaps={turn.capability_gaps}]")

    print(f"\nsession_id = {session_id}")
    print("history length =", len(app.container.resolve("conversation").history(session_id)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
