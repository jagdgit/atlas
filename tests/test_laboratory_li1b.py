"""LI.1b — personality, per-lab mail, deposit hermeticity, outage resume."""

from __future__ import annotations

from atlas.investment import portfolios as vp
from atlas.investment.laboratory import DEFAULT_INTRADAY_LAB, DEFAULT_SWING_LAB
from atlas.investment.laboratory_resume import resume_laboratory_ledger
from atlas.investment.reports import (
    InvestorReportMailer,
    format_evening_report,
    format_morning_report,
    format_trade_report,
)


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


def test_personality_presets_for_labs(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_VIRTUAL_PORTFOLIOS", str(tmp_path / "vp.json"))
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path))
    vp._STORE.clear()
    vp._LOADED = False

    swing = vp.create_laboratory(
        label="Equity Swing",
        laboratory_id=DEFAULT_SWING_LAB,
        capital=50_000.0,
        personality_kind="swing",
    )
    intra = vp.create_laboratory(
        label="Equity Intraday",
        laboratory_id=DEFAULT_INTRADAY_LAB,
        capital=25_000.0,
        personality_kind="intraday",
    )
    assert swing["persona"]["holding_philosophy"] == "weeks_ignore_noise"
    assert swing["persona"]["mentor"] == "mos_patience"
    assert intra["persona"]["holding_philosophy"] == "flat_eod"
    assert intra["persona"]["capital_policy"] == "tight_day"
    assert intra["personality_kind"] == "intraday"


def test_mail_subjects_are_lab_scoped():
    subj_m, body_m = format_morning_report(
        plan={"as_of": "2026-08-08", "phase": "learning", "confidence": "low"},
        portfolio={"portfolio_key": DEFAULT_INTRADAY_LAB, "cash": 1000},
        program_id="market_intelligence",
    )
    assert f"[{DEFAULT_INTRADAY_LAB}]" in subj_m
    assert f"Laboratory: {DEFAULT_INTRADAY_LAB}" in body_m

    subj_e, body_e = format_evening_report(
        plan={"as_of": "2026-08-08", "phase": "learning", "confidence": "low"},
        portfolio={"portfolio_key": DEFAULT_SWING_LAB, "cash": 1000, "positions": []},
        program_id="market_intelligence",
    )
    assert f"[{DEFAULT_SWING_LAB}]" in subj_e
    assert f"Laboratory: {DEFAULT_SWING_LAB}" in body_e

    subj_t, body_t = format_trade_report(
        side="buy",
        symbol="CIPLA.NS",
        quantity=1,
        price=100.0,
        laboratory_id=DEFAULT_INTRADAY_LAB,
    )
    assert f"[{DEFAULT_INTRADAY_LAB}]" in subj_t
    assert f"Laboratory: {DEFAULT_INTRADAY_LAB}" in body_t


def test_per_lab_mail_dedup_independent(tmp_path):
    email = _FakeEmail()
    mailer = InvestorReportMailer(
        email,
        data_dir=str(tmp_path),
        recipients=["ops@example.com"],
        enabled=True,
    )
    today = mailer.ist_today()
    assert mailer.already_sent_morning(today, laboratory_id=DEFAULT_SWING_LAB) is False
    mailer._sent_morning_dates.add(mailer._lab_day_key(DEFAULT_SWING_LAB, today))
    mailer._persist_sent_flags()

    # Reload flags from disk
    mailer2 = InvestorReportMailer(
        email,
        data_dir=str(tmp_path),
        recipients=["ops@example.com"],
        enabled=True,
    )
    assert mailer2.already_sent_morning(today, laboratory_id=DEFAULT_SWING_LAB) is True
    assert mailer2.already_sent_morning(today, laboratory_id=DEFAULT_INTRADAY_LAB) is False


def test_resume_ledger_marks_without_inventing_fills(tmp_path):
    class _Port:
        def ensure_portfolio(self, **kwargs):
            return {"id": "sim-1", "cash": 10000.0}

        def list_positions(self, _pid):
            return [{"symbol": "CIPLA.NS", "quantity": 1, "avg_price": 1400}]

        def snapshot(self, _pid, prices=None):
            mark = (prices or {}).get("CIPLA.NS", 1400)
            return {
                "cash": 10000.0,
                "equity": 10000.0 + mark,
                "positions": [
                    {
                        "symbol": "CIPLA.NS",
                        "quantity": 1,
                        "avg_price": 1400,
                        "mark": mark,
                    }
                ],
            }

    class _Mkt:
        def bars_for(self, symbol, **_kwargs):
            return {"bars": [{"close": 1450.0}]}

    report = resume_laboratory_ledger(
        portfolio_service=_Port(),
        market_reader=_Mkt(),
        mission_id="m1",
        laboratory_id=DEFAULT_INTRADAY_LAB,
        starting_cash=10000,
        data_dir=str(tmp_path),
        ist_date="2026-08-08",
        personality={"holding_philosophy": "flat_eod"},
    )
    assert report["invented_fills"] is False
    assert report["marks_applied"] == 1
    assert report["overnight_warning"]
    assert report["laboratory_id"] == DEFAULT_INTRADAY_LAB
