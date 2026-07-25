"""Pytest session fixtures — shared live-DB hygiene (OI-T1).

Runs once per session: if PostgreSQL is reachable, deactivate leftover
``/tmp/pytest%`` repositories/assets so path collisions after a tmpfs reboot
do not fail e2e gates. Failures are soft (warn) so hermetic runs stay green
without a DB.
"""

from __future__ import annotations

import logging

import pytest

_log = logging.getLogger("atlas.tests")


@pytest.fixture(scope="session", autouse=True)
def _clean_pytest_db_residue():
    try:
        from atlas.database.connection import DatabaseManager
        from atlas.testing.db_cleanup import clean_pytest_residue
    except Exception as exc:  # noqa: BLE001
        _log.debug("pytest DB cleanup import skipped: %s", exc)
        yield
        return

    manager = DatabaseManager()
    try:
        if not manager.health_check():
            yield
            return
        counts = clean_pytest_residue(manager)
        if any(counts.values()):
            _log.info("OI-T1 session cleanup: %s", counts)
    except Exception as exc:  # noqa: BLE001 - never fail the suite on cleanup
        _log.warning("OI-T1 session cleanup skipped: %s", exc)
    finally:
        try:
            manager.close()
        except Exception:  # noqa: BLE001
            pass
    yield
