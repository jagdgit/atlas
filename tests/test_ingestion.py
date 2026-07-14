"""Tests for the filesystem ingestion source and its text extractors.

All hermetic: extractors run on files written to tmp_path; the source is driven
with an in-memory fake knowledge service. No DB or Ollama required.
"""

from __future__ import annotations

from atlas.ingestion.extractors import content_type_for, extract
from atlas.ingestion.filesystem_source import FilesystemSource


# --- helpers --------------------------------------------------------------
def _make_pdf(text: str) -> bytes:
    """Build a minimal single-page PDF whose text layer is ``text``."""
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 200]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length %d>>\nstream\nBT /F1 20 Tf 20 100 Td (%s) Tj ET\nendstream"
        % (len(text) + 30, text.encode()),
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj" % i + o + b"endobj\n"
    xref_pos = len(out)
    out += b"xref\n0 %d\n" % (len(objs) + 1)
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF" % (
        len(objs) + 1,
        xref_pos,
    )
    return out


# --- extractors -----------------------------------------------------------
def test_extract_text_and_markdown(tmp_path):
    txt = tmp_path / "a.txt"
    txt.write_text("plain text content", encoding="utf-8")
    md = tmp_path / "b.md"
    md.write_text("# Heading\n\nbody", encoding="utf-8")
    assert extract(txt) == "plain text content"
    assert "Heading" in extract(md)


def test_extract_empty_returns_none(tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_text("   \n  ", encoding="utf-8")
    assert extract(empty) is None


def test_extract_html_strips_tags(tmp_path):
    html = tmp_path / "page.html"
    html.write_text(
        "<html><head><style>.x{}</style><script>bad()</script></head>"
        "<body><h1>Title</h1><p>Hello world</p></body></html>",
        encoding="utf-8",
    )
    text = extract(html)
    assert "Title" in text
    assert "Hello world" in text
    assert "bad()" not in text  # script stripped
    assert "<" not in text


def test_extract_pdf_text_layer(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(_make_pdf("Hello Atlas PDF"))
    assert extract(pdf) == "Hello Atlas PDF"


def test_extract_unsupported_extension(tmp_path):
    weird = tmp_path / "x.bin"
    weird.write_text("data", encoding="utf-8")
    assert extract(weird) is None


def test_content_type_mapping(tmp_path):
    assert content_type_for(tmp_path / "a.pdf") == "application/pdf"
    assert content_type_for(tmp_path / "a.md") == "text/markdown"
    assert content_type_for(tmp_path / "a.html") == "text/html"
    assert content_type_for(tmp_path / "a.txt") == "text/plain"


# --- filesystem source ----------------------------------------------------
class FakeKnowledge:
    """Records ingest calls; simulates checksum dedup + status pipeline."""

    def __init__(self):
        self.ingests = []
        self.embedded = []
        self._by_checksum = {}
        self._n = 0

    def ingest_text(self, source, content, *, uri=None, title=None,
                    content_type="text/plain", metadata=None, embed=True,
                    domain="external"):
        import hashlib

        digest = hashlib.sha256(content.encode()).hexdigest()
        self.ingests.append({"uri": uri, "content_type": content_type, "domain": domain})
        if digest in self._by_checksum:
            return self._by_checksum[digest]
        self._n += 1
        summary = {
            "document_id": f"doc-{self._n}",
            "status": "chunked",
            "chunks": 1,
            "deduped": False,
        }
        self._by_checksum[digest] = {**summary, "deduped": True, "status": "embedded"}
        return summary

    def embed_document(self, document_id):
        self.embedded.append(document_id)
        return {"document_id": document_id, "status": "embedded"}


class RecordingEnqueue:
    def __init__(self):
        self.calls = []

    def __call__(self, task_type, payload, *, delay_seconds=0.0, **kw):
        self.calls.append((task_type, payload, delay_seconds))


def test_discover_matches_configured_extensions(tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "b.md").write_text("y", encoding="utf-8")
    (tmp_path / "c.log").write_text("z", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "d.txt").write_text("w", encoding="utf-8")

    src = FilesystemSource(
        FakeKnowledge(), documents_dir=tmp_path, extensions=[".txt", ".md"]
    )
    names = [p.name for p in src.discover()]
    assert names == ["a.txt", "b.md", "d.txt"]  # recursive, .log excluded


def test_scan_ingests_and_enqueues_embed(tmp_path):
    (tmp_path / "a.txt").write_text("hello world", encoding="utf-8")
    kb = FakeKnowledge()
    enq = RecordingEnqueue()
    src = FilesystemSource(kb, documents_dir=tmp_path, enqueue=enq)

    result = src.scan()
    assert result == {"scanned": 1, "ingested": 1, "enqueued": 1, "skipped": 0}
    assert enq.calls[0][0] == "embed_document"
    assert kb.ingests[0]["content_type"] == "text/plain"


def test_scan_without_enqueue_embeds_inline(tmp_path):
    (tmp_path / "a.txt").write_text("hello world", encoding="utf-8")
    kb = FakeKnowledge()
    src = FilesystemSource(kb, documents_dir=tmp_path, enqueue=None)
    src.scan()
    assert kb.embedded == ["doc-1"]  # embedded inline (no scheduler)


def test_scan_skips_unchanged_already_embedded(tmp_path):
    (tmp_path / "a.txt").write_text("stable content", encoding="utf-8")
    kb = FakeKnowledge()
    src = FilesystemSource(kb, documents_dir=tmp_path, enqueue=RecordingEnqueue())
    first = src.scan()
    assert first["ingested"] == 1
    second = src.scan()  # unchanged -> dedup hit, already embedded
    assert second == {"scanned": 1, "ingested": 0, "enqueued": 0, "skipped": 1}


def test_scan_skips_unextractable(tmp_path):
    (tmp_path / "empty.txt").write_text("   ", encoding="utf-8")
    kb = FakeKnowledge()
    src = FilesystemSource(kb, documents_dir=tmp_path)
    result = src.scan()
    assert result == {"scanned": 1, "ingested": 0, "enqueued": 0, "skipped": 1}


def test_scan_task_reenqueues_when_periodic(tmp_path):
    kb = FakeKnowledge()
    enq = RecordingEnqueue()
    src = FilesystemSource(
        kb, documents_dir=tmp_path, enqueue=enq, scan_interval=300
    )
    src.scan_task({})
    assert ("ingest_scan", {}, 300.0) in enq.calls


def test_start_seeds_scan_only_when_none_pending(tmp_path):
    kb = FakeKnowledge()
    enq = RecordingEnqueue()
    # No pending scan -> seeds one.
    src = FilesystemSource(
        kb, documents_dir=tmp_path, enqueue=enq,
        count_pending=lambda t: 0, scan_interval=300, enabled=True,
    )
    src.start()
    assert any(c[0] == "ingest_scan" for c in enq.calls)

    # Already pending -> does not seed another.
    enq2 = RecordingEnqueue()
    src2 = FilesystemSource(
        kb, documents_dir=tmp_path, enqueue=enq2,
        count_pending=lambda t: 1, scan_interval=300, enabled=True,
    )
    src2.start()
    assert enq2.calls == []


def test_start_noop_when_manual_or_disabled(tmp_path):
    enq = RecordingEnqueue()
    FilesystemSource(
        FakeKnowledge(), documents_dir=tmp_path, enqueue=enq,
        count_pending=lambda t: 0, scan_interval=0, enabled=True,
    ).start()
    assert enq.calls == []  # scan_interval 0 => manual only
