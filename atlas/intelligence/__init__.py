"""Engineering Intelligence (Stage 2, S19, D11/§5d).

The higher-order learners that climb the Learning Levels over the **Code store**:
L2 Understand (learn a repository's structure), L3 Connect (cross-project search +
connections), L4 Generalize (patterns you *always* use), L5 Recommend (the Personal
Coding Assistant). Built on top of ``CodeService`` (S14 artifacts) and governed
through the S18b learning ledger via a store *sink* — "adds sinks, not schema".
"""

from __future__ import annotations

from atlas.intelligence.service import CodeStoreSink, IntelligenceService

__all__ = ["IntelligenceService", "CodeStoreSink"]
