# Atlas evaluation baselines

Captured for **Stage 3B.0** (`3B.0-hermetic-v1`, 2026-07-17).

Hermetic fixtures under `tests/fixtures/eval/`. Re-run with:

```bash
.venv/bin/python -c "from atlas.eval import run_baseline_suite; import json; print(json.dumps(run_baseline_suite().as_dict(), indent=2))"
```

## Summary (gates)

| Family | Metric | Baseline |
|--------|--------|----------|
| Retrieval (hermetic ranked lists) | precision@k (mean) | **0.567** |
| Retrieval (hermetic ranked lists) | recall@k (mean) | **1.000** |
| Synthesis (`group_claims` duplicates) | merge_accuracy | **1.000** |
| Synthesis (`group_claims` duplicates) | false_merge_rate | **0.000** |
| Synthesis (`group_claims` contradictions) | contradiction_recall | **1.000** |
| Lifecycle (oracle freshness policy) | freshness_label_accuracy | **1.000** |
| Lifecycle (transition labels) | supersession_correctness | **1.000** |
| Grounding (fixture completeness) | provenance_completeness | **0.812** |
| End-to-end | Atlas Benchmark Set | **15 problems seeded** (`not_run`) |

## Notes

- **Retrieval:** Hermetic `ranked_ids` establish the metric harness and labeled relevance corpus. Live hybrid capture (Postgres + Ollama) remains optional operator work after milestones; Access Layer hybrid is the production default.
- **Synthesis:** Baselines reflect `group_claims` / Evidence Synthesizer. Findings synthesizer must not regress merge_accuracy / contradiction_recall on these fixtures.
- **Freshness / supersession:** Oracle labels for 3B.3 policies; production lifecycle must meet them (append-only revisions; never overwrite).
- **Benchmark Set:** BM-001…BM-015 fixed research problems. Seeded for milestone regression; execute with live providers when ready (`not_run` until then).

## Stage 3B close-out delta (2026-07-17)

| Change | Result |
|--------|--------|
| Soft bias wired | `KnowledgeService.retrieve` loads `learning.soft_bias_terms()` after apply+enable |
| Provenance edges | Findings carry `parent_ids` + edges (claim/source/doc/chunk/reader) |
| Memory tiers | Live=`knowledge`; working/session/experience/archive deferred (meta honesty) |
| Re-verify worker | `review_finding` re-verifies evidence and completes review row |
| Docs | Plan/status reflect 3B.0–3B.5 + §10 code close-out |

## Stage 3B.5 delta (2026-07-17)

| Change | Result |
|--------|--------|
| Rich Experience payload | readers / paywalls / timings / strategies / recommendations |
| Component observations | A3B.17 keys (`reader:*`, `retrieval:hybrid`, `synthesizer:v1`, …) |
| Advice recall | `advice_for` → research + JobPlanner; `mutating=False` |
| Soft bias | Off by default; require apply + `enable_bias`; tiny rerank boost only |
| Governance | Observe still propose-only (`auto_apply=False`) |
| Migration | `0017_experience_learning.sql` |

## Stage 3B.4 delta (2026-07-17)

| Change | Result |
|--------|--------|
| Cross-doc reasoning | Edges (support/contradict/refine) + pattern cards |
| Gaps → opportunities | Contested findings + unmet gaps → opportunities |
| Hypotheses | Explicit `hypothesis` type; open status; never auto-promoted |
| Reports | `patterns` / `opportunities` / `hypotheses` sections without false certainty |
| Tests | `tests/test_reasoning.py` green; research/reports/learn regression held |

## Stage 3B.3 delta (2026-07-17)

| Change | Result |
|--------|--------|
| Consolidation | Same identity → revise (new revision + supersedes links) |
| Freshness | Production `freshness_label` = eval oracle (**1.000** on fixtures) |
| Invalidation | Component match → freshness=stale + `finding_reviews` |
| Access | `list_findings` returns active heads; archive excluded by default |

## Stage 3B.2 delta (2026-07-17)

| Change | Result |
|--------|--------|
| Evidence Synthesizer | Claims → Findings via `group_claims` + quality/provenance |
| Durable store | `knowledge.findings` (UUID + `F-######` on promote + revision) |
| Reports | Prefer findings when present (`used_findings`) |
| Eval regression | merge_accuracy / contradiction_recall still **1.000** on 3B.0 fixtures |

## Stage 3B.1 delta (2026-07-17)

| Change | Result |
|--------|--------|
| Access Layer | `retrieve(..., role=)` with Retrieve → Re-rank → Context |
| Hybrid fusion | Equal-weight RRF; hits carry `dense_score` / `lexical_score` / `rrf_score` |
| Diagnostics | Persisted to `knowledge.retrieval_diagnostics` when enabled |
| Call sites | RagAgent (`role=chat`), `POST /v1/knowledge/search`, research prior recall |
| Acceptance check | Hybrid holds/improves vs dense-only on toy labeled case (`test_access_layer`) |

Hermetic 3B.0 numbers above remain the frozen baseline; do not rewrite them.

## Regression rule

Later milestones append a new row (or section) here. Do not silently rewrite prior numbers — record the new version id and delta.
