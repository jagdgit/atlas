# Loop 0 — Operational Health (O1–O5)

**Status (2026-10-06 evening):** implemented and tested; **not live until the next service restart.**
**Principle:** fail closed, recover automatically, and fail loudly when recovery is not successful.
**Acceptance:** Atlas must never silently spend an expected operating window in a degraded state
(never `EXPECTED → NOT_READY → … → EOD` with no recovery and no alert).

Loop 0 sits alongside Loop A (trading) and Loop B (cognition). It is a P0 operational requirement and
is attached to the existing provider-health tick (`provider_health_tick`, every 120 s). It is not a
new monitoring system. It never places, modifies or blocks orders, and never changes strategy,
SMA/RSI V1, PLC.A, F&O isolation, gates, capital allocation, kernel priority or scheduler
architecture. C0–C9 are unchanged.

---

## 1. The incident that motivated it (2026-10-06)

| Time (IST) | What happened |
|---|---|
| 06:00–06:36 | Zerodha `LOGIN_REQUIRED`; tokens rejected. The MDPH login email worked as designed. |
| before 06:39 | A call to `list_nfo_futures()` with **no session** set `_nfo_futs = []` and `_nfo_futs_ist_day = today`. The empty list was pinned for the day. |
| 06:39 | Session OK via email reply. Options recovered because `list_nfo_options()` had a second fetch path. Futures never refetched. |
| 09:15–15:30 | 29/29 F&O packs `NOT_READY`, reason `expiry_missing`. That is the symptom; the real cause was an empty futures master. No ATM contracts, empty closed-loop day. |
| all day | **No alert.** The operator found out by asking. |

Same day, a separate silent failure turned up: a worker's tick result held a Python `set` in its state,
so `CheckpointRepository.save` raised `TypeError: Object of type set is not JSON serializable`.
The scheduler then retried and failed the whole tick permanently: 51 failures today, 23 on Oct 5,
44 on Oct 1, back to at least Sep 23. The log does not name the worker.

## 2. What was built

### O3 — a failed fetch never becomes a valid empty cache (`atlas/investment/zerodha_feed.py`)

- One shared `_fetch_nfo_master()` feeds both futures and options. Only success is cached:
  - **READY:** rows are present.
  - **EMPTY_VALID:** a genuine dump that contains futures but no seed/index options.
- Fetch states are `NOT_ATTEMPTED / FETCHING / READY / READY_STALE / FAILED / EMPTY_VALID /
  EMPTY_FAILED`. They are persisted to `investment/zerodha/nfo_master_state.json` (on transitions
  and on day change) and exposed through `nfo_master_status()`.
- `READY_STALE` means the fetch failed, a previous day's `nfo_fut.json` exists, and its rows are
  **not served** (fail closed). It is reported as stale, with `stale_ist_day`.
- Failures are retried after a 60 s backoff, so a rate-limited Kite is not hit with ~58 full NFO
  downloads per tick. A new login bypasses the backoff.
- `complete_login()` and `clear_session()` invalidate the NFO caches. Every feed instance
  (trading adapter, API, health probe) also invalidates when the session file's login marker
  (`ist_day|login_time`, never the token) changes. That covers the case where the login came
  through a different instance.
- `refresh_nfo_masters()` invalidates, refetches, and returns the state of each dependency.
- Packs now name the dependency instead of the symptom. When the master has typed rows but no
  FUT rows, `build_fno_data_pack` emits `futures_master_missing` (or `futures_master_stale`) ahead
  of `expiry_missing`. `instrument_master` now carries `futures_rows`, `options_rows` and
  `futures_state`.

### O2 — dependency-aware recovery (`atlas/investment/ops_health.py`)

`ZERODHA_LOGIN_RECOVERED` fires when the provider goes from not-READY to READY. The chain is:
invalidate the provider-dependent caches → refresh futures and options → health check →
`fno_readiness` = `FNO_LAB_READY`, or `FNO_DEGRADED` with `failed: ["futures_master", …]`.
This runs at any hour, so a 06:39 login has fresh masters before 09:15. Each step is recorded in
`investment/ops_health/{day}.json → events`.

### O1 — expected-work contract, idle categories, severity email

During the F&O window (trading days 09:15–15:30 IST; masters are watched from 08:45), every tick
classifies the F&O lab:

| Category | Meaning | Example finding |
|---|---|---|
| A genuine idle | outside the window, or nothing expected | — |
| B safety-blocked | gates held (recorded; systemic only via O4) | `equity:systemic:*` |
| C capability-blocked | masters and provider healthy, packs fail on data quality | `fno:capability` (P1) |
| D infrastructure failure | login, provider, futures/options/instrument master | `fno:futures_master` (P0), `fno:zerodha_provider` (P1) |
| E worker/scheduler failure | no pack for 60 min in session; any paper lab with no admitted in-session tick for 20 min (from 09:35, added 2026-10-13); ≥3 permanent task failures/day | `fno:paper_worker` (P0), `lab:<lab>:ticks` (P0), `ops:scheduler_failures` (P1) |
| OPERATING | at least one pack READY | — |

Incidents:

- Each finding opens or updates an incident. Recoverable dependencies get up to **3** automatic
  `refresh NFO masters` attempts, 90 s apart.
- A refresh that reports OK but does not clear the packs is retried after 10 minutes and counts
  toward the 3 attempts.

Escalation (deduplicated, one mail per incident, through the same SMTP path as the MDPH login email):

- **P0:** emailed as soon as automatic recovery is exhausted, or immediately when no automatic
  recovery exists.
- **P1:** emailed only after recovery is exhausted **and** the failure has persisted for ≥20 minutes.
- **P2:** never emailed. It appears only in the evening digest section `OPERATIONAL HEALTH (Loop 0)`.
- Zerodha `LOGIN_REQUIRED` is P0 but owned by the existing MDPH login email. Loop 0 records it and
  does not send a duplicate.
- When an alerted incident clears, a short `RESOLVED` mail follows.
- Exception (2026-10-13): `fno:paper_worker` and `lab:<lab>:ticks` never clear because the market
  window ended. They need fresh evidence written **after** the incident opened (a pack, or an admitted
  in-session tick) to become `RECOVERED_VERIFIED`; otherwise they end `UNRESOLVED_OPERATOR_ACTION_REQUIRED`.

Email layout (subject `[Atlas OPS] P0 ACTION REQUIRED — F&O DATA PLANE: … (day)`):

```
ATLAS ACTION REQUIRED — F&O DATA PLANE
Severity: P0
Day: 2026-10-06   Detected: 09:15 IST   Category: D_INFRASTRUCTURE_FAILURE

WHAT FAILED        Futures master = FAILED
WHY                NFO futures fetch: fetch_error:RuntimeError.
IMPACT             29/29 F&O packs NOT_READY (dominant: futures_master_missing). …
WHAT ATLAS TRIED   1. 09:15 refresh NFO masters → FAILED (futures_master)  … 3.
                   Automatic recovery: EXHAUSTED
CURRENT STATE      provider = READY, futures_master = FAILED, packs_ready = 0/29, …
WHAT YOU CAN DO    - …
Safety: No orders were submitted. Atlas stays fail-closed (paper only) while this is open.
```

### O4 — systemic safety blocks

`assess_systemic_blocks` reads `investment/decisions/pipeline/india_equity_learner/{day}.json`.
A tag is systemic when it accounts for **≥60 % of actionable buys** (with ≥3 actionable) in each
of the last **2** sessions. The finding is P1, evaluated after 15:30, and re-alerted at most every
3 days. A single-session block is only recorded. **Gates are never weakened:** the alert asks for
the evidence pipeline to be investigated.

Real data: `fundamentals_incomplete` blocked 67 % (Sep 30), 71 % (Oct 1), 100 % (Oct 5) and
80 % (Oct 6) of actionable buys. That is systemic, and tonight's dry run flags it.

### O5 — operational learning

When an incident closes, `investment/ops_health/experience.jsonl` gets one row: failure → cause →
recovery attempts → outcome → lesson. Lessons are deterministic per dependency (no LLM). For the
futures master: *"An empty futures response following provider failure must not become a valid
day cache; only a successful fetch is cached, and a new login invalidates provider-dependent
caches."*

### Silent-failure fixes found along the way

- `CheckpointRepository.save` now goes through `task_repo._json_safe`: sets and frozensets become
  sorted lists; UUIDs, dates and Paths become strings. No worker calls `.add()` on reloaded state,
  so the round trip is safe. This stops the daily `set/UUID is not JSON serializable` tick failures.
- The scheduler records every permanent task failure (task type plus `worker_id`) to
  `investment/ops_health/task_failures.jsonl`. Loop 0 surfaces ≥3 per day as category E.

## 3. Files

| File | Change |
|---|---|
| `atlas/investment/zerodha_feed.py` | fetch-state model, shared fetch, backoff, invalidation, `refresh_nfo_masters`, `nfo_master_status` |
| `atlas/investment/fno_data_pack.py` | `futures_master_missing` / `futures_master_stale`; master row breakdown |
| `atlas/workers/paper_trading.py` | passes the feed's futures state into the pack |
| `atlas/investment/ops_health.py` | **new** — Loop 0 (O1, O2, O4, O5, digest, acceptance audit) |
| `atlas/investment/market_data_provider_health.py` | `provider_health_tick` runs Loop 0 |
| `atlas/investment/reports.py` | evening digest gets the `OPERATIONAL HEALTH (Loop 0)` section |
| `atlas/scheduler/service.py` | records permanent task failures |
| `atlas/repositories/recovery_repo.py`, `task_repo.py` | JSON-safe checkpoints (sets/frozensets) |
| `tests/test_nfo_master_state.py`, `tests/test_ops_health_loop0.py` | **new** — 21 tests, including a replay of today's incident |

Runtime artifacts live under `investment/ops_health/`:

- `{day}.json`: incidents, events, alerts, window minutes per category, `fno_readiness`
- `heartbeat.json`
- `experience.jsonl`
- `task_failures.jsonl`

They also include `investment/zerodha/nfo_master_state.json`.

## 4. Kill switches

Set these in the `provider_health_tick` schedule payload:

- `"ops_health": false` disables Loop 0 entirely.
- `"ops_alert_email": false` keeps classification and recovery running but sends no ops email.

## 5. Known limits (honest)

- **Scheduler fully stopped** cannot be alerted from inside the scheduler. Loop 0 writes
  `investment/ops_health/heartbeat.json` every tick. Detecting a dead process needs an external
  watchdog (a systemd timer checking heartbeat age). That watchdog is **not installed yet** and
  needs operator approval.
- **DB down** is only visible indirectly: no ticks and a stale heartbeat. It is covered by the same
  external watchdog.
- Equity-lab idle classification is limited to O4. Per-window equity A–E classification is not
  built yet.
- The worker whose state held a `set` was not identified, because the log omits worker IDs. The
  fix is generic, and new permanent failures now record the `worker_id`.

## 6. Verification

- `tests/test_nfo_master_state.py` (9): pre-login call does not pin; backoff then retry; stale cache
  not served; empty response → EMPTY_FAILED; a login from another instance bypasses the backoff;
  pack reasons.
- `tests/test_ops_health_loop0.py` (12): today's incident (3 attempts → one P0 email with every
  section); successful recovery → resolved, no mail, lesson recorded; O2 readiness naming the
  failed dependency; LOGIN_REQUIRED owned by MDPH; P1 persistence; systemic block alerted and the
  single session only recorded; category E from task failures; digest and acceptance violation;
  tick never raises; checkpoint sets.
- Dry run on real data (11:00 IST replay): `D_INFRASTRUCTURE_FAILURE`, P0 `fno:futures_master`,
  30/30 packs NOT_READY; P1 `equity:systemic:fundamentals_incomplete` (80 %, 5 sessions).

## 7. Incident 2026-10-06 18:21–19:06 IST — found by the watchdog on its first run

The external watchdog was dry-run once before installation and immediately returned
`{"ok": false, "open": ["heartbeat_stale"]}`. It was correct, and the incident was real: Atlas's
recurring engine had been dead for 45 minutes.

**Verified root-cause chain.**

1. The Atlas CLI does not act as a client of the running service. `atlas status` (and other verbs)
   **boots a second full kernel** against the same Postgres — it logs `registered schedule …`,
   `starting service: clock/database/recovery/checkpoints`, and loads all 13 plugins.
2. That second kernel polls `scheduler.tasks` and **claims work belonging to the live service**. It
   does not register the full handler set, so claimed tasks die with
   `no handler registered for task_type '<x>'`.
3. At 12:51:45 UTC `worker-0` claimed and failed `schedule_tick` this way
   (`retry_count=0, max_retries=5` — it was marked `failed` without retrying).
4. `schedule_tick` is the only thing that advances `next_run_at`. With it dead, **no schedule ever
   became due again.** All 107 enabled schedules froze with `next_run_at` at ~12:51–12:53 UTC,
   eventually 2,613 s overdue.
5. The live service stayed `active (running)`, healthy, polling, and with nothing to do. `host_guard_tick`,
   `provider_health_tick`, `schedule_tick`, `worker_tick`, `embed_backfill` and
   `lab_loop0_s11_canary` all stopped. Only `candidates_drain` and `ingest_scan`, driven elsewhere,
   continued — which is why the process looked alive.
6. Loop 0 could not alert, because Loop 0 runs *inside* `provider_health_tick`. This is precisely the
   failure mode the external watchdog exists for, and the watchdog caught it.
7. Recovery was accidental: the next `atlas status` re-registered the schedules, which reset
   `next_run_at`, and the live service drained the backlog at 13:36:14 UTC.

**Scale.** 164 `no handler registered` failures since 2026-07-11, 163 of them on `worker-0`. This is a
long-standing intermittent fault that has been silently stopping scheduled work for months.

**Classification (O1).** Category D — infrastructure failure. Severity P0. Not genuine idleness.

**Open fixes (not yet made).**

- **F1.** The CLI must be a client, not a second kernel. Read-only verbs (`status`, `jobs`, `doctor`)
  must query the running service's API and must never start a scheduler or claim tasks.
- **F2.** `schedule_tick` must not be a single point of failure. A dead `schedule_tick` should be
  self-healing: either exempt it from permanent failure, or have the service re-register schedules
  when no schedule has advanced within N intervals.
- **F3.** `no handler registered` must be a loud P0, not a silent task failure. A handler-less claim
  means two kernels are competing for one queue, which is never correct.
- **F4.** Loop 0's own liveness cannot depend on a scheduled task. The heartbeat staleness check
  belongs in the watchdog only — which is how it behaved today, correctly.
- **F5.** Schedule registration leaks rows. Each CLI kernel boot re-registers the five recurring
  schedules as *new* rows rather than upserting: the enabled count went 107 → 112 during one
  `atlas status`. There are now ~112 enabled schedules for about six distinct task types
  (7 × `provider_health_tick`, 5 × `host_guard_tick`, 5 × `embed_backfill`, …), so every tick is
  executed several times over. Registration must be idempotent on `(task_type, payload, interval)`,
  and the accumulated duplicates should be pruned.

**Consequence for the audit.** Maturity score #21 (operational reliability) is revised from 4 to **3**.
Loop 0 and the watchdog work as designed; the layer beneath them has a single point of failure that
any CLI invocation can trigger.

---

## 8. 2026-10-07 — root filesystem at 100%, and the retention that never existed (O6)

Found while running a routine health check after the J5/J6 work: a Postgres query
failed with

```
psycopg.errors.DiskFull: could not write to file
  "base/pgsql_tmp/pgsql_tmp2956787.0.fileset/i12of512.p1.0": No space left on device
```

Atlas itself was **fine** — 2,838 task runs completed in the hour before, zero errors in
two hours, 133 enabled schedules with none overdue, same PID since 07:02 with zero
restarts. Only operations needing temp space (large sorts) were failing. That is the
same shape as §7: the service reports healthy while a subsystem is quietly broken.

### Where the space went

```
/dev/mapper/ubuntu--vg-ubuntu--lv   98G   93G  828M 100% /
/dev/mapper/ubuntu--vg-app_data    492G   93G  374G  20% /data
```

`du` on `/` accounted for only 52 GB. The missing 41 GB was the Postgres data directory,
which the unprivileged scan could not read. Asking Postgres directly:

| table | rows | total size | heap / index / toast |
|---|---|---|---|
| `audit.events` | **37,329,615** | 12 GB | 6.3 / 5.9 / 0.001 GB |
| `scheduler.task_runs` | **36,962,729** | 9.0 GB | 5.6 / 3.2 / 0.001 GB |
| `scheduler.tasks` | **36,960,401** | 7.4 GB | 5.2 / 2.0 / 0 GB |
| `system.health` | 4.6 M | 11 GB | 1.4 / 0.9 / **8.7** GB |

All four span 2026-07-11 → 2026-10-07 — 88 days, nothing ever deleted. ~420 K rows per
day in each. 28 GB of the 40 GB database is expired tick churn, and the cost compounds
through backups: each nightly `pg_dump` is 11.8 GB and growing (11.27 GB on Sep 28 →
11.78 GB on Oct 7), so the correctly-retained seven dumps hold **76 GB** on `/data` of
mostly expired ticks.

For the record, the rest of `/` is not Atlas: `/usr` 21 GB (7 GB Ollama models), `/home`
19 GB (14 GB of Cursor IDE storage), `/var` 8.3 GB (2.6 GB journald, 4.5 GB snapd).
Atlas owns 40 of the 93 GB, and that 40 GB is the part worth fixing.

### Root cause

`config/defaults.yaml` has carried `audit: retention_days: 90` since the beginning.
Searching the codebase for `retention_days` returns exactly one hit — the declaration in
`atlas/config/manager.py`. **Nothing reads it.** It is a promise with no implementation,
and `scheduler.tasks` / `task_runs` / `system.health` had no retention setting at all.

It would not have helped anyway: the oldest row is 88 days old and the window is 90
days, so even a working 90-day policy had never once fired.

Diagnostics ruled out the alternatives: no prepared transactions, no replication slots,
no long-running transactions, `age(backend_xmin)` of 0. Nothing was blocking vacuum.
`audit.events` has 12 dead tuples against 37 M live rows. This is real rows, not bloat.

### A second finding inside the first

Every one of the 37,329,934 `audit.events` rows is `status='pending'` with `processed_at`
NULL. **Nothing has ever consumed a single audit event.** 36,959,381 of them (99.0%) are
`TaskCompleted` — one row per completed tick. The table is a write-only firehose.

That mattered immediately: the obvious retention guard, `processed_at IS NOT NULL`, is a
permanent no-op here, and the first dry run duly reported 0 expired audit rows while
correctly finding 36.8 M in `scheduler.tasks`. The policy now keys on event *type*
instead, listing the four tick-telemetry types explicitly so that `DecisionMade`,
`KernelStarted` and any future event type are retained by default.

### The fix (O6)

`atlas/ops/retention.py` — a `RetentionManager` with a rule per table, registered as the
`retention_prune` task type on an hourly schedule.

* **Dry run by default** (`retention.enabled: false`). This deletes history
  irreversibly, so it reports counts at WARNING and changes nothing until an operator
  opts in. A silent default is how `retention_days` went unnoticed for three months.
* **Batched deletes**, 20 K rows per transaction, 50 batches per run. One `DELETE` over
  37 M rows would hold a transaction open for the entire run and write WAL faster than
  it clears — on an already-full disk that is as likely to hurt as help.
* **`scheduler.tasks` only**, because `task_runs.task_id` is
  `REFERENCES tasks(id) ON DELETE CASCADE`; pruning parents takes the runs with them.
* **Only `completed` and `cancelled`.** `pending`/`running` are live work, and `failed`
  rows are the evidence an operator needs after an incident — §7's outage was diagnosed
  from exactly those rows.

Measured dry run against the live database, 31.8 s, nothing deleted:

```
scheduler.tasks        days= 14  expired=36,768,012   (cascades to ~36.8M task_runs)
audit.events           days= 30  expired=36,695,382
system.health          days= 30  expired= 4,629,957
```

**78,093,351 rows** are eligible. 18 tests in `tests/test_retention_o6.py`.

### What this does and does not solve

`DELETE` makes space reusable *inside* the table and stops the growth. It does **not**
return space to the filesystem — that needs `VACUUM FULL` (or `pg_repack`) and transient
free space roughly equal to the table being rewritten, which 828 MB does not allow. So
the order has to be: prune first, let the tables stop growing, free headroom elsewhere,
then rewrite the largest tables one at a time.

Current headroom is roughly **2.5 days** at ~320 MB/day of database growth. Not tonight's
emergency, but not a week's slack either.

### Operator decisions still required

1. **Enable the prune** — `retention:enabled: true`. Deletes 78 M rows of tick history;
   windows are 14 days for scheduler tasks and 30 for audit/health.
2. **Reclaim the space** — `VACUUM FULL` per table, once there is headroom, during a
   quiet window. Needs ~12 GB transient for `audit.events`.
3. **Non-Atlas space** — 14 GB of Cursor IDE storage, 2.6 GB journald, 4.5 GB snapd.
   Not mine to prune.
4. **Stop the firehose at source** — a `TaskCompleted` audit row per tick, consumed by
   nothing, is 99% of a 12 GB table. Retention treats the symptom; not writing it would
   be the cure.

### 8b. Correction — deleting was the wrong fix. There are 270 GB sitting idle.

§8 framed this as a retention emergency and recommended enabling the prune. The operator
pushed back: *"i see ~370gb available check the resources once before pruning because i
do not want to lose anything important."* That was the right instinct and §8's
recommendation was wrong. The full picture:

| volume | size | used | free |
|---|---|---|---|
| `/dev/mapper/ubuntu--vg-ubuntu--lv` → `/` | 98 G | 93 G | **796 M** |
| `/dev/mapper/ubuntu--vg-app_data` → `/data` | 492 G | 93 G | **374 G** |
| `/dev/mapper/ubuntu--vg-d_drive` → `/d` | 285 G | **319 M** | **270 G** |
| `/dev/sdb1` → external One Touch | 932 G | 310 G | 623 G |

`/d` is a 285 GB logical volume that is **1% used**. I had not looked at it, which is why
§8 reached for deletion. Atlas does not have too much data; Postgres is simply sitting on
the one small volume. `sda3` (890.7 GB) is fully allocated across the three LVs, so `/`
cannot be extended from free extents — but the data can move to where the space is.

**The correct fix is relocation, not deletion:** move the Postgres data directory (or just
the four large tables, via a tablespace) onto `/d` or `/data`. That preserves 100% of
history, frees ~40 GB on `/` immediately, and gives Postgres years of headroom. It needs
a short downtime and root, so it is an operator action.

### 8c. What the prunable rows actually contain

Checked before recommending anything, because the operator asked:

```
prunable scheduler.tasks (>14d, completed/cancelled)
  schedule_tick          36,514,453   <- 99.2%, payload = {}
  worker_tick               120,287
  host_guard_tick            78,017
  ingest_scan                17,467
  candidates_drain           16,131
  ...

prunable audit.events (>30d)        retained audit.events (>30d)
  TaskCompleted  36,503,927           DecisionMade                3,927
  SchedulesFired    113,877           KernelStarted               2,319
  WorkerTick         74,686           RecoveryStarted             2,314
  WorkerThrottled     3,670           RecoveryCompleted           2,312
                                      KernelStopping              1,990
                                      OpportunityDiscoveryUpdated 1,024
                                      InvestmentUniverseUpdated     874
                                      job.activity                  275
```

**36,514,453 of the 36.8 M prunable rows are `schedule_tick` with an empty payload `{}`** —
bare clock ticks carrying no information at all. The retained set is precisely the
decision and lifecycle history. So the policy is safe; it simply is not *necessary* for
space any more.

Retention stays valuable as hygiene rather than rescue: it shrinks the nightly `pg_dump`
(11.8 GB and growing, ×7 retained = 76 GB) and keeps planner-facing counts meaningful. It
remains `enabled: false` until the operator chooses.

**Revised order of operations:**

1. Relocate Postgres to `/d` or `/data` — solves the actual problem, loses nothing.
2. Then optionally enable retention as hygiene, and `VACUUM FULL` with the headroom the
   move provides.
3. Separately, stop writing a `TaskCompleted` audit row per tick: 36.5 M rows that
   nothing has ever read is the upstream defect, and retention only mops it up.

## 9. 2026-10-13 — lab starvation the alerts did not catch

Host Guard deferred every paper-lab tick from ~11:15 to 17:35 (free RAM ~2.8 GB vs a 3072 MB
gate). Loop 0 sent one correct P0 at 12:18 ("Last F&O pack 65 min ago") and then a false
`RESOLVED` at 15:30: `packs > 0` was satisfied by packs written that morning. The equity labs had
no check at all.

Fixes:

- `05e7286` — the F&O worker incident verifies recovery only when `latest_pack_at > opened_at`.
- `27c4890` — `atlas/investment/lab_ticks.py`: per-day ledger `investment/ops_health/lab_ticks/<day>.json`
  of admitted ticks per lab (written at the start of each `paper_trading` tick) and deferred ticks
  per worker by cause (written by `WorkerManager._record_wait`). `assess_lab_ticks` raises a P0
  `lab:<lab>:ticks` for any lab seen today or on the previous recorded day with no admitted
  in-session tick for 20 min; the WHY line names the deferral cause and last reason. The evening
  digest prints `Lab ticks in session — <lab>: admitted N, deferred M, last HH:MM`.
- The admission problem itself is fixed in Host Guard hg.1.4 (market-critical lane, `8057120`).

Incident write-up: `docs/incidents/2026-10-13_LAB_STARVATION_AND_POST_CLOSE_FNO_FLATTEN.md`.
