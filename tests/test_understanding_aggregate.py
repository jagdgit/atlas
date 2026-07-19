"""Live-DB test for the understanding-by-domain aggregate (Phase C · §C.4, CC15).

Coverage says how much was read; understanding says how well it is understood. This aggregate rolls up
active head revisions per (domain, maturity, status) so the CoverageService can compute understanding %.
Skipped when PostgreSQL is unreachable.
"""

from __future__ import annotations

import uuid

import pytest

from atlas.knowledge.lifecycle import (
    MATURITY_CANDIDATE,
    MATURITY_ESTABLISHED,
    MATURITY_VERIFIED,
)


@pytest.fixture(scope="module")
def db():
    from atlas.database.connection import DatabaseManager

    manager = DatabaseManager()
    try:
        if not manager.health_check():
            pytest.skip("database health check failed")
    except Exception as exc:  # noqa: BLE001 - any connection error means skip
        pytest.skip(f"database unreachable: {exc}")
    yield manager
    manager.close()


def test_understanding_by_domain_groups_head_revisions(db):
    from atlas.repositories.finding_repo import FindingRepository

    repo = FindingRepository(db)
    domain = f"probe-{uuid.uuid4().hex[:8]}"  # isolate this domain from all other rows
    ids: list[str] = []
    try:
        for maturity, conf, status in [
            (MATURITY_ESTABLISHED, "HIGH", "active"),
            (MATURITY_VERIFIED, "MEDIUM", "active"),
            (MATURITY_CANDIDATE, "UNVERIFIED", "contested"),
        ]:
            token = uuid.uuid4().hex
            row = repo.create(
                f"claim {token}",
                domain=domain,
                confidence=conf,
                confidence_score=0.8 if conf == "HIGH" else 0.5,
                status=status,
                maturity=maturity,
                identity_key=["prose", domain, token],
            )
            ids.append(str(row["id"]))

        agg = {(r["maturity"], r["status"]): r for r in repo.understanding_by_domain()
               if r["domain"] == domain}
        assert agg[(MATURITY_ESTABLISHED, "active")]["n"] == 1
        assert agg[(MATURITY_VERIFIED, "active")]["n"] == 1
        assert agg[(MATURITY_CANDIDATE, "contested")]["n"] == 1
        # avg_score is populated for scoring.
        assert agg[(MATURITY_ESTABLISHED, "active")]["avg_score"] == pytest.approx(0.8)
    finally:
        for fid in ids:
            repo.set_status(fid, "archived")
