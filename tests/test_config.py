"""Tests for the Atlas configuration manager."""

from __future__ import annotations

from pathlib import Path

from atlas.config import get_config, load_config
from atlas.config.manager import AtlasConfig


def test_load_config_returns_typed_object():
    config = load_config()
    assert isinstance(config, AtlasConfig)


def test_system_defaults():
    config = load_config()
    assert config.system.name == "Atlas"
    assert config.system.timezone == "UTC"


def test_paths_are_paths():
    config = load_config()
    assert isinstance(config.paths.data, Path)
    assert str(config.paths.logs).startswith("/data/atlas_data")


def test_database_password_from_env(monkeypatch):
    monkeypatch.setenv("ATLAS_DB_PASSWORD", "secret-value")
    config = load_config()
    assert config.database.password == "secret-value"


def test_env_override_for_section_key(monkeypatch):
    monkeypatch.setenv("ATLAS_DATABASE_POOL_SIZE", "17")
    config = load_config()
    assert config.database.pool_size == 17


def test_get_config_is_singleton():
    a = get_config()
    b = get_config()
    assert a is b


def test_password_hidden_in_repr(monkeypatch):
    monkeypatch.setenv("ATLAS_DB_PASSWORD", "topsecret")
    config = load_config()
    assert "topsecret" not in repr(config.database)
