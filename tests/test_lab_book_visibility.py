"""The hourly mail must report the book it actually holds.

Operator report, 2026-10-08: the hourly mail showed

    India equity (swing) [india_equity_learner]
      Cash ₹27,408.50 · holdings unavailable · equity unavailable
      Positions: (none)

while `india_equity_learner` held 2 open positions (qty 32) in Postgres, and no P&L
line appeared at all. Two independent defects:

1. `skip_live_marks` (set for every evening/hourly mail) skipped resolving
   `sim_portfolio_id`. The registry stores it as NULL, so `pid` stayed None, the
   snapshot never ran, and holdings/equity/positions/P&L were all absent. Only `cash`
   survived, because it is read from the registry persona. The flag exists to avoid
   waiting on *Yahoo*; it was implemented as "never touch Postgres".
2. The report omitted the P&L line entirely when the figures were missing, so
   "not summarised" was indistinguishable from "flat".
"""

from __future__ import annotations

import pytest

from atlas.investment.reports import format_three_lab_books_section
from atlas.workers.investor_reports import InvestorReportsWorker

POSITIONS = [
    {"symbol": "HBLPOWER.NS", "quantity": 20.0, "avg_price": 600.0},
    {"symbol": "TATACHEM.NS", "quantity": 12.0, "avg_price": 900.0},
]


class FakeRepo:
    def __init__(self):
        self.listed: list[str] = []

    def list_positions(self, pid):
        self.listed.append(str(pid))
        return list(POSITIONS)

    def list_cash_movements(self, pid, limit=200):
        return []


class FakePortfolio:
    """Stands in for the trading portfolio service."""

    def __init__(self):
        self._repo = FakeRepo()
        self.ensured = 0
        self.snapshotted: list[dict] = []

    def ensure_portfolio(self, *, mission_id, name, starting_cash, base_currency):
        self.ensured += 1
        return {"id": "pid-1", "starting_cash": 10000.0, "cash": 27408.5}

    def snapshot(self, pid, prices=None):
        self.snapshotted.append({"pid": pid, "prices": prices})
        holdings = sum(p["quantity"] * p["avg_price"] for p in POSITIONS)
        return {
            "portfolio_id": str(pid),
            "cash": 27408.5,
            "starting_cash": 10000.0,
            "holdings_value": holdings,
            "equity": 27408.5 + holdings,
            "realized_pnl": 150.0,
            "unrealized_pnl": -40.0,
            "positions": [dict(p) for p in POSITIONS],
            "valuation_basis": None,
        }

    def trades(self, pid, limit=200):
        return []


class NoMarketReader:
    """Present but must not be consulted when marks are skipped."""

    def __init__(self):
        self.calls = 0


@pytest.fixture(autouse=True)
def _registry(monkeypatch):
    """Mirror the live registry: a real mission_id, but sim_portfolio_id NULL.

    The NULL is the precondition for the bug — it is why `pid` had to be resolved.
    """
    from atlas.investment import portfolios

    monkeypatch.setattr(
        portfolios,
        "get",
        lambda key: {
            "label": "India equity (swing)",
            "mission_id": "9bcc3175-c613-486c-bcbb-e2f094ba5dfd",
            "sim_portfolio_id": None,
            "persona": {"capital": 27408.5, "currency": "INR"},
        },
    )


def _doc(*, skip_live_marks: bool, portfolio=None, market_reader=None):
    pf = portfolio or FakePortfolio()
    worker = InvestorReportsWorker(
        mailer=None, portfolio=pf, market_reader=market_reader, data_dir=None
    )
    doc = worker._portfolio_doc(
        "india_equity_learner",
        ist_date="2026-10-08",
        compact=True,
        skip_live_marks=skip_live_marks,
    )
    return doc, pf


# --- defect 1: the timely path must still read the book ----------------------


def test_timely_path_resolves_the_portfolio_id():
    # The registry stores sim_portfolio_id as NULL; without this the book is invisible.
    _doc_, pf = _doc(skip_live_marks=True)
    assert pf.ensured == 1


def test_timely_path_reports_holdings_and_equity():
    doc, _ = _doc(skip_live_marks=True)
    assert doc is not None
    assert doc.get("holdings_value") == 20 * 600.0 + 12 * 900.0
    assert doc.get("equity") is not None


def test_timely_path_reports_the_positions_it_holds():
    doc, _ = _doc(skip_live_marks=True)
    symbols = [p["symbol"] for p in (doc.get("positions") or [])]
    assert symbols == ["HBLPOWER.NS", "TATACHEM.NS"]


def test_timely_path_reports_total_pnl():
    doc, _ = _doc(skip_live_marks=True)
    assert doc.get("total_pnl") is not None


def test_timely_path_still_skips_the_market_marks():
    # This is the whole point of the flag: Postgres yes, Yahoo no.
    reader = NoMarketReader()
    _doc_, pf = _doc(skip_live_marks=True, market_reader=reader)
    assert pf.snapshotted[0]["prices"] is None
    assert reader.calls == 0


def test_timely_path_labels_the_valuation_honestly():
    doc, _ = _doc(skip_live_marks=True)
    assert doc.get("valuation_basis") == (
        "average cost (live marks skipped for timely delivery)"
    )


def test_full_path_is_unchanged_and_still_reads_the_book():
    doc, pf = _doc(skip_live_marks=False)
    assert pf.ensured == 1
    assert doc.get("holdings_value") is not None


# --- defect 2: the P&L line must never silently disappear -------------------


def test_pnl_line_is_present_even_when_both_figures_are_missing():
    out = format_three_lab_books_section([
        {"portfolio_key": "india_equity_learner", "cash": 27408.5}
    ])
    pnl_lines = [ln for ln in out if "P&L today" in ln]
    assert len(pnl_lines) == 1
    assert "unavailable" in pnl_lines[0]


def test_total_pnl_is_reconstructed_from_realized_and_unrealized():
    out = format_three_lab_books_section([
        {
            "portfolio_key": "india_equity_learner",
            "cash": 27408.5,
            "realized_pnl": 150.0,
            "unrealized_pnl": -40.0,
        }
    ])
    line = next(ln for ln in out if "P&L today" in ln)
    assert "110.00" in line  # 150 + (-40), not one or the other


def test_an_explicit_total_pnl_is_not_overwritten():
    out = format_three_lab_books_section([
        {
            "portfolio_key": "india_equity_learner",
            "cash": 1.0,
            "total_pnl": 999.0,
            "realized_pnl": 1.0,
            "unrealized_pnl": 2.0,
        }
    ])
    line = next(ln for ln in out if "P&L today" in ln)
    assert "999.00" in line


def test_holdings_and_equity_render_when_present():
    out = format_three_lab_books_section([
        {
            "portfolio_key": "india_equity_learner",
            "cash": 27408.5,
            "holdings_value": 22800.0,
            "equity": 50208.5,
            "positions": [{"symbol": "HBLPOWER.NS", "quantity": 20, "avg_price": 600.0}],
            "total_pnl": 110.0,
        }
    ])
    body = "\n".join(out)
    # The headline book line is the thing the operator reads first; it must be numeric.
    head = next(ln for ln in out if "Cash" in ln)
    assert "unavailable" not in head
    assert "₹22,800.00" in head
    assert "HBLPOWER.NS" in body
    assert "Positions: (none)" not in body


# --- a flat, idle book made exactly zero today ------------------------------


def _pnl_doc(*, positions, day_trades):
    worker = InvestorReportsWorker(
        mailer=None, portfolio=FakePortfolio(), market_reader=None, data_dir=None
    )
    doc = {
        "starting_cash": 10000.0,
        "equity": 10000.0,
        "positions": positions,
        "recent_trades": day_trades,
        "marks": {},
        "previous_closes": {},
    }
    worker._add_cash_and_pnl_metrics(doc, pid="pid-1", ist_date="2026-10-08")
    return doc


def test_empty_book_with_no_fills_reports_zero_day_pnl():
    doc = _pnl_doc(positions=[], day_trades=[])
    assert doc["day_pnl"] == 0.0
    assert doc.get("day_pnl_note")


def test_held_positions_without_marks_keep_day_pnl_unknown():
    # Honesty: an open book's day move genuinely cannot be computed without marks.
    doc = _pnl_doc(positions=[dict(p) for p in POSITIONS], day_trades=[])
    assert doc["day_pnl"] is None
