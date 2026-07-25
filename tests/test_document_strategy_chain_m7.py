"""OI-M7 DocumentReader PDF strategy chain (text layer → OCR)."""

from __future__ import annotations

from atlas.documents.service import ExtractedDocument
from atlas.readers.document import DocumentReader


class FakeAssets:
    def __init__(self):
        self._blobs = {}
        self._versions = {}

    def add(self, asset_id, version, data, *, filename=None):
        self._blobs[(asset_id, version)] = data
        meta = {"filename": filename} if filename else {}
        self._versions.setdefault(asset_id, []).append({"version": version, "metadata": meta})

    def get_bytes(self, asset_id, version=None):
        if version is None:
            version = self.versions(asset_id)[0]["version"]
        return self._blobs[(asset_id, version)]

    def versions(self, asset_id):
        return list(reversed(self._versions.get(asset_id, [])))


class FakeArts:
    def __init__(self):
        self.store = {}

    def get(self, *a):
        return None

    def put(self, asset_id, version, reader, reader_version, artifact):
        self.store[(asset_id, version, reader, reader_version)] = artifact


class StrongDocs:
    def extract(self, path):
        return ExtractedDocument(
            path=str(path),
            text="A" * 80,
            outcome="ok",
            content_type="application/pdf",
            reason=None,
        )


class WeakDocs:
    def extract(self, path):
        return ExtractedDocument(
            path=str(path),
            text="tiny",
            outcome="ok",
            content_type="application/pdf",
            reason=None,
        )


def test_pdf_text_layer_wins_without_ocr():
    assets = FakeAssets()
    assets.add("d1", 1, b"%PDF-1.4", filename="x.pdf")
    arts = FakeArts()
    reader = DocumentReader(assets, arts, documents=StrongDocs(), min_pdf_text_chars=40)
    art = reader.read("d1", 1, filename="x.pdf")
    assert art["outcome"] == "ok"
    assert art["method"] == "pdf_text_layer"
    assert art["strategies_tried"][0]["name"] == "pdf_text_layer"
    assert art["strategies_tried"][0]["ok"] is True
    # OCR not needed — may or may not be attempted; text layer wins first.
    assert len(art["text"]) >= 40


def test_pdf_ocr_wins_when_text_weak():
    assets = FakeAssets()
    assets.add("d2", 1, b"%PDF-1.4", filename="y.pdf")
    arts = FakeArts()

    def fake_ocr(path):
        return {"outcome": "ok", "text": "OCR recovered slide text about markets"}

    reader = DocumentReader(
        assets,
        arts,
        documents=WeakDocs(),
        pdf_ocr=fake_ocr,
        min_pdf_text_chars=40,
    )
    art = reader.read("d2", 1, filename="y.pdf")
    assert art["outcome"] == "ok"
    assert art["method"] == "pdf_ocr"
    assert "OCR recovered" in art["text"]
    names = [t["name"] for t in art["strategies_tried"]]
    assert names == ["pdf_text_layer", "pdf_ocr"]
