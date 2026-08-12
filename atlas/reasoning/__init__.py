"""Atlas Reasoning — Persistent Self cognitive façade (OI-SELF0)."""

from atlas.reasoning.aging import effective_confidence, with_effective
from atlas.reasoning.experience_loop import (
    VERSION as EXP_LOOP_VERSION,
    close_loop,
    compute_delta,
    ingest_experience_to_beliefs,
    validate_belief_link,
)
from atlas.reasoning.identity_chat import (
    VERSION as IDENTITY_CHAT_VERSION,
    answer_as_atlas,
    answer_belief_benchmark,
    detect_belief_benchmark,
)
from atlas.reasoning.reflection import (
    VERSION as REFLECT_VERSION,
    belief_core_jis,
    format_reflection_section,
    merge_jis,
    run_nightly_reflection,
)
from atlas.reasoning.retrieval import (
    VERSION as LIVING_RAG_VERSION,
    build_living_rag_bundle,
    format_bundle_context,
)
from atlas.reasoning.seed import SEED_BELIEFS, seed_worldview
from atlas.reasoning.service import ReasoningService, VERSION
from atlas.repositories.belief_repo import (
    BELIEF_DOMAINS,
    BELIEF_STATUSES,
    BeliefRepository,
    InMemoryBeliefRepository,
)

__all__ = [
    "BELIEF_DOMAINS",
    "BELIEF_STATUSES",
    "BeliefRepository",
    "EXP_LOOP_VERSION",
    "IDENTITY_CHAT_VERSION",
    "InMemoryBeliefRepository",
    "LIVING_RAG_VERSION",
    "REFLECT_VERSION",
    "ReasoningService",
    "SEED_BELIEFS",
    "VERSION",
    "answer_as_atlas",
    "answer_belief_benchmark",
    "belief_core_jis",
    "build_living_rag_bundle",
    "close_loop",
    "compute_delta",
    "detect_belief_benchmark",
    "effective_confidence",
    "format_bundle_context",
    "format_reflection_section",
    "ingest_experience_to_beliefs",
    "merge_jis",
    "run_nightly_reflection",
    "seed_worldview",
    "validate_belief_link",
    "with_effective",
]
