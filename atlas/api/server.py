"""Uvicorn server runner for the Atlas API.

Builds the kernel Application, wraps it with FastAPI, and serves it. The kernel is
started/stopped via the app's lifespan (see ``create_app``), so ``atlas serve`` is
a fully running Atlas with an HTTP surface.
"""

from __future__ import annotations

import logging

import uvicorn

from atlas.api.app import create_app
from atlas.kernel import build_application

logger = logging.getLogger("atlas.api")


def serve(host: str | None = None, port: int | None = None) -> None:
    application = build_application()
    cfg = application.config
    app = create_app(application)

    bind_host = host or cfg.api.host
    bind_port = port or cfg.api.port
    if not cfg.api.keys:
        application.logger.warning(
            "API starting with NO keys configured — all /v1 routes will return 401. "
            "Set ATLAS_API_KEYS to enable access."
        )
    application.logger.info("Atlas API listening on http://%s:%d", bind_host, bind_port)
    uvicorn.run(app, host=bind_host, port=bind_port, log_level="info")
