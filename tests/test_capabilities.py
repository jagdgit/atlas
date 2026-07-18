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


# --- Phase 0 §5.10: registry self-inspection enrichment ---------------------


class _Healthy:
    class _Status:
        healthy = True
        detail = "all good"
        data = {"queue": 3}

    def health_check(self):
        return self._Status()

    def metrics(self):
        return {"processed": 42}


class _Crashy:
    def health_check(self):
        raise RuntimeError("boom")


def test_register_records_version_enabled_dependencies():
    reg = CapabilityRegistry()
    reg.register(
        "storage", object(), kind="service",
        version="2.4", enabled=False, dependencies=["clock", "db"],
    )
    described = reg.describe()["storage"]
    assert described["version"] == "2.4"
    assert described["enabled"] is False
    assert described["dependencies"] == ["clock", "db"]


def test_version_of_prefers_explicit_then_attribute():
    reg = CapabilityRegistry()
    reg.register("explicit", object(), version="9.9")

    class _Versioned:
        version = "attr-1.0"

    reg.register("from_attr", _Versioned())
    reg.register("unknown", object())
    assert reg.version_of("explicit") == "9.9"
    assert reg.version_of("from_attr") == "attr-1.0"
    assert reg.version_of("unknown") is None


def test_default_version_fallback():
    reg = CapabilityRegistry(default_version="0.1.0")
    reg.register("plain", object())
    reg.register("explicit", object(), version="3.0")
    assert reg.version_of("plain") == "0.1.0"  # falls back, never hardcoded "v1"
    assert reg.version_of("explicit") == "3.0"  # explicit still wins


def test_inspect_probes_health_and_metrics():
    reg = CapabilityRegistry()
    reg.register("svc", _Healthy(), kind="service", version="1.1")
    info = reg.inspect("svc")
    assert info.healthy is True
    assert info.health_detail == "all good"
    assert info.version == "1.1"
    assert info.metrics["processed"] == 42
    assert info.metrics["health"] == {"queue": 3}


def test_inspect_handles_provider_without_health_check():
    reg = CapabilityRegistry()
    reg.register("plain", object(), kind="kernel")
    info = reg.inspect("plain")
    assert info.healthy is None
    assert info.metrics == {}


def test_inspect_reports_unhealthy_when_health_check_raises():
    reg = CapabilityRegistry()
    reg.register("crashy", _Crashy())
    info = reg.inspect("crashy")
    assert info.healthy is False
    assert "boom" in info.health_detail


def test_inspect_flags_missing_dependencies():
    reg = CapabilityRegistry()
    reg.register("clock", object())
    reg.register("dep", object(), dependencies=["clock", "absent"])
    info = reg.inspect("dep")
    assert info.missing_dependencies == ("absent",)


def test_inspect_unknown_raises():
    import pytest

    from atlas.exceptions import CapabilityMissingError

    with pytest.raises(CapabilityMissingError):
        CapabilityRegistry().inspect("nope")


def test_inspect_all_is_serializable():
    reg = CapabilityRegistry()
    reg.register("svc", _Healthy(), kind="service")
    reg.register("plain", object())
    everything = reg.inspect_all()
    assert set(everything) == {"svc", "plain"}
    assert everything["svc"]["healthy"] is True
    assert "dependencies" in everything["plain"]


def test_runtime_checkable_isinstance():
    assert isinstance(GoodMemory(), MemoryCapability)
    assert not isinstance(NotMemory(), MemoryCapability)
    assert isinstance(GoodFetch(), FetchCapability)


def test_catalog_has_core_capabilities():
    for cap_id in (CAP_MEMORY, CAP_KNOWLEDGE, CAP_WEB, "llm", "agent", "search"):
        assert cap_id in CAPABILITY_CATALOG
        spec = CAPABILITY_CATALOG[cap_id]
        assert spec.summary and spec.unlocks and spec.since
        assert spec.version
        assert spec.cost_class


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
    assert "cost_class" in rows["search"]
    assert "metrics" in rows["search"]


def test_stage_3b_capability_stubs_catalogued_not_provided():
    from atlas.capabilities import (
        CAP_KNOWLEDGE_LIFECYCLE,
        CAP_RETRIEVAL,
        CAP_SYNTHESIS,
        KnowledgeLifecycleCapability,
        RetrievalCapability,
        SynthesisCapability,
    )

    assert CAPABILITY_CATALOG[CAP_RETRIEVAL].contract is RetrievalCapability
    assert CAPABILITY_CATALOG[CAP_RETRIEVAL].since == "3B.1"
    assert CAPABILITY_CATALOG[CAP_RETRIEVAL].version == "1"

    assert CAPABILITY_CATALOG[CAP_SYNTHESIS].contract is SynthesisCapability
    assert CAPABILITY_CATALOG[CAP_SYNTHESIS].since == "3B.2"
    assert CAPABILITY_CATALOG[CAP_SYNTHESIS].version == "1"

    assert CAPABILITY_CATALOG[CAP_KNOWLEDGE_LIFECYCLE].contract is KnowledgeLifecycleCapability
    assert CAPABILITY_CATALOG[CAP_KNOWLEDGE_LIFECYCLE].since == "3B.3"
    assert CAPABILITY_CATALOG[CAP_KNOWLEDGE_LIFECYCLE].version == "1"

    reg = CapabilityRegistry()
    rows = {r["id"]: r for r in describe_capabilities(reg)}
    assert rows[CAP_RETRIEVAL]["provided"] is False
    assert rows[CAP_SYNTHESIS]["provided"] is False
    assert rows[CAP_KNOWLEDGE_LIFECYCLE]["provided"] is False


def test_retrieval_capability_contract_shape():
    from atlas.capabilities import CAP_RETRIEVAL, RetrievalCapability

    class GoodRetrieval:
        def retrieve(self, query, *a, **k):
            return []

    reg = CapabilityRegistry()
    reg.register(CAP_RETRIEVAL, GoodRetrieval(), contract=RetrievalCapability)
    assert reg.verify(CAP_RETRIEVAL) is True
    assert isinstance(GoodRetrieval(), RetrievalCapability)


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


def test_python_capability_contract_verified(tmp_path):
    from atlas.capabilities import CAP_PYTHON, PythonExecutionCapability
    from atlas.sandbox.service import PythonSandboxService

    reg = CapabilityRegistry()
    reg.register(
        CAP_PYTHON, PythonSandboxService(workdir=tmp_path),
        contract=PythonExecutionCapability, kind="service",
    )
    assert reg.verify(CAP_PYTHON) is True
    assert CAPABILITY_CATALOG[CAP_PYTHON].contract is PythonExecutionCapability
    assert CAPABILITY_CATALOG[CAP_PYTHON].since == "S16"


def test_scholar_capability_contract_verified():
    from atlas.capabilities import CAP_SCHOLAR, ScholarCapability
    from atlas.plugins.scholar_plugin import ScholarPlugin

    reg = CapabilityRegistry()
    reg.register(CAP_SCHOLAR, ScholarPlugin([]), contract=ScholarCapability, kind="plugin")
    assert reg.verify(CAP_SCHOLAR) is True
    assert CAPABILITY_CATALOG[CAP_SCHOLAR].contract is ScholarCapability
    assert CAPABILITY_CATALOG[CAP_SCHOLAR].since == "S18"


def test_transcript_capability_contract_verified():
    from atlas.capabilities import CAP_TRANSCRIPT, TranscriptCapability
    from atlas.plugins.youtube_plugin import YouTubePlugin
    from atlas.transcripts import YouTubeTranscriptProvider

    reg = CapabilityRegistry()
    reg.register(
        CAP_TRANSCRIPT, YouTubePlugin(YouTubeTranscriptProvider(None)),
        contract=TranscriptCapability, kind="plugin",
    )
    assert reg.verify(CAP_TRANSCRIPT) is True
    assert CAPABILITY_CATALOG[CAP_TRANSCRIPT].contract is TranscriptCapability
    assert CAPABILITY_CATALOG[CAP_TRANSCRIPT].since == "S18"


def test_learning_capability_contract_verified():
    from atlas.capabilities import CAP_LEARNING, LearningCapability
    from atlas.services.learning_service import LearningService
    from tests.test_learning import FakeLearningRepo

    reg = CapabilityRegistry()
    reg.register(
        CAP_LEARNING, LearningService(FakeLearningRepo()),
        contract=LearningCapability, kind="service",
    )
    assert reg.verify(CAP_LEARNING) is True
    assert CAPABILITY_CATALOG[CAP_LEARNING].contract is LearningCapability
    assert CAPABILITY_CATALOG[CAP_LEARNING].since == "S18"


def test_intelligence_capability_contract_verified():
    from atlas.capabilities import CAP_INTELLIGENCE, IntelligenceCapability
    from atlas.intelligence.service import IntelligenceService
    from atlas.services.learning_service import LearningService
    from tests.test_intelligence import FakeCodeService, FakeIntelRepo
    from tests.test_learning import FakeLearningRepo

    svc = IntelligenceService(
        FakeCodeService(), FakeIntelRepo(), LearningService(FakeLearningRepo())
    )
    reg = CapabilityRegistry()
    reg.register(CAP_INTELLIGENCE, svc, contract=IntelligenceCapability, kind="service")
    assert reg.verify(CAP_INTELLIGENCE) is True
    assert CAPABILITY_CATALOG[CAP_INTELLIGENCE].contract is IntelligenceCapability
    assert CAPABILITY_CATALOG[CAP_INTELLIGENCE].since == "S19"


def test_git_capability_contract_verified():
    from atlas.capabilities import CAP_GIT, GitCapability
    from atlas.plugins.git_plugin import GitPlugin
    from atlas.vcs.git import GitClient

    reg = CapabilityRegistry()
    reg.register(
        CAP_GIT, GitPlugin(GitClient(None)), contract=GitCapability, kind="plugin"
    )
    assert reg.verify(CAP_GIT) is True
    assert CAPABILITY_CATALOG[CAP_GIT].contract is GitCapability
    assert CAPABILITY_CATALOG[CAP_GIT].since == "S20"


def test_sql_capability_contract_verified(tmp_path):
    from atlas.capabilities import CAP_SQL, SQLCapability
    from atlas.plugins.sql_plugin import SQLPlugin
    from atlas.sql.client import SQLClient, SQLiteBackend

    reg = CapabilityRegistry()
    reg.register(
        CAP_SQL, SQLPlugin(SQLClient(SQLiteBackend(tmp_path))),
        contract=SQLCapability, kind="plugin",
    )
    assert reg.verify(CAP_SQL) is True
    assert CAPABILITY_CATALOG[CAP_SQL].contract is SQLCapability
    assert CAPABILITY_CATALOG[CAP_SQL].since == "S20"


def test_ocr_capability_contract_verified(tmp_path):
    from atlas.capabilities import CAP_OCR, OCRCapability
    from atlas.ocr.engine import OCRClient, TesseractEngine
    from atlas.plugins.ocr_plugin import OCRPlugin

    reg = CapabilityRegistry()
    reg.register(
        CAP_OCR, OCRPlugin(OCRClient(TesseractEngine(), tmp_path)),
        contract=OCRCapability, kind="plugin",
    )
    assert reg.verify(CAP_OCR) is True
    assert CAPABILITY_CATALOG[CAP_OCR].contract is OCRCapability
    assert CAPABILITY_CATALOG[CAP_OCR].since == "S20"


def test_mail_capability_contract_verified():
    from atlas.capabilities import CAP_MAIL, MailCapability
    from atlas.mail.client import IMAPBackend, MailClient
    from atlas.plugins.mail_plugin import MailPlugin

    reg = CapabilityRegistry()
    backend = IMAPBackend(host="", port=993, username="", password="")
    reg.register(
        CAP_MAIL, MailPlugin(MailClient(backend)),
        contract=MailCapability, kind="plugin",
    )
    assert reg.verify(CAP_MAIL) is True
    assert CAPABILITY_CATALOG[CAP_MAIL].contract is MailCapability
    assert CAPABILITY_CATALOG[CAP_MAIL].since == "S20"


def test_browser_capability_contract_verified(tmp_path):
    from atlas.browser.browser import BrowserClient, PlaywrightBackend
    from atlas.capabilities import CAP_BROWSER, BrowserCapability
    from atlas.plugins.browser_plugin import BrowserPlugin

    reg = CapabilityRegistry()
    reg.register(
        CAP_BROWSER, BrowserPlugin(BrowserClient(PlaywrightBackend(), tmp_path)),
        contract=BrowserCapability, kind="plugin",
    )
    assert reg.verify(CAP_BROWSER) is True
    assert CAPABILITY_CATALOG[CAP_BROWSER].contract is BrowserCapability
    assert CAPABILITY_CATALOG[CAP_BROWSER].since == "S20"


def test_research_capability_contract_verified():
    from atlas.capabilities import CAP_RESEARCH, ResearchCapability
    from atlas.reports.generator import ReportGenerator
    from atlas.reports.service import ReportService
    from atlas.research.service import ResearchService
    from atlas.verification.engine import VerificationEngine
    from atlas.verification.service import VerificationService

    verification = VerificationService(VerificationEngine())
    service = ResearchService(verification, ReportService(verification, ReportGenerator()))
    reg = CapabilityRegistry()
    reg.register(
        CAP_RESEARCH, service, contract=ResearchCapability, kind="service",
    )
    assert reg.verify(CAP_RESEARCH) is True
    assert CAPABILITY_CATALOG[CAP_RESEARCH].contract is ResearchCapability
    assert CAPABILITY_CATALOG[CAP_RESEARCH].since == "S21"
