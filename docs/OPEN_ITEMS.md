# Atlas — Open Items, Leftovers & Known Issues

> **Purpose.** A single, living registry of *everything deferred* — intentional deviations, deferred
> features, tech/test debt, and known flakes — so nothing gets lost between phases. Each item has an
> **ID**, a **status**, where it was **introduced**, and the **target** phase/owner. Items are closed
> by referencing their ID in the commit/plan that resolves them.
>
> Companion to `ATLAS_OS_ROADMAP.md` (principles/architecture) and the `PHASE_*_PLAN.md` docs
> (per-phase scope). When a plan says "deferred", the actionable item lives **here**.
>
> **Last updated:** 2026-07-22 (Media Reader Family complete; **Media Report Honesty** RH.1–RH.4 ✅).

Legend — **Status:** 🔴 open · 🟡 partial/mitigated · 🟢 done · ⚪ won't-do/by-design
· **Priority:** P1 (do soon) · P2 (should) · P3 (nice-to-have)

---

## 1. Phase C leftovers (active)

These were introduced during Phase C and are the most likely to be picked up next.

| ID | Status | Pri | Item | Introduced | Target |
|----|--------|-----|------|-----------|--------|
| OI-C1 | 🔴 | P2 | **Relocate `DerivedArtifactStore` + `ReaderRegistry` to neutral packages** (`atlas/artifacts/`, `atlas/readers/`) and re-export from `atlas/engineering/`. Today the Document Reader is **duck-typed** against the artifact cache to avoid coupling, but the store/registry still physically live under `atlas/engineering/`. Mechanical move. | C.2b | C.3–C.6 (before more non-code readers) |
| OI-C2 | 🔴 | P2 | **Unify the Reader Registry** so non-code readers (Document, future chat/CAD/MATLAB) register there too. The current coverage matrix is code-capability-specific (`symbols`/`imports`/`call_graph`/…); needs a generic capability axis (e.g. `text`, `sections`, `tables`). Document Reader currently exposes its own `supported_extensions()` and is **not** in the registry. | C.2b | with OI-C1 |
| OI-C3 | 🟡 | P2 | **Unified-pipeline idempotency on the non-embed path.** `KnowledgeService.ingest_text` only short-circuits a re-ingest when the doc is already `embedded`; with `embed=False` it **re-chunks** the same content (duplicate chunks). Asset + document rows are correctly deduped; only chunk regeneration is wasteful. Consider a status/asset-aware early-out in `IngestionService` or `ingest_text`. | C.2c | C.3/C.4 |
| OI-C4 | 🔴 | P2 | **Back-fill existing documents to assets lazily.** The bridge makes *new* ingestion asset-first; pre-Phase-C `knowledge.documents` rows still have `asset_id IS NULL`. Plan calls for opportunistic/lazy back-fill (no big-bang migration) — not yet implemented. | C.2c | C.3–C.4 |
| OI-C5 | 🟡 | P2 | **Wire `IngestionService` + `CandidateConsumer` — mostly done (C.8d).** Both are now constructed in bootstrap (with `coverage=coverage_service`), registered in the container (`ingestion_bridge`, `candidates`), and the OwnerKnowledgeWorker drains candidates each tick. **Remaining:** a standalone CLI/API entrypoint (`atlas ingest <path>` / `POST /v1/ingest`), a *scheduled* global candidate-drain + `CandidateRepository.prune_consumed`, and wiring the real embedder into `EmbeddingIdentityResolver` so prose NN dedup is live (currently the deterministic identity path). | C.2c / C.3g | Phase D or small follow-up |
| OI-C8 | 🟡 | P2 | **Scheduled *reader-version* re-extraction (A10).** The Owner Knowledge Mission (C.8) now re-reads roots whose **content** changed (per-root checksum) and refreshes coverage, but it does **not** yet act on `CoverageService.stale_for_reader(...)` / `mark_stale_for_reextraction(...)` — i.e. re-reading unchanged assets after a **reader/extractor version bump**. The worker should, per tick, also enumerate stale-by-version coverage rows and force-re-read those assets. | C.4c | Phase D or small C.8 follow-up |
| OI-C10 | 🔴 | P3 | **Richer experience signal + revert-retraction.** C.6 extracts experiences only from **languages / frameworks / patterns**; dependency-package signal ("production Celery/Redis" from `requirements.txt`) and timeline/dates (roles/years) are not yet distilled. Also, reverting a learn intentionally does **not** retract that project's contribution to a (cross-project) experience — experiences are cumulative (P13) — so a revert can leave a stale supporting source on a still-corroborated skill. A future evidence-retraction path (drop one source, recompute confidence/maturity, archive when it hits zero) is deferred. | C.6c/C.6d | C.7/C.8 |
| OI-C11 | 🔴 | P2 | **Personal auto-inference: professional facts + skill proficiency + timeline dates.** C.7 auto-infers `skill` facts (from consolidated experiences), an `identity` summary, and a coarse `timeline` (repo first-learned). **Professional** facts (publications/patents/roles) have no reliable structured source yet, so they're operator-authored via `add_fact`/API for now — auto-inference (e.g. from Research findings / a CV asset) is deferred. Skill *proficiency* is a maturity→confidence-label mapping, not a graded level; timeline entries lack real role dates (pending User-Archive dating). | C.7b | C.8 (User Archive) |
| OI-C9 | 🟡 | P3 | **Policy scoping beyond `global`.** C.5 stores `scope` on every rule (`global | domain:<x> | mission:<id>`), but `PolicyService.retrieval_influence` only applies `global` rules unless a caller explicitly passes a `scope`, and no retrieval/advice caller threads a scope yet. Wire mission/domain scope from the retrieving surface so scoped rules actually take effect. Also: a hard-`DELETE` policy API route (rule removal is service/CLI-only today). | C.5b/C.5d | C.7/C.8 |
| OI-C6 | 🟢 | — | **Prose "distilled findings" from documents.** Was deferred from C.2 by design (must flow through the Consolidator). ✅ Resolved by C.3g (`ProseKnowledgeExtractor` → `CandidateConsumer` → `consolidate`). | C.2c | closed C.3g |
| OI-C7 | 🟡 | P3 | **Migration-number placeholders.** The `PHASE_C_PLAN.md` data-model table lists planning placeholders. Real numbers are assigned sequentially at build time — `0028`=document↔asset, `0029`=asset groups, C.3 `0030`–`0034`, `0035`=knowledge_coverage, `0036`=policy, `0037`=experience_consolidation, `0038`=personal. **C.8 added no migration** (template + config schema are code-seeded), so the next real migration is `0039`. Keep the table honest as slots are built. | C.2 | ongoing |
| OI-C12 | 🔴 | P3 | **Personal/Owner SPA dashboard view.** C.8d ships the *data* — `GET /v1/personal/dashboard` (per-domain coverage + understanding + skills/timeline/professional) and live updates over the shared `/v1/events/stream` SSE feed — and a CLI (`atlas personal dashboard`), but no dedicated `/ui` panel. Add a console view rendering the coverage bars + profile with the P9 "why" and confirm/correct controls. | C.8d | Phase D / UI pass |
| OI-C13 | 🔴 | P3 | **Conversation → experience extraction.** The Conversation Reader (C.8a) feeds chats through the pipeline as prose **candidates → findings**, but chats do not yet distill owner **experiences** (a `build_conversation_experiences` analog to `build_repo_experiences`). So skills currently derive from code repos; chat-stated skills ("I spent years on PostgreSQL") become findings, not corroborating experience evidence. | C.8a | Phase D |

---

## 1c. Phase D (complete — seeded from `docs/PHASE_D_PLAN.md`)

Scope cuts recorded at plan time; remaining rows are post-Phase-D deferrals / follow-ons.

| ID | Status | Pri | Item | Notes |
|----|--------|-----|------|-------|
| OI-D1 | 🔴 | P2 | **Live market-data feed** (real provider) as a swappable `MarketDataReader`. | DD6 ships fixture/replay first. |
| OI-D2 | 🔴 | P3 | **RM arbitration beyond weighted-priority + hard cap** (preemption, fair-share). | A7 — refine empirically. |
| OI-D3 | 🟢 | P2 | **Phase D complete** (D.1–D.11 ✅), including applied watchers + e2e gate. | PHASE_D §3 |
| OI-D4 | ⚪ | — | **Real-world side-effecting appliers** (e.g. actually submitting a draft) stay behind the P14 approval gate — out of scope until explicitly requested. | PHASE_D DD3/P14 |

---

## 1d. Future maturity directions (post-Phase-D — deferred by review discipline)

> **Intentionally deferred architectural directions. NOT part of the Phase-D implementation contract;
> they must not influence current implementation unless explicitly promoted into a future phase.**

From the 2026-07-19 external architecture review (rated ~9.9/10). **Endorsed but intentionally
deferred** — execute the roadmap before adding new top-level concepts; revisit after Phase D or when
implementation exposes a genuine limit. Mirrored in `ATLAS_OS_ROADMAP.md` §13.

| ID | Status | Pri | Item | Notes |
|----|--------|-----|------|-------|
| OI-F1 | 🔴 | P3 | **Decision Knowledge** — learn *which decisions consistently produced good outcomes* (`Decision → outcome → Decision Knowledge`), biasing future scoring. | Rides on `decision.decisions` (D) + experience consolidator (C.6). Needs Phase-D decisions+outcomes first. |
| OI-F2 | 🔴 | P3 | **Temporal Knowledge layer** — distinguish historical / current / **predicted** truth (forecasting, market/infra planning). | Rides on freshness + lineage + revisions. Introduce when a mission needs prediction-vs-fact. |
| OI-F3 | 🔴 | P3 | **System Introspection mission** — periodic self-analysis (what do I know / am uncertain about / which readers fail most / mission cost / policies blocking decisions / what to improve). | Generalizes the D.10 Self-Improvement Watcher + the P15 capability-gap self-report. |
| OI-F4 | 🔴 | P3 | **Standardized post-decision feedback loops** — `Recommendation → Outcome → Difference → Learning` as a cross-mission convention (not just D.6 Paper Trading). | Architecture already supports it; make it a convention once ≥2 applied missions run. |
| OI-F5 | 🟡 | P2 | **Capability-gap honesty (P15)** — surface *what Atlas can't do* (missing reader/data-source/rule/tool) to the operator. Partially realized today (honest-failure readers `unsupported`/`empty`, coverage map). To first-class: a Capability Registry gap self-report + the Decision-Engine `capability_gap` outcome (D.1). | Requested by the operator 2026-07-19. Land the `capability_gap` outcome in D.1; the registry self-report is a small Phase-D add. |

---

## 1e. Media Reader Family (frozen — `docs/MEDIA_ACQUISITION_PLAN.md`)

Post–Phase D. Triggered by a live YouTube run that failed at **Acquire** (no transcript /
`robots.txt` / 0 B) — honest P15 failure, thin Reader strategies. Extends the **Media Reader
family** + reusable `ReaderStrategyChain` only; no new Intelligence. Operator-approved 2026-07-21
(strategy-chain generalized; Metadata Reader; media non-special). **Plan frozen — start M.1.**

| ID | Status | Pri | Item | Notes |
|----|--------|-----|------|-------|
| OI-M0 | 🟢 | P1 | **Media Reader Family plan complete** (M.1–M.7 ✅) — strategy chain, metadata, Asset-first readers, optional Whisper, provider-agnostic fetch, research wiring + e2e gate. | `MEDIA_ACQUISITION_PLAN.md` · gate `tests/test_media_acquisition_gate.py` |
| OI-RH0 | 🟢 | P1 | **Media Report Honesty** — Research acquire-stop (RH.1–RH.4). | `MEDIA_REPORT_HONESTY_PLAN.md` |
| OI-MO0 | 🟢 | P1 | **Media learn roadmap** — RH.5–RH.8, MO.5, BA.1, MO.3 shipped. Remaining: Browser v2 media obtain. | `MEDIA_ORCHESTRATION_PLAN.md` |
| OI-RH1 | 🟢 | P1 | **Job report honesty** — waiting + Next Action + Job termination. | `MEDIA_REPORT_HONESTY_AMENDMENT.md` · `tests/test_job_report_honesty.py` |
| OI-BA0 | 🟡 | P2 | **Browser → Asset** — v1 DOM captions shipped. v2 policy-gated media obtain later. | `MEDIA_BROWSER_ACQUISITION_PLAN.md` |
| OI-UI0 | 🟡 | P1 | **Job UI live updates** — fixed overlapping poll race (stale “planning” overwrite). Hard-refresh UI to pick up `app.js`. Follow-up: richer mid-step activity for long `media.learn`. | `atlas/web/static/app.js` |
| OI-M1 | 🔴 | P3 | Official YouTube Data API captions (API key) as an extra polite strategy. | defer |
| OI-M2 | 🔴 | P3 | Speaker diarization on transcripts. | defer |
| OI-M3 | 🔴 | P3 | Streaming / live caption ingest. | defer |
| OI-M4 | ⚪ | — | CCTV / continuous video missions. | out of scope until requested |
| OI-M5 | 🔴 | P3 | Cloud STT providers (only if local Whisper insufficient). | defer |
| OI-M6 | 🔴 | P3 | **Video frames → Image/OCR Readers** (slides/diagrams aligned with speech). | Architecture allows; not now |
| OI-M7 | 🔴 | P3 | Reuse `ReaderStrategyChain` for non-media Readers (documents, git, OCR, CAD). | After media proves the pattern |

---

## 2. Cross-cutting test / infra debt

| ID | Status | Pri | Item | Notes |
|----|--------|-----|------|-------|
| OI-T1 | 🔴 | P1 | **Live-DB tests share one Postgres with no teardown.** e2e tests insert into `learning.repositories`, `knowledge.*`, `asset.*`, `audit.events` and don't clean up. After a reboot clears `/tmp` (tmpfs), pytest's temp counter restarts and fresh tmp paths **collide** with stale `active` rows (e.g. `uq_learning_repositories_root_active`). Needs a proper isolation strategy: per-test transaction rollback, a disposable schema/db per run, or session teardown fixtures. | Caused 3 false failures on 2026-07-19; mitigated by a manual cleanup of `/tmp/pytest%` rows. |
| OI-T2 | 🟡 | P2 | **`test_event_lifecycle` flake.** `EventRepository.list_pending(limit=100)` is `ORDER BY created_at ASC LIMIT 100` (oldest-first), so once >100 **undispatched** `pending` `audit.events` accumulate in the shared dev DB the newly-recorded test event falls outside the window and the assertion fails. Confirmed 2026-07-19: 187 pending events from *real* subsystems (scheduler 75, kernel 54, recovery 40, …), not test rows — deleting them is a broader cleanup decision, not made unprompted. Pre-existing; unrelated to feature code (full suite otherwise 1339 green after C.3). Fix with OI-T1 isolation, a scoped cleanup fixture, or make the test query keyed/newest-first. | Known before Phase C. |
| OI-T3 | 🔴 | P3 | **A `make test-clean` / cleanup helper** for the shared dev DB (delete `/tmp/pytest%` assets/repos, stale pending events) so contributors don't hit OI-T1/T2 manually. | Ties into OI-T1. |

---

## 3. Deferred by design (carried from earlier phases)

Tracked for completeness; these are intentional scope cuts, not accidental debt.

| ID | Status | Pri | Item | Source |
|----|--------|-----|------|--------|
| OI-B1 | 🔴 | P2 | **JS/TS call-graph resolution.** Python has full call graphs; JS/TS is symbols/imports/exports/modules only. A later reader upgrade (honestly reported by the coverage matrix today). | PHASE_B §BB5/BB10 |
| OI-B2 | 🔴 | P2 | **Partial / per-file re-ingest.** RepoWatcher re-ingests whole repos; the interface is shaped for "one file changed → partial ingest" but partial ingest itself is out of scope for B. | PHASE_B §B.6 |
| OI-B3 | 🟡 | P2 | **Knowledge Conflict *Resolver*** (reasoning about a delta, not just superseding). Consolidator (C.3) handles evolution-vs-conflict routing; deeper Decision-Engine reasoning about contradictions is later (C/D). | PHASE_B "not building" |
| OI-B4 | 🔴 | P3 | **Additive readers:** CAD / MATLAB / PLC / UML / PSpice, etc. Register in the (unified, OI-C2) Reader Registry with no changes elsewhere. | PHASE_B "not building" |
| OI-A1 | 🔴 | P3 | **Cron schedules.** Only `interval` / `continuous` are built; cron is documented, not implemented. | PHASE_A §A (schedules) |
| OI-A2 | 🔴 | P3 | **Job-advance priority threading** through the scheduler. | PHASE_A |
| OI-A3 | 🔴 | P3 | **Resource caps:** `llm_units_per_window` and host-resource caps in the Resource Manager. | PHASE_A |
| OI-X1 | ⚪ | — | **Remote access + hot/warm/cold storage tiering.** Hardware-gated; single-disk for now. | ROADMAP / PHASE_B |

---

## 4. Recently closed

| ID | Item | Closed by |
|----|------|-----------|
| OI-RH0 | **Media Report Honesty** (acquire-stop UX: NOT_APPLICABLE, Research blocked, operator strategies). | RH.1–RH.4 / `tests/test_media_report_honesty.py` |
| OI-M0 | **Media Reader Family plan** (M.1–M.7) — Asset-first media Readers, optional Whisper, provider-agnostic fetch, research wiring + e2e gate. | M.7 / `tests/test_media_acquisition_gate.py` |
| OI-G1 | **`.gitignore` silently ignored `atlas/{documents,knowledge,models}` source packages** (unanchored runtime-data rules) — 25 core source files were untracked. Anchored the rules to the repo root; source now tracked. | commit `57deac9` (2026-07-19) |
| OI-C6 | Prose "distilled findings" from documents — now flow document → candidate → Consolidator → finding. | C.3g commit `4595ee8` (2026-07-19) |
| (bug) | **`UNIQUE(canonical_id)` blocked the finding revision model** on the live DB (revise reused canonical_id). Relaxed to `UNIQUE(canonical_id, revision)`. | C.3e migration `0033` / commit `58f7c78` |
| (bug) | **Consolidator spuriously revised on subset re-observation.** Re-observing an already-known source on a multi-source finding (incoming supporting ⊆ existing, body unchanged) deferred to the transition machine, which saw the differing supporting-set and spawned a revision that discarded accumulated evidence. `_accumulate` now returns an explicit no-op. Surfaced by C.6 shared-identity experiences. | C.6d commit `2ed3771` |

---

_When you close an item, move it to §4 with the resolving commit, and flip its status to 🟢._
