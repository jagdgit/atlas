"""FastAPI application factory for Atlas (ADR-0045).

``create_app(application)`` wraps an already-built kernel ``Application`` with an
HTTP surface. Endpoints resolve services from the Application's DI container, so
the API is a thin adapter over the same capabilities the CLI and agents use.

Lifespan ties the HTTP server to the kernel: on startup the Application starts all
services (scheduler workers, health monitor, ingestion), on shutdown it stops them
cleanly. Tests construct the app without entering the lifespan (no ``with``), so
they stay hermetic and inject a fake Application into ``app.state``.
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from atlas.api.routes import public_router, v1_router
from atlas.exceptions import (
    AgentNotFoundError,
    AtlasError,
    CapabilityMissingError,
    ConfigError,
    DatabaseError,
    KnowledgeError,
    LLMError,
    PluginError,
    ToolNotFoundError,
)
from atlas.telemetry import get_metrics
from atlas.utils.logging import get_logger

if TYPE_CHECKING:
    from atlas.kernel.application import Application

# Typed errors -> HTTP status. Anything else falls through to a generic 500.
_ERROR_STATUS: list[tuple[type[AtlasError], int]] = [
    (AgentNotFoundError, 404),
    (ToolNotFoundError, 404),
    (CapabilityMissingError, 404),
    (LLMError, 502),  # upstream model backend problem
    (DatabaseError, 503),  # datastore unreachable/degraded — retryable, not a bug
    (ConfigError, 500),
    (KnowledgeError, 500),
    (PluginError, 400),  # bad tool args (e.g. path escape, non-http URL)
    (AtlasError, 500),
]


def _status_for(exc: AtlasError) -> int:
    for err_type, code in _ERROR_STATUS:
        if isinstance(exc, err_type):
            return code
    return 500


def create_app(application: "Application") -> FastAPI:
    cfg = application.config

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        application.start()
        try:
            yield
        finally:
            application.stop()

    app = FastAPI(
        title="Atlas API",
        version=cfg.system.version,
        docs_url="/docs" if cfg.api.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if cfg.api.docs_enabled else None,
        lifespan=lifespan,
    )

    # State the routes and auth read from.
    app.state.application = application
    app.state.api_keys = list(cfg.api.keys)

    if cfg.api.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cfg.api.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    log = get_logger("atlas.api.access")
    metrics = get_metrics()

    @app.middleware("http")
    async def _observe_requests(request: Request, call_next):
        """Access log + HTTP metrics + a correlation id on every request (S22).

        Records latency and status per *route template* (not raw path) to keep
        metric cardinality bounded, and echoes an ``X-Request-ID`` so a client can
        correlate a call with the server logs.
        """
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            route = request.scope.get("route")
            path = getattr(route, "path", request.url.path)
            method = request.method
            metrics.incr(
                "http.requests", method=method, path=path, status=status_code
            )
            metrics.observe("http.request.duration_ms", elapsed_ms, path=path)
            log.info(
                "%s %s -> %s (%.1fms) [%s]",
                method, path, status_code, elapsed_ms, request_id,
            )

    @app.exception_handler(AtlasError)
    async def _atlas_error_handler(_: Request, exc: AtlasError) -> JSONResponse:
        return JSONResponse(
            status_code=_status_for(exc),
            content={"error": type(exc).__name__, "detail": str(exc)},
        )

    @app.exception_handler(Exception)
    async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        # A non-AtlasError escaped a service: return the *same* structured shape as
        # typed errors (never a bare stack trace) and log it with the request id.
        request_id = getattr(request.state, "request_id", None)
        get_logger("atlas.api").exception("unhandled error [%s]", request_id)
        return JSONResponse(
            status_code=500,
            content={"error": type(exc).__name__, "detail": str(exc),
                     "request_id": request_id},
        )

    app.include_router(public_router)
    app.include_router(v1_router)

    # Bundled web console (S23): same-origin SPA at /ui, gated by api.ui_enabled.
    from atlas.web import mount_ui

    mount_ui(app, cfg)
    return app
