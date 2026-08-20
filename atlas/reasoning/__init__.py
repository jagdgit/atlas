"""Atlas Reasoning — Persistent Self cognitive façade (OI-SELF0)."""

from atlas.reasoning.aging import effective_confidence, with_effective
from atlas.reasoning.experience_loop import (
    VERSION as EXP_LOOP_VERSION,
    close_loop,
    compute_delta,
    ingest_experience_to_beliefs,
    validate_belief_link,
)
from atlas.reasoning.day_activity import (
    VERSION as DAY_ACTIVITY_VERSION,
    build_day_activity_brief,
    detect_day_activity,
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
from atlas.reasoning.decision_consult import (
    VERSION as DECISION_CONSULT_VERSION,
    consult_unique_decision,
    should_consult,
)
from atlas.reasoning.outcome_revision import (
    VERSION as OUTCOME_REVISION_VERSION,
    build_outcome_check,
    record_belief_candidate,
)
from atlas.reasoning.research_scientist import (
    VERSION as RESEARCH_SCIENTIST_VERSION,
    build_research_packet,
    drain_scientist_queue,
    is_scientist_event,
    run_research_scientist,
)
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
    "DAY_ACTIVITY_VERSION",
    "DECISION_CONSULT_VERSION",
    "EXP_LOOP_VERSION",
    "IDENTITY_CHAT_VERSION",
    "InMemoryBeliefRepository",
    "LIVING_RAG_VERSION",
    "OUTCOME_REVISION_VERSION",
    "RESEARCH_SCIENTIST_VERSION",
    "REFLECT_VERSION",
    "ReasoningService",
    "SEED_BELIEFS",
    "VERSION",
    "answer_as_atlas",
    "answer_belief_benchmark",
    "belief_core_jis",
    "build_day_activity_brief",
    "build_living_rag_bundle",
    "build_outcome_check",
    "build_research_packet",
    "close_loop",
    "compute_delta",
    "consult_unique_decision",
    "detect_belief_benchmark",
    "detect_day_activity",
    "drain_scientist_queue",
    "effective_confidence",
    "format_bundle_context",
    "format_reflection_section",
    "ingest_experience_to_beliefs",
    "is_scientist_event",
    "merge_jis",
    "record_belief_candidate",
    "run_nightly_reflection",
    "run_research_scientist",
    "seed_worldview",
    "should_consult",
    "validate_belief_link",
    "with_effective",
]
