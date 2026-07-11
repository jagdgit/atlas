"""Atlas REST API (Sprint 5, ADR-0045).

A FastAPI surface over the kernel's services. ``create_app`` builds the app from a
running ``Application``; ``serve`` runs it under uvicorn.
"""

from __future__ import annotations

from atlas.api.app import create_app
from atlas.api.server import serve

__all__ = ["create_app", "serve"]
