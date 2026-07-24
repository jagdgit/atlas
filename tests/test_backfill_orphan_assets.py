"""OI-C4 — lazy backfill of orphan knowledge.documents → Assets."""

from __future__ import annotations

from dataclasses import dataclass, replace

from atlas.ingestion.acquire import AcquiredAsset
from atlas.ingestion.service import IngestionService
from atlas.workers.base import TickContext
from atlas.workers.owner_knowledge import OwnerKnowledgeWorker


@dataclass
class _Doc:
    id: str
    source: str = "legacy"
    content: str | None = "hello orphan world"
    title: str | None = "note.txt"
    uri: str | None = "/tmp/note.txt"
    content_type: str = "text/plain"
    asset_id: str | None = None
    asset_version: int | None = None
    domain: str = "personal"
    status: str = "chunked"
    checksum: str = "abc"


class _DocsRepo:
    def __init__(self, docs: list[_Doc]):
        self.docs = {d.id: d for d in docs}

    def list_without_asset(self, *, limit=50):
        out = [d for d in self.docs.values() if d.asset_id is None]
        return out[:limit]

    def count_without_asset(self):
        return sum(1 for d in self.docs.values() if d.asset_id is None)

    def set_asset(self, document_id, asset_id, asset_version=None):
        d = self.docs[str(document_id)]
        linked = replace(d, asset_id=str(asset_id), asset_version=asset_version)
        self.docs[linked.id] = linked
        return linked


class _Knowledge:
    def __init__(self, repo: _DocsRepo):
        self._documents = repo


class _Acquirer:
    def __init__(self):
        self.calls: list[dict] = []
        self._n = 0

    def acquire_bytes(self, data, **kw):
        self._n += 1
        self.calls.append({"data": data, **kw})
        return AcquiredAsset(
            asset_id=f"asset-{self._n}",
            asset_version=1,
            kind="document",
            name="x" * 64,
            checksum="x" * 64,
            content_type=kw.get("content_type"),
            source_uri=kw.get("source_uri"),
            size_bytes=len(data),
            reused=False,
            source=kw.get("source_uri") or "bytes",
        )


def _bridge(docs: list[_Doc]) -> tuple[IngestionService, _DocsRepo, _Acquirer]:
    repo = _DocsRepo(docs)
    acq = _Acquirer()
    # Minimal IngestionService — only backfill uses acquirer + knowledge docs.
    svc = IngestionService.__new__(IngestionService)
    svc._acq = acq
    svc._reader = object()
    svc._knowledge = _Knowledge(repo)
    svc._extractor = None
    svc._candidates = None
    svc._coverage = None
    import logging

    svc._logger = logging.getLogger("test.backfill")
    return svc, repo, acq


def test_backfill_orphan_documents_links_assets():
    svc, repo, acq = _bridge([_Doc(id="d1"), _Doc(id="d2", content="")])
    out = svc.backfill_orphan_documents(limit=10)
    assert out["ok"] is True
    assert out["linked"] == 1
    assert out["errors"] == 1  # empty content
    assert repo.docs["d1"].asset_id == "asset-1"
    assert repo.docs["d1"].asset_version == 1
    assert acq.calls and acq.calls[0]["metadata"]["backfill"] is True


def test_owner_knowledge_tick_backfills():
    svc, repo, _acq = _bridge([_Doc(id="d9")])

    class _Intel:
        def learn_repository(self, **_):
            return {"outcome": "ok", "findings": 0, "experiences": 0}

    worker = OwnerKnowledgeWorker(
        ingestion=svc,
        intelligence=_Intel(),
        personal=None,
        coverage=None,
    )
    result = worker.do_tick(
        TickContext(
            worker_id="w",
            mission_id="m",
            config={"archive_roots": [], "build_profile": False, "backfill_limit": 5},
            config_version=1,
            state={},
            inputs=[],
        )
    )
    assert result.state["last_totals"]["backfilled"] == 1
    assert "backfilled=1" in result.note
    assert repo.docs["d9"].asset_id is not None
