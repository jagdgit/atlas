"""Command-line interface for Atlas database migrations.

Kept separate from ``migrations.py`` so it is never imported as a side effect
of ``import atlas.database`` (avoids the runpy double-import warning).

Usage:
    uv run atlas-db status
    uv run atlas-db migrate
    uv run atlas-db baseline
"""

from __future__ import annotations

import argparse

from atlas.config import get_config
from atlas.database.migrations import MigrationRunner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atlas-db")
    parser.add_argument(
        "command",
        choices=["status", "migrate", "baseline"],
        help="status: show state; migrate: apply pending; baseline: mark all applied",
    )
    args = parser.parse_args(argv)

    get_config()  # validate configuration early
    runner = MigrationRunner()

    if args.command == "status":
        state = runner.status()
        print(f"Applied ({len(state['applied'])}): {', '.join(state['applied']) or '-'}")
        print(f"Pending ({len(state['pending'])}): {', '.join(state['pending']) or '-'}")
    elif args.command == "migrate":
        applied = runner.migrate()
        print(
            f"Applied migrations: {', '.join(applied)}"
            if applied
            else "No pending migrations."
        )
    elif args.command == "baseline":
        recorded = runner.baseline()
        print(f"Baselined ({len(recorded)}): {', '.join(recorded)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
