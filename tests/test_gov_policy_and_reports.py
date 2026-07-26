"""Government policy + investor email report unit tests."""

from __future__ import annotations

from atlas.investment.government_policy import (
    DEFAULT_POLICY_CATALOG,
    format_policy_brief,
    policy_delta_by_symbol,
    refresh_catalog,
)
from atlas.investment.reports import (
    InvestorReportMailer,
    format_morning_report,
    format_trade_report,
    parse_recipients,
    resolve_investor_recipients,
)


def test_parse_recipients_comma_separated():
    assert parse_recipients("a@x.com, b@y.com") == ["a@x.com", "b@y.com"]


def test_resolve_investor_recipients_env_precedence(monkeypatch):
    monkeypatch.setenv("ATLAS_INVESTOR_REPORT_TO", "one@t.com,two@t.com")
    monkeypatch.setenv("ATLAS_EMAIL_TO_ADDRS", "ops@t.com")
    assert resolve_investor_recipients(config_to=["cfg@t.com"]) == ["one@t.com", "two@t.com"]


def test_refresh_catalog_and_symbol_deltas(tmp_path):
    snap = refresh_catalog(tmp_path, include_defaults=True)
    assert len(snap["items"]) >= len(DEFAULT_POLICY_CATALOG)
    assert snap["sector_deltas"]
    members = [
        {"symbol": "LT.NS", "sector": "Capital Goods"},
        {"symbol": "TCS.NS", "sector": "IT"},
        {"symbol": "UNKNOWN.NS", "sector": ""},
    ]
    deltas = policy_delta_by_symbol(members, data_dir=tmp_path)
    assert "LT.NS" in deltas
    assert deltas["LT.NS"] > 0
    brief = format_policy_brief(snap)
    assert "Government" in brief or "policy" in brief.lower()


def test_operator_item_overrides_sector():
    # Direct aggregate path
    from atlas.investment.government_policy import aggregate_sector_deltas

    items = [
        {
            "id": "custom_ev",
            "title": "Extra EV subsidy",
            "summary": "Boost EV",
            "sectors": ["Automobile"],
            "delta": 0.2,
            "source": "operator",
            "kind": "budget",
        }
    ]
    sectors = aggregate_sector_deltas(items)
    assert sectors["Automobile"] == 0.2


def test_morning_and_trade_report_format():
    plan = {
        "as_of": "2026-07-22",
        "phase": "learning",
        "confidence": "very_low",
        "capital": 10000,
        "deploy_fraction": 0.4,
        "summary": "Top 2 notionals",
        "candidates": [
            {
                "rank": 1,
                "symbol": "RELIANCE.NS",
                "sector": "Energy",
                "suggested_notional": 2000,
                "suggested_weight": 0.5,
                "why": "momentum + policy",
                "explanations": [{"sign": "+", "text": "policy boost"}],
            }
        ],
        "avoids": [],
        "notes": ["Simulation-only"],
    }
    subject, body = format_morning_report(plan=plan)
    assert "Morning investment plan" in subject
    assert "RELIANCE.NS" in body
    assert "2000" in body

    tsubj, tbody = format_trade_report(
        side="buy",
        symbol="RELIANCE.NS",
        quantity=2,
        price=100.0,
        fee=1.5,
        reason="MA cross",
        decision={"rationale": "trend up", "confidence": 0.4},
    )
    assert "BUY" in tsubj
    assert "trend up" in tbody


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


def test_mailer_send_trade(monkeypatch):
    monkeypatch.setenv("ATLAS_INVESTOR_REPORT_TO", "recv@example.com")
    mail = _FakeEmail()
    mailer = InvestorReportMailer(mail, recipients=["recv@example.com"])
    out = mailer.send_trade(side="sell", symbol="TCS.NS", quantity=1, price=50.0, reason="exit")
    assert out["sent"] is True
    assert mail.sent
    assert mail.sent[0][0] == ["recv@example.com"]


def test_mailer_status_and_preview(monkeypatch, tmp_path):
    monkeypatch.setenv("ATLAS_INVESTOR_REPORT_TO", "recv@example.com")
    mail = _FakeEmail()
    mail.status = lambda: {  # type: ignore[method-assign]
        "host": "smtp.gmail.com",
        "password_set": True,
        "from_addr": "a@b.com",
        "smtp_ready": True,
    }
    mailer = InvestorReportMailer(mail, data_dir=str(tmp_path), recipients=["recv@example.com"])
    st = mailer.status()
    assert st["ready"] is True
    assert "recv@example.com" in st["recipients"]
    prev = mailer.preview_morning()
    assert "subject" in prev and "body" in prev
    assert "Atlas morning report" in prev["body"] or "Morning" in prev["subject"]
