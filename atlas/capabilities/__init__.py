"""Typed capability contracts (Stage 2, S11).

Stage 1's ``CapabilityRegistry`` mapped a capability *name* to a provider — enough
for "do I have X?" but untyped: nothing said *what methods* an "X" provider must
offer, and the planner's capability strings ("memory", "web", …) were just
conventions. S11 makes capabilities **typed contracts**:

- ``contracts`` — ``runtime_checkable`` Protocols an implementation must satisfy,
  each bound to a canonical capability **id** (the string the planner and registry
  use).
- ``CAPABILITY_CATALOG`` — the canonical list of *known* capabilities (provided or
  not), each with a human summary and what building it *unlocks*. This drives honest
  Capability Gap Reports (R2): Atlas can say precisely what's missing and why.

The registry stays name-based (back-compatible); the contract is attached as
metadata so callers can verify a provider actually implements its protocol.
"""

from __future__ import annotations

from atlas.capabilities.contracts import (
    CAP_AGENT,
    CAP_BROWSER,
    CAP_CODE,
    CAP_CONVERSATION,
    CAP_DOCUMENT,
    CAP_GIT,
    CAP_INTELLIGENCE,
    CAP_KNOWLEDGE,
    CAP_LEARNING,
    CAP_LLM,
    CAP_MAIL,
    CAP_MEMORY,
    CAP_OCR,
    CAP_PYTHON,
    CAP_RESEARCH,
    CAP_SCHOLAR,
    CAP_SEARCH,
    CAP_SQL,
    CAP_TRANSCRIPT,
    CAP_WEB,
    CAPABILITY_CATALOG,
    BrowserCapability,
    CapabilitySpec,
    CodeCapability,
    ConversationCapability,
    DocumentCapability,
    ExecutionCapability,
    FetchCapability,
    FilesystemCapability,
    GitCapability,
    IntelligenceCapability,
    KnowledgeCapability,
    LLMCapability,
    LearningCapability,
    MailCapability,
    MemoryCapability,
    OCRCapability,
    PythonExecutionCapability,
    ResearchCapability,
    SQLCapability,
    ScholarCapability,
    SearchCapability,
    TranscriptCapability,
    describe_capabilities,
    gap_report,
)

__all__ = [
    "CAP_AGENT",
    "CAP_BROWSER",
    "CAP_CODE",
    "CAP_CONVERSATION",
    "CAP_DOCUMENT",
    "CAP_GIT",
    "CAP_INTELLIGENCE",
    "CAP_KNOWLEDGE",
    "CAP_LEARNING",
    "CAP_LLM",
    "CAP_MAIL",
    "CAP_MEMORY",
    "CAP_OCR",
    "CAP_PYTHON",
    "CAP_RESEARCH",
    "CAP_SCHOLAR",
    "CAP_SEARCH",
    "CAP_SQL",
    "CAP_TRANSCRIPT",
    "CAP_WEB",
    "CAPABILITY_CATALOG",
    "BrowserCapability",
    "CapabilitySpec",
    "CodeCapability",
    "ConversationCapability",
    "DocumentCapability",
    "ExecutionCapability",
    "FetchCapability",
    "FilesystemCapability",
    "GitCapability",
    "IntelligenceCapability",
    "KnowledgeCapability",
    "LLMCapability",
    "LearningCapability",
    "MailCapability",
    "MemoryCapability",
    "OCRCapability",
    "PythonExecutionCapability",
    "ResearchCapability",
    "SQLCapability",
    "ScholarCapability",
    "SearchCapability",
    "TranscriptCapability",
    "describe_capabilities",
    "gap_report",
]
