"""Tests for evening honesty, IST email catch-up, and session notes."""

from __future__ import annotations

from atlas.investment.reports import (
    InvestorReportMailer,
    format_evening_report,
)
from atlas.investment.session_notes import (
    classify_action,
    format_no_fill_reasons,
    merge_day_notes,
)
from atlas.workers.investor_reports import InvestorReportsWorker
from atlas.workers.base import TickContext


class _FakeEmail:
    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[tuple] = []
        self.fail = fail

    def can_send(self) -> bool:
        return True

    def smtp_ready(self) -> bool:
        return True

    def send_to(self, to, subject, body) -> bool:
        if self.fail:
            return False
        self.sent.append((list(to), subject, body))
        return True


def test_evening_report_explains_zero_fills():
    subject, body = format_evening_report(
        plan={"as_of": "2026-07-27", "summary": "quiet day", "candidates": []},
        portfolio={"cash": 10000, "equity": 10000, "positions": []},
        trades=[],
        no_fill_reasons=[
            "Live price feed empty (often internet / Yahoo outage) ×5",
            "Market session closed (outside NSE cash hours / weekend) ×12",
        ],
    )
    assert "Evening" in subject
    assert "Why no fills:" in body
    assert "Live price feed empty" in body
    assert "session closed" in body.lower() or "Market session closed" in body


def test_evening_report_shows_portfolio_delta_and_total():
    _, body = format_evening_report(
        plan={"as_of": "2026-08-05", "summary": "one fill", "candidates": []},
        portfolio={
            "cash": 34158,
            "holdings_value": 16000,
            "equity": 50158,
            "day_pnl": 158,
            "day_return_pct": 0.316,
            "total_pnl": 158,
            "total_return_pct": 0.316,
            "net_contributed_capital": 50000,
            "valuation_basis": "latest daily market bars",
            "positions": [],
            "recent_trades": [],
            "kpis": {
                "cash": 34158,
                "equity": 50158,
                "day_pnl": 158,
                "candidates_planned": 5,
                "candidates_filled": 1,
                "plan_fill_rate": 0.2,
                "buys_today": 1,
                "sells_today": 0,
                "open_positions": 0,
                "portfolio_gate_blocks": 2,
                "size_trims": 0,
                "phase": "learning",
                "confidence": "very_low",
                "research_studied": 1,
                "lessons_count": 0,
                "top_no_fill_reasons": [{"reason": "research_hold", "count": 3}],
            },
        },
    )
    assert "Today's market P&L" in body
    assert "Trading KPIs" in body
    assert "Plan→fill" in body
    assert "Total portfolio equity: ₹50,158.00" in body
    assert "Today's market P&L: ₹+158.00 (+0.32%)" in body
    assert "Total P&L after cash flows: ₹+158.00 (+0.32%)" in body
    assert "Net contributed capital: ₹50,000.00" in body


def test_session_notes_merge_and_format(tmp_path):
    merge_day_notes(
        tmp_path,
        portfolio_key="india_equity_learner",
        ist_date="2026-07-27",
        reason_counts={"empty_live_feed": 3, "research_hold": 2},
        samples=["RELIANCE.NS: empty_live_feed"],
        extra={"feed_gap_days": 2.5},
    )
    merge_day_notes(
        tmp_path,
        portfolio_key="india_equity_learner",
        ist_date="2026-07-27",
        reason_counts={"empty_live_feed": 1},
    )
    from atlas.investment.session_notes import load_day_notes

    notes = load_day_notes(
        tmp_path, portfolio_key="india_equity_learner", ist_date="2026-07-27"
    )
    assert notes["reason_counts"]["empty_live_feed"] == 4
    assert notes["reason_counts"]["research_hold"] == 2
    lines = format_no_fill_reasons(notes)
    assert any("Live price feed empty" in x for x in lines)
    assert any("gap" in x.lower() for x in lines)


def test_classify_action_buckets():
    assert classify_action("INFY.NS: empty_live_feed") == "empty_live_feed"
    assert classify_action("TCS.NS: research_hold (no_mvr)") == "research_hold"
    assert classify_action("RELIANCE.NS: buy 2 @ 100.00 (signal)") is None
    assert classify_action("RELIANCE.NS: hold @ 100.00") == "strategy_hold"


def test_mailer_ist_dedup_and_smtp_failure_does_not_mark(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_INVESTOR_REPORT_TO", "recv@example.com")
    mail = _FakeEmail(fail=True)
    mailer = InvestorReportMailer(
        mail, data_dir=str(tmp_path), recipients=["recv@example.com"]
    )
    out = mailer.send_morning(force=False)
    assert out["sent"] is False
    assert out["reason"] == "smtp_send_failed"
    assert not mailer.already_sent_morning()

    mail.fail = False
    out2 = mailer.send_morning(force=False)
    assert out2["sent"] is True
    assert mailer.already_sent_morning()

    # Durable across new mailer instance
    mailer2 = InvestorReportMailer(
        mail, data_dir=str(tmp_path), recipients=["recv@example.com"]
    )
    assert mailer2.already_sent_morning()
    out3 = mailer2.send_morning(force=False)
    assert out3["sent"] is False
    assert out3["reason"] == "already_sent_today"


def test_investor_worker_catch_up_outside_window(monkeypatch, tmp_path):
    """When morning window passed and not yet sent, catch-up should attempt send."""
    monkeypatch.setenv("ATLAS_INVESTOR_REPORT_TO", "recv@example.com")

    from datetime import datetime
    from zoneinfo import ZoneInfo

    fixed = datetime(2026, 7, 27, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

    class _FixedMailer(InvestorReportMailer):
        @staticmethod
        def ist_today() -> str:
            return "2026-07-27"

    mail = _FakeEmail()
    mailer = _FixedMailer(mail, data_dir=str(tmp_path), recipients=["recv@example.com"])
    worker = InvestorReportsWorker(mailer=mailer, data_dir=str(tmp_path))

    import atlas.workers.investor_reports as ir
    import datetime as dt_mod

    real_datetime = dt_mod.datetime

    class _NowDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed.astimezone(dt_mod.timezone.utc).replace(tzinfo=None)
            return fixed.astimezone(tz)

    monkeypatch.setattr(ir, "datetime", _NowDatetime)

    result = worker.do_tick(
        TickContext(
            worker_id="w1",
            mission_id="m1",
            config={
                "program_id": "market_intelligence",
                "portfolio_key": "india_equity_learner",
            },
            state={},
            inputs=[],
            config_version=1,
        )
    )
    assert "morning sent" in (result.note or "")
    assert "(catch-up)" in (result.note or "")
    assert mail.sent


def test_investor_worker_resolves_live_book_after_restart(monkeypatch, tmp_path):
    from atlas.investment import portfolios as pf

    monkeypatch.setenv(
        "ATLAS_VIRTUAL_PORTFOLIOS", str(tmp_path / "virtual_portfolios.json")
    )
    pf.clear()
    pf.register(
        label="India learner",
        portfolio_key="india_equity_learner",
        persona={"capital": 50000, "currency": "INR"},
        mission_id="mission-paper",
    )

    class _Portfolio:
        def __init__(self):
            self._repo = self

        def ensure_portfolio(self, **kwargs):
            assert kwargs["mission_id"] == "mission-paper"
            assert kwargs["name"] == "india_equity_learner"
            return {
                "id": "sim-1",
                "cash": 34158,
                "starting_cash": 10000,
            }

        def list_positions(self, _pid):
            return [
                {
                    "symbol": "EICHERMOT.NS",
                    "quantity": 2,
                    "avg_price": 7921,
                }
            ]

        def snapshot(self, _pid, prices=None):
            mark = (prices or {}).get("EICHERMOT.NS", 7921)
            return {
                "cash": 34158,
                "starting_cash": 10000,
                "holdings_value": 2 * mark,
                "equity": 34158 + 2 * mark,
                "positions": [
                    {
                        "symbol": "EICHERMOT.NS",
                        "quantity": 2,
                        "avg_price": 7921,
                        "mark": mark,
                        "unrealized_pnl": 2 * (mark - 7921),
                    }
                ],
            }

        def trades(self, _pid, limit=50):
            return [
                {
                    "symbol": "EICHERMOT.NS",
                    "side": "buy",
                    "quantity": 2,
                    "price": 7921,
                    "created_at": "2026-08-05T03:48:25+00:00",
                }
            ]

        def list_cash_movements(self, _pid, limit=200):
            return [{"kind": "deposit", "amount": 40000}]

    class _Market:
        def bars_for(self, symbol, **_kwargs):
            assert symbol == "EICHERMOT.NS"
            return {"bars": [{"close": 7900}, {"close": 8000}]}

    worker = InvestorReportsWorker(
        mailer=None,
        portfolio=_Portfolio(),
        market_reader=_Market(),
        data_dir=str(tmp_path),
    )
    doc = worker._portfolio_doc("india_equity_learner", ist_date="2026-08-05")
    assert doc is not None
    assert doc["sim_portfolio_id"] == "sim-1"
    assert doc["cash"] == 34158
    assert doc["equity"] == 50158
    assert doc["recent_trades"][0]["ist_day_match"] is True
    assert doc["net_contributed_capital"] == 50000
    assert doc["total_pnl"] == 158
    assert doc["day_pnl"] == 158
