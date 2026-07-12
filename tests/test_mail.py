"""Tests for the read-only email capability (S20d).

The client + outcome mapping are hermetic via an injectable fake backend. The default
`IMAPBackend` is exercised only for its offline behaviour — it must report `unavailable`
(never raise) when it isn't configured — plus its pure header/body parsing helpers.
"""

from __future__ import annotations

from email.message import EmailMessage

from atlas.mail.client import (
    MAIL_EMPTY,
    MAIL_ERROR,
    MAIL_OK,
    MAIL_UNAUTHORIZED,
    MAIL_UNAVAILABLE,
    IMAPBackend,
    MailClient,
    MailError,
    MailUnauthorized,
    MailUnavailable,
    _extract_text_body,
    _strip_html,
)
from atlas.plugins.mail_plugin import MailPlugin


class FakeBackend:
    name = "fake"

    def __init__(self, *, folders=None, messages=None, one=None, exc=None, available=True):
        self._folders = folders if folders is not None else ["INBOX", "Sent"]
        self._messages = messages if messages is not None else []
        self._one = one
        self._exc = exc
        self._available = available

    def available(self):
        return self._available

    def folders(self):
        if self._exc:
            raise self._exc
        return self._folders

    def search(self, query, folder, limit):
        if self._exc:
            raise self._exc
        return self._messages[:limit]

    def message(self, uid, folder):
        if self._exc:
            raise self._exc
        return self._one


_MSG = {"uid": "7", "subject": "Invoice", "from": "a@x.com", "to": "me@x.com", "date": "Mon"}


# --- outcome mapping -----------------------------------------------------
def test_search_ok():
    client = MailClient(FakeBackend(messages=[_MSG, dict(_MSG, uid="8")]))
    res = client.search("invoice")
    assert res["outcome"] == MAIL_OK
    assert res["count"] == 2
    assert res["folder"] == "INBOX"


def test_search_empty():
    res = MailClient(FakeBackend(messages=[])).search("nope")
    assert res["outcome"] == MAIL_EMPTY
    assert res["count"] == 0


def test_search_respects_max_results():
    many = [dict(_MSG, uid=str(i)) for i in range(100)]
    res = MailClient(FakeBackend(messages=many), max_results=10).search("")
    assert res["count"] == 10


def test_search_unavailable():
    res = MailClient(FakeBackend(exc=MailUnavailable("not configured"))).search("x")
    assert res["outcome"] == MAIL_UNAVAILABLE
    assert "configured" in res["reason"]


def test_search_unauthorized():
    res = MailClient(FakeBackend(exc=MailUnauthorized("bad creds"))).search("x")
    assert res["outcome"] == MAIL_UNAUTHORIZED


def test_search_error():
    res = MailClient(FakeBackend(exc=MailError("boom"))).search("x")
    assert res["outcome"] == MAIL_ERROR


def test_search_never_raises_on_unexpected():
    res = MailClient(FakeBackend(exc=RuntimeError("kaboom"))).search("x")
    assert res["outcome"] == MAIL_ERROR
    assert "kaboom" in res["reason"]


def test_folders_ok():
    res = MailClient(FakeBackend(folders=["INBOX", "Sent", "Trash"])).folders()
    assert res["outcome"] == MAIL_OK
    assert "Sent" in res["folders"]


def test_message_ok():
    res = MailClient(FakeBackend(one=dict(_MSG, body="hello"))).message("7")
    assert res["outcome"] == MAIL_OK
    assert res["message"]["body"] == "hello"


def test_message_missing_is_empty():
    res = MailClient(FakeBackend(one=None)).message("999")
    assert res["outcome"] == MAIL_EMPTY


def test_custom_folder_passed_through():
    res = MailClient(FakeBackend(messages=[_MSG])).search("x", folder="Archive")
    assert res["folder"] == "Archive"


# --- default IMAP backend: honest offline behaviour ----------------------
def test_imap_backend_unconfigured_is_unavailable():
    backend = IMAPBackend(host="", port=993, username="", password="")
    assert backend.available() is False
    # The client must translate this to `unavailable`, never raise.
    assert MailClient(backend).search("x")["outcome"] == MAIL_UNAVAILABLE
    assert MailClient(backend).folders()["outcome"] == MAIL_UNAVAILABLE


# --- pure parsing helpers ------------------------------------------------
def test_extract_text_body_plain():
    msg = EmailMessage()
    msg["Subject"] = "Hi"
    msg.set_content("Hello there\n")
    assert "Hello there" in _extract_text_body(msg)


def test_extract_text_body_prefers_plain_over_html():
    msg = EmailMessage()
    msg.set_content("plain body")
    msg.add_alternative("<p>html body</p>", subtype="html")
    assert _extract_text_body(msg) == "plain body"


def test_strip_html():
    assert _strip_html("<p>Hello <b>world</b></p><script>x=1</script>") == "Hello world"


# --- plugin wiring -------------------------------------------------------
def test_plugin_delegates_and_health():
    plugin = MailPlugin(MailClient(FakeBackend(messages=[_MSG], available=False)))
    assert plugin.search("x")["outcome"] == MAIL_OK
    health = plugin.health_check()
    assert health.healthy is True  # unconfigured mailbox = degraded, not failed
    assert health.data["configured"] is False


class _Kernel:
    def __init__(self) -> None:
        caps: dict = {}
        tools: dict = {}
        self.caps = caps
        self.tool_map = tools

        class _Caps:
            def register(self, name, provider, *, contract=None, kind=None):
                caps[name] = provider

        class _Tools:
            def register(self, name, fn, *, description="", params=None, plugin=None):
                tools[name] = fn

        self.capabilities = _Caps()
        self.tools = _Tools()


def test_plugin_registers_capability_and_tools():
    plugin = MailPlugin(MailClient(FakeBackend()))
    kernel = _Kernel()
    plugin.register(kernel)
    assert "mail" in kernel.caps
    assert {"mail.search", "mail.message", "mail.folders"} <= set(kernel.tool_map)
