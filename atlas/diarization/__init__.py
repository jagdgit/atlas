"""Speaker diarization package (OI-M2)."""

from atlas.diarization.engine import (
    CAPABILITY_GAP,
    DIA_EMPTY,
    DIA_ERROR,
    DIA_OK,
    DIA_UNAVAILABLE,
    DiarizationClient,
    LabelPreservingEngine,
)

__all__ = [
    "CAPABILITY_GAP",
    "DIA_EMPTY",
    "DIA_ERROR",
    "DIA_OK",
    "DIA_UNAVAILABLE",
    "DiarizationClient",
    "LabelPreservingEngine",
]
