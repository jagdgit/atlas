"""Root of the Atlas exception hierarchy (ADR-0037).

Every Atlas-specific error inherits from :class:`AtlasError`, so callers can catch
the whole family with one ``except AtlasError`` while telemetry and boundaries can
still discriminate by domain subclass. Bare ``RuntimeError`` / ``KeyError`` /
``Exception`` should not cross module boundaries; raise a typed error instead.
"""

from __future__ import annotations

from typing import Any


class AtlasError(Exception):
    """Base class for all Atlas errors.

    Carries an optional ``details`` mapping so failures can be classified or
    logged with structured context without parsing message strings.
    """

    def __init__(self, message: str = "", **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details

    def __str__(self) -> str:  # keep details out of the primary message
        return self.message or self.__class__.__name__
