"""Tests for typed capability contracts + the enhanced registry (S11)."""

from __future__ import annotations

from atlas.capabilities import (
    CAP_KNOWLEDGE,
    CAP_MEMORY,
    CAP_WEB,
    CAPABILITY_CATALOG,
    FetchCapability,
    MemoryCapability,
    describe_capabilities,
)
from atlas.capabilities.contracts import gap_report
from atlas.kernel.capabilities import CapabilityRegistry


class GoodMemory:
    def remember(self, *a, **k):
        return "m"

    def recall(self, *a, **k):
        return []


class NotMemory:
    def only(self):  # missing remember/recall
        return None


class GoodFetch:
    def fetch(self, url, *a, **k):
        return {"url": url}


def test_register_with_contract_and_verify():
    reg = CapabilityRegistry()
    reg.register(CAP_MEMORY, GoodMemory(), contract=MemoryCapability, kind="service")
    assert reg.has(CAP_MEMORY)
    assert reg.verify(CAP_MEMORY) is True
    assert reg.contract_of(CAP_MEMORY) is MemoryCapability


def test_verify_false_when_provider_does_not_implement_contract():
    reg = CapabilityRegistry()
    reg.register(CAP_MEMORY, NotMemory(), contract=MemoryCapability)
    assert reg.has(CAP_MEMORY) is True
    assert reg.verify(CAP_MEMORY) is False


def test_verify_true_without_contract():
    reg = CapabilityRegistry()
    reg.register("scheduler", object(), kind="service")
    assert reg.verify("scheduler") is True


def test_verify_false_for_unregistered():
    assert CapabilityRegistry().verify("nope") is False


def test_missing_is_ordered_and_deduped():
    reg = CapabilityRegistry()
    reg.register(CAP_MEMORY, GoodMemory(), contract=MemoryCapability)
    missing = reg.missing([CAP_MEMORY, CAP_WEB, CAP_KNOWLEDGE, CAP_WEB])
    assert missing == [CAP_WEB, CAP_KNOWLEDGE]


def test_describe_includes_contract_name():
    reg = CapabilityRegistry()
    reg.register(CAP_WEB, GoodFetch(), contract=FetchCapability, kind="plugin")
    described = reg.describe()
    assert described[CAP_WEB]["contract"] == "FetchCapability"
    assert described[CAP_WEB]["kind"] == "plugin"


def test_runtime_checkable_isinstance():
    assert isinstance(GoodMemory(), MemoryCapability)
    assert not isinstance(NotMemory(), MemoryCapability)
    assert isinstance(GoodFetch(), FetchCapability)


def test_catalog_has_core_capabilities():
    for cap_id in (CAP_MEMORY, CAP_KNOWLEDGE, CAP_WEB, "llm", "agent", "search"):
        assert cap_id in CAPABILITY_CATALOG
        spec = CAPABILITY_CATALOG[cap_id]
        assert spec.summary and spec.unlocks and spec.since


def test_describe_capabilities_merges_catalog_and_registry():
    reg = CapabilityRegistry()
    reg.register(CAP_MEMORY, GoodMemory(), contract=MemoryCapability, kind="service")
    rows = {r["id"]: r for r in describe_capabilities(reg)}
    # provided one reflects registry state + kind
    assert rows[CAP_MEMORY]["provided"] is True
    assert rows[CAP_MEMORY]["kind"] == "service"
    # a catalogued-but-unregistered one is surfaced as not provided, with unlocks
    assert rows["search"]["provided"] is False
    assert rows["search"]["unlocks"]
    assert rows["search"]["since"] == "S13"


def test_gap_report_describes_missing():
    report = gap_report([CAP_WEB, "totally-unknown"])
    by_id = {r["missing_capability"]: r for r in report}
    assert by_id[CAP_WEB]["unlocks"]  # catalogued → has unlocks
    assert "not registered" in by_id["totally-unknown"]["reason"]


def test_code_capability_contract_verified():
    from atlas.capabilities import CAP_CODE, CodeCapability
    from atlas.code import CodeParser, CodeService

    reg = CapabilityRegistry()
    reg.register(CAP_CODE, CodeService(CodeParser()), contract=CodeCapability, kind="service")
    assert reg.verify(CAP_CODE) is True
    assert CAPABILITY_CATALOG[CAP_CODE].contract is CodeCapability
    assert CAPABILITY_CATALOG[CAP_CODE].since == "S14"
