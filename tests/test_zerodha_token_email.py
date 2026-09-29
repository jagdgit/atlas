"""MDPH Zerodha login email + IMAP request_token reply poll."""

from __future__ import annotations

from pathlib import Path

import atlas.investment.market_data_provider_health as mdph
from atlas.investment.zerodha_feed import ZerodhaMarketFeed
from atlas.investment.zerodha_token_email import (
    POLL_INTERVAL_S,
    atlas_public_base_url,
    escalate_login_email,
    load_pending,
    parse_request_token_from_text,
    poll_token_reply,
    save_pending,
)
from atlas.mail.client import MAIL_OK
from tests.test_zerodha_feed import _FakeKite


class _FakeSender:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self._to = ["ops@example.com"]

    def available(self) -> bool:
        return True

    def send(self, subject: str, body: str) -> bool:
        self.sent.append({"subject": subject, "body": body, "headers": {}})
        return True

    def send_to_with_headers(self, to_addrs, subject, body, *, headers=None) -> bool:
        self.sent.append(
            {"subject": subject, "body": body, "headers": dict(headers or {}), "to": to_addrs}
        )
        return True


class _FakeMail:
    def __init__(self, messages: list[dict] | None = None) -> None:
        self._messages = list(messages or [])

    def search(self, query: str = "", folder: str | None = None, limit: int | None = None):
        return {
            "outcome": MAIL_OK if self._messages else "empty",
            "messages": list(self._messages)[: limit or 25],
            "query": query,
            "folder": folder,
        }

    def message(self, uid: str, folder: str | None = None):
        for m in self._messages:
            if str(m.get("uid")) == str(uid):
                return {"outcome": MAIL_OK, "message": m, "uid": uid}
        return {"outcome": "empty", "uid": uid}


def test_parse_request_token_variants():
    assert (
        parse_request_token_from_text("ATLAS_ZERODHA_REQUEST_TOKEN: abcDEF123456")
        == "abcDEF123456"
    )
    assert (
        parse_request_token_from_text(
            "see http://127.0.0.1:8000/zerodha/callback?request_token=tok_99XYZ&action=login"
        )
        == "tok_99XYZ"
    )
    assert parse_request_token_from_text("no token here") is None
    # Must not treat access_token line as request token without marker
    assert parse_request_token_from_text("access_token=should_not_match_alone") is None


def test_public_base_url_env(monkeypatch):
    monkeypatch.setenv("ATLAS_PUBLIC_BASE_URL", "http://datanode.lan:8000/")
    assert atlas_public_base_url() == "http://datanode.lan:8000"


def test_public_base_ignores_placeholder(monkeypatch):
    monkeypatch.setenv(
        "ATLAS_PUBLIC_BASE_URL", "http://<datanode-hostname-or-IP>:8000"
    )
    monkeypatch.setenv("ZERODHA_REDIRECT_URL", "http://127.0.0.1:8000/zerodha/callback")
    assert atlas_public_base_url() == "http://127.0.0.1:8000"


def test_email_sender_uses_investor_report_to_env(monkeypatch):
    monkeypatch.setenv("ATLAS_INVESTOR_REPORT_TO", "ops@example.com,second@example.com")
    monkeypatch.setenv("ATLAS_EMAIL_HOST", "smtp.gmail.com")
    monkeypatch.setenv("ATLAS_EMAIL_USERNAME", "ops@example.com")
    monkeypatch.setenv("ATLAS_EMAIL_FROM_ADDR", "ops@example.com")
    monkeypatch.setenv("ATLAS_SMTP_PASSWORD", "x")

    class _EC:
        host = "smtp.gmail.com"
        port = 587
        username = "ops@example.com"
        from_addr = "ops@example.com"
        password_env = "ATLAS_SMTP_PASSWORD"
        to_addrs = []
        investor_to_addrs = []
        use_tls = True
        timeout = 20.0

    class _Cfg:
        email = _EC()

    monkeypatch.setattr("atlas.config.get_config", lambda: _Cfg())
    from atlas.investment.zerodha_token_email import _email_sender

    sender = _email_sender()
    assert sender is not None
    assert sender.available() is True
    assert "ops@example.com" in sender._to
    assert "second@example.com" in sender._to


def test_escalate_email_arms_pending(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ATLAS_PUBLIC_BASE_URL", "http://datanode.lan:8000")
    sender = _FakeSender()
    health = {
        "status": mdph.STATUS_LOGIN_REQUIRED,
        "trading_date": "2099-01-01",
    }
    # Force past hour gate via monkeypatch of datetime in module? use force=True
    out = escalate_login_email(tmp_path, health, sender=sender, force=True)
    assert out["sent"] is True
    assert out["public_base"] == "http://datanode.lan:8000"
    assert "datanode.lan:8000/zerodha/login" in sender.sent[0]["body"]
    assert "ATLAS_ZERODHA_REQUEST_TOKEN" in sender.sent[0]["body"]
    pending = load_pending(tmp_path)
    assert pending["status"] == "awaiting_reply"
    assert pending["message_id"]
    # second send same day blocked
    out2 = escalate_login_email(tmp_path, health, sender=sender, force=False)
    # force=False may hit before_06 or already_sent — pending exists so already_sent
    assert out2["sent"] is False
    assert out2["reason"] == "already_sent_today"


def test_escalate_body_loopback_is_reply_first():
    from atlas.investment.zerodha_token_email import build_escalate_body

    body = build_escalate_body(
        status="LOGIN_REQUIRED",
        trading_date="2026-09-28",
        login_url="http://127.0.0.1:8000/zerodha/login",
        force_login_url="http://127.0.0.1:8000/zerodha/force-login",
        public_base="http://127.0.0.1:8000",
        kite_login_url="https://kite.zerodha.com/connect/login?api_key=demo",
    )
    assert "PRIMARY" in body
    assert "no public URL" in body
    assert "kite.zerodha.com/connect/login" in body
    assert body.index("PRIMARY") < body.index("OPTIONAL")
    assert "No special prefix needed" in body or "just the http://" in body
    # Atlas LAN links are demoted, not removed
    assert "127.0.0.1:8000/zerodha/login" in body


def test_poll_reply_completes_login(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ATLAS_PUBLIC_BASE_URL", "http://datanode.lan:8000")
    day = __import__("atlas.investment.zerodha_token_email", fromlist=["_ist_day"])._ist_day()
    save_pending(
        tmp_path,
        {
            "version": "test",
            "ist_day": day,
            "status": "awaiting_reply",
            "subject": f"[Atlas MDPH] Zerodha LOGIN_REQUIRED — live labs paused ({day})",
            "message_id": "<test@atlas>",
            "sent_at": "2026-01-01T00:00:00+00:00",
            "last_poll_at": None,
            "poll_count": 0,
            "consumed_uids": [],
        },
    )
    kite = _FakeKite()
    feed = ZerodhaMarketFeed(
        api_key="key", api_secret="secret", data_dir=tmp_path, client=kite
    )
    mail = _FakeMail(
        [
            {
                "uid": "42",
                "subject": f"Re: [Atlas MDPH] Zerodha LOGIN_REQUIRED ({day})",
                "body": "ATLAS_ZERODHA_REQUEST_TOKEN: req123\n",
            }
        ]
    )
    sender = _FakeSender()
    monkeypatch.setattr(
        "atlas.investment.zerodha_token_email._email_sender", lambda: sender
    )
    result = poll_token_reply(tmp_path, mail_client=mail, feed=feed, force=True)
    assert result["ok"] is True
    assert result["via"] == "email_reply"
    assert feed.has_session
    pending = load_pending(tmp_path)
    assert pending["status"] == "completed"
    assert pending["result"]["token_len"] == len("req123")
    # confirm mail sent, no raw token in confirm body
    assert sender.sent
    assert "req123" not in sender.sent[-1]["body"]


def test_poll_throttled(tmp_path: Path):
    from datetime import datetime, timezone

    day = __import__("atlas.investment.zerodha_token_email", fromlist=["_ist_day"])._ist_day()
    save_pending(
        tmp_path,
        {
            "ist_day": day,
            "status": "awaiting_reply",
            "last_poll_at": datetime.now(timezone.utc).isoformat(),
            "poll_count": 1,
            "consumed_uids": [],
        },
    )
    out = poll_token_reply(tmp_path, mail_client=_FakeMail(), force=False)
    assert out["reason"] == "poll_throttled"
    assert POLL_INTERVAL_S == 300


def test_save_health_preserves_login_email_flag(tmp_path: Path):
    mdph.save_health(
        tmp_path,
        {
            "status": mdph.STATUS_LOGIN_REQUIRED,
            "login_email_sent_ist_day": "2026-09-28",
            "login_email_message_id": "<x@y>",
        },
    )
    mdph.save_health(tmp_path, {"status": mdph.STATUS_LOGIN_REQUIRED, "token_valid": False})
    doc = mdph.load_health(tmp_path)
    assert doc["login_email_sent_ist_day"] == "2026-09-28"
    assert doc["login_email_message_id"] == "<x@y>"


def test_provider_health_tick_wires_poll(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ATLAS_PUBLIC_BASE_URL", "http://datanode.lan:8000")

    def _fake_cfg():
        class P:
            data = tmp_path

        class C:
            paths = P()

        return C()

    monkeypatch.setattr("atlas.config.get_config", _fake_cfg)
    # Avoid real evaluate network — stub health + escalate/poll
    monkeypatch.setattr(
        mdph,
        "evaluate_zerodha_health",
        lambda *a, **k: {
            "status": mdph.STATUS_LOGIN_REQUIRED,
            "live_trading_allowed": False,
            "trading_date": "2026-09-28",
            "message": "need login",
        },
    )
    monkeypatch.setattr(mdph, "stamp_phase2_session", lambda *a, **k: {"sessions_observed": 1})
    monkeypatch.setattr(
        mdph, "maybe_escalate_login_email", lambda *a, **k: {"sent": True, "reason": "smtp_ok"}
    )
    monkeypatch.setattr(
        mdph, "maybe_poll_zerodha_token_email", lambda *a, **k: {"ok": False, "reason": "poll_throttled"}
    )
    monkeypatch.setattr(mdph, "record_mdph_event", lambda *a, **k: None)
    out = mdph.provider_health_tick({})
    assert out["email_escalate"]["sent"] is True
    assert out["token_email_poll"]["reason"] == "poll_throttled"
