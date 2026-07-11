"""Tests for the typed exception hierarchy (ADR-0037)."""

from __future__ import annotations

import atlas.exceptions as exc


def test_every_domain_error_descends_from_atlas_error():
    for name in exc.__all__:
        err = getattr(exc, name)
        assert issubclass(err, exc.AtlasError), name


def test_domain_subclasses_group_correctly():
    assert issubclass(exc.DatabaseConnectionError, exc.DatabaseError)
    assert issubclass(exc.MigrationError, exc.DatabaseError)
    assert issubclass(exc.QueryError, exc.DatabaseError)
    assert issubclass(exc.ProviderUnreachableError, exc.LLMError)
    assert issubclass(exc.ModelMissingError, exc.LLMError)
    assert issubclass(exc.GenerationError, exc.LLMError)
    assert issubclass(exc.EmbeddingMismatchError, exc.KnowledgeError)
    assert issubclass(exc.IngestError, exc.KnowledgeError)
    assert issubclass(exc.SearchError, exc.KnowledgeError)
    assert issubclass(exc.AgentNotFoundError, exc.AgentError)
    assert issubclass(exc.AgentRunError, exc.AgentError)
    assert issubclass(exc.PluginLoadError, exc.PluginError)
    assert issubclass(exc.CapabilityMissingError, exc.PluginError)


def test_details_are_captured_and_kept_out_of_message():
    err = exc.EmbeddingMismatchError("bad count", expected=2, got=1)
    assert str(err) == "bad count"
    assert err.details == {"expected": 2, "got": 1}


def test_catch_broadly_by_root():
    try:
        raise exc.AgentNotFoundError("nope", agent="x")
    except exc.AtlasError as caught:
        assert caught.details["agent"] == "x"


def test_ollama_error_is_llm_error():
    from atlas.llm.ollama_provider import OllamaError

    assert issubclass(OllamaError, exc.LLMError)
