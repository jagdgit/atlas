# Atlas Autonomous Self-Diagnosis v1 — Discussion & Execution Plan

**Date:** 2026-10-08  
**Status:** DECISIONS LOCKED · Phases 1–8 **COMPLETE** (2026-10-08) · Autonomous Self-Diagnosis v1 closed (G8 ops)  
**Constraint:** Do **not** remove Ollama models. Do **not** delete knowledge / experiences / learning / trading history / embeddings / documents merely to free space.

This document is the single working artifact for:

1. Where Atlas started vs where it is now (shared diagnosis).
2. What is still broken / incomplete.
3. The exact ordered plan to become operationally healthy, then prove autonomous self-diagnosis.

Related prior docs: `docs/2026-10-06_NORTH_STAR_AUDIT.md`, `docs/2026-10-07_SESSION_CHANGELOG.md`, `docs/2026-10-06_OPERATIONAL_HEALTH_LOOP0.md`.

---

## 0. Live facts (re-checked 2026-10-08 ~19:30 IST)

| Fact | Value |
|---|---|
| `/` | 98G, **92G used, 1.1G free (99%)** |
| `/data` | 492G, 94G used, **373G free** |
| `/d` | 285G, 319M used, **270G free** |
| Postgres | **18**, data dir `/var/lib/postgresql/18/main` **on `/`** |
| `atlas` DB size | **40 GB** |
| Enabled schedules | **111** (disabled 328) |
| `retention_prune` enabled | **7** (should be 1; currently failing) |
| `worker_tick` enabled | **69** |
| Failed `task_runs` today | **13,191** — **all** `no handler registered for task_type 'retention_prune'` |
| Atlas service | active (PID from earlier check ~1991, started after earlier restart) |
| Ollama models | **keep** (`/usr/share/ollama` ~7G on `/`) |

**Disk accounting that closes the earlier confusion:**

| On `/` | ~Size |
|---|---|
| Postgres `atlas` DB (postgres-owned; normal `du` can't see it) | ~40G |
| Visible rest of `/` (`du -x`) | ~52G |
| of which Cursor config | ~15G |
| of which Ollama | ~7G (**do not remove**) |
| of which snapd | ~4.5G |
| of which journal | ~2.5G |
| **df Used** | **~92G** |

**Backups are already on `/data`** (`/data/atlas_data/backups` ≈ 76G, seven dumps). They are **not** filling `/`.

**Target layout (agreed):**

| Mount | Current role | Target |
|---|---|---|
| `/` | OS + Postgres + Cursor + Ollama | OS + app runtime + Ollama + Cursor |
| `/data` | Atlas repo + `atlas_data` + backups | **+ PostgreSQL 18 data dir** |
| `/d` | Almost empty | **Reserve** (overflow / second copy / future cold store) — not the first move target |

Postgres target path: **`/data/postgresql/18/main`**.

---

## 1. Where Atlas started vs where it is now

### Stage 1 — Collection of subsystems (islands)

Market intelligence, F&O lab, equity learner, intraday, FEL, knowledge/RAG, Cognitive Core, memory, scheduler, Kernel, LLM, research, experience, learning — largely independent.

The real defect was not missing code. It was missing joins:

```
capability A ──X── capability B
experience ───X── decision
learning ─────X── future behavior
Kernel ───────X── toolbox
```

**Implication that still holds:** highest-value work is joining existing systems, not building another subsystem.

### Stage 2 — Agent Kernel (architecture jump)

From predetermined schedule→execute to:

```
OBSERVE → IDENTIFY WORK → PRIORITIZE → PLAN → INVESTIGATE
→ VERIFY → RECORD → LEARN → SCHEDULE NEXT WORK
```

Kernel can discover work, prioritize blockers, multi-step plan, retry, record gaps, resume, create experiences, talk to Cognitive Core.

**Still open:** Kernel's capability vocabulary ≪ Atlas's real toolbox. That is **J1**.

### Stage 3 — C0–C9 learning architecture

From “trade/P&L = learning” to:

```
hypothesis → prediction → action → outcome → prediction error
→ attribution → candidate → validation → belief → later behavior
```

Oct 8 report correctly reporting `learning_records=0` when no qualifying chains exist is a **maturity signal**, not a regression.

### Stage 4 — Operational Health

Zero trades ≠ idle. States are distinct: NO OPPORTUNITY / SAFETY BLOCK / CAPABILITY GAP / PROVIDER FAILURE / WORKER FAILURE / SCHEDULER FAILURE. F&O Zerodha→empty futures→no packs is the proof case.

### Stage 5 — Self-inspection (J0/J2/J3/J5/J6)

Atlas can inspect its own Postgres (bounded, read-only), logs (redacted), real schema, real values, task history. That enabled the schedule-duplication root-cause chain. Atlas can use **itself** as an evidence source.

### Where we actually are (“YOU ARE HERE”)

```
collection of tools
 → workflow engine
 → Agent Kernel
 → closed-loop labs
 → operational health
 → self-inspection
 → grounded planning
 → honest execution
 → self-diagnosis (demonstrated once, not yet productized)
 →  ← HERE
 → unified capability registry (J1)
 → autonomous investigation (blind North-Star)
 → self-generated hypothesis
 → validated learning
 → behavioral change (C8)
 → persistent autonomous Atlas
```

**Working:** autonomous work discovery, prioritization, multi-step grounded plans, job-path tool execution, self DB/log inspection, honest completion, capability-gap memory, experience recording, continuous investigation under blockage.

**Not yet proven end-to-end:** Kernel→full toolbox (J1), autonomous hypothesis generation, cognitive cycle runtime (C0/C9 often “not run yet”), validated learning that changes later behavior (C8), blind North-Star investigation without tool hints.

**Philosophy refinement (adopted):**

> Atlas must always produce a **productive state transition**  
> (TRADE | OPPORTUNITY | LEARNING | VALIDATED DATA | HYPOTHESIS | EXPERIMENT | CAPABILITY RECOVERY | CAPABILITY GAP | OPERATOR ALERT | SYSTEM FIX)  
> — not merely “positive learning.”

Failed → understand → gap → wait → retry is productive. Failed → same failure forever is not.

---

## 2. Problems that must be fixed before celebrating autonomy

### P0-A — Mass scheduler failures — Phase 1 DONE

| Metric | Count | Classification |
|---|---|---|
| Report “permanently failed scheduled tasks” | ~50,841 | Failed **`task_runs`** stock; dominated by `retention_prune` |
| Live stock `retention_prune` failed runs | **51,523** | Same storm (grew since report) |
| Today’s failed runs (earlier recheck) | **13,191** | Same error: no handler for `retention_prune` |
| Other failed-run types (stock) | ~2k combined | Secondary (`worker_tick` 1631, etc.) — Phase 4/5 |
| `tasks.status='failed'` | 463 | Different KPI — not the 50k |

**Generator stopped 2026-10-08 19:44 IST:** all 7 enabled `retention_prune` schedules disabled; 6 pending tasks cancelled; failed rows **kept**. New fails last 15m/2h = 0. Evidence: `/data/atlas_data/ops/phase1_retention_prune_2026-10-08/`.

### P0-B — PostgreSQL on the wrong volume

Root cause of `/` fullness is **location + firehose**, not “Atlas has too much valuable data.”

- Move **Postgres 18** → `/data/postgresql/18/main` (copy → verify → switch → verify → delete old).
- Keep `/d` free as reserve.
- Keep Ollama models.
- Keep retention **disabled** until failure storm and registration are fixed.

### P0-C — F1 + F5 (one architectural issue)

```
CLI / test / doctor
  must → talk to existing Atlas service/API
  must NOT → boot second Kernel → register schedules → claim tasks
```

Schedule registration must be idempotent on a durable identity  
`(task_type, payload_fingerprint, interval, owner)`.

Hard regression: boot Atlas 100 times → enabled schedule count unchanged.

### P0/P1 — Classify 69–71 `worker_tick` schedules

Do **not** mass-delete. Classify each payload: ACTIVE / STALE / ORPHANED / UNKNOWN. Then remove only STALE/ORPHANED with an audit trail.

### P1 — J1 unified capability registry

Single source of truth for capabilities → Job Engine, Agent Kernel, Planner, Cognitive Core, Research. Until J1, Kernel cannot autonomously use SQL/logs/code/git that the job path already has.

### Then — Blind North-Star self-diagnosis test

Operator prompt only:

> Investigate why Atlas experienced a large number of scheduled-task failures today. Determine the root cause, verify using available evidence, and report what should be done.

No tool hints. Pass criteria in §7.

### Then — Cognitive loop consumes the experience → C8 behavioral proof

One genuine learning candidate that later changes registration/behavior beats 10,000 synthetic lessons.

---

## 3. What we will prune vs what we will never prune

### Never prune for space (VALUABLE STATE)

- Knowledge / RAG corpora / embeddings
- Experiences, learning stories, beliefs, hypotheses, experiments
- Trading history / sim blotter / lab books
- Documents / research artifacts
- Configuration / portfolios / missions
- **Ollama models** (explicit operator constraint)

### High priority OPERATIONAL HISTORY (retain, then prune with policy)

| Object | ~Size / rows | Proposed retain | Notes |
|---|---|---|---|
| `scheduler.task_runs` | 9.1G / 37.1M | 14–30 days | Firehose; FK cascade from tasks |
| `scheduler.tasks` | 7.4G / 37.0M | completed/cancelled older than 14–30d | Keep failed samples needed for diagnosis briefly |
| `audit.events` | 12G / 37.4M | 30–90d; preserve security/important types | Most rows are tick noise |
| `system.health` | 11G / 6.9M | 7–14 days | High-frequency samples |

**Do not truncate blindly.** Fix generators first (`retention_prune` duplicates, F5, audit firehose of `TaskCompleted` per tick), then prune under retention rules (O6 already drafted; keep **dry-run / disabled** until post-migration).

### DISPOSABLE (after verification)

- Duplicate/orphan schedules
- Temp files, caches (not Ollama)
- Journal vacuum to a sane cap
- Baseline worktree `/data/atlas_data/tmp_baseline/atlas` (~25–38M) when no longer needed
- Old package/snap caches on `/` **after** PG move (low urgency)

### Cursor 15G on `/`

Optional later cleanup of Cursor caches — **not** part of P0 Atlas migration; operator-owned IDE data. Document only.

---

## 4. Execution plan — ordered phases

### Phase 0 — Freeze risk & capture baseline (30–60 min, Atlas can stay up)

**Goal:** Evidence pack so we can prove “nothing valuable was lost.”

Run and store under `/data/atlas_data/ops/pg_move_2026-10-08/`:

```bash
mkdir -p /data/atlas_data/ops/pg_move_2026-10-08
df -h / /data /d | tee /data/atlas_data/ops/pg_move_2026-10-08/df_before.txt
systemctl status postgresql@18-main --no-pager | tee .../pg_status_before.txt
systemctl status atlas --no-pager | tee .../atlas_status_before.txt

# As postgres (sudo):
sudo -u postgres psql -d atlas -c "\l+" | tee .../psql_l_plus.txt
sudo -u postgres psql -d atlas -c "SELECT pg_size_pretty(pg_database_size('atlas'));" | tee .../db_size.txt
sudo -u postgres psql -d atlas -c "
SELECT n.nspname||'.'||c.relname AS rel,
       pg_size_pretty(pg_total_relation_size(c.oid)) AS total,
       pg_total_relation_size(c.oid) AS bytes
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE c.relkind='r' AND n.nspname NOT IN ('pg_catalog','information_schema')
ORDER BY 3 DESC LIMIT 20;" | tee .../top_relations.txt
sudo -u postgres psql -d atlas -c "
SELECT 'audit.events' AS t, count(*) FROM audit.events
UNION ALL SELECT 'scheduler.tasks', count(*) FROM scheduler.tasks
UNION ALL SELECT 'scheduler.task_runs', count(*) FROM scheduler.task_runs
UNION ALL SELECT 'system.health', count(*) FROM system.health;" | tee .../row_counts.txt
sudo du -sh /var/lib/postgresql/18/main | tee .../pgdata_du.txt
```

Also snapshot schedule inventory:

```sql
SELECT enabled, task_type, count(*)
FROM scheduler.schedules
GROUP BY 1,2 ORDER BY 1 DESC, 3 DESC;
```

**Stop condition:** If free space on `/` drops below ~500M during capture, abort nonessential writes and jump to Phase 1 emergency (disable `retention_prune` schedules immediately via SQL — that does not require downtime).

---

### Phase 1 — Stop the bleeding — **DONE** (2026-10-08 19:44 IST)

**Goal:** Stop adding tens of thousands of failed rows today.

1. ~~**Disable all `retention_prune` schedules`** (all 7).~~ Done — 7 disabled, 11 total rows now all `enabled=false`.
2. Cancelled 6 pending `retention_prune` tasks (would have failed on claim).
3. Left `worker_tick` alone until Phase 5.
4. Confirmed new `retention_prune` fails = 0 (15m and 2h windows).
5. Classified 50,841 ≈ stock of `retention_prune` failed runs (now 51,523); 13,191 = today’s slice of same storm.

**Acceptance:** met. Failed historical rows **not** deleted.

---

### Phase 2 — PostgreSQL 18 move: `/` → `/data` (controlled downtime)

**Goal:** Recover ~40G on `/` without losing any DB history.  
**Method:** **copy → verify → switch → verify → delete old.** Never `mv` as the first operation. Never delete Ollama.

#### 2.1 Preconditions

- `/data` has ≥ 80G free (currently ~373G — OK).
- Fresh dump already exists on `/data/atlas_data/backups/` (today’s dump present — OK). Optional: take one more dump **before** stop if last dump is >24h old.
- Operator available for sudo password and to confirm each gate.
- Estimated downtime: **15–40 minutes** depending on copy speed of ~40G.

#### 2.2 Procedure (command-level outline)

```text
0. Phase 0 baseline captured
1. Disable retention_prune (Phase 1) if not done
2. sudo systemctl stop atlas
3. Confirm no atlas clients: ss / pg_stat_activity
4. sudo systemctl stop postgresql@18-main
5. sudo mkdir -p /data/postgresql/18
6. sudo rsync -aHAX --info=progress2 \
     /var/lib/postgresql/18/main/ \
     /data/postgresql/18/main/
7. Verify:
     - du -sb both trees nearly equal
     - sudo -u postgres test -r /data/postgresql/18/main/PG_VERSION
     - ownership postgres:postgres, mode 700 on main
8. Edit /etc/postgresql/18/main/postgresql.conf:
     data_directory = '/data/postgresql/18/main'
   (Keep a copy of old conf in the ops folder)
9. Optional safety: bind-mount or rename old dir aside:
     sudo mv /var/lib/postgresql/18/main /var/lib/postgresql/18/main.pre_move_YYYYMMDD
   ONLY after rsync checksum/size OK — or leave in place until first successful start
10. sudo systemctl start postgresql@18-main
11. Verify:
     - systemctl is-active postgresql@18-main
     - show data_directory → /data/postgresql/18/main
     - \l+ / row counts match Phase 0
     - Timescale / extensions: \dx
     - SELECT count(*) from key tables
12. sudo systemctl start atlas
13. Verify:
     - atlas ActiveState=active
     - /v1/ops or health OK
     - mailer/workers ticking
     - one SQL query via Atlas path works
14. df -h /  → expect ~40G recovered
15. ONLY AFTER ≥1 hour healthy (or operator sign-off):
     sudo rm -rf /var/lib/postgresql/18/main.pre_move_YYYYMMDD
```

#### 2.3 Rollback

If Postgres fails to start on `/data`:

1. Stop postgres.
2. Restore `data_directory` to `/var/lib/postgresql/18/main` (or rename pre_move back).
3. Start postgres → start atlas.
4. Leave `/data/postgresql/18/main` for forensics; do not delete until understood.

#### 2.4 Explicit non-goals for Phase 2

- No retention prune.
- No Ollama changes.
- No Cursor deletion.
- No `/d` involvement yet.
- No Timescale schema changes.

---

### Phase 3 — Database cleanup — **DONE** (2026-10-08 20:43–21:49 IST)

**Goal:** Shrink the firehose under policy; keep diagnostic window.  
**Constraint honored:** `retention_prune` **schedule stayed disabled** (7-day freeze). Prune was a **manual one-shot**.

Evidence: `/data/atlas_data/ops/phase3_retention_2026-10-08/`

| Step | Result |
|---|---|
| Dry-run | ~78.2M expired rows eligible (tasks 36.8M / audit 36.7M / health 4.7M) |
| Live prune | **78,221,855** rows deleted across 37 passes; 0 errors |
| Policy | scheduler 14d (completed/cancelled only); audit 30d (tick types); health 30d |
| Evidence kept | **51,523** `retention_prune` failed `task_runs`; **463** `tasks.status=failed` |
| Positions / trades | Unchanged (valuable state) |
| `VACUUM ANALYZE` | Done (space reusable inside PG, not OS) |
| `VACUUM FULL` | Done — **40 GB → 4.5 GB** DB; `/data` **146G → 110G** used (~36G returned) |
| Schedule | `retention_prune` enabled count still **0** |

| Relation after FULL | Size |
|---|---|
| `system.health` | 3.8 GB |
| `audit.events` | 221 MB |
| `scheduler.task_runs` | 88 MB |
| `scheduler.tasks` | 52 MB |

**Filesystem cleanup done:** removed `/data/atlas_data/tmp_baseline` (38M);  
`sudo journalctl --vacuum-size=500M` freed **2.2G** on `/` (2026-10-08 ~22:38 IST).

**Do not** set `retention.enabled=true` or re-enable the schedule until the 7-day freeze ends and F5 is fixed.

---

### Phase 4 — F1 + F5 (architecture) — **COMPLETE** (2026-10-08)

**F1 — single runtime**

- CLI read-only verbs (`status`, `jobs`, `doctor`, tests that previously booted a kernel) must attach to the **running** service or use a **no-scheduler / no-claim** mode.
- Hard rule: process that is not `atlas.service` must not `REGISTER` schedules or `CLAIM` live tasks.

**F5 — idempotent schedule registration**

- Durable unique key / upsert on schedule identity.
- Boot 100× regression test: enabled schedule count invariant.
- Re-check after every deploy: no new duplicate `task_type` clusters.

**Acceptance:** Reboot thrice → schedule counts identical; no second kernel claiming tasks during `pytest` or `atlas status`.

#### Phase 4 execution log (2026-10-08 ~22:50 IST)

| Change | Where |
|---|---|
| Identity lookup | `ScheduleRepository.find_by_identity` + `exists_task_type` |
| `register_schedule` → `ensure_schedule` | `atlas/scheduler/schedules.py` |
| Ephemeral kernel | `build_application(ephemeral=True)` — no system ensure, `seed_tick_on_start=False`, scheduler `workers=0` + `mutate_queue=False`, skip program reconcile |
| CLI path | `atlas/cli/main.py` `_cli_app` → `ephemeral=True` |
| Retention freeze | bootstrap calls retention ensure **only if** `cfg.retention.enabled` |
| Tests | `tests/test_schedules.py` (F5 cases) + `tests/test_f1_f5_schedule_idempotency.py` (100× boot invariant) — **24 passed** |

**Live verify (ephemeral build+start against prod DB):**

| Metric | Value |
|---|---|
| Schedules total / enabled | **450 / 75** (unchanged across ephemeral start) |
| `ensure_schedule(host_guard_tick)` ×2 | same id; total stayed 450 |
| Scheduler start log | `scheduler start skipped (ephemeral — no claim/recover)` |
| Pre-F5 duplicate stock (still present; not deleted) | `worker_tick` 285 (70 en), system ticks ~28–32 each (1 en), `retention_prune` 12 (**0 en**) |

Optional later: DB unique index on identity (cleanup of duplicate stock first). Do **not** re-enable `retention_prune` until 7-day freeze ends.

---

### Phase 5 — Classify 69–71 `worker_tick` schedules — **COMPLETE** (2026-10-08)

For each enabled `worker_tick` payload:

| Question | Output |
|---|---|
| Does worker_id exist in current config? | yes/no |
| Last successful run? | timestamp / never |
| Owner / mission still valid? | yes/no |
| Still needed? | ACTIVE / STALE / ORPHANED / UNKNOWN |

Disable/delete only STALE/ORPHANED with logged reason. Prefer Atlas self-maintenance job once J0 path is trusted.

#### Phase 5 execution log (2026-10-08 ~22:59 IST)

| Metric | Before | After |
|---|---|---|
| Enabled `worker_tick` | **70** | **30** |
| Classification | 70 looked “running+active” | **30 ACTIVE / 40 STALE / 0 ORPHANED** |
| Action | — | Disabled 40 schedules; paused 40 workers |

**Rule applied:** one enabled tick per `(program_id, worker_type)`. Keep oldest mission’s best-ticking worker; mark extras **STALE** (program-reconcile duplicates — e.g. `investor_reports` was 7×).

**Evidence:** `/data/atlas_data/ops/phase5_worker_tick_2026-10-08/` (`classification.json`, `actions.json`, `VERIFY.md`).

Duplicate missions remain `active` with paused workers (no mass archive this phase). `paper_trading` intentionally keeps **2** ACTIVE under distinct scopes.

---

### Phase 6 — J1 unified capability registry — **COMPLETE** (2026-10-08)

Make one registry the source of truth for:

```
CAPABILITY REGISTRY
   ├── Job Engine
   ├── Agent Kernel
   ├── Planner
   ├── Cognitive Core
   └── Research
```

Kernel must be able to name and invoke at least: `sql`, `logs`, `git`, `code` (read paths), plus existing tools — without a second hard-coded list.

**Acceptance:** Agent Kernel plan for a DB question includes a real `sql` step with args; no parallel orphan catalog.

#### Phase 6 execution log (2026-10-08 ~23:10 IST)

| Change | Where |
|---|---|
| Unified catalog | `build_unified_catalog(capabilities, tools)` — investment ladder + **live** `sql`/`logs`/`git`/`code`/`python` only when registered |
| Bus holds catalog | `EvidenceBus.replace_catalog` / `sync_from_registries` |
| Bootstrap bind | `agent_kernel_worker.bind_live_toolbox(app.capabilities, app.tools)` after plugins |
| Logs capability | `logs_plugin` registers `CAP_LOGS` + `LogsCapability` contract |
| Planner grounding | `_ensure_sql_step` for DB-shaped open objectives; toolbox steps require live catalog |
| Tests | `tests/test_j1_capability_registry.py` (+ agent kernel / J0 regression) |

**Live verify:** ephemeral boot catalog includes `sql`/`logs`/`git`/`code`; DB objective plans a `sql` step with non-empty `args.sql` + `source=atlas`.

Evidence: `/data/atlas_data/ops/phase6_j1_2026-10-08/`.

---

### Phase 7 — Blind North-Star self-diagnosis (milestone gate) — **COMPLETE** (2026-10-08)

Operator gives **only** the natural-language objective (no tool list).

**Pass (Autonomous Self-Diagnosis v1):**

| ID | Criterion |
|---|---|
| A | Operationally healthy: PG on `/data`, F1/F5 done, workers classified, no unexplained mass failures |
| B | J1 done; Kernel discovers SQL/logs/code |
| C | Investigation uses ≥2 different capabilities; revises plan if needed; verifies |
| D | Honest outcome if stuck: FAILED/CAPABILITY_GAP with tried/succeeded/failed/why/next |
| E | Persists as experience; later tick can continue |
| F | At least one `next_question` not supplied by operator |
| G | One genuine learning **candidate** (not synthetic) |
| H | Later task consumes that learning (C8 light) — may be Phase 8 |

Until A–E pass, do **not** expand market-intelligence surface area.

#### Phase 7 execution log (2026-10-08 ~23:17 IST)

**Operator objective (verbatim, no tool hints):**

> Investigate why Atlas experienced a large number of scheduled-task failures today. Determine the root cause, verify using available evidence, and report what should be done.

| Gate | Result | Notes |
|---|---|---|
| A | **PASS** | PG at `/data/postgresql/18/main`; `retention_prune` enabled=0; worker_tick enabled=30 |
| B | **PASS** | Live catalog includes sql/logs/git/code |
| C | **PASS** | Succeeded **sql** + **logs** (job_step execution via ToolRegistry) |
| D | **PASS** | status=SUCCESS; attempted/succeeded/failed/reason/next_action populated |
| E | **PASS** | Experience + lineage written; second tick loaded state |
| F | **PASS** | Derived next_question (retention freeze / unique index) — not operator-supplied |
| G | **PASS** | `ops_learning_candidate` from measured failure rows |
| H | **PASS** (Phase 8) | Ops belief cited on identity-first `ensure_schedule` |

**Enabler shipped for the gate:** Agent Kernel now **executes** `job_step`s through the live ToolRegistry (was plan-only stub). Ops objectives ground to sql+logs without research fillers.

**Evidence:** `/data/atlas_data/ops/phase7_north_star_2026-10-08/` · tests: `tests/test_phase7_north_star.py`

---

### Phase 8 — Cognitive loop consumes self-diagnosis (after v1) — **COMPLETE** (2026-10-08)

Wire experience → pattern → hypothesis → experiment → candidate → belief → **behavior change**.

Example desired learning:

> “Resource registration must be idempotent.”

Later registration path checks identity first. That is C8 proof.

Nightly cognition / cognitive cycle must actually **run** (today’s report: often “not run yet”) — fix scheduling/windows, don’t add new market features to paper over it.

#### Phase 8 execution log (2026-10-08 ~23:23 IST)

**Path chosen (ops, not a new market subsystem):** Phase 7 `ops_learning_candidate` → accepted ops belief → later `ensure_schedule` identity reuse **cites** that belief.

| Step | Result |
|---|---|
| Nightly cognition | Already `ran=true` for 2026-10-08 (no schedule fix needed) |
| Consume candidate | `AK-44aaa15d4cd7` → `B-atlas_ops-schedule_registration` |
| Belief statement | Schedule registration must be idempotent by identity… |
| Later path | `ensure_schedule(host_guard_tick)×2` → **same id** + consume receipt |
| G8 | **PASS** |

**Code:** `atlas/agent_kernel/ops_learning.py`; `ScheduleService.bind_ops_learning` / `_cite_identity_reuse`; bootstrap wires `data_dir`.

**Evidence:** `/data/atlas_data/ops/phase8_c8_2026-10-08/` · tests: `tests/test_phase8_c8_ops_consume.py`

**Honesty:** Ops belief is `ACCEPTED_OPS` / provisional — changes registration/diagnosis context, **not** a market L5 lesson and never sizes trades. FNO cognitive cycle remains separate (0 market candidates today).

---

## 5. Explicit “do not do” list

1. Do **not** delete `/var/lib/postgresql` manually before switch+verify.
2. Do **not** `TRUNCATE` firehose tables before generators are fixed.
3. Do **not** remove Ollama models.
4. Do **not** delete knowledge/experiences/learning/trading history for space.
5. Do **not** move Postgres to `/d` in this plan (reserve `/d`; primary target is `/data`).
6. Do **not** enable live retention until Phase 1 + handler + single schedule.
7. Do **not** build another market-intelligence subsystem before J1 + blind North-Star.
8. Do **not** treat FEA counts / E[R] scores as Atlas intelligence metrics.
9. Do **not** commit/push unless explicitly asked.
10. Do **not** celebrate investigation counts while mass scheduler failures remain unclassified.

---

## 6. Intelligence metrics (what we will score after this plan)

**Count as Atlas intelligence:**

- Encounter unknown problem → choose tools → investigate → verify → record → change future behavior
- Productive state transitions under blockage
- Correct refusal to call activity “learning”
- Self-diagnosis that survives reboot and becomes experience

**Do not count as Atlas intelligence:**

- Scheduled task volume
- FEA acquisition counts
- Email volume
- Market E[R] / challenger scores alone
- “Steps done” without productive evidence

---

## 7. Acceptance scoreboard — Autonomous Self-Diagnosis v1

| Gate | Owner | Done when | Status |
|---|---|---|---|
| G0 | Ops | Failure storm classified; `retention_prune` not generating new fails | **DONE** |
| G1 | Ops | Postgres on `/data/postgresql/18/main`; `/` has ≥35G free vs today; Atlas healthy | **DONE** |
| G2 | Eng | F1: CLI/tests cannot claim/register against live scheduler | **DONE** |
| G3 | Eng | F5: idempotent schedules + 100-boot invariant test | **DONE** |
| G4 | Ops+Atlas | worker_tick classified; orphans disabled | **DONE** |
| G5 | Eng | J1: Kernel uses shared registry including sql/logs | **DONE** |
| G6 | Eval | Blind North-Star diagnosis passes C–F | **DONE** (2026-10-08) |
| G7 | Eval | One learning candidate from that investigation | **DONE** (2026-10-08) |
| G8 | Eval | Behavioral consumption (can slip to immediately-next milestone) | **DONE** (ops C8, 2026-10-08) |

---

## 8. Suggested working session order (operator + agent)

| Step | Downtime? | Who |
|---|---|---|
| 1. Agree this plan | No | Both |
| 2. Phase 1 disable `retention_prune` ×7 | No | Agent (SQL) + operator confirm |
| 3. Phase 0 baseline capture | No | Agent + sudo |
| 4. Phase 2 PG move | **Yes** | Operator sudo; agent provides commands & verifies |
| 5. Watch 1 market session / evening mail | No | Operator |
| 6. Phase 3 retention dry-run then cautious enable | No | Agent |
| 7. Phase 4–6 engineering | No | Agent (F1/F5/J1) |
| 8. Phase 7 blind test | No | Operator writes objective only |

---

## 9. Locked decisions (operator 2026-10-08)

| # | Decision | Lock |
|---|---|---|
| 1 | Target `/data/postgresql/18/main`; `/d` reserved | **YES** |
| 2 | Downtime only off-market; copy→verify→switch→verify→delete | **YES** |
| 3 | Fresh PG dump immediately before stop | **YES** |
| 4 | Retention disabled 7 days after migration (temporary freeze) | **YES** |
| 5 | Investigate 50,841 and 13,191 together | **YES** |
| 6 | Cursor 15G leave alone for now | **YES** |
| 7 | Ollama models — do not remove | **LOCKED** |
| 8 | No commit/push until operator asks | **LOCKED** |

### Phase 1 execution log (DONE)

**When:** 2026-10-08 19:42–19:44 IST  
**Evidence:** `/data/atlas_data/ops/phase1_retention_prune_2026-10-08/`

| Action | Result |
|---|---|
| Snapshot all `retention_prune` schedules (11 rows; 7 enabled) | `evidence_before.json` |
| `UPDATE … SET enabled=false` on 7 enabled rows | 7 IDs disabled |
| Confirm enabled count | **0** (`evidence_after.json`) |
| Cancel pending `retention_prune` tasks | 6 cancelled (`pending_cancelled.json`) |
| Delete failed `task_runs` rows? | **No** — preserved for diagnosis |
| New `retention_prune` fails (last 15m / 2h after disable) | **0 / 0** |

Disabled schedule IDs:

```
219fc6d4-436d-4470-bd67-18dae78d0185
0e3a64cd-5c48-4802-9693-86e552a695a3
55f06a2a-9fa1-4f2c-9be3-65141b038a56
ededd6fd-3cf4-4d26-a94a-9b04f8fae410
efaa0e50-b2da-4f38-8708-eae809e00ba1
5b36d250-0e0c-4fbd-b517-0689cdf17e90
10878e04-eb4f-4a1d-9a1f-2cf24ec313fb
```

### Classification: 50,841 vs 13,191 (same storm)

Treat as **two observations of one generator**, confirmed by stock query:

| Observation | Count | What it is |
|---|---|---|
| Report “permanently failed scheduled tasks” | **~50,841** | Matches failed **`task_runs`** stock dominated by `retention_prune` (snapshot timing) |
| Live stock `task_runs` failed where `task_type=retention_prune` | **51,523** | Same class; grew slightly since the report |
| Today’s failed runs (recheck earlier) | **13,191** | Subset of that storm for 2026-10-08; error = `no handler registered for task_type 'retention_prune'` |
| `scheduler.tasks` with `status='failed'` | **463** | Different metric — do **not** confuse with the 50k |

**Causal chain (preserved, not pruned):**

```
retention_prune code registered as schedule (O6)
 → non-idempotent registration → 7 enabled duplicates (+ 4 already disabled)
 → running Atlas process had no live handler for retention_prune
 → every tick: "no handler registered"
 → 51,523 failed task_runs (13,191 of them dated today in earlier count)
 → DB growth / report KPI inflation
```

Secondary failure classes in stock (much smaller, do not explain 50k):

| task_type | failed runs |
|---|---|
| `worker_tick` | 1,631 |
| `embed_document` | 177 |
| `schedule_tick` | 34 |
| `lab_loop0_s11_canary` / `provider_health_tick` | 32 each |
| other | <30 each |

2-day sample also shows older “no handler registered” bursts for several tick types (second-kernel / F1 signature) — relevant to Phase 4, not the 50k mass.

### Phase 2 execution log — SWITCH COMPLETE (2026-10-08 20:23–20:29 IST)

| Step | Result |
|---|---|
| Fresh dump | `atlas_atlas_20261008_141816.dump` 12G |
| rsync | **42,895,973,379 bytes exact match** both sides (~3 min @ 227 MB/s) |
| `data_directory` | **`/data/postgresql/18/main`** (active) |
| systemd drop-in | `RequiresMountsFor=/data/postgresql/18/main` installed |
| Old dir aside | `/var/lib/postgresql/18/main.pre_move_20261008_145348` (**still on `/`**) |
| Extensions | pgcrypto, plpgsql, vector — present |
| Row counts | positions 2, trades 1234 preserved; tick tables continuous |
| Atlas | active PID 86155, API `:8000` (401 without bearer = up), PG `:5432` |
| `/v1/health` 401 | Expected (auth required) — not a failure |
| **`/` free space** | After delete-old (20:39 IST): **52G used / 41G avail (56%)** — ~40G recovered |
| `/data` | **145G** used (+40G live PG), 322G free |

**Post-switch incident (fixed immediately):** Atlas boot re-registered a **new** enabled `retention_prune` (`86202483-…`) because `list_schedules()` is capped at **200 rows**, so the existence check missed the 11 disabled rows. Re-disabled; 0 new failures. Bootstrap patched: only register if `cfg.retention.enabled`, and existence query is by `task_type` without the 200 limit. **Needs Atlas restart to load the patch** (or survives until next restart).

**Delete-old** (frees ~40G on `/`). `sudo` strips env vars set *before* it — use one of:

```bash
sudo env CONFIRM_DELETE=1 bash /data/atlas_data/ops/pg_move_2026-10-08/phase2_migrate.sh delete-old
# or
sudo bash /data/atlas_data/ops/pg_move_2026-10-08/phase2_migrate.sh delete-old --confirm
```

After delete, `/` should drop by ~40G.

---

## 10. Bottom line

Atlas has moved from islands → Kernel → closed-loop labs → ops health → self-inspection → grounded/honest planning. That is real progress.

The correct next move is **not** another sophisticated subsystem. It is:

```
Stop failure storm
 → Move Postgres to /data (keep history, keep Ollama)
 → Fix F1/F5
 → Classify worker_tick
 → Complete J1
 → Blind North-Star self-diagnosis
 → Let cognitive loop consume that experience
 → Prove one behavioral change
```

When that passes, the architecture is mature enough for C0–C9 to become genuinely autonomous.

---

## Appendix A — First SQL for the 50,841 / failure classification

```sql
-- Adjust date / status names to match schema used by the Oct 8 report.
SELECT task_type,
       left(coalesce(error,''), 120) AS err,
       count(*) AS n,
       min(started_at) AS first_seen,
       max(started_at) AS last_seen
FROM scheduler.task_runs
WHERE status = 'failed'
  AND started_at >= current_date - interval '2 days'
GROUP BY 1, 2
ORDER BY n DESC
LIMIT 50;

SELECT task_type, enabled, count(*)
FROM scheduler.schedules
GROUP BY 1, 2
ORDER BY enabled DESC, count(*) DESC;
```

## Appendix B — Dual numbers discipline

Always report separately:

- **Generator health** (new failures per hour)
- **Stock of historical failures** (total failed rows / “permanently failed” report KPI)

Cleaning history without fixing generators recreates the disk incident. Fixing generators without moving Postgres leaves `/` one bad week away from another outage.
