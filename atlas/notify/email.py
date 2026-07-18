"""Best-effort SMTP email sender (Phase 0 · ATLAS_OS_ROADMAP §2.5, A1).

The **email channel** of the Notifier — the *second* channel after web/SSE. Uses the
stdlib ``smtplib``/``email`` only. Honest + non-fatal by construction:

  * ``available()`` is False when SMTP isn't configured → the Notifier silently skips
    email (email is optional; the web console is the primary channel).
  * ``send()`` never raises — a failure is logged and returns False.

The password is a **secret**: it is handed in already-resolved (read from an env var,
per A1 — never YAML/DB) and is never logged.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage


class EmailSender:
    def __init__(
        self,
        *,
        host: str = "",
        port: int = 587,
        username: str = "",
        password: str = "",
        from_addr: str = "",
        to_addrs: list[str] | None = None,
        use_tls: bool = True,
        timeout: float = 20.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self._host = host
        self._port = int(port)
        self._username = username
        self._password = password
        self._from = from_addr or username
        self._to = list(to_addrs or [])
        self._use_tls = use_tls
        self._timeout = float(timeout)
        self._logger = logger or logging.getLogger("atlas.notify.email")

    def available(self) -> bool:
        """True iff enough config is present to attempt a send."""
        return bool(self._host and self._from and self._to)

    def send(self, subject: str, body: str) -> bool:
        """Send a plain-text email. Returns True on success; never raises."""
        if not self.available():
            return False
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self._from
        msg["To"] = ", ".join(self._to)
        msg.set_content(body)
        try:
            if self._port == 465:
                with smtplib.SMTP_SSL(self._host, self._port, timeout=self._timeout) as smtp:
                    self._deliver(smtp, msg)
            else:
                with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as smtp:
                    if self._use_tls:
                        smtp.starttls()
                    self._deliver(smtp, msg)
            self._logger.info("notification email sent: %s", subject)
            return True
        except Exception:  # noqa: BLE001 - email is best-effort; never crash the notifier
            self._logger.exception("failed to send notification email")
            return False

    def _deliver(self, smtp: smtplib.SMTP, msg: EmailMessage) -> None:
        if self._username and self._password:
            smtp.login(self._username, self._password)
        smtp.send_message(msg)
