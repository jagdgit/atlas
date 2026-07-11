"""Tests for the capability registry and plugin seam (ADR-0040/0041)."""

from __future__ import annotations

import pytest

from atlas.exceptions import CapabilityMissingError
from atlas.kernel.capabilities import CapabilityRegistry
from atlas.plugins import BasePlugin, Plugin
from atlas.services.base import HealthStatus


def test_register_has_get_and_names():
    reg = CapabilityRegistry()
    provider = object()
    reg.register("browser", provider, vendor="test")
    assert reg.has("browser")
    assert reg.get("browser") is provider
    assert reg.names() == ["browser"]
    assert reg.describe() == {"browser": {"vendor": "test"}}


def test_missing_capability_raises_typed_error():
    reg = CapabilityRegistry()
    assert reg.has("browser") is False
    with pytest.raises(CapabilityMissingError):
        reg.get("browser")


def test_last_registration_wins():
    reg = CapabilityRegistry()
    reg.register("llm", "a")
    reg.register("llm", "b")
    assert reg.get("llm") == "b"


def test_agent_can_degrade_gracefully_when_absent():
    reg = CapabilityRegistry()
    # The ADR-0040 usage pattern: ask, don't import.
    result = reg.get("browser").search("x") if reg.has("browser") else "no browser"
    assert result == "no browser"


def test_baseplugin_satisfies_plugin_protocol():
    class FsPlugin(BasePlugin):
        name = "filesystem"
        version = "1.0.0"

        def register(self, kernel):
            self.registered = True

    plugin = FsPlugin()
    assert isinstance(plugin, Plugin)
    assert isinstance(plugin.health_check(), HealthStatus)
    assert plugin.health_check().healthy is True
