"""Mail client + IMAP backend (S20d).

``MailClient`` lists folders, searches messages, and opens one message through an
injectable ``MailBackend`` (default ``IMAPBackend``, stdlib ``imaplib`` + ``email``).
The backend seam keeps the client hermetic in tests (inject a fake) while the real
backend is **read-only by construction**:
  * mailboxes are selected with ``readonly=True`` (the server rejects any write), and
  * message bodies are fetched with ``BODY.PEEK[...]`` so opening a mail never sets the
    ``\\Seen`` flag — reading is genuinely side-effect-free, and
  * there is simply no STORE/DELETE/EXPUNGE/APPEND code path.

Outcomes are honest and never raise (R2/R3):
  ``ok`` | ``empty`` (no matches) | ``unauthorized`` (bad credentials) |
  ``unavailable`` (not configured / cannot connect) | ``error``.

The password is a **secret**: the client is handed an already-resolved password (read
from an env var by ``build``), and it is never logged.
"""

from __future__ import annotations

import email
import imaplib
import logging
import re
from email.header import decode_header, make_header
from email.message import Message
from typing import Any, Protocol

MAIL_OK = "ok"
MAIL_EMPTY = "empty"
MAIL_UNAUTHORIZED = "unauthorized"
MAIL_UNAVAILABLE = "unavailable"
MAIL_ERROR = "error"

_MAX_BODY_CHARS = 100_000  # cap the body text returned for a single message


class MailUnavailable(Exception):
    """Not configured, or the server cannot be reached → unavailable."""


class MailUnauthorized(Exception):
    """The server rejected the credentials → unauthorized."""


class MailError(Exception):
    """The server returned an error for a valid request → error."""


class MailBackend(Protocol):
    name: str

    def available(self) -> bool:
        """True iff enough config is present to attempt a connection."""
        ...

    def folders(self) -> list[str]:
        """List mailbox/folder names. Raise MailUnavailable/MailUnauthorized/MailError."""
        ...

    def search(self, query: str, folder: str, limit: int) -> list[dict[str, Any]]:
        """Return message summaries (most recent first), newest `limit` matches."""
        ...

    def message(self, uid: str, folder: str) -> dict[str, Any] | None:
        """Return one full message (with text body), or None if the uid is unknown."""
        ...


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except Exception:  # noqa: BLE001 - a malformed header must not crash reading
        return value.strip()


def _extract_text_body(msg: Message) -> str:
    """Best-effort plain-text body (prefers text/plain; falls back to stripped HTML)."""
    def _payload(part: Message) -> str:
        try:
            raw = part.get_payload(decode=True)
            if raw is None:
                return ""
            charset = part.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace")
        except Exception:  # noqa: BLE001
            return ""

    if msg.is_multipart():
        plain, html = "", ""
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp.lower():
                continue
            ctype = part.get_content_type()
            if ctype == "text/plain" and not plain:
                plain = _payload(part)
            elif ctype == "text/html" and not html:
                html = _payload(part)
        body = plain or _strip_html(html)
    else:
        body = _payload(msg)
        if msg.get_content_type() == "text/html":
            body = _strip_html(body)
    return body.strip()[:_MAX_BODY_CHARS]


def _strip_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+\n", "\n", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _summary(uid: str, msg: Message) -> dict[str, Any]:
    return {
        "uid": uid,
        "subject": _decode(msg.get("Subject")),
        "from": _decode(msg.get("From")),
        "to": _decode(msg.get("To")),
        "date": _decode(msg.get("Date")),
    }


class IMAPBackend:
    """Read-only IMAP backend using the stdlib. Connects per call (occasional use)."""

    name = "imap"

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        use_ssl: bool = True,
        timeout: float = 20.0,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_ssl = use_ssl
        self._timeout = timeout

    def available(self) -> bool:
        return bool(self._host and self._username and self._password)

    def _connect(self) -> imaplib.IMAP4:
        if not self.available():
            raise MailUnavailable("email is not configured (host/username/password)")
        try:
            if self._use_ssl:
                conn: imaplib.IMAP4 = imaplib.IMAP4_SSL(
                    self._host, self._port, timeout=self._timeout
                )
            else:
                conn = imaplib.IMAP4(self._host, self._port, timeout=self._timeout)
        except (OSError, imaplib.IMAP4.error) as exc:
            raise MailUnavailable(f"cannot reach IMAP server: {exc}") from exc
        try:
            conn.login(self._username, self._password)
        except imaplib.IMAP4.error as exc:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass
            raise MailUnauthorized(f"IMAP login failed: {exc}") from exc
        return conn

    @staticmethod
    def _close(conn: imaplib.IMAP4) -> None:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001 - closing must never raise
            pass

    def folders(self) -> list[str]:
        conn = self._connect()
        try:
            typ, data = conn.list()
            if typ != "OK":
                raise MailError(f"LIST failed: {typ}")
            names: list[str] = []
            for line in data:
                if not line:
                    continue
                decoded = line.decode(errors="replace") if isinstance(line, bytes) else str(line)
                match = re.search(r'"[^"]*"\s+("?)([^"\r\n]+)\1\s*$', decoded)
                if match:
                    names.append(match.group(2).strip())
            return names
        finally:
            self._close(conn)

    def search(self, query: str, folder: str, limit: int) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            typ, _ = conn.select(folder, readonly=True)
            if typ != "OK":
                raise MailError(f"cannot open folder {folder!r}")
            if query.strip():
                typ, data = conn.uid("SEARCH", "TEXT", f'"{query}"')
            else:
                typ, data = conn.uid("SEARCH", None, "ALL")
            if typ != "OK":
                raise MailError(f"SEARCH failed: {typ}")
            uids = (data[0].split() if data and data[0] else [])
            recent = uids[-limit:][::-1]  # newest first
            out: list[dict[str, Any]] = []
            for raw_uid in recent:
                uid = raw_uid.decode() if isinstance(raw_uid, bytes) else str(raw_uid)
                typ, msg_data = conn.uid(
                    "FETCH", uid,
                    "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE TO)])",
                )
                if typ != "OK" or not msg_data or not msg_data[0]:
                    continue
                header_bytes = msg_data[0][1]
                msg = email.message_from_bytes(header_bytes)
                out.append(_summary(uid, msg))
            return out
        finally:
            self._close(conn)

    def message(self, uid: str, folder: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            typ, _ = conn.select(folder, readonly=True)
            if typ != "OK":
                raise MailError(f"cannot open folder {folder!r}")
            typ, msg_data = conn.uid("FETCH", uid, "(BODY.PEEK[])")
            if typ != "OK" or not msg_data or not msg_data[0]:
                return None
            msg = email.message_from_bytes(msg_data[0][1])
            summary = _summary(uid, msg)
            summary["body"] = _extract_text_body(msg)
            return summary
        finally:
            self._close(conn)


class MailClient:
    def __init__(
        self,
        backend: MailBackend,
        *,
        default_folder: str = "INBOX",
        max_results: int = 25,
        logger: logging.Logger | None = None,
    ) -> None:
        self._backend = backend
        self._default_folder = default_folder
        self._max_results = max_results
        self._logger = logger or logging.getLogger("atlas.mail")

    def folders(self) -> dict[str, Any]:
        return self._guard({"backend": self._backend.name}, self._folders)

    def _folders(self) -> dict[str, Any]:
        names = self._backend.folders()
        return {
            "outcome": MAIL_OK if names else MAIL_EMPTY,
            "backend": self._backend.name,
            "folders": names,
        }

    def search(
        self, query: str = "", folder: str | None = None, limit: int | None = None
    ) -> dict[str, Any]:
        folder = folder or self._default_folder
        limit = min(limit or self._max_results, self._max_results)
        base = {"backend": self._backend.name, "folder": folder, "query": query}
        return self._guard(base, lambda: self._search(query, folder, limit, base))

    def _search(self, query, folder, limit, base) -> dict[str, Any]:
        messages = self._backend.search(query, folder, limit)
        return {
            **base,
            "outcome": MAIL_OK if messages else MAIL_EMPTY,
            "count": len(messages),
            "messages": messages,
        }

    def message(self, uid: str, folder: str | None = None) -> dict[str, Any]:
        folder = folder or self._default_folder
        base = {"backend": self._backend.name, "folder": folder, "uid": uid}
        return self._guard(base, lambda: self._message(uid, folder, base))

    def _message(self, uid, folder, base) -> dict[str, Any]:
        msg = self._backend.message(uid, folder)
        if msg is None:
            return {**base, "outcome": MAIL_EMPTY, "reason": f"no message {uid}"}
        return {**base, "outcome": MAIL_OK, "message": msg}

    def _guard(self, base: dict[str, Any], fn) -> dict[str, Any]:
        """Run a backend call, translating every failure into an honest outcome."""
        try:
            return fn()
        except MailUnauthorized as exc:
            return {**base, "outcome": MAIL_UNAUTHORIZED, "reason": str(exc)}
        except MailUnavailable as exc:
            return {**base, "outcome": MAIL_UNAVAILABLE, "reason": str(exc)}
        except MailError as exc:
            return {**base, "outcome": MAIL_ERROR, "reason": str(exc)}
        except Exception as exc:  # noqa: BLE001 - a bad backend must not crash the caller
            self._logger.exception("mail backend crashed")
            return {**base, "outcome": MAIL_ERROR, "reason": str(exc)}
