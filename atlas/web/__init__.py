"""Bundled web console (Stage 2, S23).

A **zero-build**, dependency-free single-page app (vanilla HTML/CSS/JS) served by
the same FastAPI app as the REST API, so it runs same-origin (no CORS) and needs no
Node toolchain — consistent with Atlas's zero-heavy-deps ethos.

``mount_ui(app, config)`` mounts the static assets at ``/ui`` and redirects ``/`` to
it, gated by ``api.ui_enabled``. The shell is public; the app authenticates every
``/v1`` call with the operator's API key (entered once, kept in ``localStorage``).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

    from atlas.config import AtlasConfig

STATIC_DIR = Path(__file__).resolve().parent / "static"


def static_dir() -> Path:
    """Absolute path to the bundled static assets directory."""
    return STATIC_DIR


def mount_ui(app: "FastAPI", config: "AtlasConfig") -> bool:
    """Mount the web console on ``app`` when enabled. Returns True if mounted."""
    if not config.api.ui_enabled:
        return False
    if not STATIC_DIR.is_dir():
        return False

    from fastapi.responses import RedirectResponse
    from fastapi.staticfiles import StaticFiles

    # html=True serves index.html at the mount root (/ui/) and resolves relative assets.
    app.mount("/ui", StaticFiles(directory=str(STATIC_DIR), html=True), name="ui")

    @app.get("/", include_in_schema=False)
    def _root() -> RedirectResponse:  # pragma: no cover - trivial redirect
        return RedirectResponse(url="/ui/")

    return True
