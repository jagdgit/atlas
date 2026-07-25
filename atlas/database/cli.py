"""Command-line interface for Atlas database migrations.

Kept separate from ``migrations.py`` so it is never imported as a side effect
of ``import atlas.database`` (avoids the runpy double-import warning).

Usage:
    uv run atlas-db status
    uv run atlas-db migrate
    uv run atlas-db baseline
    uv run atlas-db test-clean [--dry-run]
"""

from __future__ import annotations

import argparse

from atlas.config import get_config
from atlas.database.migrations import MigrationRunner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atlas-db")
    parser.add_argument(
        "command",
        choices=["status", "migrate", "baseline", "test-clean"],
        help=(
            "status: show state; migrate: apply pending; baseline: mark all applied; "
            "test-clean: remove pytest /tmp residue from the shared dev DB (OI-T1/T3)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="with test-clean: report counts without mutating",
    )
    args = parser.parse_args(argv)

    get_config()  # validate configuration early

    if args.command == "test-clean":
        from atlas.database.connection import DatabaseManager
        from atlas.testing.db_cleanup import clean_pytest_residue

        manager = DatabaseManager()
        try:
            if not manager.health_check():
                print("database unreachable — aborting test-clean")
                return 1
            counts = clean_pytest_residue(manager, dry_run=args.dry_run)
        finally:
            manager.close()
        verb = "would clean" if args.dry_run else "cleaned"
        print(
            f"test-clean {verb}: repositories_reverted={counts['repositories_reverted']} "
            f"assets_deleted={counts['assets_deleted']} "
            f"test_events_deleted={counts['test_events_deleted']}"
        )
        return 0

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
