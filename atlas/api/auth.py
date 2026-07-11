"""API-key authentication (ADR-0046).

Clients send ``Authorization: Bearer <key>``; the key is compared (constant-time)
against the configured set (``api.keys`` from ``ATLAS_API_KEYS``). If no keys are
configured the API **fails closed** — every protected route returns 401 — so a
misconfigured deployment is never accidentally open.
"""

from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False, description="API key as a bearer token")

_UNAUTHORIZED = {"WWW-Authenticate": "Bearer"}


def require_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    keys: list[str] = list(getattr(request.app.state, "api_keys", ()))
    if not keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API authentication is not configured (no keys set)",
            headers=_UNAUTHORIZED,
        )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or malformed bearer token",
            headers=_UNAUTHORIZED,
        )
    token = credentials.credentials
    if not any(hmac.compare_digest(token, key) for key in keys):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid API key",
            headers=_UNAUTHORIZED,
        )
