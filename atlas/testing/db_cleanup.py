"""Shared-dev-DB cleanup for live pytest residue (OI-T1 / OI-T3).

Live-DB tests share the operator Postgres. After a reboot clears ``/tmp`` (tmpfs),
pytest's temp counter restarts and fresh paths collide with stale ``active``
``learning.repositories`` rows (``uq_learning_repositories_root_active``).

This module deactivates / deletes **only** clearly pytest-shaped residue — never
real mission or kernel rows — so contributors can run ``atlas-db test-clean`` or
rely on the session-scoped ``tests/conftest.py`` fixture.
"""

from __future__ import annotations

from typing import Any

# Filesystem roots pytest uses under /tmp (Linux tmpfs). Match both classic and
# pytest-of-<user> layouts without touching real operator paths.
_PYTEST_ROOT_SQL = (
    "root LIKE '/tmp/pytest%' OR root LIKE '%/pytest-%' OR root LIKE '%/pytest_%'"
)
_PYTEST_URI_SQL = (
    "source_uri LIKE '/tmp/pytest%' OR source_uri LIKE '%/pytest-%' "
    "OR source_uri LIKE '%/pytest_%'"
)


def clean_pytest_residue(db: Any, *, dry_run: bool = False) -> dict[str, int]:
    """Revert / delete pytest temp residue. Returns counts of affected rows.

    ``db`` is a :class:`~atlas.database.connection.DatabaseManager` (or anything
    with ``.connection()`` yielding a psycopg connection).
    """
    counts = {
        "repositories_reverted": 0,
        "assets_deleted": 0,
        "test_events_deleted": 0,
    }
    with db.connection() as conn:
        with conn.cursor() as cur:
            if dry_run:
                cur.execute(
                    f"SELECT count(*) FROM learning.repositories "
                    f"WHERE status = 'active' AND ({_PYTEST_ROOT_SQL})"
                )
                counts["repositories_reverted"] = int(cur.fetchone()[0])
                cur.execute(
                    f"SELECT count(*) FROM asset.assets WHERE {_PYTEST_URI_SQL}"
                )
                counts["assets_deleted"] = int(cur.fetchone()[0])
                cur.execute(
                    "SELECT count(*) FROM audit.events "
                    "WHERE source = 'test' AND status = 'pending'"
                )
                counts["test_events_deleted"] = int(cur.fetchone()[0])
                return counts

            cur.execute(
                f"""
                UPDATE learning.repositories
                SET status = 'reverted', updated_at = now()
                WHERE status = 'active' AND ({_PYTEST_ROOT_SQL})
                """
            )
            counts["repositories_reverted"] = cur.rowcount

            # Cascade deletes asset.versions. Safe: only pytest source_uri shapes.
            cur.execute(f"DELETE FROM asset.assets WHERE {_PYTEST_URI_SQL}")
            counts["assets_deleted"] = cur.rowcount

            # Only hermetic ``source='test'`` pending rows — never scheduler/kernel.
            cur.execute(
                "DELETE FROM audit.events "
                "WHERE source = 'test' AND status = 'pending'"
            )
            counts["test_events_deleted"] = cur.rowcount
        conn.commit()
    return counts
