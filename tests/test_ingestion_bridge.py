"""Tests for the unified ingestion bridge (Phase C · §C.2, CC2).

Hermetic tests use light fakes to verify the bridge *orchestration* (acquire → read → ingest,
provenance threading, honest handling of unreadable inputs). A live-DB e2e wires the real Asset
Store + Storage + Derived Artifact Store + Document Reader + KnowledgeService (embed disabled so
the test stays DB-only, no LLM) and proves the document↔asset link (migration 0028) and dedup.
"""

from __future__ import annotations

import pytest

from atlas.ingestion.acquire import AcquiredAsset
from atlas.ingestion.service import IngestionService, IngestResult


# --- fakes ---------------------------------------------------------------
def _acquired(reused=False):
    return AcquiredAsset(
        asset_id="asset-1", asset_version=1, kind="document",
        name="sha", checksum="sha", content_type="text/plain",
        source_uri="/tmp/note.txt", size_bytes=10, reused=reused, source="note.txt",
    )


class FakeAcquirer:
    def __init__(self, acquired):
        self._acquired = acquired
        self.calls: list = []

    def acquire_file(self, path, *, kind="document", metadata=None):
        self.calls.append(("file", str(path), kind))
        return self._acquired

    def acquire_bytes(self, data, *, kind="document", filename=None, source_uri=None, metadata=None):
        self.calls.append(("bytes", filename, kind))
        return self._acquired


class FakeReader:
    id = "document"
    VERSION = "1.0.0"

    def __init__(self, artifact):
        self._artifact = artifact
        self.read_args = None

    def read(self, asset_id, asset_version=None, *, filename=None, force=False):
        self.read_args = (asset_id, asset_version, filename)
        return self._artifact


class FakeKnowledge:
    def __init__(self, summary):
        self._summary = summary
        self.ingest_kwargs = None

    def ingest_text(self, source, content, **kw):
        self.ingest_kwargs = {"source": source, "content": content, **kw}
        return self._summary


def _artifact(outcome="ok", text="hello world"):
    return {
        "reader": "document", "reader_version": "1.0.0",
        "asset_id": "asset-1", "asset_version": 1, "outcome": outcome,
        "content_type": "text/plain", "extension": ".txt", "text": text,
        "chars": len(text), "reason": None,
        "sections": [{"ordinal": 0, "text": text}] if text else [],
    }


# --- hermetic ------------------------------------------------------------
def test_bridge_acquires_reads_and_ingests_with_provenance():
    acq = FakeAcquirer(_acquired())
    reader = FakeReader(_artifact())
    know = FakeKnowledge({"document_id": "doc-1", "status": "chunked", "chunks": 3, "deduped": False})
    svc = IngestionService(acq, reader, know)

    result = svc.ingest_bytes(b"hello world", filename="note.txt", domain="external", embed=False)

    assert isinstance(result, IngestResult) and result.ok
    assert result.document_id == "doc-1" and result.chunks == 3
    # The reader was asked to read the acquired asset with the right filename.
    assert reader.read_args == ("asset-1", 1, "note.txt")
    # The asset provenance was threaded into the knowledge ingest (P9 traceability).
    kw = know.ingest_kwargs
    assert kw["asset_id"] == "asset-1" and kw["asset_version"] == 1
    assert kw["metadata"]["sha256"] == "sha"
    assert kw["metadata"]["reader"] == "document"
    assert kw["embed"] is False


def test_bridge_reports_unreadable_input_without_ingesting():
    acq = FakeAcquirer(_acquired())
    reader = FakeReader(_artifact(outcome="unsupported", text=""))
    know = FakeKnowledge({"document_id": "doc-x", "chunks": 1})
    svc = IngestionService(acq, reader, know)

    result = svc.ingest_bytes(b"\x00\x01", filename="thing.zip")
    assert result.outcome == "unsupported"
    assert result.document_id is None and result.chunks == 0
    assert know.ingest_kwargs is None  # never tried to ingest empty/unsupported content


def test_bridge_treats_blank_text_as_no_ingest():
    acq = FakeAcquirer(_acquired())
    reader = FakeReader(_artifact(outcome="ok", text="   \n  "))
    know = FakeKnowledge({"document_id": "doc-y"})
    svc = IngestionService(acq, reader, know)
    result = svc.ingest_bytes(b"whitespace", filename="blank.txt")
    assert result.document_id is None
    assert know.ingest_kwargs is None


def test_bridge_propagates_asset_reuse_flag():
    acq = FakeAcquirer(_acquired(reused=True))
    reader = FakeReader(_artifact())
    know = FakeKnowledge({"document_id": "doc-1", "chunks": 2, "deduped": True})
    svc = IngestionService(acq, reader, know)
    result = svc.ingest_bytes(b"hello world", filename="note.txt")
    assert result.asset_reused is True and result.deduped is True


class FakeCoverage:
    def __init__(self):
        self.records: list[dict] = []

    def record(self, asset_id, asset_version, reader, reader_version, **kw):
        self.records.append({"asset_id": asset_id, "asset_version": asset_version,
                             "reader": reader, "reader_version": reader_version, **kw})
        return {"id": "cov-1"}


def test_bridge_records_coverage_on_success():
    acq = FakeAcquirer(_acquired())
    reader = FakeReader(_artifact())
    know = FakeKnowledge({"document_id": "doc-1", "chunks": 3, "deduped": False})
    cov = FakeCoverage()
    svc = IngestionService(acq, reader, know, coverage=cov)

    svc.ingest_bytes(b"hello world", filename="note.txt", domain="external", embed=False)
    assert len(cov.records) == 1
    rec = cov.records[0]
    assert rec["asset_id"] == "asset-1" and rec["reader"] == "document"
    assert rec["status"] == "done" and rec["chunks_count"] == 3
    assert rec["domain"] == "external" and rec["source"] == "document"


def test_bridge_records_failed_coverage_for_unreadable_input():
    acq = FakeAcquirer(_acquired())
    reader = FakeReader(_artifact(outcome="unsupported", text=""))
    know = FakeKnowledge({"document_id": "doc-x"})
    cov = FakeCoverage()
    svc = IngestionService(acq, reader, know, coverage=cov)

    svc.ingest_bytes(b"\x00\x01", filename="thing.zip")
    assert len(cov.records) == 1
    assert cov.records[0]["status"] == "unsupported"


def test_bridge_coverage_failure_never_breaks_ingest():
    class BoomCoverage:
        def record(self, *a, **k):
            raise RuntimeError("db down")

    acq = FakeAcquirer(_acquired())
    reader = FakeReader(_artifact())
    know = FakeKnowledge({"document_id": "doc-1", "chunks": 1})
    svc = IngestionService(acq, reader, know, coverage=BoomCoverage())
    result = svc.ingest_bytes(b"hello world", filename="note.txt", embed=False)
    assert result.ok  # coverage is best-effort telemetry, not a gate


# --- live DB e2e ---------------------------------------------------------
@pytest.fixture(scope="module")
def db():
    from atlas.database.connection import DatabaseManager

    manager = DatabaseManager()
    try:
        if not manager.health_check():
            pytest.skip("database health check failed")
    except Exception as exc:  # noqa: BLE001 - any connection error means skip
        pytest.skip(f"database unreachable: {exc}")
    yield manager
    manager.close()


class _StubLLM:
    """Never called (embed=False path); present only to satisfy the constructor."""

    embedding_model = "stub"

    def embed(self, texts, **kw):  # pragma: no cover - must not run in this test
        raise AssertionError("embed should not be called with embed=False")


def test_unified_ingestion_links_document_to_asset_live(db, tmp_path):
    import uuid

    from atlas.assets import AssetRepository, AssetStore
    from atlas.engineering.artifacts import DerivedArtifactStore
    from atlas.ingestion.acquire import AssetAcquirer
    from atlas.knowledge.service import KnowledgeService
    from atlas.readers.document import DocumentReader
    from atlas.repositories.chunk_repo import ChunkRepository
    from atlas.repositories.document_repo import DocumentRepository
    from atlas.repositories.embedding_repo import EmbeddingRepository
    from atlas.storage.repository import StorageRepository
    from atlas.storage.service import StorageManager

    storage = StorageManager(tmp_path / "storage", StorageRepository(db))
    storage.start()
    assets = AssetStore(storage, AssetRepository(db))
    artifacts = DerivedArtifactStore(storage)
    documents = DocumentRepository(db)
    knowledge = KnowledgeService(
        documents, ChunkRepository(db), EmbeddingRepository(db), _StubLLM(),
        embedding_model="stub", chunk_max_words=8, chunk_overlap=2,
    )
    svc = IngestionService(AssetAcquirer(assets), DocumentReader(assets, artifacts), knowledge)

    token = uuid.uuid4().hex
    body = (
        f"# Phase C unified ingestion {token}\n\n"
        "Atlas turns a document asset into searchable chunks through one pipeline. "
        "This paragraph exists so the chunker produces more than a single chunk.\n"
    ).encode("utf-8")

    result = svc.ingest_bytes(body, filename=f"phase_c_{token}.md", domain="external", embed=False)
    assert result.ok and result.document_id is not None
    assert result.asset_reused is False and result.chunks >= 1

    # The document is linked back to the asset it was read from (migration 0028, P9).
    doc = documents.get(result.document_id)
    assert doc is not None
    assert doc.asset_id == result.asset_id
    assert doc.asset_version == result.asset_version
    assert documents.get_by_asset(result.asset_id).id == result.document_id

    # Re-ingesting the identical bytes reuses the same content-addressed asset and resolves to
    # the same (checksum-deduped) document row — one asset, one document, no duplicate bytes.
    # (The `deduped` no-op short-circuit only fires on the embed path, where status='embedded'.)
    again = svc.ingest_bytes(body, filename=f"phase_c_{token}.md", domain="external", embed=False)
    assert again.asset_reused is True
    assert again.document_id == result.document_id
    assert again.asset_id == result.asset_id
