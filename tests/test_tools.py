"""Tests for the ToolRegistry (Sprint 7)."""

from __future__ import annotations

import pytest

from atlas.exceptions import ToolError, ToolNotFoundError
from atlas.kernel.tools import ToolRegistry


def test_register_and_invoke():
    reg = ToolRegistry()
    reg.register("add", lambda a, b: a + b, description="add two numbers")
    assert reg.has("add")
    assert reg.invoke("add", a=2, b=3) == 5


def test_duplicate_registration_raises():
    reg = ToolRegistry()
    reg.register("x", lambda: 1)
    with pytest.raises(ToolError):
        reg.register("x", lambda: 2)


def test_unknown_tool_raises():
    reg = ToolRegistry()
    with pytest.raises(ToolNotFoundError):
        reg.get("nope")
    with pytest.raises(ToolNotFoundError):
        reg.invoke("nope")


def test_describe_is_sorted_catalog():
    reg = ToolRegistry()
    reg.register("b.tool", lambda: 1, description="B", params={"p": "hint"}, plugin="b")
    reg.register("a.tool", lambda: 2, description="A", plugin="a")
    catalog = reg.describe()
    assert [t["name"] for t in catalog] == ["a.tool", "b.tool"]
    assert catalog[1]["params"] == {"p": "hint"}
    assert catalog[0]["plugin"] == "a"
