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
    KnowledgeError,
    LLMError,
    PluginError,
    ToolNotFoundError,
)

if TYPE_CHECKING:
    from atlas.kernel.application import Application

# Typed errors -> HTTP status. Anything else falls through to a generic 500.
_ERROR_STATUS: list[tuple[type[AtlasError], int]] = [
    (AgentNotFoundError, 404),
    (ToolNotFoundError, 404),
    (CapabilityMissingError, 404),
    (LLMError, 502),  # upstream model backend problem
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

    @app.exception_handler(AtlasError)
    async def _atlas_error_handler(_: Request, exc: AtlasError) -> JSONResponse:
        return JSONResponse(
            status_code=_status_for(exc),
            content={"error": type(exc).__name__, "detail": str(exc)},
        )

    app.include_router(public_router)
    app.include_router(v1_router)
    return app
