"""Best-effort SMTP email sender (Phase 0 · ATLAS_OS_ROADMAP §2.5, A1).

The **email channel** of the Notifier — the *second* channel after web/SSE. Uses the
stdlib ``smtplib``/``email`` only. Honest + non-fatal by construction:

  * ``available()`` is False when SMTP isn't configured → the Notifier silently skips
    email (email is optional; the web console is the primary channel).
  * ``send()`` / ``send_to()`` never raise — a failure is logged and returns False.

The password is a **secret**: it is handed in already-resolved (read from an env var,
per A1 — never YAML/DB) and is never logged.

Investor reports (Market Program) use ``send_to`` with Gmail recipients from env.
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

    def can_send(self) -> bool:
        """True iff SMTP identity is configured (recipients may be supplied per send)."""
        return bool(self._host and self._from)

    def smtp_ready(self) -> bool:
        """True when host/from/password look set enough to attempt Gmail SMTP login."""
        return self.can_send() and bool(self._password)

    def status(self) -> dict:
        """Operator-facing config check (never includes the password)."""
        return {
            "host": self._host or None,
            "port": self._port,
            "username": self._username or None,
            "from_addr": self._from or None,
            "password_set": bool(self._password),
            "default_to_addrs": list(self._to),
            "can_send": self.can_send(),
            "smtp_ready": self.smtp_ready(),
            "use_tls": self._use_tls,
        }

    def available(self) -> bool:
        """True iff enough config is present to attempt a send to default recipients."""
        return self.can_send() and bool(self._to)

    def send(self, subject: str, body: str) -> bool:
        """Send a plain-text email to configured default recipients."""
        return self.send_to(self._to, subject, body)

    def send_to(self, to_addrs: list[str] | str, subject: str, body: str) -> bool:
        """Send a plain-text email to explicit recipients. Returns True on success; never raises."""
        if isinstance(to_addrs, str):
            recipients = [p.strip() for p in to_addrs.split(",") if p.strip()]
        else:
            recipients = [str(a).strip() for a in (to_addrs or []) if str(a).strip()]
        if not self.can_send() or not recipients:
            return False
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self._from
        msg["To"] = ", ".join(recipients)
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
            self._logger.info("email sent to %s: %s", recipients, subject)
            return True
        except Exception:  # noqa: BLE001 - email is best-effort; never crash the notifier
            self._logger.exception("failed to send email")
            return False

    def _deliver(self, smtp: smtplib.SMTP, msg: EmailMessage) -> None:
        if self._username and self._password:
            smtp.login(self._username, self._password)
        smtp.send_message(msg)
