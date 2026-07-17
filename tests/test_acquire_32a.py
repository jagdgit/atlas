"""Stage 3.2a acquire helpers — ar5iv preference + biblio metadata."""

from __future__ import annotations

from atlas.evidence.models import Source
from atlas.jobs.workspace import JobWorkspace
from atlas.net import OUTCOME_OK, FetchResult
from atlas.research.acquire import Librarian, ar5iv_html_url, arxiv_id_from_url


def test_arxiv_id_and_ar5iv_url():
    assert arxiv_id_from_url("https://arxiv.org/abs/2301.12345") == "2301.12345"
    assert arxiv_id_from_url("https://arxiv.org/pdf/2301.12345.pdf") == "2301.12345"
    assert (
        ar5iv_html_url("https://arxiv.org/abs/2301.12345")
        == "https://ar5iv.labs.arxiv.org/html/2301.12345"
    )


def test_librarian_prefers_ar5iv_first():
    calls: list[str] = []

    class Fetcher:
        def get(self, url):
            calls.append(url)
            if "ar5iv" in url:
                html = "<html><body><h1>Abstract</h1><p>loss 1.2%/day</p></body></html>"
                return FetchResult(
                    url, OUTCOME_OK, content_type="text/html",
                    text=html, content=html.encode(),
                )
            return FetchResult(url, OUTCOME_OK, content_type="text/html",
                               text="<html><body>fallback</body></html>",
                               content=b"<html><body>fallback</body></html>")

    src = Source(
        id="s1",
        url="https://arxiv.org/abs/2301.12345",
        title="Soiling",
        evidence_level=3,
        doi="10.48550/arXiv.2301.12345",
        citation="Doe (2023). Soiling.",
        authors=("Jane Doe",),
        year=2023,
        venue="arXiv",
    )
    result = Librarian(Fetcher(), prefer_ar5iv=True).acquire([src])
    assert calls[0].startswith("https://ar5iv.labs.arxiv.org/html/")
    assert result.stats["read"] == 1
    doc = result.documents[0]
    assert "1.2%/day" in doc.text
    assert doc.metadata.get("doi") == "10.48550/arXiv.2301.12345"
    assert doc.metadata.get("year") == 2023
    assert doc.quality == "full"


def test_empty_read_surfaces_failure_code(tmp_path):
    class Fetcher:
        def get(self, url):
            # Minimal PDF bytes that pypdf accepts but has no text.
            from pypdf import PdfWriter
            from io import BytesIO

            buf = BytesIO()
            w = PdfWriter()
            w.add_blank_page(width=100, height=100)
            w.write(buf)
            return FetchResult(
                url, OUTCOME_OK, content_type="application/pdf",
                content=buf.getvalue(), text="",
            )

    # Disable OCR so empty PDF stays empty with an explicit code.
    from atlas.research.reader import Reader

    ws = JobWorkspace.for_job(tmp_path, "1")
    lib = Librarian(Fetcher(), reader=Reader(ocr_enabled=False), prefer_ar5iv=False)
    src = Source(id="pdf1", url="https://ex.com/a.pdf", title="Blank", evidence_level=2)
    result = lib.acquire([src], workspace=ws)
    assert result.stats["downloaded"] == 1
    doc = result.documents[0]
    assert not doc.has_text
    assert doc.failure_code  # surfaced, not silent
