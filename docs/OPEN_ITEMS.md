# Atlas — Open Items, Leftovers & Known Issues

> **Purpose.** A single, living registry of *everything deferred* — intentional deviations, deferred
> features, tech/test debt, and known flakes — so nothing gets lost between phases. Each item has an
> **ID**, a **status**, where it was **introduced**, and the **target** phase/owner. Items are closed
> by referencing their ID in the commit/plan that resolves them.
>
> Companion to `ATLAS_OS_ROADMAP.md` (principles/architecture) and the `PHASE_*_PLAN.md` docs
> (per-phase scope). When a plan says "deferred", the actionable item lives **here**.
>
> **Last updated:** 2026-07-19 (after Phase C.2).

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
| OI-C5 | 🔴 | P1 | **Wire `IngestionService` into the kernel + surfaces.** It is constructed only in tests. Needs bootstrap wiring (kernel service registry) and a CLI/API entrypoint (`atlas ingest <path>` / `POST /v1/ingest`) so operators/missions can drive it. | C.2c | C.3 or a small C.2e |
| OI-C6 | 🟢 | — | **Prose "distilled findings" from documents.** Deferred from C.2 **by design** — must flow through the Knowledge Consolidator. Resolved by C.3. | C.2c | **C.3** |
| OI-C7 | 🟡 | P3 | **Migration-number placeholders.** The `PHASE_C_PLAN.md` data-model table lists planning placeholders (`00xx_finding_embeddings`, `knowledge_coverage`, …). Real numbers are assigned sequentially at build time — `0028`=document↔asset, `0029`=asset groups; C.3 uses `0030`–`0032`. Keep the table honest as slots are built. | C.2 | ongoing |

---

## 2. Cross-cutting test / infra debt

| ID | Status | Pri | Item | Notes |
|----|--------|-----|------|-------|
| OI-T1 | 🔴 | P1 | **Live-DB tests share one Postgres with no teardown.** e2e tests insert into `learning.repositories`, `knowledge.*`, `asset.*`, `audit.events` and don't clean up. After a reboot clears `/tmp` (tmpfs), pytest's temp counter restarts and fresh tmp paths **collide** with stale `active` rows (e.g. `uq_learning_repositories_root_active`). Needs a proper isolation strategy: per-test transaction rollback, a disposable schema/db per run, or session teardown fixtures. | Caused 3 false failures on 2026-07-19; mitigated by a manual cleanup of `/tmp/pytest%` rows. |
| OI-T2 | 🟡 | P2 | **`test_event_lifecycle` flake.** `EventRepository.list_pending(limit=100)` can't see a newly-recorded event once >100 `pending` `audit.events` accumulate from prior test runs. Pre-existing; unrelated to feature code. Fix with the OI-T1 isolation work (or a scoped cleanup fixture / higher/keyed lookup in the test). | Known before Phase C. |
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
| OI-G1 | **`.gitignore` silently ignored `atlas/{documents,knowledge,models}` source packages** (unanchored runtime-data rules) — 25 core source files were untracked. Anchored the rules to the repo root; source now tracked. | commit `57deac9` (2026-07-19) |
| OI-C6 | Prose findings from documents (see §1). | **pending C.3** |

---

_When you close an item, move it to §4 with the resolving commit, and flip its status to 🟢._
