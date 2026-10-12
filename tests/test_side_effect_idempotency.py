"""OI-OPS-1INST L7 — side-effect idempotency smoke (I13).

Full fill/mail integration is covered elsewhere; these assert the duplicate
guards the ownership model relies on.
"""

from __future__ import annotations

from atlas.investment.reports import InvestorReportMailer


class _Sink:
    def __init__(self) -> None:
        self.sent: list[tuple] = []

    def can_send(self) -> bool:
        return True

    def smtp_ready(self) -> bool:
        return True

    def send_to(self, to, subject, body) -> bool:
        self.sent.append((list(to), subject, body))
        return True


def test_i13_duplicate_hourly_mail_is_noop(tmp_path) -> None:
    sink = _Sink()
    mailer = InvestorReportMailer(
        email=sink,
        data_dir=str(tmp_path),
        recipients=["ops@example.com"],
    )
    lab = "india_equity_learner"
    mailer._sent_hourly_keys.add(f"{mailer._lab_day_key(lab, mailer.ist_today())}|10")
    result = mailer.send_hourly(
        program_id=lab,
        laboratory_id=lab,
        portfolio={"cash": 1, "equity": 1, "positions": [], "laboratory_id": lab},
        hour=10,
    )
    assert result.get("sent") is False
    assert result.get("reason") == "already_sent_this_hour"
    assert sink.sent == []
