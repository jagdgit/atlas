"""Reader Registry — re-export from ``atlas.readers.registry`` (OI-C1 back-compat).

The physical home is now ``atlas.readers.registry``. Import from either path.
"""

from atlas.readers.registry import (
    ALL_CAPABILITIES,
    CAP_AUDIO,
    CAP_CALL_GRAPH,
    CAP_DECORATORS,
    CAP_EXPORTS,
    CAP_IMPORTS,
    CAP_METADATA,
    CAP_MODULES,
    CAP_SECTIONS,
    CAP_SYMBOLS,
    CAP_TABLES,
    CAP_TEXT,
    CAP_TRANSCRIPT,
    CAP_TYPING,
    Reader,
    ReaderRegistry,
    default_document_readers,
    default_media_readers,
    default_readers,
)

__all__ = [
    "ALL_CAPABILITIES",
    "CAP_AUDIO",
    "CAP_CALL_GRAPH",
    "CAP_DECORATORS",
    "CAP_EXPORTS",
    "CAP_IMPORTS",
    "CAP_METADATA",
    "CAP_MODULES",
    "CAP_SECTIONS",
    "CAP_SYMBOLS",
    "CAP_TABLES",
    "CAP_TEXT",
    "CAP_TRANSCRIPT",
    "CAP_TYPING",
    "Reader",
    "ReaderRegistry",
    "default_document_readers",
    "default_media_readers",
    "default_readers",
]
