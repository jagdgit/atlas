# Phase 0 — Infrastructure & Durability (implementation plan)

> **Status:** 🟢 **IN PROGRESS.** Derived from `docs/ATLAS_OS_ROADMAP.md` §6 (Phase 0) after
> the roadmap was frozen (R3). This is the per-phase detail doc; it resolves the Phase-0
> ambiguities (A1–A4) and tracks concrete work items, order, and acceptance.
>
> **Goal:** lay the durable, self-inspecting, explainable foundation every later phase relies
> on — before any Mission/Worker code (Phase A). Nothing here changes the research/knowledge
> behaviour; it hardens the substrate.

---

## 0. Guiding constraints (from the constitution, §3)

- **P1 durability / P4 design-for-failure:** everything added here must survive `kill -9`
  and resume; recovery is idempotent and re-entrant (R1/Q6).
- **P2 model-independence:** artifacts get *real* component versions (no hardcoded `"v1"`).
- **P8 storage discipline:** new persistence flows through the Storage Manager; hot/warm/cold
  tiering is **deferred** (single disk today) but the `tier` column ships.
- **P9 explainability:** new events/records carry enough to answer "why / from what".
- **Constitution:** each item is a **Kernel Service** (Clock, Storage, Recovery, Event bus,
  Capability Registry) — none is a new intelligence or mission.

---

## 1. Resolved ambiguities (defaults locked for Phase 0)

| # | Ambiguity | **Decision for Phase 0** |
|---|---|---|
| A1 (Q8) | Notification secrets + channel order | **Web/SSE first, email second.** Secrets **env-only** (`ATLAS_SMTP_*`), never DB/YAML — mirrors existing `ATLAS_MAIL_PASSWORD`/`ATLAS_API_KEYS` handling. |
| A2 (Q12) | Storage Manager migration order + quotas | **Workspaces + backups first**, then cache/models. **Quotas advisory (warn only)** in Phase 0; enforcement later. Checksums on write from day one. |
| A3 (Q14) | Capability health: push vs pull | **Pull/probe on demand** (`/health` + dashboard), short in-process cache. Capabilities may *optionally* self-report metrics, but the registry never blocks on them. |
| A4 (Q15) | Dashboard host metrics in v1 | **CPU / RAM / disk / internet** in v1 (stdlib + best-effort). **Temperature / UPS best-effort**: show "not present" when no sensor/agent is available. |

---

## 2. Work items (ordered) & acceptance

Order is chosen so each item can land, be tested, and be committed independently.

### 2.1 Clock / Time service  ·  *first (foundational)*
- **Build:** `atlas/system/time.py` — `ClockService`: `now_utc()`, `monotonic()`,
  `to_local()`, `iso()`, `drift_seconds()`, `ntp_status()`; best-effort SNTP drift monitor on
  a daemon thread (never blocks startup; never fails the system — R1/Q9).
- **Config:** `ClockConfig` (ntp on/off, servers, timeout, check interval, drift-warn).
- **Wire:** register in container (`clock`), capability (`clock`), and as a lifecycle service
  started early.
- **Acceptance:** `now_utc()` is tz-aware UTC; `to_local()` respects `system.timezone`;
  drift monitor reports status in health and **degrades (never fails)** when NTP is
  unreachable; startup does not block on the network.
- **Status:** ✅ implemented in this slice (see §3).

### 2.2 Capability Registry enrichment  ·  ✅ done (this session)
- **Extended** `atlas/kernel/capabilities.py`: `register()` now takes optional
  `version`/`enabled`/`dependencies` (all back-compatible); added `CapabilityInfo`,
  `inspect(name)` / `inspect_all()` (pull model — probes `health_check`/`metrics` defensively,
  never crashes inspection), `version_of(name)`, and a registry-level `default_version`
  fallback wired from `cfg.system.version`. `describe()` gained `version`/`enabled`/
  `dependencies` keys (existing `contract`/`kind` preserved).
- **Feeds** artifact versioning (§2.6): `version_of()` becomes the source of real component
  versions.
- **Acceptance (met):** every registered capability reports a version (explicit → provider
  attr → package default, never `"v1"`) and a probed health/metrics snapshot; missing
  dependencies are surfaced. Covered by `tests/test_capabilities.py` (+9 tests).
- **Deferred to §2.7:** surfacing `inspect_all()` on `/health` + the dashboard, and the short
  pull cache (A3) — no consumer yet, so kept out to avoid dead code.

### 2.3 Storage Manager (workspaces + backups first)  ·  ✅ done (this session)
- **Landed** `atlas/storage/` — `StorageManager` (kernel service): versioned, sha256-checksummed
  file `put_file`/`get_bytes`/`path_of`/`verify`/`list_files`; `allocate_workspace(scope)`;
  **advisory** per-scope quotas (`quota_status`/`set_quota` — over-quota **warns**, never blocks,
  R2/A2); `integrity_check()` (missing/corrupt report, feeds §2.8 Recovery); `run_backup()`
  wrapping the existing `pg_dump` `BackupManager`. Path segments are sanitised so unsafe
  `scope`/`name` can't escape the root. `tier` column ships (default `hot`); **no tier moves**
  (single disk, R2). Backed by `StorageRepository` (SQL only) over the new schema.
- **Migration** `0018_storage.sql` — `storage.files` (scope/name/version/relpath/size/checksum/
  tier/metadata, `UNIQUE(scope,name,version)`) + `storage.quotas` (advisory, `enforce` flag off).
  New `storage` schema owned by `atlas` (run via `atlas-db migrate`); referenced fully-qualified,
  **not** added to the role `search_path` (mirrors `learning.*`).
- **Config:** `StorageConfig` (`dir`, `default_quota_mb`) in `manager.py` + `defaults.yaml`.
- **Wire:** container `storage`, capability `storage` (kind `kernel`, `version=StorageManager.VERSION`),
  lifecycle service after `backup`.
- **Acceptance (met):** files written via the manager are checksummed and retrievable (survive a
  process restart — metadata in Postgres, bytes on disk); corruption/deletion is caught by
  `verify`/`get_bytes`/`integrity_check`; quota breach logs a warning (no enforcement); backup
  delegates to the existing manager. Covered by `tests/test_storage.py` (+19, hermetic via an
  in-memory fake repo). **Apply:** `.venv/bin/atlas-db migrate` (see §5).

### 2.4 Asset Store (thin, Assets ≠ Knowledge)  ·  ✅ done (this session)
- **Landed** `atlas/assets/` — `AssetStore` (kernel service) over the Storage Manager:
  `register(kind, name, data, …)` (creates the asset on first sight, bumps a version on
  re-register), `get_bytes` / `path_of` / `verify` (checksum-verified via storage),
  `get` / `get_by_name` / `list_assets` / `versions`. Bytes live in `storage.files`; asset
  versioning mirrors storage versioning because the storage `(scope, name)` is keyed by the
  asset id (collision-free). Backed by `AssetRepository` (SQL only).
- **Migration** `0019_assets.sql` — `asset.assets` (`UNIQUE(kind, name)`, `current_version`) +
  `asset.versions` (`UNIQUE(asset_id, version)`, storage re-fetch coords + soft
  `storage_file_id` → `storage.files`, no cross-schema FK for loose coupling). New `asset`
  schema owned by `atlas`.
- **Wire:** container `assets`, capability `assets` (kind `kernel`, versioned), lifecycle
  service after `storage`.
- **Acceptance (met):** an asset can be stored, versioned, checksum-verified, and referenced
  by `(asset_id, version)`; re-register preserves history; corruption is caught by
  `verify`/`get_bytes`. Fully exercised in Phase B (CAD/repo ingestion). Covered by
  `tests/test_assets.py` (+10, hermetic: real `StorageManager` over fake repos).
  **Apply:** `.venv/bin/atlas-db migrate` (see §5).

### 2.5 Durable event bus + Notifier + SSE  ·  ✅ done (this session)
- **Durable bus:** `EventDispatcher` gained an optional `store` and now persists every
  published event to `audit.events` **before** dispatch (best-effort — a DB blip is logged
  and never blocks the in-process bus). `EventRepository` (existing, extended) got
  `persist(event)` (idempotent on the event UUID via `ON CONFLICT DO NOTHING`), `recent()`,
  `since()` (replay/backfill), `count()`. **No migration** — `audit.events` already exists
  (0003) and the `Event` shape maps 1:1.
- **Notifier** (`atlas/notify/`): one wildcard subscriber, **web/SSE first, email second**
  (A1). `EventBroker` fans every event out to per-client bounded queues (drops oldest when a
  slow client's buffer is full — live status beats perfect history; `audit.events` is the
  replay source). `EmailSender` (stdlib `smtplib`) emails **notable** events (`*.failed` /
  `*.completed` / `*.error` + configurable `notable_types`) only when SMTP is configured;
  otherwise silently skipped. Both channels best-effort (never crash dispatch).
- **API:** `GET /v1/events` (recent from the durable log) + `GET /v1/events/stream`
  (`text/event-stream` SSE, the web console's push feed) in `atlas/api/routes.py`.
- **Config:** `NotificationsConfig` (`enabled`, `channels`, `notable_types`, `sse_max_queue`)
  + `EmailConfig` in `manager.py` + `defaults.yaml`. **SMTP password is a secret** read from
  the env var named by `email.password_env` (`ATLAS_SMTP_PASSWORD`) — never YAML/DB (A1).
- **Wire:** `event_repo` as the dispatcher store; `EventBroker`/`EmailSender`/`Notifier`
  built in bootstrap and subscribed `WILDCARD`; container `event_repo`/`notifier`, capability
  `notifier` (kind `kernel`, versioned), lifecycle service.
- **Acceptance (met):** events are persisted before handlers run (survive a restart,
  replayable via `recent`/`since`); the web console gets live events over SSE instead of
  polling; email sends when `ATLAS_SMTP_*` is configured and is skipped cleanly when absent.
  Covered by `tests/test_notify.py` (+23) and `tests/test_api.py` (+3). **No migration.**

### 2.6 Artifact versioning (P2)  ·  ✅ done (this session)
- **Landed** real `llm_id`/`embedding_id`/`reader_version`/`extractor_version`/
  `verifier_version`/`synthesizer_version`/`knowledge_schema_version` stamping on every
  Finding **and** Experience. **No migration needed** — findings already carry a
  `provenance` JSONB and experiences a payload dict, so versions are embedded under a
  `versions` key (queryable via JSONB; dedicated columns deferred until filter-by-version is
  a hot path).
- **How:** new `atlas/system/versioning.py` (`ArtifactVersions`, `build_artifact_versions`,
  `KNOWLEDGE_SCHEMA_VERSION`); bumpable `VERSION` constants on `Reader`, `ClaimExtractor`,
  `VerificationEngine`, `EvidenceSynthesizer`; bootstrap builds the version set (from those
  constants + configured model names) and threads it into the synthesizer and learning
  service; `verification`/`synthesis` capabilities now register their `version` too.
- **Acceptance (met):** a new finding/experience records the actual model + component
  versions; provenance without versions still validates (back-compatible). Covered by
  `tests/test_versioning.py` (+8) with no regressions (full suite 1039 passed).

### 2.7 Operations Dashboard (localhost-first)  ·  ✅ done (this session)
- **Host metrics** (`atlas/system/host.py`, `HostMetrics`): stdlib-only, best-effort (A4) —
  **CPU** (%, sampled from `/proc/stat` + core count), **RAM** (`/proc/meminfo`), **disk**
  (`shutil.disk_usage` on the data root), **internet** (cached best-effort socket probe),
  plus **temperature** (`/sys/class/thermal`, else `present: false`) and **UPS**
  (`present: false` — no NUT/apcupsd source). Every metric degrades to `None`/`{}` rather
  than erroring.
- **Aggregator** (`atlas/ops/dashboard.py`, `OperationsDashboard`): one guarded `snapshot()`
  with `atlas` status, live `counts` (jobs total/active/queued; workers/missions 0 until
  Phase A), `host`, `backup` (last + count), `storage` health, capability inventory,
  `sse_subscribers`, and `last_checkpoint` (None until §2.8). Each section is isolated so one
  broken source can't break the screen.
- **API:** `GET /v1/ops` returns the snapshot; the UI live-updates via the §2.5 SSE stream.
- **UI:** new **Overview** view in the bundled console (`atlas/web/static/`), now the
  **default first screen** — metric cards (status, CPU/RAM/disk/internet, temp/UPS, jobs,
  backups, live clients) with warn/fail coloring, plus a **live activity feed** consuming
  `/v1/events/stream` (fetch-based SSE reader, since `EventSource` can't send the auth
  header). Mobile-first (cards wrap; flex `1 1 140px`).
- **Wire:** `HostMetrics` + `OperationsDashboard` built after `app`, registered on the
  container (`host_metrics`, `ops_dashboard`) + capability `ops_dashboard`.
- **Acceptance (met):** one screen shows Atlas status, job/worker/mission counts (0 until
  Phase A), CPU/RAM/disk/internet, last backup, last checkpoint (n/a yet); renders on a
  phone-sized viewport. Remote reach deferred (R2). Covered by `tests/test_ops_dashboard.py`
  (+13) and `tests/test_api.py` (+2). **No migration.**

### 2.8 Recovery Manager (+ storage integrity) & resumable downloads — **done**
- **Built** `atlas/recovery/` — `RecoveryManager` runs **first** in the lifecycle (right after
  `DatabaseService`, before any work-accepting service starts). It does *not* duplicate
  per-subsystem recovery, which already exists (`SchedulerService.start()` resets interrupted
  tasks; `JobService.start()` recovers interrupted steps + re-enqueues unfinished jobs). Instead
  it adds the **cross-cutting** startup layer:
  - a **durable, re-entrant run record** (`system.recovery_runs`): any run left `running` (a
    crash *during* recovery) is marked `interrupted` and the next boot re-runs recovery cleanly
    (R1/Q6);
  - **storage integrity** (`StorageManager.integrity_check()` — missing/corrupt checksums);
  - **backup verification** (newest `pg_dump` exists and is non-empty);
  - an idempotent **task-recovery sweep** (`task_repo.recover_interrupted()`).
  Every step is isolated (one failing step doesn't abort the pass) and the whole pass **never
  blocks boot** (a failure is recorded + surfaced via health/events, not fatal). Emits
  `RecoveryStarted`/`RecoveryCompleted` through the durable bus → Operations Dashboard.
- **Checkpoint foundation** (`atlas/recovery/checkpoints.py`, `CheckpointStore`): upsertable
  `(owner_type, owner_id, label) → state` over `system.checkpoints` — the resume-point primitive
  Phase A workers/jobs adopt in their step loops. Surfaced as `last_checkpoint` on the dashboard.
- **Resumable + checksummed downloads** (`atlas/net/download.py`, `resumable_download`): a
  standalone helper (injectable transport) that resumes a partial `.part` via HTTP `Range`,
  verifies SHA-256, and atomically renames into place (the rename is the commit point). Handles
  server-ignores-Range restart, `416`-means-complete, and retry exhaustion. Foundation for Phase
  B asset ingestion — not yet wired into the research hot path.
- **Migration** `0020_recovery.sql` — `system.recovery_runs` + `system.checkpoints`.
- **Wired** into `atlas/kernel/bootstrap.py`: `recovery_manager` + `checkpoint_store` constructed
  after the Asset Store, registered on the container + capabilities, and registered in the
  lifecycle immediately after `DatabaseService` (so recovery precedes scheduler/jobs).
- **Dashboard:** `OperationsDashboard.snapshot()` now includes a `recovery` section (last run
  status + per-step results) and a real `last_checkpoint`.
- **Acceptance (met):** `kill -9` mid-research → reboot → the job resumes (scheduler resets the
  interrupted `advance_job` task; the Job Engine re-enqueues the unfinished job) rather than
  restarting; `kill -9` *during* recovery → the prior run is marked `interrupted` and the next
  boot re-runs the idempotent recovery pass to completion before work is accepted. Covered by
  `tests/test_recovery.py` (+15) and `tests/test_download.py` (+6).

---

## 3. Slices landed so far

**§2.1 Clock / Time service**
- `atlas/system/__init__.py`, `atlas/system/time.py` — `ClockService`; `ClockConfig` in
  `manager.py` + `defaults.yaml`; wired in `bootstrap.py` (started early); `tests/test_clock.py`.

**§2.2 Capability Registry enrichment** — see §2.2 above (`tests/test_capabilities.py`, +9).

**§2.6 Artifact versioning** — see §2.6 above (`atlas/system/versioning.py`, `tests/test_versioning.py`, +8).

**§2.3 Storage Manager**
- `atlas/storage/{__init__,service,repository}.py` — `StorageManager` + `StorageRepository`.
- `StorageConfig` in `atlas/config/manager.py`; `storage:` block in `config/defaults.yaml`.
- Migration `database/migrations/0018_storage.sql` (`storage.files`, `storage.quotas`) — **applied**.
- Wired into `atlas/kernel/bootstrap.py` (container/capability/lifecycle after `backup`).
- `tests/test_storage.py` (+19, hermetic).

**§2.4 Asset Store**
- `atlas/assets/{__init__,service,repository}.py` — `AssetStore` + `AssetRepository`.
- Migration `database/migrations/0019_assets.sql` (`asset.assets`, `asset.versions`) — **applied**.
- Wired into `atlas/kernel/bootstrap.py` (container/capability/lifecycle after `storage`).
- `tests/test_assets.py` (+10, hermetic).

**§2.5 Durable event bus + Notifier + SSE**
- `atlas/events/dispatcher.py` — optional durable `store` (persist-before-dispatch).
- `atlas/repositories/event_repo.py` — extended with `persist`/`recent`/`since`/`count`.
- `atlas/notify/{__init__,broker,email,service}.py` — `EventBroker`, `EmailSender`, `Notifier`.
- `NotificationsConfig` + `EmailConfig` in `manager.py`; `notifications:`/`email:` in `defaults.yaml`.
- `GET /v1/events` + `GET /v1/events/stream` (SSE) in `atlas/api/routes.py`.
- `tests/test_notify.py` (+23) + `tests/test_api.py` (+3). No migration (`audit.events` exists).

**§2.7 Operations Dashboard** *(this slice)*
- `atlas/system/host.py` — `HostMetrics` (stdlib CPU/RAM/disk/internet; temp/UPS best-effort).
- `atlas/ops/dashboard.py` — `OperationsDashboard` (guarded single-screen `snapshot()`).
- `GET /v1/ops` route; **Overview** view + live SSE activity feed in `atlas/web/static/`
  (`index.html`, `app.js`, `styles.css`), now the default screen.
- Wired into `atlas/kernel/bootstrap.py` (container `host_metrics`/`ops_dashboard`, capability).
- `tests/test_ops_dashboard.py` (+13) + `tests/test_api.py` (+2). **No migration.**

**§2.8 Recovery Manager + checkpoints + resumable downloads** *(this slice)*
- `atlas/recovery/{__init__,manager,checkpoints}.py` — `RecoveryManager` (durable, re-entrant
  startup recovery) + `CheckpointStore` (resume-point foundation).
- `atlas/repositories/recovery_repo.py` — `RecoveryRepository` + `CheckpointRepository`.
- `atlas/net/download.py` — `resumable_download` (Range-resume + SHA-256 + atomic rename).
- Migration `database/migrations/0020_recovery.sql` (`system.recovery_runs`, `system.checkpoints`).
- Wired into `atlas/kernel/bootstrap.py` — lifecycle **right after `DatabaseService`** (before
  scheduler/jobs), container + capabilities. Dashboard gains `recovery` + `last_checkpoint`.
- `tests/test_recovery.py` (+15) + `tests/test_download.py` (+6) + `tests/test_ops_dashboard.py` (+2).

**Phase 0 is complete** — all §2 work items landed. Full suite green (1126 passed).

---

## 4. Progress checklist

- [x] 2.1 Clock / Time service
- [x] 2.2 Capability Registry enrichment
- [x] 2.6 Artifact versioning (provenance-embedded; no migration)
- [x] 2.3 Storage Manager (workspaces + backups) — migration `0018` (applied)
- [x] 2.4 Asset Store (thin) — migration `0019` (applied)
- [x] 2.5 Durable event bus + Notifier + SSE (no migration — `audit.events` exists)
- [x] 2.7 Operations Dashboard (localhost-first, SSE live; no migration)
- [x] 2.8 Recovery Manager + checkpoints + resumable downloads — migration `0020`

---

## 5. Applying migrations

```bash
source .venv/bin/activate
.venv/bin/atlas-db status     # shows any Pending migrations
.venv/bin/atlas-db migrate    # applies pending migrations (0018 storage, 0019 assets, 0020 recovery)
.venv/bin/atlas-db status     # confirm all Applied
```

- `0018_storage.sql` → `storage` schema (**applied**).
- `0019_assets.sql` → `asset` schema (**applied**).
- `0020_recovery.sql` → `system.recovery_runs` + `system.checkpoints` (apply pending).

Each new schema is created `AUTHORIZATION atlas`, so `atlas-db migrate` (which connects as the
`atlas` role) owns everything it creates — no separate ownership/grants migration is needed.
