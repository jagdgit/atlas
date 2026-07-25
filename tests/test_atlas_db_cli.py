"""CLI smoke for ``atlas-db test-clean`` (OI-T3)."""

from __future__ import annotations

from atlas.database.cli import main


def test_atlas_db_test_clean_dry_run(monkeypatch):
    class _Mgr:
        def health_check(self):
            return True

        def connection(self):
            raise AssertionError("dry_run path should not open for fake — stub cleanup")

        def close(self):
            return None

    calls: list[dict] = []

    def _clean(db, *, dry_run=False):
        calls.append({"dry_run": dry_run})
        return {
            "repositories_reverted": 1,
            "assets_deleted": 0,
            "test_events_deleted": 2,
        }

    monkeypatch.setattr("atlas.database.connection.DatabaseManager", lambda: _Mgr())
    monkeypatch.setattr("atlas.testing.db_cleanup.clean_pytest_residue", _clean)
    monkeypatch.setattr("atlas.config.get_config", lambda: None)

    assert main(["test-clean", "--dry-run"]) == 0
    assert calls == [{"dry_run": True}]
