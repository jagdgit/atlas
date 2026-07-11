"""LLM errors (provider unreachable, model missing, generation)."""

from __future__ import annotations

from atlas.exceptions.base import AtlasError


class LLMError(AtlasError):
    """Any failure talking to an LLM provider."""


class ProviderUnreachableError(LLMError):
    """The LLM backend (e.g. Ollama) could not be reached."""


class ModelMissingError(LLMError):
    """A required model is not installed on the provider."""


class GenerationError(LLMError):
    """The provider returned an error while generating/embedding."""
