"""Tests for the Atlas logging setup.

These tests are hermetic: they redirect the log directory to a pytest tmp_path
so they never depend on (or write to) the real /data/atlas_data/logs.
"""

from __future__ import annotations

import logging
from pathlib import Path

from atlas.config import load_config
from atlas.utils.logging import LOG_FILENAME, get_logger, setup_logging


def _tmp_config(tmp_path: Path):
    cfg = load_config()
    cfg.paths.logs = tmp_path
    return cfg


def test_setup_returns_log_file_path(tmp_path):
    log_file = setup_logging(_tmp_config(tmp_path), force=True)
    assert isinstance(log_file, Path)
    assert log_file.name == LOG_FILENAME
    assert log_file.parent == tmp_path


def test_handlers_configured(tmp_path):
    setup_logging(_tmp_config(tmp_path), force=True)
    root = logging.getLogger()
    handler_types = {type(h).__name__ for h in root.handlers}
    assert "StreamHandler" in handler_types
    assert "RotatingFileHandler" in handler_types


def test_get_logger_writes_to_file(tmp_path):
    log_file = setup_logging(_tmp_config(tmp_path), force=True)
    logger = get_logger("atlas.test")
    marker = "logging-smoke-test-marker"
    logger.info(marker)

    for handler in logging.getLogger().handlers:
        handler.flush()

    assert log_file.exists()
    assert marker in log_file.read_text(encoding="utf-8")


def test_get_logger_named(tmp_path):
    setup_logging(_tmp_config(tmp_path), force=True)
    logger = get_logger("atlas.subsystem")
    assert logger.name == "atlas.subsystem"
