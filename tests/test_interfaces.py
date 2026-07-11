"""Tests for the provider interfaces (ADR-0038).

These lock the "depend on abstractions" seam: the concrete backends must satisfy
the protocols structurally, so a service typed against the protocol keeps working
if the backend is swapped.
"""

from __future__ import annotations

from atlas.database.connection import DatabaseManager
from atlas.interfaces import (
    EmbeddingProvider,
    LLMProvider,
    StorageProvider,
)
from atlas.llm.ollama_provider import OllamaProvider


def test_ollama_satisfies_llm_and_embedding_providers():
    provider = OllamaProvider(client=object())  # no network; structural check only
    assert isinstance(provider, LLMProvider)
    assert isinstance(provider, EmbeddingProvider)


def test_database_manager_satisfies_storage_provider():
    assert isinstance(DatabaseManager, type)
    # Structural check on an instance (no pool opened until used).
    manager = DatabaseManager.__new__(DatabaseManager)
    assert isinstance(manager, StorageProvider)


def test_embedding_provider_is_narrower_than_llm_provider():
    # A pure embedding backend need not implement chat/generate.
    class EmbedOnly:
        name = "embed-only"

        def embed(self, texts, **options):  # noqa: D401
            return []

        def health(self):
            return True

    assert isinstance(EmbedOnly(), EmbeddingProvider)
    assert not isinstance(EmbedOnly(), LLMProvider)
