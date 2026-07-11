"""Structured logging for Atlas.

One place configures logging for the whole system. Everything else just calls
``get_logger(__name__)``.

Design:
    - Console handler (human-readable) at the configured level.
    - Rotating file handler writing to ``<paths.logs>/atlas.log``
      (size + backup count from config; defaults 10MB x 5).
    - Idempotent setup: safe to call ``setup_logging`` multiple times.
    - Level, rotation size, and backup count all come from AtlasConfig.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from atlas.config import AtlasConfig, get_config

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_FILENAME = "atlas.log"

_configured = False


def setup_logging(config: AtlasConfig | None = None, *, force: bool = False) -> Path:
    """Configure root logging handlers. Returns the log file path.

    Idempotent: subsequent calls are no-ops unless ``force=True``.
    """
    global _configured
    cfg = config or get_config()

    log_dir = Path(cfg.paths.logs)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / LOG_FILENAME

    if _configured and not force:
        return log_file

    level = getattr(logging, cfg.logging.level.upper(), logging.INFO)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    root = logging.getLogger()
    root.setLevel(level)

    # Remove existing handlers so re-configuration is clean.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=cfg.logging.max_bytes,
        backupCount=cfg.logging.backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    _configured = True
    return log_file


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a logger, configuring logging on first use."""
    if not _configured:
        setup_logging()
    return logging.getLogger(name if name else "atlas")
