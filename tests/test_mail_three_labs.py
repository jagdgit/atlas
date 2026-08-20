"""Three-lab operator mail board + hourly 08–20 IST (independent of morning)."""

from __future__ import annotations

from atlas.investment.laboratory import (
    DEFAULT_FNO_LAB,
    DEFAULT_INTRADAY_LAB,
    DEFAULT_SWING_LAB,
)
from atlas.investment.reports import (
    InvestorReportMailer,
    format_evening_report,
    format_hourly_activity_report,
    format_morning_report,
    format_three_lab_books_section,
    format_trade_report,
)
from atlas.workers.base import TickContext
from atlas.workers.investor_reports import InvestorReportsWorker
from atlas.workers.paper_trading import skip_cash_alts_for_lab


def _three_books() -> list[dict]:
    return [
        {
            "portfolio_key": DEFAULT_SWING_LAB,
            "cash": 15000,
            "holdings_value": 35000,
            "equity": 50000,
            "day_pnl": -20,
            "total_pnl": 80,
            "valuation_basis": "latest daily market bars",
            "positions": [
                {
                    "symbol": "CIPLA.NS",
                    "quantity": 13,
                    "avg_price": 1400,
                    "mark": 1410,
                    "unrealized_pnl": 130,
                }
            ],
            "no_fill_reasons": ["PLC.A fail-closed (debt_to_equity incomplete) ×2"],
        },
        {
            "portfolio_key": DEFAULT_FNO_LAB,
            "cash": 100000,
            "holdings_value": 0,
            "equity": 100000,
            "valuation_basis": "index_proxy daily underlier",
            "positions": [],
        },
        {
            "portfolio_key": DEFAULT_INTRADAY_LAB,
            "cash": 50000,
            "holdings_value": 0,
            "equity": 50000,
            "positions": [],
        },
    ]


def test_three_lab_section_names_isolated_books():
    lines = format_three_lab_books_section(_three_books())
    body = "\n".join(lines)
    assert "India equity (swing)" in body
    assert "NIFTY index-proxy (F&O lab)" in body
    assert "India equity (intraday 5m)" in body
    assert "CIPLA.NS" in body
    assert "do not add the three equities" in body
    assert DEFAULT_SWING_LAB in body
    assert DEFAULT_FNO_LAB in body
    assert DEFAULT_INTRADAY_LAB in body


def test_morning_evening_hourly_trade_include_three_labs():
    books = _three_books()
    port = {"portfolio_key": DEFAULT_SWING_LAB, "cash": 15000, "lab_books": books}
    plan = {"as_of": "2026-08-18", "phase": "learning", "confidence": "low"}
    _, morning = format_morning_report(plan=plan, portfolio=port)
    _, evening = format_evening_report(plan=plan, portfolio=port)
    _, hourly = format_hourly_activity_report(
        portfolio=port, hour=8, ist_date="2026-08-18"
    )
    _, trade = format_trade_report(
        side="buy",
        symbol="CIPLA.NS",
        quantity=1,
        price=100.0,
        laboratory_id=DEFAULT_SWING_LAB,
        lab_books=books,
    )
    for body in (morning, evening, hourly, trade):
        assert "Three laboratories (paper books)" in body
        assert "India equity (swing)" in body
        assert "NIFTY index-proxy (F&O lab)" in body
        assert "India equity (intraday 5m)" in body


def test_swing_cash_alts_are_not_skipped():
    assert not skip_cash_alts_for_lab({}, portfolio_key=DEFAULT_SWING_LAB)


class _FakeEmail:
    def __init__(self) -> None:
        self.sent: list[tuple] = []

    def can_send(self) -> bool:
        return True

    def smtp_ready(self) -> bool:
        return True

    def send_to(self, to, subject, body) -> bool:
        self.sent.append((list(to), subject, body))
        return True


def _freeze_ist(monkeypatch, hour: int, minute: int = 0):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import atlas.workers.investor_reports as ir
    import datetime as dt_mod

    fixed = datetime(2026, 7, 27, hour, minute, tzinfo=ZoneInfo("Asia/Kolkata"))
    real_datetime = dt_mod.datetime

    class _NowDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed.astimezone(dt_mod.timezone.utc).replace(tzinfo=None)
            return fixed.astimezone(tz)

    monkeypatch.setattr(ir, "datetime", _NowDatetime)
    return fixed


def _worker(tmp_path):
    class _FixedMailer(InvestorReportMailer):
        @staticmethod
        def ist_today() -> str:
            return "2026-07-27"

    mail = _FakeEmail()
    mailer = _FixedMailer(mail, data_dir=str(tmp_path), recipients=["recv@example.com"])
    worker = InvestorReportsWorker(mailer=mailer, data_dir=str(tmp_path))
    return worker, mail


def _tick(worker, **cfg):
    config = {
        "program_id": "market_intelligence",
        "portfolio_key": DEFAULT_SWING_LAB,
        **cfg,
    }
    return worker.do_tick(
        TickContext(
            worker_id="w1",
            mission_id="m1",
            config=config,
            state={},
            inputs=[],
            config_version=1,
        )
    )


def test_hourly_sends_at_08_during_morning_window(monkeypatch, tmp_path):
    _freeze_ist(monkeypatch, 8, 0)
    worker, mail = _worker(tmp_path)
    result = _tick(worker)
    note = result.note or ""
    assert "hourly sent 08:00" in note
    assert "morning sent" in note
    hourly_bodies = [b for _to, subj, b in mail.sent if "Hourly" in subj]
    assert hourly_bodies
    assert any("08:00" in subj for _to, subj, _b in mail.sent if "Hourly" in subj)


def test_hourly_does_not_send_at_07(monkeypatch, tmp_path):
    _freeze_ist(monkeypatch, 7, 15)
    worker, mail = _worker(tmp_path)
    result = _tick(worker)
    note = result.note or ""
    assert "hourly sent" not in note
    assert "morning sent" in note
    assert not any("Hourly" in subj for _to, subj, _b in mail.sent)


def test_hourly_sends_at_20(monkeypatch, tmp_path):
    _freeze_ist(monkeypatch, 20, 0)
    worker, mail = _worker(tmp_path)
    result = _tick(worker)
    note = result.note or ""
    assert "hourly sent 20:00" in note
    assert any("Hourly" in subj for _to, subj, _b in mail.sent)
