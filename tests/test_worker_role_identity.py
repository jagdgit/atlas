"""Lab-aware worker_tick role key — regression for Phase 5 F&O pause."""

from __future__ import annotations

from atlas.workers.role_identity import (
    ACTIVE,
    STALE,
    assert_known_paper_labs_survive,
    classify_worker_tick_roles,
    role_key,
)


def _row(
    *,
    schedule_id: str,
    worker_id: str,
    mission_id: str,
    program_id: str,
    worker_type: str,
    portfolio_key: str = "",
    mission_created_at: str = "2026-08-01T00:00:00+00:00",
    last_tick_at: str = "2026-10-08T17:00:00+00:00",
) -> dict:
    return {
        "schedule_id": schedule_id,
        "worker_id": worker_id,
        "mission_id": mission_id,
        "program_id": program_id,
        "worker_type": worker_type,
        "portfolio_key": portfolio_key,
        "mission_created_at": mission_created_at,
        "last_tick_at": last_tick_at,
    }


def test_paper_labs_under_same_program_stay_distinct():
    rows = [
        _row(
            schedule_id="s-intra",
            worker_id="w-intra",
            mission_id="m-intra",
            program_id="market_intelligence",
            worker_type="paper_trading",
            portfolio_key="equity_intraday_learner",
            mission_created_at="2026-08-08T10:44:54+00:00",
        ),
        _row(
            schedule_id="s-fno",
            worker_id="w-fno",
            mission_id="m-fno",
            program_id="market_intelligence",
            worker_type="paper_trading",
            portfolio_key="india_fno_learner",
            mission_created_at="2026-08-08T10:45:02+00:00",
        ),
        _row(
            schedule_id="s-swing",
            worker_id="w-swing",
            mission_id="m-swing",
            program_id="_unscoped",
            worker_type="paper_trading",
            portfolio_key="india_equity_learner",
            mission_created_at="2026-07-25T13:51:35+00:00",
        ),
    ]
    first = classify_worker_tick_roles(rows)
    second = classify_worker_tick_roles(rows)
    assert all(r["classification"] == ACTIVE for r in first)
    assert assert_known_paper_labs_survive(first) == []
    # Idempotent: second pass still all ACTIVE
    assert all(r["classification"] == ACTIVE for r in second)
    keys = {tuple(r["role_key"].values()) for r in first}
    assert (
        "market_intelligence",
        "paper_trading",
        "india_fno_learner",
    ) in keys
    assert (
        "market_intelligence",
        "paper_trading",
        "equity_intraday_learner",
    ) in keys


def test_true_duplicates_still_collapse():
    rows = [
        _row(
            schedule_id="s1",
            worker_id="w1",
            mission_id="m1",
            program_id="market_intelligence",
            worker_type="investor_reports",
            mission_created_at="2026-07-01T00:00:00+00:00",
        ),
        _row(
            schedule_id="s2",
            worker_id="w2",
            mission_id="m2",
            program_id="market_intelligence",
            worker_type="investor_reports",
            mission_created_at="2026-08-01T00:00:00+00:00",
        ),
    ]
    out = classify_worker_tick_roles(rows)
    by = {r["schedule_id"]: r["classification"] for r in out}
    assert by["s1"] == ACTIVE
    assert by["s2"] == STALE


def test_same_paper_lab_still_dedupes():
    rows = [
        _row(
            schedule_id="s-a",
            worker_id="w-a",
            mission_id="m-a",
            program_id="market_intelligence",
            worker_type="paper_trading",
            portfolio_key="india_fno_learner",
            mission_created_at="2026-08-01T00:00:00+00:00",
        ),
        _row(
            schedule_id="s-b",
            worker_id="w-b",
            mission_id="m-b",
            program_id="market_intelligence",
            worker_type="paper_trading",
            portfolio_key="india_fno_learner",
            mission_created_at="2026-09-01T00:00:00+00:00",
        ),
    ]
    out = classify_worker_tick_roles(rows)
    by = {r["schedule_id"]: r["classification"] for r in out}
    assert by["s-a"] == ACTIVE
    assert by["s-b"] == STALE


def test_role_key_ignores_lab_for_non_paper():
    assert role_key("market_intelligence", "investor_reports", "india_fno_learner") == (
        "market_intelligence",
        "investor_reports",
        "",
    )


def test_phase5_collision_would_have_failed_old_key_but_passes_new():
    """Document the 2026-10-08 failure mode: old key collapses; new key does not."""
    old = {
        ("market_intelligence", "paper_trading"),
        ("market_intelligence", "paper_trading"),
    }
    assert len(old) == 1
    new = {
        role_key("market_intelligence", "paper_trading", "equity_intraday_learner"),
        role_key("market_intelligence", "paper_trading", "india_fno_learner"),
    }
    assert len(new) == 2
