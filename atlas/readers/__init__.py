"""Neutral reader package (Phase C · §C.2, constitution P11).

Readers are **stateless translators**: they turn an Asset into a structured Artifact
(``Asset → Reader → Artifact → Extraction → Knowledge``) and own no knowledge, state, or
decisions. The first non-code reader — the Document Reader — lives here rather than under
``atlas.engineering`` because ingestion is global, not engineering-specific (P12).
"""

from __future__ import annotations

from atlas.readers.conversation import (
    CONVERSATION_READER_ID,
    CONVERSATION_READER_VERSION,
    ConversationReader,
)
from atlas.readers.document import (
    DOCUMENT_READER_ID,
    DOCUMENT_READER_VERSION,
    DocumentReader,
)

__all__ = [
    "DocumentReader",
    "DOCUMENT_READER_ID",
    "DOCUMENT_READER_VERSION",
    "ConversationReader",
    "CONVERSATION_READER_ID",
    "CONVERSATION_READER_VERSION",
]
