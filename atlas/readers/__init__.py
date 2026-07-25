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
from atlas.readers.market_data import (
    MARKET_DATA_READER_ID,
    MARKET_DATA_READER_VERSION,
    MarketDataReader,
)
from atlas.readers.job_postings import (
    JOB_POSTINGS_READER_ID,
    JOB_POSTINGS_READER_VERSION,
    JobPostingsReader,
)
from atlas.readers.advisory_feed import (
    ADVISORY_FEED_READER_ID,
    ADVISORY_FEED_READER_VERSION,
    AdvisoryFeedReader,
)
from atlas.readers.media_kinds import (
    ASSET_KIND_AUDIO,
    ASSET_KIND_TRANSCRIPT,
    ASSET_KIND_VIDEO,
    MEDIA_ASSET_KINDS,
    content_type_for,
    infer_media_kind,
    media_extensions,
)
from atlas.readers.media_metadata import (
    MEDIA_METADATA_READER_ID,
    MEDIA_METADATA_READER_VERSION,
    MediaMetadataReader,
)
from atlas.readers.transcript_file import (
    TRANSCRIPT_FILE_READER_ID,
    TRANSCRIPT_FILE_READER_VERSION,
    TranscriptFileReader,
)
from atlas.readers.audio_demux import (
    AUDIO_DEMUX_READER_ID,
    AUDIO_DEMUX_READER_VERSION,
    AudioDemuxReader,
)
from atlas.readers.speech_to_text import (
    SPEECH_TO_TEXT_READER_ID,
    SPEECH_TO_TEXT_READER_VERSION,
    SpeechToTextReader,
)
from atlas.readers.strategy_chain import ChainResult, ReaderStrategyChain, StrategyResult
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
    default_domain_stub_readers,
    default_media_readers,
    default_readers,
)

__all__ = [
    "DocumentReader",
    "DOCUMENT_READER_ID",
    "DOCUMENT_READER_VERSION",
    "ConversationReader",
    "CONVERSATION_READER_ID",
    "CONVERSATION_READER_VERSION",
    "MarketDataReader",
    "MARKET_DATA_READER_ID",
    "MARKET_DATA_READER_VERSION",
    "JobPostingsReader",
    "JOB_POSTINGS_READER_ID",
    "JOB_POSTINGS_READER_VERSION",
    "AdvisoryFeedReader",
    "ADVISORY_FEED_READER_ID",
    "ADVISORY_FEED_READER_VERSION",
    "ReaderStrategyChain",
    "StrategyResult",
    "ChainResult",
    "MediaMetadataReader",
    "MEDIA_METADATA_READER_ID",
    "MEDIA_METADATA_READER_VERSION",
    "TranscriptFileReader",
    "TRANSCRIPT_FILE_READER_ID",
    "TRANSCRIPT_FILE_READER_VERSION",
    "AudioDemuxReader",
    "AUDIO_DEMUX_READER_ID",
    "AUDIO_DEMUX_READER_VERSION",
    "SpeechToTextReader",
    "SPEECH_TO_TEXT_READER_ID",
    "SPEECH_TO_TEXT_READER_VERSION",
    "ASSET_KIND_VIDEO",
    "ASSET_KIND_AUDIO",
    "ASSET_KIND_TRANSCRIPT",
    "MEDIA_ASSET_KINDS",
    "infer_media_kind",
    "content_type_for",
    "media_extensions",
    "Reader",
    "ReaderRegistry",
    "ALL_CAPABILITIES",
    "CAP_SYMBOLS",
    "CAP_IMPORTS",
    "CAP_EXPORTS",
    "CAP_CALL_GRAPH",
    "CAP_DECORATORS",
    "CAP_TYPING",
    "CAP_MODULES",
    "CAP_TEXT",
    "CAP_METADATA",
    "CAP_TRANSCRIPT",
    "CAP_AUDIO",
    "CAP_SECTIONS",
    "CAP_TABLES",
    "default_readers",
    "default_media_readers",
    "default_document_readers",
    "default_domain_stub_readers",
]
