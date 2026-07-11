"""Tests for DocumentService (DocumentCapability, S13)."""

from __future__ import annotations

from atlas.documents.service import DocumentService


def test_supported_lists_formats():
    svc = DocumentService()
    assert ".pdf" in svc.supported()
    assert ".docx" in svc.supported()


def test_can_extract():
    svc = DocumentService()
    assert svc.can_extract("/x/report.pdf") is True
    assert svc.can_extract("/x/thing.xyz") is False


def test_extract_ok(tmp_path):
    p = tmp_path / "note.txt"
    p.write_text("Hello Atlas.", encoding="utf-8")
    doc = DocumentService().extract(p)
    assert doc.ok
    assert doc.outcome == "ok"
    assert "Hello Atlas." in doc.text
    assert doc.chars == len(doc.text)
    assert doc.content_type == "text/plain"


def test_extract_unsupported(tmp_path):
    p = tmp_path / "thing.xyz"
    p.write_text("data", encoding="utf-8")
    doc = DocumentService().extract(p)
    assert doc.outcome == "unsupported"
    assert not doc.ok
    assert ".xyz" in doc.reason


def test_extract_empty_file(tmp_path):
    p = tmp_path / "empty.txt"
    p.write_text("   \n  ", encoding="utf-8")
    doc = DocumentService().extract(p)
    assert doc.outcome == "empty"


def test_extract_missing_file(tmp_path):
    doc = DocumentService().extract(tmp_path / "nope.pdf")
    assert doc.outcome == "error"
    assert "not a file" in doc.reason


def test_health_reports_formats():
    h = DocumentService().health_check()
    assert h.healthy
    assert ".pdf" in h.data["formats"]
