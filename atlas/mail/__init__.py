"""Read-only email retrieval (Stage 2, S20d).

Lets Atlas *read* a mailbox — list folders, search messages, open one message — over
IMAP, so email becomes a research/assistant source alongside the web. Built on an
injectable ``MailBackend`` seam: the default ``IMAPBackend`` uses the stdlib ``imaplib``
+ ``email`` and is **read-only by construction** (mailboxes selected ``readonly=True``,
messages fetched with ``BODY.PEEK`` so nothing is ever marked read, and no
STORE/DELETE/EXPUNGE path exists). It **degrades gracefully**: when no server/credentials
are configured or the server is unreachable, calls return an honest ``unavailable`` /
``unauthorized`` outcome instead of raising (R2/R3). Credentials are a **secret** — the
password comes from an environment variable, never YAML/DB/logs (Q7). Tests inject a
fake backend for full hermetic coverage.
"""

from __future__ import annotations

from atlas.mail.client import (
    MAIL_EMPTY,
    MAIL_ERROR,
    MAIL_OK,
    MAIL_UNAUTHORIZED,
    MAIL_UNAVAILABLE,
    IMAPBackend,
    MailBackend,
    MailClient,
    MailError,
    MailUnauthorized,
    MailUnavailable,
)

__all__ = [
    "MailClient",
    "MailBackend",
    "IMAPBackend",
    "MailError",
    "MailUnavailable",
    "MailUnauthorized",
    "MAIL_OK",
    "MAIL_EMPTY",
    "MAIL_UNAVAILABLE",
    "MAIL_UNAUTHORIZED",
    "MAIL_ERROR",
]
