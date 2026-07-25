"""OI-C1/C2 — neutral packages + document/conversation registry."""

from __future__ import annotations

from atlas.artifacts import DerivedArtifactStore, artifact_key
from atlas.engineering import artifacts as eng_artifacts
from atlas.engineering import readers as eng_readers
from atlas.readers.registry import (
    CAP_SECTIONS,
    CAP_TABLES,
    CAP_TEXT,
    ReaderRegistry,
    default_document_readers,
)


def test_artifacts_reexport_and_key():
    assert eng_artifacts.DerivedArtifactStore is DerivedArtifactStore
    assert artifact_key("a", 1, "document", "1.0.0") == "a-v1-document-1.0.0"


def test_readers_reexport():
    assert eng_readers.ReaderRegistry is ReaderRegistry
    assert eng_readers.CAP_SECTIONS == CAP_SECTIONS


def test_document_and_conversation_registered():
    reg = ReaderRegistry()
    assert reg.get("document") is not None
    assert reg.get("conversation") is not None
    doc = reg.get("document")
    assert doc.supports(CAP_TEXT)
    assert doc.supports(CAP_SECTIONS)
    assert doc.supports(CAP_TABLES) is False  # honest
    assert reg.can_produce(CAP_TEXT, language="document")["supported"] is True
    assert reg.VERSION.startswith("2.")


def test_default_document_readers_ids():
    ids = {r.id for r in default_document_readers()}
    assert ids == {"document", "conversation"}
