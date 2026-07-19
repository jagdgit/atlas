"""Live-DB smoke for the virtual-portfolio repository (Phase D · §D.6).

Exercises ``sim.portfolios`` / ``sim.positions`` / ``sim.trades`` against a real PostgreSQL (skipped
if unreachable): ensure-portfolio is idempotent, positions upsert + delete, and the blotter records
fills linked to a decision. Requires migration 0041.
"""

from __future__ import annotations

import uuid

import pytest

from atlas.database.connection import DatabaseManager
from atlas.repositories.sim_repo import SimTradingRepository


@pytest.fixture(scope="module")
def repo():
    db = DatabaseManager()
    try:
        if not db.health_check():
            pytest.skip("database health check failed")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {exc}")
    yield SimTradingRepository(db)
    db.close()


def test_ensure_portfolio_is_idempotent(repo: SimTradingRepository):
    mission_id = uuid.uuid4()
    a = repo.ensure_portfolio(mission_id=mission_id, name="default", starting_cash=5000.0)
    b = repo.ensure_portfolio(mission_id=mission_id, name="default", starting_cash=9999.0)
    assert a["id"] == b["id"]  # same (mission, name) → same row
    assert float(a["starting_cash"]) == 5000.0
    assert float(a["cash"]) == 5000.0


def test_positions_upsert_and_delete(repo: SimTradingRepository):
    p = repo.ensure_portfolio(mission_id=uuid.uuid4(), name="pos", starting_cash=1000.0)
    repo.upsert_position(p["id"], "ACME", quantity=10, avg_price=20.0)
    repo.upsert_position(p["id"], "ACME", quantity=15, avg_price=18.0)
    pos = repo.get_position(p["id"], "ACME")
    assert float(pos["quantity"]) == 15 and float(pos["avg_price"]) == 18.0
    assert len(repo.list_positions(p["id"])) == 1
    assert repo.delete_position(p["id"], "ACME") == 1
    assert repo.get_position(p["id"], "ACME") is None


def test_blotter_records_fill_with_decision_ref(repo: SimTradingRepository):
    mission_id = uuid.uuid4()
    decision_id = uuid.uuid4()
    p = repo.ensure_portfolio(mission_id=mission_id, name="blotter", starting_cash=1000.0)
    trade = repo.record_trade(
        portfolio_id=p["id"], mission_id=mission_id, decision_id=decision_id,
        symbol="ACME", side="buy", quantity=5, price=20.0, fee=0.0,
        cash_after=900.0, realized_pnl=0.0,
    )
    assert trade["side"] == "buy"
    assert str(trade["decision_id"]) == str(decision_id)  # fill links to the P9 decision
    assert repo.count_trades(p["id"]) == 1
    repo.update_portfolio_cash(p["id"], cash=900.0, realized_pnl_delta=0.0)
    assert float(repo.get_portfolio(p["id"])["cash"]) == 900.0
