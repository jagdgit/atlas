"""Uvicorn server runner for the Atlas API.

Builds the kernel Application, wraps it with FastAPI, and serves it. The kernel is
started/stopped via the app's lifespan (see ``create_app``), so ``atlas serve`` is
a fully running Atlas with an HTTP surface.

OI-OPS-1INST boot order (Step 0B):
  L5 manual gate → L1 flock → L2 pre-bound socket → build kernel → uvicorn
  (lifespan → app.start()). Conflict exits **before** ``build_application``.
"""

from __future__ import annotations

import logging

import uvicorn

from atlas.api.app import create_app
from atlas.config import get_config
from atlas.kernel import build_application
from atlas.ops.instance_lock import EXIT_INSTANCE_CONFLICT
from atlas.ops.serve_boot import boot_or_exit
from atlas.ops.service_locks import ServiceLockManager, set_service_lock_manager

logger = logging.getLogger("atlas.api")


def serve(
    host: str | None = None,
    port: int | None = None,
    *,
    manual: bool = False,
) -> int:
    """Run Atlas API. Returns 0 on clean shutdown, 75 on instance conflict."""
    cfg = get_config()
    bind_host = host or cfg.api.host
    bind_port = int(port or cfg.api.port)
    log = logging.getLogger("atlas.kernel")

    # L5 → L1 → L2 before any service construction (I4: start() never runs on conflict).
    boot = boot_or_exit(
        data_dir=cfg.paths.data,
        host=bind_host,
        port=bind_port,
        manual=manual,
        logger=log,
    )
    if isinstance(boot, int):
        return boot

    application = build_application()
    try:
        set_service_lock_manager(
            ServiceLockManager(
                conninfo=application.config.database.conninfo,
                logger=application.logger,
            )
        )
    except Exception:  # noqa: BLE001
        application.logger.exception("service lock manager init failed")

    app = create_app(application)

    if not application.config.api.keys:
        application.logger.warning(
            "API starting with NO keys configured — all /v1 routes will return 401. "
            "Set ATLAS_API_KEYS to enable access."
        )

    config = uvicorn.Config(app, log_level="info", access_log=True)
    server = uvicorn.Server(config)
    application.logger.info(
        "Atlas API listening on http://%s:%d", boot.host, boot.port
    )
    if application.config.api.ui_enabled:
        application.logger.info(
            "Atlas Console (web UI) at http://%s:%d/ui/", boot.host, boot.port
        )
    try:
        server.run(sockets=[boot.sock])
    finally:
        try:
            from atlas.ops.service_locks import get_service_lock_manager

            mgr = get_service_lock_manager()
            if mgr is not None:
                mgr.release_all()
        except Exception:  # noqa: BLE001
            pass
        set_service_lock_manager(None)
        boot.release()
    return 0


def serve_exit_conflict() -> int:
    return EXIT_INSTANCE_CONFLICT
