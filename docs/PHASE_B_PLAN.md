# Phase B — Engineering Intelligence expansion (implementation plan)

> **Status:** 🟢 **FROZEN FOR IMPLEMENTATION (2026-07-18, review round 3).** Derived from
> `docs/ATLAS_OS_ROADMAP.md` §5.9 (Asset Store), §5.10 (Capability Registry), §6 (Phase B),
> building on Phase 0 (Asset Store, Storage, Capability Registry, Clock, event bus + SSE) and
> Phase A (Missions, Workers, Config, Templates, Schedules). **Five key decisions confirmed by the
> operator (2026-07-18):** remote clone **+** local path into the Asset Store; **JS/TS** as the
> second language; **include** LLM design reasoning (advice-only); **embed code** into the `code`
> knowledge domain; **ship** the Repository-Learning Mission + RepoWatcher worker.
>
> **Review round 2 (pre-freeze architecture hardening, per operator):** four additions folded in,
> none of which change the implementation order — (1) **explicit Reader versioning** separate from
> extractor/service versioning (BB8); (2) a **Repository UUID** stable across path/URL/clone-location
> moves (BB12); (3) **structural-change-triggered** design reviews instead of running the LLM on
> every ingest (BB6/Q-B3); (4) **P11 — Readers never own knowledge** as a constitutional rule. Plus
> the supporting shape: the **Asset → Reader → Artifact → Extraction → Knowledge** pipeline with a
> **Derived Artifact Store** (BB11), a **Reader Registry** + **capability matrix** for honest
> failure (BB10), and `reader` added to finding identity (Q-B5).
>
> **Review round 3 (freeze):** renamed *Reader Output Cache → **Derived Artifact Store*** (BB11) —
> artifacts (AST, symbol tables, dependency graphs, parse trees) are deterministic derived products,
> not throwaway cache; physical backing stays an implementation detail. Deferred the **Knowledge
> Conflict Resolver** to Phase C/D (§5; roadmap A10). **Plan frozen — starting B.1.** Post-freeze
> refinements (reader compatibility metadata, reader confidence, artifact-format versioning, graph
> identifiers) are incremental and won't change the architecture.
>
> **Goal:** grow the existing **narrow** Engineering Intelligence (`atlas/intelligence/` L2–L5
> Code store) into the roadmap pipeline — **repository ingestion → code understanding →
> architecture graph → design reasoning → engineering findings → engineering memory** — with
> assets flowing through the **Asset Store** (a better reader later **re-parses the stored asset**,
> not a re-clone), knowledge retrievable via the Access Layer, and a persistent **RepoWatcher**
> Mission tying it into the Phase-A foundation. Multi-language: **Python (full) + JS/TS**; later
> document types (docs, UML, SQL, Docker, CAD, MATLAB, PLC, LabVIEW, PSpice, drawings, …) are just
> new **Readers** feeding the same pipeline — **not** new intelligences.
>
> **Not in Phase B:** Personal/Professional Intelligence (Phase C); the Decision Engine and the
> big autonomous Missions — Job/Research/Paper-Trading/Security watchers (Phase D); remote access
> (deferred); hot/warm/cold tiering (single-disk, deferred). **Engineering Intelligence
> *understands* engineering — it does not write/edit code** (roadmap; **P10**, now formalized in
> the constitution §3).

---

## 0. Guiding constraints (from the constitution, §3)

- **P5 few-intelligences / P7 four-questions:** Phase B adds **no new intelligence and no new
  top-level subsystem**. New file *types* are **Readers**; new knowledge is **findings + a
  `code` knowledge domain**; the recurring behaviour is a **Mission + Worker**. We extend via
  **readers / findings / ledger sinks**, matching the existing "adds sinks, not schema" pattern.
- **Assets ≠ Knowledge (R2 / §5.9):** raw repos are **versioned, checksummed assets**; knowledge
  is *extracted* from them. Every engineering finding/graph references the **asset id + version**
  it came from, so re-parsing with a better reader is a background **re-extraction**, never a
  re-download.
- **P1 durability / P4 design-for-failure:** ingestion is resumable and idempotent; the
  RepoWatcher is a **short-task + checkpoint** worker (reuses the Phase-A framework verbatim); a
  `kill -9` mid-ingest resumes from the last asset/checkpoint, not from scratch.
- **P2 model independence + artifact versioning:** every finding/graph is stamped with the real
  `code_service_version` **and an explicit, independently-tracked `reader_version`** (per language
  reader) / `extractor_version` (and `llm_id` for design findings) from the **Capability
  Registry** — so switching the LLM/embedder later never invalidates extracted engineering
  knowledge (only design-review re-runs / re-embeds do), and "which reader produced this?" is
  always answerable (BB8).
- **P11 readers never own knowledge (§3, new):** a Reader is a **stateless translator**. The
  pipeline is **Asset → Reader → Artifact (AST/parse tree, cached) → Extraction → Knowledge**.
  Readers never store state, own findings, make decisions, or touch missions — so a better reader
  drops in without disturbing the knowledge it produced, and extraction can improve **without
  re-parsing** (the stored Artifact in the **Derived Artifact Store** is reused; BB11). A **Reader
  Registry** (BB10) exposes each
  reader's version, coverage matrix, health, and priority, so Atlas fails **honestly** ("this
  reader can't produce a JS call graph") rather than silently.
- **P6 everything configurable + versioned:** the RepoWatcher runs off a **versioned mission
  config** (repo source, languages, depth, embed on/off, re-ingest interval); nothing hardcoded.
- **P9 explainability + governance (S18b ledger):** every engineering write goes through the
  existing **learning ledger** (`propose → apply → revert`) and journals *why / refs / versions*.
  Design reasoning is **advice-only** — it emits findings, never edits code or changes behaviour.
- **Provenance everywhere:** repo/asset/symbol refs on every finding; `mission_id` on assets +
  findings the RepoWatcher produces. "Show me everything the RepoWatcher learned about repo X" is
  a filter, not a join graph.

---

## 1. Resolved decisions (locked for Phase B)

| # | Decision area | **Decision for Phase B** |
|---|---|---|
| BB1 | **Repo acquisition** (operator-confirmed: local + remote) | Two entry points, both landing in the **Asset Store** as a `git_repo` asset: (a) **local path** → snapshot + register; (b) **remote URL** → **read-only shallow clone** (`git clone --depth 1`, no creds mutation, matching the existing read-only `GitClient` posture) into a Storage **workspace**, then register. Ingestion always reads from the **checked-out asset copy**, never the live remote. Re-ingest computes a **tree checksum** (per file: `relative-path + blob hash + file mode`, sorted; ignoring `.git`, `__pycache__`, `*.pyc`, `node_modules`, plus `code` ignores — Git-object-model-like, no permission surprises) → **new asset version only if changed** (else reuse). No push/pull/commit — ever. |
| BB2 | **Engineering-findings home** | **Reuse `knowledge.findings` with `domain="code"`** (the domain already exists but is empty) — *no new findings table* (P5/P7). Findings carry `provenance = {repo_uid, asset_id, asset_version, repo, path, symbol, reader, reader_version}`, `claim_type ∈ {structure, dependency, pattern, design, risk}`, confidence + the standard lifecycle (`active/contested/deprecated/superseded/archived`). Reuses `FindingRepository` + the existing consolidation/lifecycle machinery. |
| BB3 | **Architecture graph persistence** | Persist each ingest's import/call/module graph as a **versioned JSON asset** (`kind="architecture_graph"`, linked to the repo asset id+version) — *no new top-level schema*. Because it's an asset, versions are **diffable across re-ingests** ("what changed in the architecture?"). A compact summary is also emitted as a `structure` finding for retrieval. |
| BB4 | **Code embeddings / retrieval** (operator-confirmed: yes) | On ingest, embed code chunks into **`knowledge` domain `"code"`** (reuse `CodeService.index(ingest=True)` / `_ingest_code`, currently unwired) so engineering knowledge is retrievable via the **Access Layer** (dense+lexical, domain-scoped). **Cost-bounded:** respects `code.max_files`; per-repo embed cap + an `embed` config toggle so a huge monorepo can ingest structure without embedding everything. |
| BB5 | **Multi-language** (operator-confirmed: JS/TS) | **Python (full: symbols + imports + call graph) + JavaScript/TypeScript (symbols + imports + repo map + findings)** through the **same pipeline**, formalizing the existing tree-sitter path. **Call-graph stays Python-first** (documented limitation; JS/TS call resolution is a later reader upgrade). Other tree-sitter langs keep working at symbol level but aren't a Phase-B acceptance target. |
| BB6 | **Design reasoning** (operator-confirmed: include) | A **bounded, `code`-role LLM pass** over the architecture graph + mined patterns emits **advice-only design findings** (strengths / risks / smells / suggested refactors) with **confidence, provenance, and rejected alternatives** (P9). **Trigger = structural change only** (operator-revised): the graph diff must show a **new/removed module, a public-API change, a dependency-graph change, or a class-hierarchy change** — documentation/comment/whitespace-only edits **skip** the LLM entirely (big token savings). Also runnable **on demand** (`POST /design-review/{id}`). Governed/reversible via the ledger; token/size-budgeted; if the LLM is unavailable it **skips** (structure findings still land) rather than failing the ingest. **Never edits code** (P10). |
| BB7 | **Repository-Learning Mission + Worker** (operator-confirmed: include) | Make the Phase-A `repository_learning` template **real** + a persistent **RepoWatcher** worker (reusing the Phase-A worker framework): re-ingests on a schedule, detects change via **asset checksum/version**, refreshes findings + graph, journals. Config schema: `{sources:[{path|url, branch?}], languages:[…], depth, embed:bool, reingest_interval_seconds}`. Budget-gated (mission `max_concurrent_tasks`). |
| BB8 | **Artifact + explicit Reader versioning (P2)** (operator-revised) | Findings/graphs stamped with real `code_service_version` + `extractor_version` + `embedding_id` (embedded chunks) + `llm_id` (design findings), **and — tracked independently — a per-reader `reader` name + `reader_version`** (e.g. `python@2.4.1`, `jsts@1.0.0`), sourced from the **Capability Registry / Reader Registry** — never hardcoded. Reader versions bump on their **own** cadence (a reader upgrade that finds more symbols is visible as a version delta, distinct from a `CodeService` or extractor change) so engineering knowledge is comparable across time. |
| BB9 | **Governance / reversibility** | All engineering knowledge writes flow through the **S18b learning ledger** (`propose → apply → revert`) via a store sink, consistent with the existing `learn_repository` flow — so a bad ingest or design review is **auditable and reversible**, not a silent mutation. |
| BB10 | **Reader Registry + capability matrix** (operator-added) | A dedicated **Reader Registry** (distinct from, but feeding, the Capability Registry) answers *"who can read `.mat` / `.py` / `.ts`?"* and holds each reader's **enabled / healthy / version / coverage matrix / priority / extensions / config**. The coverage matrix records what each reader **can and cannot** do (e.g. Python: ✓imports ✓call-graph ✓decorators ✓typing ✗C-extensions; JS/TS: ✓imports ✓exports ✓modules ✗call-graph) so Atlas fails **honestly** ("this reader can't produce a JS call graph") instead of silently. Phase-B ships the registry + Python and JS/TS entries; new readers (CAD/MATLAB/…) register later without code changes elsewhere. |
| BB11 | **Artifact-first pipeline + Derived Artifact Store** (operator-added, P11) | Readers emit a structured **Artifact** (AST, symbol table, dependency graph, parse tree, repo map) **before** knowledge extraction: **Asset → Reader → Artifact → Extraction → Knowledge**. These are **deterministic derived products**, not throwaway cache entries, so they live in a **Derived Artifact Store** keyed by `{asset_id, asset_version, reader, reader_version}` — improving the *extractor* later re-runs extraction against stored artifacts **without re-parsing** (big CPU win on large repos). Artifacts remain **regenerable/derived** (prunable, never authoritative — the Asset is the source of truth); whether they physically sit in a Storage cache scope or a durable store is an **implementation detail**. |
| BB12 | **Repository identity = stable UUID** (operator-added) | Every repository gets a durable **`repo_uid` (UUID)**, independent of path / remote URL / clone location. On (re-)ingest, identity is resolved in order: (a) **git root-commit hash** (stable across clones & moves), else (b) **normalized remote URL**, else (c) an operator-supplied id / generated UUID persisted on first ingest. Moving `~/atlas → ~/projects/atlas` keeps the **same** `repo_uid`; findings/graphs/history stay linked. Path is **never** the identity. |

---

## 2. Work items (ordered) & acceptance

Order chosen so each item lands, tests, and commits independently, mirroring Phases 0/A. Each is
wired in `bootstrap.py` with hermetic (fake-repo) unit tests plus a live-DB smoke where relevant.

### B.1 Asset-backed repo ingestion  ·  *first (the seam)*  ·  migration `0026`
- **Build** `atlas/engineering/ingest.py` (or extend `atlas/intelligence/`): a **RepoAcquirer**
  that, given a **local path** or **remote URL**, produces a checked-out working copy in a Storage
  workspace and **registers/updates a `git_repo` asset** (Asset Store) — versioned by a **tree
  checksum** (per file: `relative-path + blob hash + file mode`, sorted; ignoring `.git`,
  `__pycache__`, `*.pyc`, `node_modules` + `code` ignores — BB1/Q-B1), so an unchanged repo re-uses
  its current version.
- **Resolve a stable `repo_uid`** (BB12): git **root-commit hash** → normalized remote URL →
  generated UUID (persisted on first ingest). Moving/re-cloning the repo maps to the **same**
  `repo_uid`; path is never the identity.
- **Read-only clone:** shallow `git clone --depth 1 <url>` via a new read-only path in
  `atlas/vcs/` (no fetch/pull/push/commit); credentials via env only if ever needed (none for
  public). Honours `code` ignores + `max_files`.
- **Wire** `IntelligenceService.learn_repository` to accept `{path|url}` → acquire → register asset
  → distill **from the asset copy**, recording `repo_uid + asset_id + asset_version` on the learned
  repo.
- **Migration `0026_engineering_provenance.sql`:** add `repo_uid UUID`, `root_commit TEXT`,
  `normalized_remote TEXT`, `asset_id UUID`, `asset_version INT` to `learning.repositories`
  (identity + provenance link; nullable for pre-B rows; `repo_uid` unique index); write
  `mission_id` on the repo asset when a mission owns the ingest. *(No new tables.)*
- **Acceptance:** ingesting the same local repo twice re-uses the asset version (no dup); the same
  repo **cloned to a different path** resolves to the **same `repo_uid`**; a public remote URL
  clones read-only into the Asset Store and ingests; the learned repo row carries its
  `repo_uid` + asset id+version; the raw asset is retrievable + checksum-verified.
- **✅ DONE (2026-07-18).** Delivered: migration `0026` (repo_uid/root_commit/normalized_remote/
  asset_id/asset_version + partial-unique index on active `repo_uid`); `atlas/vcs/acquire.py`
  (`GitAcquirer` shallow read-only clone + root-commit/remote helpers, keeping `GitClient`
  read-only; `normalize_remote`); `atlas/engineering/ingest.py` (`RepoAcquirer`, `AcquiredRepo`,
  `compute_tree_checksum` = relpath+mode+blob-sha ignoring `.git`/`__pycache__`/`*.pyc`/
  `node_modules`, deterministic `.tar.gz` packing, tree-checksum version reuse, `repo_uid`
  resolution root-commit→remote→path); `LearnedRepository` + `IntelligenceRepository` carry the
  new provenance and supersede by `repo_uid`; `IntelligenceService.learn_repository(path=…|url=…)`
  acquires → registers the `git_repo` asset → distills from the asset copy → stamps provenance;
  wired in `bootstrap.py`. Tests: `tests/test_engineering_ingest.py` (18 hermetic) +
  `tests/test_engineering_ingest_db.py` (live-DB smoke) + 2 in `tests/test_intelligence.py`; full
  suite green (1225 passed).

### B.2 Engineering findings + searchable code  ·  *artifact-first (P11) + Derived Artifact Store*
- **Artifact boundary (BB11):** the reader produces a structured **Artifact** (repo map / AST /
  symbol table / dependency graph) that is written to the **Derived Artifact Store** keyed by
  `{asset_id, asset_version, reader, reader_version}`; **extraction consumes the artifact**, not the
  raw tree. Re-running extraction (e.g. a smarter extractor, same reader) reuses the stored artifact
  **without re-parsing**. Artifacts are deterministic derived products (regenerable; the Asset stays
  authoritative).
- **Extract findings** from the artifact (repo map, symbols, patterns, dependencies) into
  **`knowledge.findings` (`domain="code"`)** via the ledger sink — `structure`, `dependency`, and
  `pattern` claim types, each with `{repo_uid, asset_id, asset_version, repo, path, symbol, reader,
  reader_version}` provenance and artifact versions (BB8). Re-ingest **supersedes** prior findings
  (append-revision lifecycle), never blind-overwrites.
- **Embed code** into `knowledge` domain `"code"` (BB4): wire `CodeService.index(ingest=True)` into
  the governed flow, **priority-capped** (public API → core modules → frequently-imported → rest;
  Q-B4) + `embed` toggle.
- **Acceptance:** after ingest, engineering findings are listable (`domain="code"`) and retrievable
  via `retrieve(role="engineering"/domains=["code"])`; a code query returns embedded code chunks; a
  re-ingest of a changed repo supersedes stale findings (canonical id stable, **including
  `reader`**); a second extraction pass over an **unchanged** asset **reuses the cached artifact**
  (no re-parse).
- **✅ DONE (2026-07-18).** Delivered: `atlas/engineering/artifacts.py` (`DerivedArtifactStore`
  over a Storage `derived-artifacts` cache scope, keyed by `{asset_id, asset_version, reader,
  reader_version}` — BB11); `CodeService.VERSION` + `CodeService.artifact()` (Reader→Artifact:
  repo map, import/call graph, mined patterns, bounded symbol list + reader identity, BB8);
  `atlas/engineering/findings.py` (`build_engineering_findings` → `structure`/`dependency`/
  `pattern` findings with `{repo_uid,asset_id,asset_version,repo,path,symbol,reader,
  reader_version,extractor_version}` provenance; `EngineeringFindingWriter` — governed
  create/supersede/archive keyed on the code-aware identity `{repo_uid,path,symbol,claim_type,
  reader}`, Q-B5). `finding_identity_key` extended for `domain="code"`; `FindingRepository.
  list_active_by_repo_uid`; supersession mints a **new** canonical row (respects
  `UNIQUE(canonical_id)`), archiving vanished findings. `IntelligenceService.learn_repository`
  now goes Asset→Reader→Artifact (reusing the Derived Artifact Store on an unchanged asset
  version — no re-parse)→Extraction→Knowledge, rides the same governed `CodeStoreSink` ledger
  event (revert archives findings too), and does **priority-capped** code embedding (public API
  → frequently-imported → symbol-rich; `embed_code`/`embed_cap` config, Q-B4). Wired in
  `bootstrap.py`. Tests: `tests/test_engineering_findings.py` (7 hermetic: extraction, identity
  incl. reader, create/noop/revise/archive, artifact-store round-trip, end-to-end reuse) + a
  live-DB smoke in `tests/test_engineering_ingest_db.py`; suite green (1231 passed; the single
  unrelated `test_event_lifecycle` failure is pre-existing live-DB pending-event accumulation).

### B.3 Architecture graph as a versioned artifact
- **Persist** the import/call/module graph as a **versioned `architecture_graph` asset** linked to
  the repo asset (BB3) + a compact `structure` finding summary. Provide a **diff** between two
  versions (added/removed modules, edges, entry points).
- **Acceptance:** the graph for an ingested repo is retrievable by repo/asset id and by version;
  re-ingesting a changed repo produces a new graph version whose **diff** reflects the change.
- **✅ DONE (2026-07-18).** Delivered: `atlas/engineering/architecture.py` —
  `build_architecture_graph()` (normalizes the reader artifact into a compact, sorted doc:
  `modules / import_edges / call_edges / entry_points / languages / frameworks / counts`),
  `graph_checksum()` (content hash over the structural parts → version reuse), `diff_graphs()`
  (added/removed modules/import-edges/call-edges/entry-points + `changed` flag), and
  `ArchitectureGraphStore` over the Asset Store (`persist` → versioned `architecture_graph`
  asset keyed by `repo_uid`, reusing the version when the checksum is unchanged and returning a
  `diff` vs the previous version when it isn't; `get`/`versions`/`diff` retrieval, with metadata
  linking back to the `repo_asset_id/version`). `IntelligenceService.learn_repository` builds the
  graph from the same artifact and persists it best-effort (never fails a learn), surfacing
  `architecture_graph: {asset_id, version, reused, diff}`; added `architecture_graph()`,
  `architecture_graph_versions()`, `architecture_graph_diff()` accessors. Wired in `bootstrap.py`.
  Tests: `tests/test_engineering_architecture.py` (7 hermetic: builders, checksum, diff,
  persist/reuse/version-diff, retrieval, end-to-end) + a live-DB smoke in
  `tests/test_engineering_ingest_db.py`; suite green (1239 passed; the single unrelated
  `test_event_lifecycle` failure remains pre-existing live-DB pending-event accumulation).

### B.4 Multi-language + Reader Registry (Python + JS/TS)
- **Reader Registry (BB10):** introduce `atlas/engineering/readers/` with a small **ReaderRegistry**
  that maps **extensions → reader**, and records each reader's `enabled / healthy / version /
  coverage-matrix / priority / config`. Register **Python** (✓imports ✓call-graph ✓decorators
  ✓typing ✗C-extensions) and **JS/TS** (✓imports ✓exports ✓modules ✗call-graph). It reports into
  the **Capability Registry** for self-inspection/health. New readers register here later with no
  changes elsewhere ("who can read `.mat`?").
- **Formalize** the tree-sitter path so a **JS/TS** repo flows end-to-end through the same
  artifact-first pipeline: repo map (deps/frameworks via `package.json`), symbols, findings,
  embeddings — same code as Python minus the call graph (**declared unsupported via the coverage
  matrix**, not faked). Add framework detection for the JS/TS ecosystem where missing.
- **Acceptance:** a real JS/TS repo ingests → repo map + symbols + engineering findings +
  (optional) embeddings, retrievable identically to a Python repo; the registry answers which
  reader handled each extension; **call-graph absence for JS/TS is reported honestly from the
  coverage matrix** (not silently empty).
- **✅ DONE (2026-07-18).** Delivered: `atlas/engineering/readers.py` — `Reader` (id / name /
  `version` (BB8) / extensions / languages / **coverage matrix** / priority / enabled / config, P11:
  no state) and `ReaderRegistry` mapping **extensions & languages → reader** by priority. Built-in
  readers: **python** (✓symbols ✓imports ✓call_graph ✓decorators ✓typing ✓modules ✗exports,
  priority 100), **jsts** (✓symbols ✓imports ✓exports ✓modules ✓typing **✗call_graph** ✗decorators,
  priority 90) and a **treesitter** breadth reader (c/cpp/rust/go/java/sql/bash). Registry API:
  `reader_for_extension/path/language`, `supports`, **`can_produce(capability, language)`** (honest
  `{supported, reader, reason}` — e.g. *"the JavaScript/TypeScript Reader does not support
  call_graph"*), `extension_map`, `coverage_matrix`, `describe`, plus `metrics()`/`health_check()`
  so it **reports into the Capability Registry** (registered as capability `readers` + a lifecycle
  service in `bootstrap.py`). `CodeService.artifact()` now attaches **per-language reader
  attribution + coverage** (`readers: [{language, reader, reader_version, coverage, call_graph}]`),
  so JS/TS's empty `call_edges` is **declared, not faked**. JS/TS framework detection extended in
  `repomap.py` (NestJS, Nuxt, Remix, SvelteKit, Vite, Vitest, Jest, TypeScript, Tailwind, Prisma,
  Electron, React Native, …). Tests: `tests/test_engineering_readers.py` (registry routing/priority/
  disable/coverage/honesty + a real tree-sitter **JS/TS repo end-to-end** through `Intelligence
  .learn_repository` → repo map + symbols + node dependency findings, retrievable like Python);
  suite green (1247 passed; the single unrelated `test_event_lifecycle` live-DB pending-event
  accumulation remains pre-existing).

### B.5 Design reasoning (LLM design review) — advice-only, structural-change-triggered
- **Build** a bounded `code`-role LLM pass over the architecture graph + patterns → **design
  findings** (`design`/`risk` claim types) with confidence, provenance, and **rejected
  alternatives** (P9). Governed/reversible (ledger); token-budgeted; **skips** cleanly if the LLM
  is unavailable. Never edits code (P10).
- **Structural-change trigger (BB6/Q-B3):** the review runs **only when the graph diff (B.3) shows a
  structural change** — a new/removed module, a public-API change, a dependency-graph change, or a
  class-hierarchy change. Doc-/comment-/whitespace-only re-ingests **skip** the LLM. Always
  available **on demand** via the API. This keeps LLM cost proportional to real architectural
  change, not ingest frequency.
- **Acceptance:** ingesting a repo with a structural change produces explainable design findings,
  each answerable with *why / evidence (which modules) / confidence / model version*; a re-ingest
  with **only documentation edits skips the LLM** (no new design findings, no token spend); disabling
  the LLM still yields structural findings; design findings are revertible via the ledger.
- **✅ DONE (2026-07-18).** Delivered: `atlas/engineering/design_review.py` — `DesignReviewer`
  (advice-only, `code`-role LLM over the architecture graph + mined patterns → `design`/`risk`
  findings with confidence, evidence modules, rationale and **rejected_alternatives** (P9); each
  finding stamps `model` + `extractor_version` = `DESIGN_REVIEWER_VERSION` for explainability;
  stable `symbol` slug identity so a re-review **supersedes** the same concern; token-budgeted
  (`design_review_max_findings`, bounded context via top import-hub modules) and **never edits
  code** (P10)). `should_review(graph_info)` is the **structural-change gate** (BB6/Q-B3): review
  runs on a **new** graph version (first version or a changed structure) and **skips** on a reused
  (unchanged) graph — doc-/comment-/whitespace-only re-ingests spend **zero** tokens. Skips cleanly
  when the LLM is unavailable (`available()`), so structural findings from B.2 still land. Wiring:
  `learn_repository` now persists the graph **first**, runs the gated review, appends design/risk
  to the same governed findings batch, and passes `engineering_finding_claim_types` so the writer's
  archival is **claim-type-scoped** (`EngineeringFindingWriter.write(..., archive_claim_types=…)`)
  — a skipped review **preserves** prior design findings instead of archiving them. On-demand
  `IntelligenceService.review_design(repo_uid)` (+ `POST /intelligence/repositories/{repo_uid}/
  design-review`) re-runs from the persisted graph + learned metadata, writing scoped to
  `design`/`risk`. Revert archives all code findings incl. design (BB9). Config:
  `intelligence.design_review` / `design_review_max_findings` / `design_review_timeout`. Wired in
  `bootstrap.py` (reviewer built only when enabled; writer shared with the sink). Tests:
  `tests/test_engineering_design_review.py` (11 hermetic: gate, parsing/provenance/alternatives,
  no-LLM + bad-JSON skips, structural-change triggers, **doc-only skip preserves design**, no-LLM
  structural-only, on-demand, revert) + a live-DB smoke in `tests/test_engineering_ingest_db.py`;
  suite green (1257 passed; the single unrelated `test_event_lifecycle` live-DB pending-event
  accumulation remains pre-existing).

### B.6 Repository-Learning Mission + RepoWatcher worker
- **Real template + worker:** upgrade the Phase-A `repository_learning` stub to a working template
  with a `RepoWatcherConfig` (Pydantic schema, BB7) + a `RepoWatcher` persistent worker that
  re-ingests on its schedule, refreshes findings/graph, journals, and respects the mission budget.
  Reuses B.1–B.5 as its tick body.
- **Detect → Compare → Policy → Ingest (operator-added interface):** the tick is structured as
  **Detect** (checksum/version changed?) → **Compare** (which files/modules changed) → **Policy**
  (what to do) → **Ingest**. Phase B implements the **full-repo** ingest path plus the
  **structural-change gate** for design review (B.5); the **Policy** hook and change set are
  **surfaced in the interface now** so a later **partial / per-file re-ingest** ("one file changed →
  partial ingest") drops in without reshaping the worker. Partial ingest itself is **out of scope
  for Phase B** (see §5).
- **Acceptance:** instantiate a Repository-Learning mission from the template → its RepoWatcher
  ingests on schedule, **survives reboot** (resumes), re-ingest after a repo change updates the
  graph + supersedes findings, an unchanged repo tick is a **cheap no-op** (Detect short-circuits),
  config edit (e.g. add a language / toggle embed) bumps a version and is picked up next tick — all
  journaled.
- **✅ DONE (2026-07-18).** Delivered: strict `RepoWatcherConfig` (BB7) in
  `atlas/configuration/schemas.py` (`extra='forbid'`; `repo_url`/`repo_path`/`branch`/`languages`/
  `embed_code`/`policy`/`tick_interval_seconds`) registered in `default_registry`; the
  `repository_learning` built-in template upgraded to **v2** (real `repo_watcher` schema +
  `repo_watcher` worker spec). New `atlas/workers/repo_watcher.py` — `RepoWatcher(PersistentWorker)`
  whose one bounded tick is the operator-added interface **Detect → Compare → Policy → Ingest**:
  **Detect** cheaply checksums a local tree (`compute_tree_checksum`) and short-circuits an
  unchanged repo to a **quiet no-op** (no clone/parse/LLM/ledger event); **Compare** normalizes the
  learn result into a `change_set` (graph diff, added/removed modules, findings counts); **Policy**
  is the `decide_policy(change_set)` hook (full-repo ingest now, `POLICY_PARTIAL_INGEST` reserved
  for a later phase — surfaced so per-file re-ingest drops in without reshaping the worker);
  **Ingest** calls the governed `IntelligenceService.learn_repository` (refresh graph, supersede
  findings, structural-change-gated design review B.5). Live operator input `{"force": true}`
  bypasses Detect; a versioned-config edit is picked up next tick (journaled); an ingest failure
  raises so the manager applies crash backoff (B4). Durability (checkpoint resume, reboot, config
  pickup) is the WorkerManager's — the worker stays a pure `do_tick`. Registered in `bootstrap.py`
  after Intelligence is built. Tests: `tests/test_repo_watcher.py` (13 hermetic: policy, first
  ingest, **cheap no-op**, change → re-ingest, force, config pickup, idle, failure→raise, embed
  forwarding, strict schema, template wiring, **manager-driven resume + Detect short-circuit**) +
  a live-DB smoke `tests/test_repo_watcher_db.py` (instantiate template → tick → restart-resume →
  change → re-ingest → config-version pickup, journaled); suite green (1270 passed; the single
  unrelated `test_event_lifecycle` live-DB pending-event accumulation remains pre-existing).

### B.7 API + "Engineering" dashboard view
- **API** (`atlas/api/routes.py`): `GET /v1/engineering/repositories` (+ `/{id}` with asset +
  versions), `GET /v1/engineering/repositories/{id}/graph[?version=]` (+ `/diff`),
  `GET /v1/engineering/findings` (`domain="code"` filter), `POST /v1/engineering/ingest`
  (`{path|url}`, optional `mission_id`), `POST /v1/engineering/design-review/{id}`. API-key gated;
  events over SSE.
- **Dashboard** (`atlas/web/static/`): an **Engineering** view — repos (with asset version),
  architecture graph summary, engineering + design findings with the "why" (P9). Mobile-first,
  consistent with Phases 0/A.
- **Acceptance:** the operator can ingest a repo, browse its architecture + findings, trigger a
  design review, and see it all update live from the console.
- **✅ DONE (2026-07-19).** Delivered: an `/v1/engineering/*` API namespace (API-key gated) in
  `atlas/api/routes.py` — `GET /engineering/repositories` (+ `/{id}` returning the learned record
  with `asset_id/version` + `graph_versions`), `GET /engineering/repositories/{id}/graph[?version=]`
  and `/graph/diff?from_version=&to_version=` (both resolve the learned id → stable `repo_uid`;
  404 when absent), `GET /engineering/findings?repo_id=&claim_type=` (active `domain="code"`
  findings), `POST /engineering/ingest` (`{path|url}` — exactly one, optional
  `branch`/`mission_id`/`policy`/`embed`), and `POST /engineering/design-review/{id}`; ingest +
  design-review push `EngineeringIngested`/`DesignReviewed` onto the bus (best-effort) so the
  console updates live over the existing SSE stream. Read side added as
  `IntelligenceService.list_findings` (shaped with the P9 **"why"** — statement, confidence, value
  evidence/rationale/rejected-alternatives, reader/model provenance), backed by a `finding_repo`
  wired in `bootstrap.py`. Dashboard: a new **Engineering** view in `atlas/web/static/`
  (`index.html`/`app.js`/`styles.css`) — ingest form (path or git URL, optional embed), repo list,
  and a detail pane with an architecture-graph summary (module/import/call/entry counts + version
  count), a **Run design review** action, and findings grouped by claim type (structure /
  dependency / pattern / design / risk) each expandable to its "why"; it live-refreshes off SSE.
  Tests: 5 hermetic API tests in `tests/test_api.py` (ingest→browse flow, exactly-one-source 422,
  unknown-repo 404, design-review-unavailable, auth) + 2 `list_findings` unit tests in
  `tests/test_intelligence.py` (repo/claim scoping, empty without a finding repo); full suite green
  (1277 passed; the single unrelated `test_event_lifecycle` live-DB pending-event accumulation
  remains pre-existing).

### B.8 End-to-end acceptance (the Phase-B gate)
Ingest a **real Python repo** → **architecture graph + design findings retrievable and versioned**;
ingest a **JS/TS repo** through the **same pipeline**; **re-ingest** after a change bumps the asset
version, updates the graph (diff reflects the change), and supersedes stale findings; a
**RepoWatcher mission** runs it on a schedule, survives reboot, and is config-versioned; **every
artifact is provenance-stamped + explainable + reversible**. Hermetic unit tests per item + one
integration test against the live DB (mirrors `tests/test_phase_a_e2e.py`).
- **✅ DONE (2026-07-19).** Delivered the Phase-B gate as a live-DB integration module
  `tests/test_phase_b_e2e.py` that wires the **real** stack exactly as `bootstrap` does (Storage /
  Asset Store / Repo Acquirer / Code reader / Derived Artifact Store / Architecture Graph Store /
  Engineering Finding writer / Learning ledger + Code sink / IntelligenceService; a deterministic
  fake LLM makes the design review reproducible; a path-derived fake git avoids the `git` binary),
  skipped when PostgreSQL is unreachable. `test_engineering_full_lifecycle`: ingest a **real Python
  repo** → asset v1 + architecture graph v1 + engineering & **design/risk** findings, all
  retrievable and versioned; ingest a **JS/TS repo** through the *same* pipeline (distinct
  `repo_uid`, same governance); **re-ingest** the Python repo after a change bumps the asset to v2,
  the **graph diff** reflects the added module, and the stale structure finding is **superseded**
  (new active canonical row, prior marked `superseded`) while design/risk survive; every artifact
  is **provenance-stamped** (learned row + graph asset carry `repo_uid`/`asset_id`/version and
  verify), **explainable** (governed ledger events + `explain`), and **reversible** (revert retires
  the row and archives its findings, leaving the JS repo untouched). `test_repo_watcher_mission_
  runs_real_ingest_and_survives_reboot`: a `repository_learning` mission drives the *real* governed
  ingest on tick, a fresh WorkerManager **resumes after a restart** with an unchanged-tree Detect
  no-op, a repo change re-ingests, and a config edit **bumps a version picked up next tick**
  (journaled). **Bug fixed en route:** `CodeService.artifact(refresh=…)` now busts the in-memory
  parse cache on a genuine re-parse, so re-ingesting the *same local path* after on-disk changes is
  no longer served a stale parse (would otherwise make RepoWatcher blind to local edits); the
  Derived Artifact Store remains the authoritative cross-run cache keyed by asset version. Full
  suite green (1279 passed; the single unrelated `test_event_lifecycle` live-DB pending-event
  accumulation remains pre-existing).

---

## 3. Data-model additions (Phase B)

Deliberately minimal — Phase B mostly **reuses** existing schema (Assets, Knowledge findings +
`code` domain, Learning ledger). New schemas created `AUTHORIZATION atlas` (Phase-0 pattern).

| Migration | Objects |
|---|---|
| `0026_engineering_provenance.sql` | `learning.repositories`: add **`repo_uid UUID`** (stable identity, BB12; unique index), **`root_commit TEXT`**, **`normalized_remote TEXT`** (identity resolution inputs), **`asset_id UUID`**, **`asset_version INT`** (provenance link to the Asset Store). All nullable for pre-B rows. *(No new tables.)* |

**Reused, no schema change:**
- **Asset Store** (`asset.assets`/`asset.versions`) — repos as `git_repo` assets; graphs as
  `architecture_graph` assets. `mission_id` (Phase A) stamped when a mission owns the ingest.
- **Derived Artifact Store (BB11)** — parse **artifacts** (AST / symbol tables / dependency graphs /
  parse trees) keyed by `{asset_id, asset_version, reader, reader_version}`; **deterministic derived
  products**, regenerable/prunable, so no schema and no durability guarantee — the Asset remains the
  source of truth. Physical backing (Storage cache scope vs. durable store) is an implementation
  detail.
- **Reader Registry (BB10)** — an in-process registry reporting into the **Capability Registry**
  (health/version/coverage); no dedicated table in Phase B (registry state is derived from
  installed readers + config).
- **Knowledge** — `knowledge.findings` (`domain="code"`) for engineering + design findings, with
  `reader`/`reader_version` carried in the existing **`provenance` JSONB** (no column change);
  `knowledge.documents/chunks/embeddings` (`domain="code"`) for embedded code (768-dim, existing).
- **Learning ledger** (`learning.events` + store sinks) — governs all engineering writes.
- **Mission/Worker/Config/Schedule/Template** (Phase A) — the RepoWatcher rides these verbatim.

---

## 4. Dependencies & sequencing

```
B.1 Asset-backed ingestion ─┬─> B.2 Findings + embeddings ─┐
                            └─> B.3 Architecture graph ─────┼─> B.4 JS/TS ─> B.5 Design reasoning ─┐
                                                            │                                       ├─> B.6 RepoWatcher Mission ─> B.7 API/UI ─> B.8 E2E
                                                            └───────────────────────────────────────┘
```

- **Reuses Phase 0:** Asset Store + Storage Manager (repo/graph assets, checksums), Capability
  Registry (artifact versions), Clock (timestamps), event bus + SSE (engineering events),
  Operations Dashboard (counts).
- **Reuses Phase A:** Mission Manager, Worker Manager (RepoWatcher), Configuration Manager
  (`RepoWatcherConfig`), Schedule table (re-ingest), Template service (`repository_learning`),
  priority/budget arbitration.
- **Extends existing code:** `atlas/code/` (formalize tree-sitter JS/TS path, graph → asset),
  `atlas/intelligence/` (asset-backed `learn_repository`, findings sink, design review),
  `atlas/knowledge/` (populate the `code` domain), `atlas/vcs/` (read-only shallow clone),
  `atlas/assets/` (write `mission_id`; `architecture_graph` kind).
- **New (small, additive):** `atlas/engineering/readers/` (**ReaderRegistry** + Python/JS-TS reader
  adapters emitting cached **artifacts**, BB10/BB11) and `atlas/engineering/ingest.py`
  (RepoAcquirer + `repo_uid` resolution, BB12). Stateless per P11 — no knowledge ownership.

---

## 5. Non-goals (Phase B)

- **No code writing/editing.** Engineering Intelligence *understands*; it never authors or mutates
  source (P10). Design reasoning is advice-only.
- **No new "Intelligence" per topic** (CAD/Electrical/Control/…): those are later **Readers** +
  Knowledge Domains + Missions on this same pipeline (P5). Do not reopen.
- **No non-Python call graph** yet (JS/TS = symbols/imports only; **declared** via the reader
  coverage matrix, BB10 — not silently empty).
- **No CAD/MATLAB/PLC/UML/PSpice readers** yet (later, additive readers registered in the Reader
  Registry).
- **No partial / per-file re-ingest** yet — RepoWatcher does **full-repo** ingest; the
  Detect→Compare→Policy→Ingest **interface + change set are in place** (B.6) so partial ingest drops
  in later without reshaping the worker.
- **No advanced Derived-Artifact-Store management** (eviction policy, size quotas, cross-run GC) —
  the Phase-B store is a simple keyed derived store; tuning comes with very large repos.
- **No remote access; no hot/warm/cold tiering** (deferred, hardware-gated).
- **No Decision Engine / big autonomous Missions** (Phase D).
- **No Knowledge Conflict Resolver** (deferred to **Phase C/D**, operator-noted) — when a reader
  upgrade changes results (e.g. `python@2.4.1` finds 120 functions, `python@3.0.0` finds 135), Atlas
  should attribute the delta to **"reader improved"** vs. **"repository evolved."** The Phase-B
  provenance already makes this *possible* (findings carry `reader` + `reader_version` + asset
  version), but the resolver that *reasons about* the delta is a later kernel/Decision-Engine
  concern. Recorded so we don't build it prematurely.

---

## 6. Ambiguities — RESOLVED (operator review round 2)

All five are now decided per the operator's recommendations; folded into §1 / the work items.

| # | Ambiguity | **Resolution** |
|---|---|---|
| Q-B1 | Tree-checksum granularity for asset versioning | ✅ Per file: **`relative-path + blob hash + file mode`**, sorted; **ignore** `.git`, `*.pyc`, `node_modules`, `__pycache__` (+ `code` ignores). Git-object-model-like; avoids permission-related surprises. (BB1, B.1) |
| Q-B2 | Where the read-only clone lives | ✅ **Workspace → register asset → delete workspace.** A dedicated Storage workspace scope (`engineering-clones`) is cleaned after registration; the **asset is the source of truth**. (BB1, B.1) |
| Q-B3 | Design-review trigger | ✅ **Structural change only** (new/removed module, public-API change, dependency-graph change, class-hierarchy change) — doc-/comment-only edits **skip** the LLM; plus on-demand via `POST /design-review/{id}`. Budget-capped. (BB6, B.5) |
| Q-B4 | Embedding cap for large repos | ✅ **Priority-based**, not top-N-files: **public API → core modules → frequently-imported → everything else**, up to the cap; `embed:false` skips embedding entirely (structure findings still land). (BB4, B.2) |
| Q-B5 | Finding identity for supersession | ✅ Canonical id keyed on **`{repo_uid, path, symbol, claim_type, reader}`** — adding **`reader`** (two readers can produce different findings for the same symbol) and using the stable `repo_uid`. (BB2/BB12, B.2) |

---

> **Progress:** ✅ **B.1 complete** (2026-07-18) — asset-backed ingestion, `repo_uid`, migration
> `0026`, acquirer + provenance. ✅ **B.2 complete** (2026-07-18) — Derived Artifact Store (BB11),
> artifact-first pipeline (`CodeService.artifact()` + reader versioning BB8), engineering findings in
> `knowledge.findings` (`domain="code"`) with identity/supersession incl. `reader` (Q-B5), governed
> via the code-store ledger, and priority-capped code embeddings (Q-B4). ✅ **B.3 complete**
> (2026-07-18) — architecture graph persisted as a versioned `architecture_graph` asset with
> content-addressed reuse + structural version diffs and retrieval accessors; tests green.
> ✅ **B.4 complete** (2026-07-18) — Reader Registry (BB10) mapping extensions/languages → readers
> (python / jsts / treesitter) with versioned coverage matrices, honest `can_produce` answers
> (no JS/TS call graph), Capability-Registry reporting, per-language reader attribution in
> artifacts, extended JS/TS framework detection, and a real tree-sitter JS/TS repo ingesting
> end-to-end like Python.
> ✅ **B.5 complete** (2026-07-18) — advice-only, structural-change-triggered LLM design review
> (`design`/`risk` findings with evidence, rejected alternatives + model provenance, P9/P10);
> doc-only re-ingests skip the LLM and preserve prior design findings (claim-type-scoped archival);
> no-LLM still yields structural findings; on-demand via API + revert via ledger.
> ✅ **B.6 complete** (2026-07-18) — Repository-Learning mission is real: strict `RepoWatcherConfig`
> (BB7) + `repository_learning` template v2 + a `RepoWatcher` persistent worker whose tick is
> Detect→Compare→Policy→Ingest (cheap no-op on unchanged trees, force via operator input, config
> pickup, governed re-ingest reusing B.1–B.5), with reboot-resume via the WorkerManager.
> **B.7 ✅ done** — an `/v1/engineering/*` API namespace (repos + asset versions, architecture graph
> + diff, `domain="code"` findings, ingest, on-demand design review; events over SSE) plus a new
> **Engineering** console view (ingest, architecture-graph summary, findings grouped by claim type
> with the P9 "why", live-refresh).
> **B.8 ✅ done — the Phase-B gate is closed.** A live-DB integration test drives the real pipeline
> end to end: ingest a Python repo (versioned graph + engineering/design findings), ingest a JS/TS
> repo through the same pipeline, re-ingest a change (asset-version bump, graph diff, findings
> superseded), and a RepoWatcher mission running it on schedule + surviving reboot + config-
> versioned — every artifact provenance-stamped, explainable, and reversible. **Phase B (Engineering
> Intelligence) is complete.**
