# Atlas — Open Items, Leftovers & Known Issues

> **Purpose.** A single, living registry of *everything deferred* — intentional deviations, deferred
> features, tech/test debt, and known flakes — so nothing gets lost between phases. Each item has an
> **ID**, a **status**, where it was **introduced**, and the **target** phase/owner. Items are closed
> by referencing their ID in the commit/plan that resolves them.
>
> Companion to `ATLAS_OS_ROADMAP.md` (principles/architecture) and the `PHASE_*_PLAN.md` docs
> (per-phase scope). When a plan says "deferred", the actionable item lives **here**.
>
> **Last updated:** 2026-07-25 (OI-A3 resource caps closed).

Legend — **Status:** 🔴 open · 🟡 partial/mitigated · 🟢 done · ⚪ won't-do/by-design
· **Priority:** P1 (do soon) · P2 (should) · P3 (nice-to-have)

---

## 1. Phase C leftovers (active)

These were introduced during Phase C and are the most likely to be picked up next.

| ID | Status | Pri | Item | Introduced | Target |
|----|--------|-----|------|-----------|--------|
| OI-C1 | 🟢 | P2 | **Relocate `DerivedArtifactStore` + `ReaderRegistry`** to `atlas/artifacts/` + `atlas/readers/registry.py`; engineering re-exports kept. | C.2b | closed OI-C1 |
| OI-C2 | 🟢 | P2 | **Unify the Reader Registry** — document/conversation registered with `text`/`sections`/`tables` axis (VERSION 2.0.0). | C.2b | closed OI-C2 |
| OI-C3 | 🟢 | P2 | **Unified-pipeline idempotency on the non-embed path.** `ingest_text` short-circuits when status is already `chunked`/`embedded` (no re-chunk). | C.2c | closed EX/OI-C3 |
| OI-C4 | 🟢 | P2 | **Back-fill existing documents to assets lazily.** `IngestionService.backfill_orphan_documents` + Owner Knowledge tick drain; `GET /v1/knowledge/orphans`, `POST /v1/knowledge/backfill-assets`, `atlas backfill-assets`. | C.2c | closed OI-C4 |
| OI-C5 | 🟢 | P2 | **Wire `IngestionService` + `CandidateConsumer`.** Bridge CLI/`POST /v1/ingest`; scheduled `candidates_drain` + `candidates_prune`; live `EmbeddingIdentityResolver` on consolidator. | C.2c / C.3g | closed OI-C5 |
| OI-C8 | 🟢 | P2 | **Scheduled *reader-version* re-extraction (A10).** Owner Knowledge ticks call `mark_stale_for_reextraction` + `IngestionService.reingest_asset(force=True)`. | C.4c | closed OI-C8 |
| OI-C10 | 🟢 | P3 | **Richer experience signal + revert-retraction.** Dependency-package signal from manifests ✅. Revert peels that project's ``source_id`` from shared experiences (`ExperienceWriter.retract_source` + `CodeStoreSink.revert`); archives when no supporters remain. | C.6c/C.6d | closed OI-C10 |
| OI-C11 | 🟢 | P2 | **Personal auto-inference: proficiency + timeline years + heuristic professional.** Skills get graded `proficiency`; stated `years` feed timeline tenure; role/publication heuristics from Experience text. Full CV / Research-finding professional auto-inference still deferred. | C.7b | closed OI-C11 |
| OI-C9 | 🟢 | P3 | **Policy scoping beyond `global`.** Retrieval, Decision Engine, planning notes, and Policy Engine admit `domain:*` / `mission:*` / `mission_type:*` scopes (plus always-`global`). Search accepts optional `policy_scope` / `mission_id`. Hard-`DELETE` via `DELETE /v1/policy/rules/{id}` and `atlas policy delete`. | C.5b/C.5d | closed OI-C9 |
| OI-C6 | 🟢 | — | **Prose "distilled findings" from documents.** Was deferred from C.2 by design (must flow through the Consolidator). ✅ Resolved by C.3g (`ProseKnowledgeExtractor` → `CandidateConsumer` → `consolidate`). | C.2c | closed C.3g |
| OI-C7 | 🟡 | P3 | **Migration-number placeholders.** Real numbers are assigned sequentially at build time. Through Phase C: `0028`–`0038` as listed; C.8/C.9 needed no migration. Post-C: `0039`=decision, `0040`=decision_approvals, `0041`=sim_trading, `0042`=schedule_cron. **Next free slot: `0043`.** Keep the PHASE_C table honest as slots are built. | C.2 | ongoing |
| OI-C12 | 🟢 | P3 | **Personal/Owner SPA dashboard view.** Console `/ui` Personal panel: coverage bars, skills/timeline/professional/identity with P9 "why", Confirm/Reject for inferred facts, Infer + draft-resume actions over `/v1/personal/*`. | C.8d | closed OI-C12 |
| OI-C13 | 🟢 | P3 | **Conversation → experience extraction.** `build_conversation_experiences` distills owner-stated skills from user turns; `IngestionService` writes them when `source=conversation` + `extract_findings` (Owner Knowledge). | C.8a | closed OI-C13 |

---

## 1c. Phase D (complete — seeded from `docs/PHASE_D_PLAN.md`)

Scope cuts recorded at plan time; remaining rows are post-Phase-D deferrals / follow-ons.

| ID | Status | Pri | Item | Notes |
|----|--------|-----|------|-------|
| OI-D1 | 🟢 | P2 | **Live market-data feed** — `asset_replay` default; Yahoo opt-in; **Alpha Vantage + Polygon live** when env keys set; NSE/BSE remain ToS-gated skeletons + CapabilityGap. | MI.3 · `atlas/trading/adapters.py` | closed OI-D1 |
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
| OI-F5 | 🟢 | P2 | **Capability-gap honesty (P15)** — Decision Engine `capability_gap` + `GET /v1/decision/gaps` + registry `self_report_gaps` (`GET /v1/capabilities/gaps`, `atlas capability-gaps`). | closed F5 |

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
| OI-MO0 | 🟢 | P1 | **Media learn orchestration** — planner/orchestrator/report honesty validated (V4). | `MEDIA_ORCHESTRATION_PLAN.md` |
| OI-RH1 | 🟢 | P1 | **Job report honesty** — waiting + Next Action. Stop investing. | `MEDIA_REPORT_HONESTY_AMENDMENT.md` |
| OI-AC0 | 🟢 | P1 | **Acquisition + learning report** — BA.v2, AL1–AL5, LR1–LR8 shipped. Remaining: Whisper ops; AL6 later. | `MEDIA_ACQUISITION_CLOSURE_PLAN.md` · `MEDIA_ASSET_LIFECYCLE_PLAN.md` · `MEDIA_LEARNING_REPORT_PLAN.md` |
| OI-LR0 | 🟢 | P1 | **Learning Report** — media.learn jobs render Learning Report (not Research INSUFFICIENT). LS1 capability summary + OC1 reason codes done. | `MEDIA_LEARNING_REPORT_PLAN.md` · `tests/test_learning_report.py` |
| OI-STT0 | 🟢 | P1 | **speech_to_text (Whisper)** — installed in venv + `plugins.speech.enabled` in local.yaml. Knowledge categories + metadata-vs-spoken honesty shipped. First live spoken run still needed (model download on first use). | `docs/SPEECH_TO_TEXT_OPS.md` · `config/local.yaml` |
| OI-KE0 | 🟢 | P1 | **Knowledge Extraction** — KE.2.4–2.7 ✅. KG.1 derived graph ✅. | `docs/MEDIA_KNOWLEDGE_EXTRACTION_PLAN.md` |
| OI-KV0 | 🟢 | P1 | **Knowledge Verification (V5)** — KV.0–KV.10 ✅. | `docs/KNOWLEDGE_VERIFICATION_PLAN.md` |
| OI-MP0 | 🟢 | P1 | **Mission Philosophy** — Layer 1 vs Layer 2; kinds; lifecycle; experience shape. | `docs/ATLAS_MISSION_PHILOSOPHY.md` |
| OI-MP1 | 🟢 | P1 | **Experience journal** — Experience OS first-class (`GET /v1/experience/shape`, `POST /v1/experience/journal`). | EX.1 |
| OI-MI0 | 🟢 | P1 | **Market Intelligence Program** — MI→KG→MCA + platform PA gaps ✅. **Next:** governance / ops polish. | `docs/MARKET_INTELLIGENCE_MISSIONS_PLAN.md` |
| OI-MP2 | 🟢 | P1 | **Split paper trading** — `decision_simulation` is primary; `paper_trading` remains compat alias. | `OI-MI0` |
| OI-MP3 | 🟢 | P1 | **Daily Learning Governance Report** — `GET /v1/governance/daily` + `learning_governance` mission. | MP3 |
| OI-MP4 | 🟢 | P3 | **Engineering Mentor Mission** — weekly engineering-judgment lessons from repo/architecture Experiences → Experience OS (`engineering_mentor` template + worker; soft-bias default). | Philosophy | closed OI-MP4 |
| OI-PM0 | 🟢 | P3 | **Personal Mentor Mission** — weekly owner/career judgment lessons → Experience OS (`personal_mentor`); Personal Intelligence Program now stub-free. | Programs | closed OI-PM0 |
| OI-MP5 | 🟢 | P2 | **Missions teach missions** — Investment Mentor journals → optional soft-bias (default on) → Decision Engine Experience nudge + Decision Simulation `advice_for` / strategy mentor bias (MI.7). | Philosophy MP6 | closed OI-MP5 |
| OI-PA0 | 🟢 | P1 | **Atlas Platform Architecture** — SETTLED master (Programs→Missions→Workers; Memory/Planning/Policy/Capability/Scheduler gaps tracked below). | `docs/ATLAS_PLATFORM_ARCHITECTURE.md` |
| OI-PA-PLAN | 🟢 | P2 | **Planning OS** — goal → gaps → compare → risk → decide (`GET /v1/planning/plan`). | PA.1 |
| OI-PA-MEM | 🟢 | P2 | **Memory hierarchy** — working / session / long_term ↔ Knowledge / Experience (`GET /v1/memory/hierarchy`). | MEM.1 |
| OI-PA-POLICY | 🟢 | P2 | **Policy Engine** — soft influence + hard forbid/limit (`POST /v1/policy/evaluate`). | PA.2 |
| OI-PA-CAP | 🟢 | P2 | **Capability Registry enrichment** — needs/aliases/inspect (`POST /v1/capabilities/needs`). | CAP.1 |
| OI-PA-SCHED | 🟢 | P3 | **Scheduler hierarchy** — Program → Mission → Worker (`GET /v1/scheduler/hierarchy`). | SCHED.1 |
| OI-PA-WM | 🟢 | P1 | **World Models framework** — registry + indian_markets + solar_plant stub. | WM.1 |
| OI-PA-MCA | 🟢 | P1 | **Mission Context API** — Knowledge + Graph + World Models + Experience; Decision Simulation cites. | MCA.1 |
| OI-BA0 | 🟢 | P2 | **Browser → Asset** — BA.1b + BA.v2 (opt-in yt-dlp) done. BA.v2+ later. | `MEDIA_BROWSER_ACQUISITION_PLAN.md` · `atlas/ingestion/youtube_media_obtain.py` |
| OI-M1 | 🟢 | P1 | Official YouTube captions API — executable when `plugins.youtube.api_key` set (download may still need OAuth). | `atlas/transcripts/official_captions.py` |
| OI-UI0 | 🟢 | P1 | **Job UI live updates** — sequential poll (no race) + SSE `job.activity`/`job.step_blocked`/`job.finalized` refresh; static `/ui` assets served with `Cache-Control: no-cache` so deploys do not require a hard-refresh. | `atlas/web/` · `app.js` | closed OI-UI0 |
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
| OI-T1 | 🟢 | P1 | **Live-DB tests share one Postgres with no teardown.** Session autouse cleanup + `atlas-db test-clean` deactivate `/tmp/pytest%` `learning.repositories` and delete matching `asset.assets` / pending `source=test` events (OI-T3). | closed OI-T1 |
| OI-T2 | 🟢 | P2 | **`test_event_lifecycle` flake.** `list_pending` gains optional `source=`; the test scopes to `source='test'` so >100 pending system events cannot hide it. Dispatcher still oldest-first globally. | closed OI-T2 |
| OI-T3 | 🟢 | P3 | **`atlas-db test-clean` / cleanup helper** for shared-dev-DB pytest residue (`--dry-run` supported). | closed OI-T3 |

---

## 3. Deferred by design (carried from earlier phases)

Tracked for completeness; these are intentional scope cuts, not accidental debt.

| ID | Status | Pri | Item | Source |
|----|--------|-----|------|--------|
| OI-B1 | 🟢 | P2 | **JS/TS call-graph resolution.** Tree-sitter collects `call_expression` sites; graph resolves unique / same-file / `this`→`self` edges (OI-B1). Go/etc. remain symbols/imports only. | PHASE_B §BB5/BB10 | closed OI-B1 |
| OI-B2 | 🟢 | P2 | **Partial / per-file re-ingest.** RepoWatcher Detect builds file blob manifests; Policy may choose `partial_ingest`; `learn_repository(paths=/drop_paths=)` merges re-parsed files into the prior artifact (same stores). Large/first/forced ticks stay full. | PHASE_B §B.6 | closed OI-B2 |
| OI-B3 | 🟢 | P2 | **Knowledge Conflict Resolver.** Contested findings get `quality.conflict` why-records; `GET /v1/knowledge/contested` + `POST .../resolve` (hold/supersede/reactivate); DecisionRule `knowledge_conflict` recommends options. Still one Knowledge OS — no parallel conflict DB. | PHASE_B "not building" | closed OI-B3 |
| OI-B4 | 🔴 | P3 | **Additive readers:** CAD / MATLAB / PLC / UML / PSpice, etc. Register in the (unified, OI-C2) Reader Registry with no changes elsewhere. | PHASE_B "not building" |
| OI-A1 | 🟢 | P3 | **Cron schedules.** `scheduler.schedules.kind` + `cron_expr` (migration `0042`); `ScheduleService.register_cron_schedule` / worker `cron_expr` / template `worker_specs.cron`. Interval + continuous unchanged. | PHASE_A §A (schedules) | closed OI-A1 |
| OI-A2 | 🟢 | P3 | **Job-advance priority threading** through the scheduler. `plan_job` / `advance_job` stamp `Mission.effective_priority` when `job.mission_id` is set (same A7 formula as schedules). | PHASE_A | closed OI-A2 |
| OI-A3 | 🟢 | P3 | **Resource caps:** `llm_units_per_window` (+ optional `llm_window_seconds`) and `ram_mb` host reserve enforced on the MissionArbiter / WorkerManager tick gate (OI-A3). Machine RM remains the global complement. | PHASE_A | closed OI-A3 |
| OI-X1 | ⚪ | — | **Remote access + hot/warm/cold storage tiering.** Hardware-gated; single-disk for now. | ROADMAP / PHASE_B |

---

## 4. Recently closed

| ID | Item | Closed by |
|----|------|-----------|
| OI-A3 | **Resource caps** — `llm_units_per_window` + `ram_mb` on MissionArbiter tick admit. | _(pending commit)_ |
| OI-A2 | **Job-advance priority threading** — plan/advance tasks inherit mission effective_priority. | `a68daf5` |
| OI-A1 | **Cron schedules** — 5-field crontab on `scheduler.schedules` + claim advance. | `7facc54` |
| OI-C10 | **Experience evidence-retraction on revert** — peel repo_uid from shared experiences; archive if alone. | `2393b65` |
| OI-B3 | **Knowledge Conflict Resolver** — conflict quality + list/resolve API + DE rule. | `3602eab` |
| OI-B2 | **Partial / per-file re-ingest** — file Detect + `paths=` merge into prior artifact. | `a5975aa` |
| OI-B1 | **JS/TS call-graph resolution** — tree-sitter call sites + heuristic edges. | `3fb8f3c` |
| OI-PM0 | **Personal Mentor Mission** — owner/career weekly lessons; Programs stub-free. | `4742c4c` |
| OI-MP4 | **Engineering Mentor Mission** — weekly judgment lessons → Experience OS. | `005b8c6` |
| OI-C12 | **Personal/Owner SPA dashboard** — `/ui` Personal panel + coverage/confirm/infer/draft. | `6835729` |
| OI-D1 | **Live market-data feed** — Yahoo + Polygon/AV live clients; NSE/BSE skeletons. | `df2d71b` |
| OI-C11 | **Personal proficiency + timeline years + heuristic professional.** | `869ec44` |
| OI-C13 | **Conversation → experience extraction** — `build_conversation_experiences` + ingest wire. | `7f35a28` |
| OI-T1/T2/T3 | **Live-DB test hygiene** — session cleanup + `atlas-db test-clean`; `list_pending(source=)`. | `44dd079` |
| OI-MP5 | **Missions teach missions** — mentor soft-bias + Decision Engine Experience nudge. | `9d22b66` |
| OI-UI0 | **Job UI live updates** — sequential poll + SSE refresh; `/ui` no-cache headers. | `efc7091` |
| OI-RH0 | **Media Report Honesty** (acquire-stop UX: NOT_APPLICABLE, Research blocked, operator strategies). | RH.1–RH.4 / `tests/test_media_report_honesty.py` |
| OI-M0 | **Media Reader Family plan** (M.1–M.7) — Asset-first media Readers, optional Whisper, provider-agnostic fetch, research wiring + e2e gate. | M.7 / `tests/test_media_acquisition_gate.py` |
| OI-G1 | **`.gitignore` silently ignored `atlas/{documents,knowledge,models}` source packages** (unanchored runtime-data rules) — 25 core source files were untracked. Anchored the rules to the repo root; source now tracked. | commit `57deac9` (2026-07-19) |
| OI-C6 | Prose "distilled findings" from documents — now flow document → candidate → Consolidator → finding. | C.3g commit `4595ee8` (2026-07-19) |
| (bug) | **`UNIQUE(canonical_id)` blocked the finding revision model** on the live DB (revise reused canonical_id). Relaxed to `UNIQUE(canonical_id, revision)`. | C.3e migration `0033` / commit `58f7c78` |
| (bug) | **Consolidator spuriously revised on subset re-observation.** Re-observing an already-known source on a multi-source finding (incoming supporting ⊆ existing, body unchanged) deferred to the transition machine, which saw the differing supporting-set and spawned a revision that discarded accumulated evidence. `_accumulate` now returns an explicit no-op. Surfaced by C.6 shared-identity experiences. | C.6d commit `2ed3771` |

---

_When you close an item, move it to §4 with the resolving commit, and flip its status to 🟢._
