"""Tests for the Reader — normalize artifacts to Documents (Stage 3, Step 3 / §5e)."""

from __future__ import annotations

from atlas.research.reader import (
    READ_HTML,
    READ_NONE,
    READ_TEXT,
    SECTION_ABSTRACT,
    SECTION_BODY,
    SECTION_CONCLUSION,
    SECTION_RESULTS,
    Reader,
    split_sections,
)

_PAPER = """Abstract
We measured soiling loss of 0.35 %/day on PV modules.

1. Introduction
Soiling reduces yield.

4. Results
The CNN model reduced RMSE from 3.1% to 1.2%.

Conclusion
Data-driven cleaning saves cost.

References
[1] Smith et al.
"""


def test_split_sections_labels_headings():
    sections = split_sections(_PAPER)
    labels = [s.label for s in sections]
    assert SECTION_ABSTRACT in labels
    assert SECTION_RESULTS in labels
    assert SECTION_CONCLUSION in labels
    abstract = next(s for s in sections if s.label == SECTION_ABSTRACT)
    assert "0.35" in abstract.text


def test_split_sections_no_headings_is_single_body():
    sections = split_sections("just a blob of text with no headings")
    assert len(sections) == 1
    assert sections[0].label == SECTION_BODY


def test_split_sections_empty():
    assert split_sections("") == []


def test_read_text_builds_document_with_sections():
    doc = Reader().read_text(_PAPER, source_id="s1", title="Soiling", url="https://x")
    assert doc.has_text
    assert doc.read_method == READ_TEXT
    assert doc.section(SECTION_ABSTRACT).startswith("We measured")
    assert "1.2%" in doc.section(SECTION_RESULTS)
    assert doc.as_dict()["chars"] == doc.chars


def test_read_text_empty_is_read_none():
    doc = Reader().read_text("   ", source_id="s1")
    assert not doc.has_text
    assert doc.read_method == READ_NONE
    assert doc.sections == []


def test_truncation_flag():
    reader = Reader(max_chars=10)
    doc = reader.read_text("0123456789ABCDEFG", source_id="s1")
    assert doc.truncated
    assert doc.chars == 10


def test_read_path_txt(tmp_path):
    p = tmp_path / "note.txt"
    p.write_text("Results\nvalue is 42 units\n", encoding="utf-8")
    doc = Reader().read_path(p, source_id="s1", content_type="text/plain")
    assert doc.has_text
    assert "42 units" in doc.text
    assert doc.read_method == READ_TEXT


def test_read_path_html(tmp_path):
    p = tmp_path / "page.html"
    p.write_text("<html><body><h1>Abstract</h1><p>loss 0.3%/day</p>"
                 "<script>ignore()</script></body></html>", encoding="utf-8")
    doc = Reader().read_path(p, source_id="s1", content_type="text/html")
    assert doc.read_method == READ_HTML
    assert "0.3%/day" in doc.text
    assert "ignore" not in doc.text  # script stripped


def test_read_path_html_content_type_without_suffix(tmp_path):
    # A page fetched at a bare URL saved without .html still reads via CT sniffing.
    p = tmp_path / "download"
    p.write_text("<html><body>hello <b>world</b></body></html>", encoding="utf-8")
    doc = Reader().read_path(p, source_id="s1", content_type="text/html; charset=utf-8")
    assert doc.read_method == READ_HTML
    assert "hello" in doc.text


def test_read_path_html_flags_paywall_landing(tmp_path):
    # A thin publisher gate: some abstract text but a login wall, not an article.
    p = tmp_path / "gate.html"
    p.write_text(
        "<html><body><h1>Soiling losses in PV</h1>"
        "<p>Abstract: soiling reduces module output.</p>"
        "<p>Sign in to continue reading this article.</p></body></html>",
        encoding="utf-8",
    )
    doc = Reader().read_path(p, source_id="s1", content_type="text/html")
    assert doc.metadata.get("paywall_suspected") is True
    assert doc.failure_code == "paywall"
    assert doc.has_text  # text is kept so the abstract can still be mined
