"""Tests for the Librarian — acquire + read top sources (Stage 3, Step 3 / §5d)."""

from __future__ import annotations

from atlas.evidence.models import Source
from atlas.jobs.workspace import JobWorkspace
from atlas.net import OUTCOME_BLOCKED, OUTCOME_ERROR, OUTCOME_OK, FetchResult
from atlas.research.acquire import Librarian, canonical_source_id, citation_pdf_url


class FakeFetcher:
    """Maps a URL to a canned FetchResult (or a default OK html page)."""

    def __init__(self, by_url=None, default=None):
        self._by_url = by_url or {}
        self._default = default
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        if url in self._by_url:
            return self._by_url[url]
        if self._default is not None:
            return self._default
        return FetchResult(url, OUTCOME_OK, content_type="text/html",
                           text="<html><body>Abstract: loss is 0.3%/day</body></html>",
                           content=b"<html><body>Abstract: loss is 0.3%/day</body></html>")


def _src(sid, url, level=2, title="T"):
    return Source(id=sid, url=url, title=title, evidence_level=level)


def test_acquires_and_reads_open_source():
    fetcher = FakeFetcher()
    lib = Librarian(fetcher)
    result = lib.acquire([_src("s1", "https://arxiv.org/abs/1", level=3)])
    assert result.stats["downloaded"] == 1
    assert result.stats["read"] == 1
    assert "0.3%/day" in result.documents[0].text


def test_paywall_source_is_blocked_not_fetched():
    # A publisher domain classifies as paywall → blocked *without* a network call.
    fetcher = FakeFetcher()
    lib = Librarian(fetcher)
    result = lib.acquire([_src("s1", "https://www.sciencedirect.com/science/article/x")])
    assert result.stats["downloaded"] == 0
    assert len(result.blocked) == 1
    assert "paywall" in result.blocked[0]["reason"].lower()
    assert fetcher.calls == []  # never attempted


def test_http_blocked_outcome_is_recorded_as_blocked():
    url = "https://openish.example/paper"
    fetcher = FakeFetcher(by_url={
        url: FetchResult(url, OUTCOME_BLOCKED, reason="HTTP 403: login required")
    })
    lib = Librarian(fetcher)
    result = lib.acquire([_src("s1", url)])
    assert len(result.blocked) == 1
    assert "403" in result.blocked[0]["reason"]


def test_fetch_error_is_skipped_not_fatal():
    url = "https://broken.example/x"
    fetcher = FakeFetcher(by_url={url: FetchResult(url, OUTCOME_ERROR, reason="boom")})
    lib = Librarian(fetcher)
    result = lib.acquire([_src("s1", url)])
    assert result.documents == []
    assert len(result.skipped) == 1


def test_canonical_source_id_collapses_representations():
    # arXiv abstract, PDF, and ar5iv HTML are one logical paper.
    abs_src = Source(id="a", url="https://arxiv.org/abs/2101.00001")
    pdf_src = Source(id="b", url="https://arxiv.org/pdf/2101.00001v2")
    ar5iv = Source(id="c", url="https://ar5iv.labs.arxiv.org/html/2101.00001")
    keys = {canonical_source_id(s) for s in (abs_src, pdf_src, ar5iv)}
    assert len(keys) == 1
    # DOI dominates and normalizes the doi.org prefix.
    d1 = Source(id="d", url="https://ieee.org/x", doi="10.1000/xyz")
    d2 = Source(id="e", url="https://other.org/y", doi="https://doi.org/10.1000/xyz")
    assert canonical_source_id(d1) == canonical_source_id(d2) == "doi:10.1000/xyz"
    # Unrelated pages stay distinct.
    assert canonical_source_id(Source(id="f", url="https://a.org/1")) != canonical_source_id(
        Source(id="g", url="https://a.org/2")
    )


def test_citation_pdf_url_parsing():
    base = "https://ex.example/article/1"
    assert (
        citation_pdf_url(
            '<meta name="citation_pdf_url" content="https://ex.example/a/1.pdf">', base
        )
        == "https://ex.example/a/1.pdf"
    )
    # reversed attribute order + relative href resolved against the base URL
    assert (
        citation_pdf_url('<meta content="/a/1.pdf" name="citation_pdf_url">', base)
        == "https://ex.example/a/1.pdf"
    )
    assert citation_pdf_url("<html>no meta here</html>", base) is None


def test_landing_page_resolves_to_citation_pdf():
    landing = "https://open.example/article/1"
    pdf = "https://open.example/article/1.pdf"
    html = (
        f'<html><head><meta name="citation_pdf_url" content="{pdf}"></head>'
        "<body>Abstract only — full text is in the PDF.</body></html>"
    )
    fulltext = (
        "<html><body>Results: the model reduced RMSE from 3.1% to 1.2%. "
        "SVR outperformed Ridge regression.</body></html>"
    )
    fetcher = FakeFetcher(by_url={
        landing: FetchResult(landing, OUTCOME_OK, content_type="text/html",
                             text=html, content=html.encode()),
        pdf: FetchResult(pdf, OUTCOME_OK, content_type="text/html",
                         text=fulltext, content=fulltext.encode()),
    })
    lib = Librarian(fetcher)
    result = lib.acquire([_src("s1", landing, level=4)])
    doc = result.documents[0]
    assert "outperformed Ridge" in doc.text or "RMSE" in doc.text
    assert doc.metadata.get("resolved_pdf_url") == pdf
    assert pdf in fetcher.calls


def test_one_source_read_exception_does_not_discard_batch(monkeypatch):
    # Regression (2026-07-18): a single source raising during read/resolve used to
    # propagate through the thread pool and discard EVERY already-read document, so
    # the funnel showed 0 acquired/read even though a doc had been written to disk.
    good = _src("good", "https://arxiv.org/abs/1", level=3)
    bad = _src("bad", "https://example.org/paper", level=2)
    lib = Librarian(FakeFetcher(), max_workers=2)

    original = lib._maybe_resolve_pdf

    def boom(doc, res, source, content_type, attempt_url, workspace):
        if source.id == "bad":
            raise RuntimeError("kaboom in resolver")
        return original(doc, res, source, content_type, attempt_url, workspace)

    monkeypatch.setattr(lib, "_maybe_resolve_pdf", boom)

    result = lib.acquire([good, bad])
    ids = {d.source_id for d in result.documents}
    assert "good" in ids  # survivor kept — batch not discarded
    assert "bad" not in ids  # failed source excluded from documents
    assert any(s.get("failure_code") == "parse_error" for s in result.skipped)


def test_video_source_skipped():
    lib = Librarian(FakeFetcher())
    result = lib.acquire([_src("s1", "https://www.youtube.com/watch?v=abcdefghijk")])
    assert len(result.skipped) == 1
    assert "video" in result.skipped[0]["reason"].lower()


def test_document_cap_limits_downloads():
    srcs = [_src(f"s{i}", f"https://ex{i}.example/p") for i in range(5)]
    lib = Librarian(FakeFetcher(), max_documents=2)
    result = lib.acquire(srcs)
    assert result.stats["downloaded"] == 2


def test_open_access_prioritized_over_paywalled_within_cap():
    # 1 open (arxiv) + 1 paywalled (ieee); cap=1 → the open one wins the single slot.
    srcs = [
        _src("pay", "https://ieeexplore.ieee.org/document/1", level=4),
        _src("open", "https://arxiv.org/abs/2", level=3),
    ]
    lib = Librarian(FakeFetcher(), max_documents=1)
    result = lib.acquire(srcs)
    assert result.stats["downloaded"] == 1
    assert result.documents[0].source_id == "open"


def test_workspace_artifacts_and_manifest_written(tmp_path):
    ws = JobWorkspace.for_job(tmp_path, "1")
    ws.init_manifest(objective="x")
    lib = Librarian(FakeFetcher())
    result = lib.acquire([_src("s1", "https://arxiv.org/abs/1", level=3)], workspace=ws)

    # raw artifact saved under downloads/, normalized text under documents/
    assert any(ws.downloads_dir.iterdir())
    assert any(ws.documents_dir.iterdir())
    manifest = ws.load_manifest()
    s1 = next(s for s in manifest["sources"] if s["id"] == "s1")
    assert "read" in s1["stages"]
    assert result.documents[0].has_text


def test_activity_feed_records_progress(tmp_path):
    from atlas.jobs.activity import ActivityRecorder

    ws = JobWorkspace.for_job(tmp_path, "1")
    rec = ActivityRecorder("1", workspace=ws)
    Librarian(FakeFetcher()).acquire(
        [_src("s1", "https://arxiv.org/abs/1", level=3)], workspace=ws, activity=rec
    )
    messages = " ".join(e["message"] for e in ws.read_activity())
    assert "Downloading" in messages
    assert "Read" in messages
    assert "Acquired" in messages
