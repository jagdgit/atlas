# Phase C — Global Knowledge foundations + Personal & Professional Intelligence (implementation plan)

> **Open items / leftovers / known issues:** tracked centrally in **[`docs/OPEN_ITEMS.md`](OPEN_ITEMS.md)**
> (Phase-C leftovers: `OI-C1`–`OI-C7`). When this plan says "deferred", the actionable item lives there.
>
> **Status:** 🟢 **FROZEN FOR IMPLEMENTATION (2026-07-19).** Derived from `docs/ATLAS_OS_ROADMAP.md`
> §3 (**P12 — Knowledge is global**, **P13 — Knowledge is cumulative**), §5.9 (Asset relationships),
> §5.12 (Knowledge Consolidator), §5.13 (Policy store), and §6 (Phase C). Builds on Phase 0 (Storage,
> Asset Store, Capability Registry, Clock, event bus + SSE), Phase A (Missions, Workers, Config,
> Templates, Schedules), and Phase B (Asset→Reader→Artifact→Extraction→Knowledge pipeline, Derived
> Artifact Store, Reader Registry, engineering findings, RepoWatcher). **Phase B is complete.**
>
> **Operator decisions confirmed (2026-07-19):** split into **C-Foundations → C-Personal**
> (foundations built with *no compromise* first); **P12 formalized** and provenance stamping starts;
> **full ingestion unification** (Asset-first, *bridge* strategy for existing RAG data);
> **hybrid prose dedup** (deterministic identity + pgvector nearest-neighbor); findings =
> **selective distilled claims** (full text stays RAG chunks); **experiences consolidate** like
> knowledge; inferred personal facts are **auto-inferred with confidence + provenance, promoted to
> `verified` only on operator confirmation** (no silent scraping); the **Policy store** ships in
> Phase C but decision **arbitration** is deferred to the Phase-D Decision Engine.
>
> **R5 pre-freeze refinements (2026-07-19):** added **P13 — Knowledge is cumulative**;
> **Knowledge Candidate ≠ Finding** made explicit (readers emit *candidates*; the Consolidator alone
> synthesizes *findings*); **Knowledge Lineage** (an evidence graph — created/supported/revised/
> superseded/contradicted — not just provenance); a **full lifecycle** (candidate → verified →
> established → deprecated/contradicted/superseded → archived); **Asset relationships/groups** (tie a
> project's repo + docs + chats + PDFs together); **evolution-vs-conflict** routing in the
> consolidator (a revision over time ≠ a contradiction); and **understanding quality** exposed on the
> coverage map (coverage ≠ comprehension).
>
> **Readiness pass (2026-07-19):** verified against the live codebase. Foundations confirmed present
> (`KnowledgeLifecycleService.consolidate`, deterministic `finding_identity_key`, pgvector
> `knowledge.embeddings`, `asset.assets`/`versions`, `DerivedArtifactStore`, `ReaderRegistry`,
> `learning.experiences`, `KnowledgeService.ingest_text`/`retrieve`). Corrections applied: (1) `0027`
> **adds** `mission_id`/`job_id` — they do **not** exist on `knowledge.findings` (`0015`); (2) `0038`
> must ALTER the locked status CHECK + add `maturity` — stored status **stays `contested`**
> ("contradicted" is display-only, avoids an eval-fixture rename); (3) engineering **batch archival**
> is preserved as a wrapper around `consolidate()` (not dropped); (4) **evidence-merge + confidence
> growth** is flagged as **net-new** (today a new source triggers a revision, not an in-place merge);
> plus candidate retention, lineage indexing, reader/artifact **namespace relocation**, and an
> **experience-store adapter** for the shared consolidator.
>
> **Goal:** make the Knowledge OS a truly **global** layer that every mission/job reads and none
> owns (P12), fed by **one unified ingestion pipeline** for every source (repos, documents, chats,
> transcripts, …), deduplicated by a single **Knowledge Consolidator** so Atlas never stores the
> same understanding twice — then build **Personal & Professional Intelligence** on top: a curated,
> provenance-stamped model of the owner, fed by **dual extraction** (one read → engineering
> findings *and* experience) and maintained by a permanent **Owner Knowledge Mission** over the
> owner's archive.
>
> **Not in Phase C:** the **Decision Engine** and policy **arbitration** (Phase D); the big
> autonomous Missions — Job/Research/Paper-Trading/Security watchers (Phase D); remote access
> (deferred); hot/warm/cold tiering (single-disk, deferred). Atlas still **recommends**, never acts
> irreversibly without the operator (P10).

---

## 0. Guiding constraints (from the constitution, §3)

- **P12 knowledge is global (§3, new):** knowledge belongs to Atlas, not to Missions/Jobs/Workers/
  Readers/Intelligences. Producers **discover**, they never **own**. `mission_id`/`job_id`/`asset_id`
  are **provenance**. Archiving a mission never deletes its knowledge (already true — soft refs).
- **P13 knowledge is cumulative (§3, new):** a new observation **creates / strengthens / revises /
  contradicts** existing knowledge — it is **never** blindly duplicated. This governs dedup,
  confidence growth, revisions, evidence accumulation, and consolidation (C.3). Its corollary:
  **readers emit Knowledge Candidates, never Findings** — extraction (observation) is separated from
  synthesis (the Consolidator's decision).
- **P11 readers never own knowledge:** every new source is a **Reader** over an **Asset**; the
  pipeline stays **Asset → Reader → Artifact → Extraction → Knowledge Candidate → Consolidator →
  Knowledge**. A **Knowledge Candidate** is a transient observation; only the Consolidator writes a
  durable **Finding**. New source types (chat/PDF/email/transcript) add **readers + a generic
  acquirer**, not new intelligences and not new pipelines.
- **P8 Assets ≠ Knowledge / one Storage Manager:** the **Asset is the single source of truth**;
  **chunks/embeddings AND findings are both derived products** of the same asset. Re-reading a
  better reader is a **re-extraction**, never a re-download; identical raw bytes are stored once
  (content sha256).
- **P2 model independence + artifact versioning:** every finding/experience/coverage row is stamped
  with real `reader_version`/`extractor_version`/`llm_id`/`embedding_id` from the Capability
  Registry, so a model swap invalidates nothing except what genuinely depends on that model
  (re-embed / re-review). Enables A10 (attribute a delta to *reader improved* vs *source evolved*).
- **P1 durability / P4 design-for-failure:** ingestion is resumable + idempotent; the Owner
  Knowledge Mission is a **mission spawning jobs + a persistent worker** (reuses Phase-A/B
  frameworks verbatim); a `kill -9` mid-archive resumes from coverage + checkpoints, not scratch.
- **P6 everything configurable + versioned:** the Owner Knowledge Mission runs off a **versioned
  mission config** (archive roots, reader selection, extraction depth, embed on/off, interval).
- **P9 explainability + governance:** every knowledge/experience/policy write goes through the
  governed ledger (`propose → apply → revert`) and journals *why / refs / versions*. Personal facts
  carry provenance for **how each fact was learned** and stay operator-confirmable.
- **P10 no irreversible action without the operator:** Personal Intelligence and the Policy store
  are **read/advice** surfaces. Nothing edits LinkedIn/resume/code or acts on the world; Atlas
  drafts, the operator approves.

---

## 1. Resolved decisions (locked for Phase C)

| # | Decision |
|---|---|
| CC1 | **P12 is a constitutional principle.** Add to roadmap (done); stamp `mission_id`/`job_id`/`source` as provenance on findings. **`knowledge.findings` has no `mission_id`/`job_id` columns today** (verified against `0015`), so `0027` **adds** them (nullable) — they do not yet exist. Ownership stays absent. |
| CC2 | **Unify ingestion, Asset-first, via *bridge*.** New sources go Asset→Reader→…; the existing Document/RAG path becomes a reader over an asset and is back-filled lazily. Existing documents keep working throughout. |
| CC3 | **One Consolidator = the single knowledge write path.** Route the engineering writer through it. |
| CC4 | **Hybrid dedup:** deterministic `identity_key` for structured/engineering + **pgvector nearest-neighbor** for prose (similarity threshold → merge/revise vs create). |
| CC5 | **Findings = selective distilled claims;** full text stays as **RAG chunks** on the same asset. Extraction depth is reader/config-driven (code exhaustive; prose selective). |
| CC6 | **Experiences consolidate** with the same dedup/merge/confidence-growth model (shared engine, experience-tuned identity). |
| CC7 | **Personal facts:** auto-infer with confidence + provenance; **operator confirmation promotes to `verified`.** No silent scraping (A9). |
| CC8 | **Policy store ships in C; arbitration in D.** Retrieval/advice respect policies; the Decision Engine combines Knowledge×Policy later. |
| CC9 | **Coverage map** tracks per-`(asset, reader, reader_version)` extraction status + per-domain rollups; drives targeted re-extraction. |
| CC10 | **P13 — Knowledge is cumulative** is constitutional. The Consolidator (C.3) enforces it: create / strengthen / revise / contradict, never duplicate. |
| CC11 | **Knowledge Candidate ≠ Finding.** Readers emit **candidates** (transient, short-retention audit trail); the Consolidator alone synthesizes durable **findings**. Concretizes P11. |
| CC12 | **Knowledge Lineage = an evidence graph**, not just provenance. Every finding records `created_by` / `supported_by` / `revised_by` / `superseded_by` / `contradicted_by` edges over (candidate, asset+version, source, job, mission), so confidence changes are traceable to evidence (P9). |
| CC13 | **Full lifecycle.** Two axes: a **new `maturity` column** (candidate → verified → established, from corroboration/confidence) × the existing **validity** `status` machine (active → deprecated / contested / superseded → archived). `0038` ALTERs the `0015` status CHECK + adds maturity. **Stored status stays `contested`**; "contradicted" is display-only (a physical rename would ripple into the locked eval fixtures — deferred/opt-in). |
| CC14 | **Asset relationships / groups.** Assets aren't islands — a project's repo + design doc + PDF + chats link via `asset.groups` (+ membership) / pairwise `related`, so readers/consolidator traverse across sources; membership flows into lineage. |
| CC15 | **Evolution ≠ conflict.** The Consolidator uses **recency/temporal signals** (evidence timestamps + asset version order) to route same-claim-newer-state → **revise/supersede** and same-time-disagreement → **contested**. Coverage also exposes **understanding quality** (comprehension), not just coverage %. |

---

## 2. Work items (ordered) & acceptance

### C-Foundations (the P12 base — no compromise, first)

#### C.1 P12 + provenance stamping  ·  ✅ **DONE (2026-07-19)**  ·  migration `0027`
- **Add the columns first.** `0027` **adds** `mission_id UUID` + `job_id UUID` (nullable, soft refs,
  indexed) to `knowledge.findings` — verified they are **absent** in `0015`. (Correction to the prior
  draft, which wrongly assumed the column already existed.) ✅ applied (27 migrations, 0 pending).
- **Provenance, not ownership.** Extend the provenance builders (`atlas/knowledge/provenance.py`,
  `atlas/engineering/findings.py::_provenance`) to carry `mission_id`, `job_id`, and a `source`
  descriptor; write the new `knowledge.findings.mission_id`/`job_id` columns on create.
- Add read paths: `FindingRepository.list_by_mission(mission_id)` / `list_by_job(job_id)` and an
  API/console "discovered by this mission" view (reuses the Phase-B engineering findings surface).
- **Acceptance:** a finding produced under a mission/job records who discovered it + from which
  asset/version/model; deleting/archiving that mission leaves the finding intact (P12); hermetic
  tests assert provenance is stamped and never used as an ownership filter.
- **Delivered:** `0027` (mission_id/job_id columns + indexes); `FindingRepository` persists the
  columns (from kwargs *or* the provenance JSON), carries them across revisions, and adds
  `list_by_mission`/`list_by_job`; `_provenance`/`build_engineering_findings` + the design reviewer
  stamp `mission_id`/`job_id`/`source` (omitted when absent → pre-Phase-C ingests stay byte-identical);
  `learn_repository` threads `mission_id`/`job_id`; `IntelligenceService.list_findings` +
  `GET /v1/engineering/findings` gain a `mission_id`/`job_id` discovery lens and surface who
  discovered each finding. **Tests:** hermetic (provenance stamping for structure/dependency/pattern
  + design/risk; mission/job scoping) + live-DB (`tests/test_phase_c_provenance.py`: columns persist
  from both paths, soft-ref/no-cascade, supersede carries provenance) + a full-pipeline
  mission-scoped e2e in `tests/test_phase_b_e2e.py`. Full suite: 1287 passed (the 1 unrelated
  `test_event_lifecycle` failure is a pre-existing shared-DB pollution flake).

#### C.2 Unified ingestion — generic acquirer + document/PDF reader  ·  *the spine*  ·  ✅ **DONE (2026-07-19)**  ·  migrations `0028`, `0029`
- **Generic (non-git) Asset Acquirer** (`atlas/ingestion/acquire.py` or `atlas/assets/…`): register
  arbitrary bytes/files as an **asset** (kind e.g. `document`, `pdf`, `transcript`), identity =
  **content sha256** (matches today's `DocumentRepository` dedup), versioned + checksummed via the
  Asset Store. Mirrors `RepoAcquirer` (BB1/BB12) for the non-repo case.
- **Document Reader** (`atlas/readers/document.py`, registered in the **Reader Registry**): turns a
  document asset into an **Artifact** (page text, sections, tables) cached in the **Derived Artifact
  Store**; the existing `atlas/ingestion/extractors.py` (txt/md/pdf/html/docx/pptx/xlsx/csv) becomes
  the reader's engine. **Namespace note:** the **Reader Registry** (`atlas/engineering/readers.py`)
  and **Derived Artifact Store** (`atlas/engineering/artifacts.py`) are logic-generic but currently
  live under `atlas/engineering/`. First non-code reader → **relocate both to a neutral package**
  (`atlas/readers/`, `atlas/artifacts/`) and re-export from engineering (small, mechanical), so
  readers aren't rooted in the engineering domain.
- **Bridge the two universes (CC2):** the Asset is the source of truth; from one asset a reader
  produces **both** RAG **chunks/embeddings** (existing `KnowledgeService.ingest_text` path,
  re-homed as a derived product keyed to the asset) **and** distilled **findings** (via C.3).
  Existing documents keep working; new ingestion is Asset-first; old docs are back-filled to assets
  lazily/opportunistically (no big-bang migration).
- **Asset relationships / groups (CC14)  ·  migration `0035`:** add `asset.groups` (id, name, kind)
  + `asset.membership` and/or pairwise `asset.related` (asset_a, asset_b, relation) so a project's
  repo + design doc + PDF + chat link together. Group/relationship membership is provenance and is
  consumable by readers/consolidator (cross-source corroboration) and by lineage (C.3). Grouping is
  operator- or mission-assigned now; auto-grouping heuristics are out of scope for Phase C.
- **Acceptance:** ingest a PDF and a text file → one asset each (deduped by sha256), retrievable +
  checksum-verified; the same asset yields searchable chunks **and** distilled findings, both
  provenance-linked to the asset id + version; re-ingesting the identical file reuses the asset (no
  duplicate bytes); two related assets can be grouped and the group is queryable. Hermetic unit tests
  + one live-DB smoke.
- **✅ Delivered (2026-07-19):**
  - **C.2a** `atlas/ingestion/acquire.py` — `AssetAcquirer.acquire_bytes/acquire_file`, content-sha256
    identity, reuse-on-identical, via the Asset Store (P11). *(commit `51927a5`)*
  - **C.2b** `atlas/readers/document.py` — `DocumentReader` turns a doc asset → cached text artifact
    in the Derived Artifact Store keyed by `{asset_id, asset_version, reader, reader_version}`.
    *(commit `5f0ee51`)*
  - **C.2c** `atlas/ingestion/service.py` — `IngestionService` bridge (acquire → read → chunks/
    embeddings); migration **`0028`** links `knowledge.documents` → `(asset_id, asset_version)`
    (soft ref); `DocumentRepository.set_asset/get_by_asset`; `ingest_text` threads the link.
    *(commit `cd6805f`)*
  - **C.2d** migration **`0029`** `asset.groups` + `asset.group_members`; `AssetStore` group API
    (create/add/remove/members/groups_for_asset). *(commit `7971359`)*
  - **Repo hygiene:** `.gitignore` was silently ignoring the `atlas/{documents,knowledge,models}`
    **source** packages (unanchored runtime-data rules) — fixed + 25 core files now tracked.
    *(commit `57deac9`)*
  - **⚠ Deviations from plan (intentional, low-risk):**
    (1) The Document Reader lives in the new neutral **`atlas/readers/`** package as planned, but the
    **Derived Artifact Store was NOT physically relocated** out of `atlas/engineering/artifacts.py`;
    the reader is **duck-typed** against `get/put` instead, so it doesn't couple to engineering. A
    later mechanical relocation of `DerivedArtifactStore` (+ `ReaderRegistry`) to `atlas/artifacts/`
    remains open.
    (2) The Document Reader is **not registered in the code `ReaderRegistry`** (whose coverage matrix
    is code-capability-specific); it exposes its own `supported_extensions()`. Unifying the registry
    is deferred with the relocation above.
    (3) **Prose "distilled findings" are deferred to C.3** (they must flow through the Consolidator,
    which C.3 builds) — the bridge deliberately stops at the RAG/chunks product so C.3 adds the
    finding path without reworking the seam. The C.2 acceptance's "findings" clause lands with C.3.
    (4) Asset groups shipped as **`0029`** (next sequential slot), not the penciled `0035`.

#### C.3 Consolidator as the single write path + hybrid dedup + candidates/lineage/lifecycle  ·  ✅ **DONE (2026-07-19)**  ·  migrations `0030`, `0031`, `0032`, `0033`, `0034`

> **✅ Delivered (2026-07-19).** Built in seven committed sub-steps (`7919464`, `de0522b`, `deaac08`,
> `5f1634c`, `58f7c78`, `f5624b0`, `4595ee8`):
> - **C.3a** `knowledge.candidates` inbox (migration `0030`) + `CandidateRepository` (CC11) —
>   readers emit candidates; only the Consolidator consumes them; consumed rows prunable.
> - **C.3b** `knowledge.lineage` append-only evidence graph (migration `0031`) + `LineageRepository`
>   (CC12/P9) — created/supported/revised/superseded/contradicted_by edges; never pruned.
> - **C.3c** maturity axis (migration `0032`): `candidate → verified → established` as a **separate**
>   column (0015 status CHECK untouched; `contested` stays stored, "contradicted" is display) +
>   `derive_maturity`/`independent_source_count` + `FindingRepository.set_maturity`/`update_evidence`.
> - **C.3d** evidence accumulation + conflict in `consolidate()` — `body_fingerprint` separates
>   statement/value changes from evidence-only changes; same fact + new source **merges in place**
>   (no revision, grows confidence/maturity); same-statement contradiction → `contested`; body change
>   routed evolution (newer → revise) vs conflict (same/older → contested) by timestamp (CC15).
> - **C.3e** `EngineeringFindingWriter` routed through `consolidate()` (single write path, CC3);
>   batch archival kept as a wrapper. **Migration `0033`** fixes a latent bug it exposed:
>   `UNIQUE(canonical_id)` → `UNIQUE(canonical_id, revision)` so the revise path works on the live DB
>   (benefits research promote too).
> - **C.3f** hybrid identity (CC4): **migration `0034`** `knowledge.finding_embeddings`
>   (vector(768), HNSW) + `FindingEmbeddingRepository` + `EmbeddingIdentityResolver`; prose paraphrases
>   merge via cosine NN above a threshold (explainable via lineage `nn_similarity`). Optional +
>   back-compatible (deterministic-only when no resolver wired).
> - **C.3g** document → candidate → Consolidator → finding: `ProseKnowledgeExtractor` (bounded
>   distillation, CC5) + `CandidateConsumer` (the single candidate→finding path); `IngestionService`
>   emits **candidates only** under `extract_findings=True`. Enforcement test proves the bridge writes
>   ZERO findings (P11); findings appear only after the Consolidator drains the inbox.
>
> **Deviations / notes:** (1) Migrations landed as `0030`–`0034` (candidates, lineage, maturity,
> canonical-revision fix, finding-embeddings) — **five**, not the penciled three (the canonical-uniq
> bug fix and the finding-embeddings table were surfaced during implementation). Downstream C.4–C.8
> migration numbers below are **re-penciled to `0035`+** (assigned sequentially at build time).
> (2) The maturity axis is a new column, so 0015's `status` CHECK was **not** altered (cleaner than
> loosening it; `contested`/"contradicted" split preserved). (3) NN + prose extraction are wired as
> **optional** collaborators so C.2/existing callers are byte-unchanged until explicitly enabled.
> (4) Kernel/API wiring of `CandidateConsumer` + `IngestionService` is tracked as `OI-C5` (they're
> constructed in tests today). See `docs/OPEN_ITEMS.md`.

*(Original plan — migrations penciled `0030`–`0032`, renumbered from `0036`–`0038`.)*
- **Single write path (CC3):** route the per-finding write of `EngineeringFindingWriter` (and all
  future extractors) through `KnowledgeLifecycleService.consolidate()`; keep its
  create/noop/revise/supersede/contested + confidence/freshness behavior. **Keep the repo-scoped,
  claim-type-scoped batch archival (`_archive_stale`, B.5/BB9) as a wrapper around consolidate** —
  `consolidate()` is one-finding-at-a-time and has *no* notion of "archive stale findings not in this
  batch", so this logic must **not** be dropped (verified: it lives only in
  `EngineeringFindingWriter`). Net effect: consolidate becomes the single *create/revise* path;
  batch archival stays a distinct post-step.
- **Knowledge Candidate object (CC11)  ·  migration `0036`:** readers/extractors emit
  `knowledge.candidates` — transient observations `{statement, claim_type, identity_key, embedding,
  evidence_ref (asset+version, source, job, mission, reader/model versions), ts, consumed_at}`. Only
  the Consolidator reads candidates and writes findings; readers **never** touch `knowledge.findings`
  (enforces P11/P13). **Retention policy:** candidates are marked `consumed_at` on consolidation and
  pruned by a scheduled job after a configurable window (default 30 days) so the table stays bounded;
  the durable audit trail is the lineage graph (below), not the candidate rows.
- **Hybrid identity (CC4):** keep deterministic `finding_identity_key` for structured/engineering;
  add an **embedding nearest-neighbor** stage for prose — embed the candidate statement (pgvector),
  find the nearest active finding above a similarity threshold → treat as the same logical finding
  (merge evidence, grow confidence, revise if content differs); else create. Never scan all rows
  (ANN index). Threshold is configurable + explainable ("merged with F-1928 @ 0.94").
- **Lineage — evidence graph (CC12)  ·  migration `0037`:** on every consolidation decision, write
  `knowledge.lineage` edges `{finding_id, revision, edge_type ∈ {created_by, supported_by,
  revised_by, superseded_by, contradicted_by}, evidence_ref, ts}`, indexed on `finding_id` +
  `edge_type` (append-only; it *is* the durable audit trail, so no pruning). Answers P9's *"what
  evidence created/changed me?"* precisely and lets confidence changes be traced to their cause.
  Extends today's `provenance_edges` rather than replacing it.
- **Full lifecycle (CC13)  ·  migration `0038`:** add a **maturity** axis (`candidate → verified →
  established`, derived from corroboration count + confidence; *established* = N independent sources)
  as a **new `maturity` column** on `knowledge.findings`, alongside the existing **validity** `status`
  machine (`active → deprecated / superseded / contested → archived`). `0038` must **ALTER the
  existing `knowledge_findings_status_check` CHECK** (currently locked to
  `active/contested/deprecated/superseded/archived`, per `0015`) to admit the new maturity values /
  any new status, and add a maturity CHECK.
- **Naming decision — keep `contested` stored, present as "contradicted" (recommended):** the stored
  status value stays **`contested`** (that literal is wired through `atlas/knowledge/lifecycle.py`,
  `consolidation.py`, **and** the locked eval oracle `atlas/eval/lifecycle.py` — a rename ripples into
  fixtures). "Contradicted" is the **display/label** for `contested`. A physical rename is a separate,
  opt-in slice if ever wanted — **not** on the Phase-C critical path.
- **Evidence accumulation + conflict (⚠ NET-NEW behavior):** same fact from mission + job + reader →
  **one finding, N evidence entries, higher confidence, rising maturity**; contradicting evidence →
  `contested`/`contradicted` (no silent averaging). **This is new work, not existing behavior:** today
  adding a supporting source changes `content_fingerprint` → triggers a **revise** (a new revision
  row), so the consolidator does *not* yet merge evidence in place or grow confidence. C.3 must add
  true evidence-merge (append to `supporting[]` + recompute confidence **without** spawning a
  revision, reserving revisions for genuine statement/value changes). This is the single largest new
  algorithm in Phase C.
- **Evolution ≠ conflict (CC15):** distinguish a **revision over time** ("Redis optional" 2025 →
  "Redis required" 2027 → **revise/supersede**, keep lineage) from a **contradiction** (two sources
  disagree at the same time → **contested**) using evidence timestamps + asset version order.
- **Selective granularity (CC5):** extraction depth is reader/config-driven; prose readers emit a
  bounded set of distilled claims worth remembering, not per-sentence facts.
- **Acceptance:** readers write only candidates (a test asserts no reader path writes findings
  directly); the same fact discovered three ways becomes one finding with three evidence entries +
  increased confidence + rising maturity (not three rows); a paraphrase merges via NN; a
  contradiction at the same time marks `contested`, while a newer-dated claim **revises** (lineage
  shows `revised_by`/`superseded_by`); the lineage graph answers "what evidence created/changed this
  finding?"; re-reading a large document **updates** existing findings rather than duplicating;
  engineering findings still supersede correctly through the unified path. Hermetic tests per
  behavior + one live-DB test (mirrors the 5 GB scenario at small scale).

#### C.4 Knowledge Coverage map (+ understanding quality)  ·  ✅ **DONE (2026-07-19)**  ·  migration `0035`

> **✅ Delivered (2026-07-19).** Built in five committed sub-steps (`4039739`, `b40ab0f`, `949a125`,
> `c8b3b40`, `f3e0f91`):
> - **C.4a** `knowledge.coverage` store (migration `0035`) + `CoverageRepository` — one row per the
>   Derived-Artifact 4-tuple `(asset_id, asset_version, reader, reader_version)`; idempotent upsert
>   `record()`, `get`/`list`, per-domain/source `summary()` rollups, and `stale()` enumeration.
>   A **new reader_version mints a new row** (old read preserved for the reader-improved delta);
>   `extractor_version` is stored (not keyed) so an extractor bump updates in place.
> - **C.4b** `FindingRepository.understanding_by_domain()` — per-(domain, maturity, status) aggregate
>   over active head revisions (one row per canonical_id) that backs **understanding %** (CC15).
> - **C.4c** `CoverageService` (capability `coverage`) — combines coverage % (done/total) with a
>   maturity/confidence-weighted, contested-discounted understanding % into a per-domain + overall
>   summary (**coverage ≠ comprehension**), and enumerates/flags stale rows for targeted
>   re-extraction (A10).
> - **C.4d** recording wired at both extraction completion points: `IngestionService` (success +
>   the unreadable/unsupported/empty path) and `IntelligenceService.learn_repository` (asset-backed
>   learns, stamped with `extractor_version`). Coverage is **best-effort telemetry** — a recorder
>   failure never breaks ingest/learn.
> - **C.4e** bootstrap wiring (`CoverageRepository` + `CoverageService` → `IntelligenceService` +
>   container/capability) + `GET /v1/knowledge/coverage` + `atlas coverage` CLI. Hermetic API/CLI
>   tests + a bootstrap smoke.

> **Deviations / notes:** (1) C.4 consumed exactly the one penciled migration `0035`, so downstream
> C.5–C.8 numbers (`0036`–`0039`) are unchanged. (2) The unified `IngestionService` is not yet
> constructed in the kernel (that bridge is still `OI-C5`), so its coverage recorder is wired +
> hermetically tested but only takes effect once `IngestionService` is bootstrapped; the code path
> for `IntelligenceService` is live now. (3) `understanding %` weighting (established 1.0 / verified
> 0.66 / candidate 0.33, × status factor active 1.0 / contested 0.5 / deprecated 0.25) is a policy in
> `atlas/knowledge/coverage.py`, kept out of SQL so it stays explainable and tunable.

*(Original plan below.)*

- **Coverage store** (`knowledge.coverage`): per `(asset_id, asset_version, reader, reader_version)`
  extraction status (pending/done/failed, counts, timestamps, extractor_version); a service that
  rolls up **per-domain / per-source coverage** ("Python 100%, MATLAB 20%").
- **Understanding quality (CC15):** alongside *coverage %* (how much was read) expose
  *understanding %* (comprehension) — a per-domain rollup of finding **confidence/maturity** (and
  contested/low-confidence share). **Coverage ≠ comprehension:** Atlas may have read everything yet
  hold low confidence ("Python: coverage 98%, understanding 82%").
- **Targeted re-extraction (A10):** when a reader/extractor version increases, enumerate the assets
  extracted by the older version and re-extract **only those** — the delta is attributable to
  *reader improved* vs *source evolved* because both versions are stamped.
- **Acceptance:** ingesting assets populates coverage; bumping a reader version marks affected assets
  for re-extraction and leaves others untouched; a coverage summary **with both coverage % and
  understanding %** is queryable via API/console.

#### C.5 Policy store  ·  ✅ **DONE (2026-07-19)**  ·  migration `0036`

> **✅ Delivered (2026-07-19).** Built in four committed sub-steps (`7682a8b`, `ea69571`, `6c25809`,
> `b2ef4c7`):
> - **C.5a** `policy` schema (migration `0036`): `policy.rules`
>   (scope/subject/rule/strength/enabled/provenance, `prefer|avoid|trust|distrust`, unique per
>   scope+subject+rule) + append-only `policy.events` before/after journal + `PolicyRepository`
>   (CRUD, natural-key upsert, snapshot restore, JSON-safe journaling).
> - **C.5b** `PolicyService` (capability `policy`): create/update/enable-disable/delete each **journal**
>   a before/after event; **`revert(event_id)`** restores the prior state (undo create→delete,
>   delete→restore, update/toggle→restore-before). `retrieval_influence()` derives a **signed, bounded**
>   weight per enabled rule (prefer/trust +, avoid/distrust −; magnitude = `strength × POLICY_INFLUENCE_MAX`,
>   0.02) with global-only scoping unless a caller scope is supplied.
> - **C.5c** influence wired into **retrieval + advice**: `heuristic_rerank` applies signed policy
>   deltas and records the affecting rule ids on each hit + citation ("boosted by policy P-12");
>   `KnowledgeService.retrieve` reports `policy_rules_applied` in `meta`; `IntelligenceService.recommend`
>   re-orders advice by the same influence. **Influence, not arbitration** — a hit/rec is never removed.
> - **C.5d** operator surfaces: `GET/POST /v1/policy/rules`, `GET /v1/policy/rules/{id}`,
>   `POST .../enable`, `GET /v1/policy/events`, `POST /v1/policy/events/{id}/revert` + an
>   `atlas policy <set|list|show|enable|disable|revert|events>` CLI; registered as the `policy`
>   capability and attached to KnowledgeService + IntelligenceService in bootstrap.

> **Deviations / notes:** (1) Governance uses a **dedicated `policy.events` journal** (before/after +
> `revert`) rather than routing through the Learning ledger — keeps the Policy layer cleanly separate
> from Experience (the five-things model). (2) No hard `DELETE` route (the codebase uses POST
> sub-actions); rule removal is available via the service/CLI, and API edits are create/enable/disable/
> revert. (3) Policy influence magnitude (0.02) is deliberately small — larger than experience
> soft-bias (0.005) but far below relevance, so it nudges ranking without overriding it (CC8).
> (4) Scoping beyond `global` is stored but retrieval only applies `global` unless a caller passes a
> scope; mission/domain-scoped application is a later hook. (5) Full suite 1385 green, same known
> pre-existing env flake `OI-T2`.

*(Original plan below.)*

- **`policy.*` schema + service** (`atlas/policy/`): durable, editable, provenance-stamped operator
  rules — `{scope, subject, rule, strength, enabled, provenance, created_by, created_at}`. Governed
  (edits are journaled + reversible). Examples: *prefer momentum strategies*, *never trade crypto*,
  *trust finding F-1928*.
- **Influence, not arbitration (CC8):** evolve the existing gated **soft-bias** into a first-class,
  policy-driven **retrieval/advice** influence (`KnowledgeService.retrieve` + advice surfaces
  respect enabled policies). **No decision arbitration** — that's the Phase-D Decision Engine.
- **Acceptance:** the operator can create/edit/disable a policy via API/console; retrieval + advice
  visibly respect it (explainable: "boosted by policy P-12"); policies are separate from knowledge,
  experience, and mission config (the five-things model); nothing acts on the world.

### C-Personal (on the foundations)

#### C.6 Experience extraction + consolidation (dual extraction)  ·  migration `0037` *(re-penciled)*
- **Dual extraction (P12/P11):** one read of an asset feeds **two** extractors — engineering
  findings (existing) **and** an **experience** extractor that emits owner-experience records
  ("solo Django project, 2022, designed auth, production Celery/Redis"). No code/raw duplication;
  the repo is read once.
- **Experience consolidation (CC6):** run experiences through the shared consolidator with an
  experience-tuned identity (e.g. skill/technology + context) so "used Celery" corroborated across
  many projects becomes **one experience with growing confidence + evidence**, not N rows. Extend
  `learning.experiences` (evidence list, confidence, corroboration count) rather than a new store.
  **Adapter work:** `KnowledgeLifecycleService` binds to a `FindingStore` **Protocol**
  (`find_active_by_identity`/`append_revision`/`create`/`set_status`/…); to reuse it, provide an
  **experience-store adapter** implementing that Protocol over `learning.experiences` (its own status
  CHECK), or factor the consolidation core to be store-agnostic. The evidence-merge/confidence-growth
  behavior from C.3 is a prerequisite (same engine).
- **Acceptance:** ingesting several repos yields consolidated experiences (one skill, many
  corroborating projects, rising confidence), each provenance-linked to the assets that evidenced
  it; hermetic + live-DB tests.

#### C.7 Personal Intelligence domain (`atlas/personal/`)  ·  migration `0038` *(re-penciled)*
- **A model of you, not a memory dump.** `personal.*` schema for a curated profile: identity/profile
  facts, **skills** (from experience), **timeline** (projects/roles over years), professional
  profile (publications, patents, roles). Fed **indirectly** from Research + Engineering +
  Experience + operator interaction.
- **Inferred-fact confirmation (CC7/A9):** facts are auto-inferred with **confidence + provenance**
  and held as `inferred`; **operator confirmation promotes to `verified`**; operator can correct or
  reject. No silent scraping.
- **Retrieval, not action (P10):** other missions read the profile (e.g. job-search constraints);
  LinkedIn/resume/portfolio managers **draft** from the experience/profile, never scan code and
  never post.
- **Acceptance:** a durable, editable personal/professional profile with per-fact provenance +
  confidence + `inferred/verified` status, readable by other missions; operator confirm/correct
  flows work; a resume/LinkedIn draft is generated purely from the experience profile.

#### C.8 Owner Knowledge Mission + User Archive source + API/dashboard  ·  migration `0039` *(re-penciled)*
- **User Archive** = a new **asset source** (not a job that finishes): a configured set of archive
  roots (code, docs, papers, notes, chats/Cursor exports). A **Conversation Reader**
  (`atlas/readers/conversation.py`) turns chat/Cursor exports into assets → artifacts → findings +
  experience (chats as a first-class knowledge source), reusing C.2/C.3/C.6.
- **Owner Knowledge Mission** (permanent; new built-in template + worker): orchestrates per-domain
  **jobs** (Read Python, Read MATLAB, Read Papers, Read Chats, Build Timeline…), maintains
  **coverage** (C.4), re-extracts with better readers, updates engineering knowledge + experience +
  personal profile, and **never stops** (watches for new/changed assets; resumes on reboot).
- **API + console:** a **Personal / Owner** view — coverage bars per domain, experience/skills/
  timeline with the P9 "why", profile edit/confirm, and live updates over SSE (consistent with
  Phases 0/A/B).
- **Acceptance:** instantiate the Owner Knowledge Mission over a sample archive → it spawns
  per-domain jobs, ingests code + docs + a chat export **once each**, produces engineering findings
  **and** a consolidated experience/skills/timeline profile, shows coverage, survives a restart, and
  is config-versioned — all journaled.

#### C.9 End-to-end acceptance (the Phase-C gate)
Mirrors `tests/test_phase_b_e2e.py` against the live DB: ingest a mixed archive (a real code repo +
a document + a chat export) through the **one unified pipeline** → **global, deduplicated** findings
(same fact from two sources = one finding + two evidence + higher confidence) **and** a
**consolidated experience/skills/timeline** profile; **re-extract** with a bumped reader version →
coverage-driven, updates-not-duplicates (asset unchanged), delta attributable to reader vs source;
a **policy** visibly biases retrieval; the **Owner Knowledge Mission** runs it on schedule, survives
reboot, and is config-versioned; **every artifact is provenance-stamped (P12), explainable (P9),
and reversible.** Hermetic unit tests per item + one integration test against the live DB.

---

## 3. Data-model additions (Phase C)

Reuses existing schema wherever possible (Assets, `knowledge.findings`, `learning.experiences`,
Learning ledger, mission/config/schedule/worker). New objects created `AUTHORIZATION atlas`
(Phase-0 pattern). Migrations continue from `0026` (last shipped).

| Migration | Objects |
|---|---|
| `0027_finding_provenance` ✅ | **Add** `knowledge.findings.mission_id UUID` + `job_id UUID` (nullable soft refs — verified absent in `0015`) + indexes for provenance lookups. *(No new tables; `source` rides existing `provenance` JSON.)* |
| `0028_document_asset_link` ✅ | **Add** `knowledge.documents.asset_id UUID` + `asset_version INTEGER` (nullable soft refs) + index — link the chunked/embedded document back to the source Asset it was read from (P9). *(Shipped as C.2c; the planned "asset_documents mapping" realized as columns, not a join table.)* |
| `0029_asset_groups` ✅ | `asset.groups` + `asset.group_members` — group related assets (repo + design doc + chat) (CC14). *(Shipped as C.2d; this is the table planned below as `0035_asset_relationships`.)* |
| _(placeholders below)_ | **Note:** numbers `0030+` are **planning placeholders**; actual migration numbers are assigned sequentially at implementation time. `finding_embeddings`, `knowledge_coverage`, etc. now shift to `0030`, `0031`, … as the slots below are built. |
| `00xx_finding_embeddings` | Prose-finding **embeddings** for NN dedup + retrieval (pgvector — already used by `knowledge.embeddings`); `embedding_id` provenance stamp. |
| `0035_knowledge_coverage` ✅ | `knowledge.coverage` — per `(asset_id, asset_version, reader, reader_version)` extraction status/counts + `extractor_version`/`domain`/`source`/`repo_uid`. *(Shipped as C.4a at slot `0035`; understanding % is a `FindingRepository.understanding_by_domain()` aggregate + `CoverageService` policy, not columns on this table.)* |
| `0036_policy` ✅ | `policy` schema — `policy.rules` (scope/subject/rule/strength/enabled/provenance/created_by, `prefer|avoid|trust|distrust`) + append-only `policy.events` before/after journal. *(Shipped as C.5a at slot `0036`; governance is a dedicated journal, not the learning ledger.)* |
| `0032_experience_consolidation` | Extend `learning.experiences` with evidence list + confidence + corroboration count (consolidation fields). |
| `0033_personal` | `personal.*` — profile facts, skills, timeline, professional (publications/patents), each with provenance + confidence + `inferred/verified` status. |
| `0034_owner_mission` | Owner Knowledge Mission built-in template + `user_archive` config schema; (worker types reuse Phase-A/B). |
| `0035_asset_relationships` | `asset.groups` (id, name, kind) + `asset.membership`, and/or pairwise `asset.related` (asset_a, asset_b, relation) — tie a project's repo/doc/PDF/chat together (CC14). |
| `0036_knowledge_candidates` | `knowledge.candidates` — transient reader observations (statement, claim_type, identity_key, embedding, evidence_ref, ts); Consolidator input, pruned after consolidation (CC11). |
| `0037_knowledge_lineage` | `knowledge.lineage` — evidence-graph edges `{finding_id, revision, edge_type (created_by/supported_by/revised_by/superseded_by/contradicted_by), evidence_ref, ts}` (CC12). |
| `0038_knowledge_lifecycle` | Add **`maturity`** column to `knowledge.findings` (`candidate/verified/established`) + a maturity CHECK; **ALTER `knowledge_findings_status_check`** (locked in `0015`) to admit it. **Status value stays `contested`** ("contradicted" is display-only — avoids a rename ripple into `atlas/eval/lifecycle.py` fixtures). Understanding-quality rollup fields on `knowledge.coverage` (CC13/CC15). |

**Reused, no schema change:** Asset Store (`asset.assets`/`asset.versions`), Derived Artifact Store,
Reader Registry, `knowledge.findings` + consolidation, Learning ledger, Mission/Config/Schedule/
Worker/Template infrastructure, `knowledge.documents/chunks/embeddings` (re-homed as derived
products, not replaced).

---

## 4. Dependencies & sequencing

**C-Foundations first (no compromise):** C.1 (provenance) → C.2 (unified ingestion) → C.3
(consolidator single path + hybrid dedup) → C.4 (coverage) → C.5 (policy). C.3 depends on C.2 (a
non-code reader to consolidate) and on pgvector for prose NN. C.4 depends on C.2 (assets to cover).
C.5 is independent of C.2–C.4 and can proceed in parallel.

**C-Personal on top:** C.6 (experience extraction + consolidation) needs C.3; C.7 (personal domain)
needs C.6; C.8 (Owner Knowledge Mission + archive + conversation reader) composes C.2/C.3/C.4/C.6/
C.7; C.9 is the gate.

Each item follows the established rhythm: **land → hermetic tests → live-DB smoke → update this
doc**, exactly as Phases A/B did.

---

## 5. Non-goals (Phase C)

- **No Decision Engine / policy arbitration** — the store + retrieval influence only; combining
  Knowledge×Policy into "do X first" is Phase D.
- **No autonomous world actions** — no posting to LinkedIn, editing resumes/code, or acting on
  trades/jobs; Atlas drafts + recommends (P10).
- **No new intelligence per source** — chats/PDFs/emails/CAD/MATLAB are **Readers**, not new
  intelligences (P5/P7).
- **No big-bang RAG migration** — existing documents are bridged/back-filled lazily, never a
  blocking rewrite.
- **No silent personal-fact scraping** — inferred facts require operator confirmation to become
  `verified` (A9).
- Remote access, hot/warm/cold tiering — deferred as before.

---

> **Plan frozen (2026-07-19).** **C.1 (P12 + provenance) ✅ DONE.** **C.2 (unified ingestion +
> asset groups — the spine) ✅ DONE** (migrations `0028`, `0029`; commits `51927a5`, `5f0ee51`,
> `cd6805f`, `7971359`, + gitignore hygiene `57deac9`). **C.3 (Consolidator as the single write path +
> candidates/lineage/maturity + evidence accumulation + hybrid NN dedup + prose pipeline) ✅ DONE**
> (migrations `0030`–`0034`; commits `7919464`, `de0522b`, `deaac08`, `5f1634c`, `58f7c78`, `f5624b0`,
> `4595ee8`; full suite 1339 green, 1 known pre-existing env flake `OI-T2`; leftovers `OI-C1`–`OI-C5`).
> **C.4 (Knowledge Coverage map + understanding quality) ✅ DONE** (migration `0035`; commits
> `4039739`, `b40ab0f`, `949a125`, `c8b3b40`, `f3e0f91`; full suite 1360 green). C.4 consumed exactly
> `0035`. **C.5 (Policy store + retrieval/advice influence) ✅ DONE** (migration `0036`; commits
> `7682a8b`, `ea69571`, `6c25809`, `b2ef4c7`; full suite 1385 green, same 1 known pre-existing env
> flake `OI-T2`). C.5 consumed exactly `0036`, so C.6–C.8 keep `0037`–`0039`.
> **C-Foundations complete.** **Next: C.6** (Experience extraction + consolidation — first C-Personal
> slice; migration `0037`).
> Land/test/smoke/update-doc per slice, exactly as Phases A/B.
