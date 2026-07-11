"""Tests for typed domain models and row mapping (ADR-0036)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from atlas.models import (
    AgentRun,
    Chunk,
    Document,
    HealthRecord,
    Task,
)


def test_from_row_maps_fields_and_stringifies_uuid():
    doc_id = uuid4()
    now = datetime.now(timezone.utc)
    row = {
        "id": doc_id,
        "source": "note",
        "checksum": "abc",
        "content_type": "text/markdown",
        "uri": "/tmp/x.md",
        "title": "X",
        "content": "hello",
        "metadata": {"k": "v"},
        "status": "chunked",
        "created_at": now,
        "updated_at": now,
    }
    doc = Document.from_row(row)
    assert doc.id == str(doc_id)  # UUID normalized to str
    assert isinstance(doc.id, str)
    assert doc.status == "chunked"
    assert doc.metadata == {"k": "v"}
    assert doc.created_at is now


def test_from_row_ignores_extra_columns_and_uses_defaults():
    row = {"id": "d1", "source": "note", "checksum": "c", "extra_col": 123}
    doc = Document.from_row(row)
    assert doc.status == "pending"  # default
    assert doc.metadata == {}  # default factory
    assert not hasattr(doc, "extra_col")


def test_models_are_frozen():
    task = Task.from_row({"id": "t1", "task_type": "embed"})
    with pytest.raises((AttributeError, TypeError)):
        task.status = "running"  # type: ignore[misc]


def test_from_rows_batch():
    rows = [
        {"id": "1", "service": "db", "status": "healthy"},
        {"id": "2", "service": "llm", "status": "unhealthy"},
    ]
    records = HealthRecord.from_rows(rows)
    assert [r.healthy for r in records] == [True, False]


def test_to_dict_roundtrips_shape():
    run = AgentRun.from_row(
        {"id": "r1", "agent_name": "rag", "status": "completed", "input": {"q": "hi"}}
    )
    data = run.to_dict()
    assert data["agent_name"] == "rag"
    assert data["input"] == {"q": "hi"}


def test_chunk_defaults():
    chunk = Chunk.from_row({"id": "c1", "document_id": "d1", "ordinal": 0, "content": "x"})
    assert chunk.token_count is None
    assert chunk.metadata == {}
