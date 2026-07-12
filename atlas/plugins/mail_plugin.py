"""Mail plugin (S20d): read-only email retrieval over IMAP.

Exposes tools (registered as the ``mail`` capability):
    mail.folders()                          -> mailbox/folder names
    mail.search(query=?, folder=?, limit=?) -> message summaries (newest first)
    mail.message(uid, folder=?)             -> one full message with text body

Read-only by construction (mailboxes selected ``readonly=True``, bodies fetched with
``BODY.PEEK`` so nothing is marked read, no write path). **Degrades gracefully**: when
no server/credentials are configured (or the server is unreachable), calls return an
``unavailable``/``unauthorized`` outcome instead of raising (R2/R3). The password is a
secret read from an env var at build time — never stored in config/DB/logs (Q7).
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from atlas.mail.client import IMAPBackend, MailClient
from atlas.plugins.base import BasePlugin
from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.config import AtlasConfig
    from atlas.kernel.application import Application


class MailPlugin(BasePlugin):
    name = "mail"
    version = "0.1.0"

    def __init__(self, client: MailClient, *, logger: logging.Logger | None = None) -> None:
        self._client = client
        self._logger = logger or logging.getLogger("atlas.plugins.mail")

    def register(self, kernel: "Application") -> None:
        from atlas.capabilities import CAP_MAIL, MailCapability

        kernel.capabilities.register(
            CAP_MAIL, self, contract=MailCapability, kind="plugin"
        )
        kernel.tools.register(
            "mail.search", self.search,
            description="Search a mailbox (read-only) and return message summaries.",
            params={
                "query": "text to search for (empty => most recent messages)",
                "folder": "mailbox/folder (default INBOX)",
                "limit": "max messages to return",
            },
            plugin=self.name,
        )
        kernel.tools.register(
            "mail.message", self.message,
            description="Open one message by uid (read-only; never marks it read).",
            params={"uid": "message uid", "folder": "mailbox/folder (default INBOX)"},
            plugin=self.name,
        )
        kernel.tools.register(
            "mail.folders", self.folders,
            description="List mailbox folders.",
            params={},
            plugin=self.name,
        )

    # --- capability -----------------------------------------------------
    def search(
        self, query: str = "", folder: str | None = None, limit: int | None = None
    ) -> dict[str, Any]:
        return self._client.search(query, folder=folder, limit=limit)

    def message(self, uid: str, folder: str | None = None) -> dict[str, Any]:
        return self._client.message(uid, folder=folder)

    def folders(self) -> dict[str, Any]:
        return self._client.folders()

    def health_check(self) -> HealthStatus:
        backend = getattr(self._client, "_backend", None)
        configured = bool(backend and backend.available())
        return HealthStatus(
            healthy=True,  # an unconfigured mailbox is a degraded, not failed, state
            detail=("mail (read-only) configured" if configured
                    else "mail unavailable (no server/credentials configured)"),
            data={"configured": configured},
        )


def build(config: "AtlasConfig") -> MailPlugin:
    mail = config.plugins.mail
    # The password is a secret: read from the named env var, never from YAML/DB.
    password = os.environ.get(mail.password_env, "")
    backend = IMAPBackend(
        host=mail.host,
        port=mail.port,
        username=mail.username,
        password=password,
        use_ssl=mail.use_ssl,
        timeout=mail.timeout,
    )
    client = MailClient(
        backend, default_folder=mail.default_folder, max_results=mail.max_results
    )
    return MailPlugin(client)
