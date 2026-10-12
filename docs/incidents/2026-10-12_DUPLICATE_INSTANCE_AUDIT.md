# Duplicate-instance window audit (OI-DELI0 Step 0A)

> **Window:** 2026-10-12 **18:36:19 → 20:39:17 IST**  
> **Status:** complete (read-only)  
> **Plan:** [`docs/2026-10-12_DECISION_EVIDENCE_LEARNING_INTEGRITY_PLAN.md`](../2026-10-12_DECISION_EVIDENCE_LEARNING_INTEGRITY_PLAN.md) §9.1  
> **Writes:** this document only. No Atlas restart. No `/data/atlas_data` modifications.

---

## Summary

Two Atlas control planes overlapped for ≈ 2 h 3 m. A hand-started `atlas serve` held port 8000 after the original systemd PID 1928 was killed; systemd (`Restart=always`) then launched **172** further copies that each started scheduler, workers, and recovery, logged “Atlas is ready”, then died on `Errno 98` (median lifetime ≈ 43 s). Containment at 20:39:17 left systemd PID **1233554** as the sole instance.

**Side effects are not empty.** Confirmed from journal and files: a crash-loop copy sent the 20:00 hourly investment email; the 19:00 hourly mail was never recorded; ≈ 1,418 data-dir files were modified in the window (including 865 ops-consume receipts, one per crashed launch × five schedule identities); scheduler recover/abandon cycles ran repeatedly. **No fill / BUY / SELL / paper-trading activity appears in the journal for this window.**

**Cannot determine from this agent environment:** Postgres table writes (`scheduler.tasks`, `system.recovery_runs`, `sim.trades`, `decision.decisions`, …). Host Postgres is live (Atlas holds TCP sessions), but this execution namespace cannot open `127.0.0.1:5432` or `/var/run/postgresql`. DB checks below are therefore **cannot determine**, not “no effect”.

---

## Timeline (IST)

| Time | Event |
|------|--------|
| 18:36:09 | PID 1928 (prior systemd main) begins shutdown |
| 18:36:19 | systemd: Main process exited `signal/KILL`; service failed |
| 18:36:19+ | Hand-started `atlas serve` holds `:8000` (PID cited historically as 853080; stop logged in `atlas.log.1` at 20:39:16–20:39:46) |
| 18:36:27 | First systemd relaunch (`Started atlas.service`); crash loop begins |
| 18:36:29–35 | Typical failing copy: services start (incl. `scheduler`, `schedules`, `workers`, `recovery`) → “Atlas is ready” → `Errno 98` |
| 18:37:05 onward | Repeated `drain timeout (30s): N task(s) still running, abandoning` |
| ≈ 19:07+ | Intermittent `recovered 1 interrupted task(s)` / `TasksRecovered` |
| 20:05:25 | **Effect:** crash-loop PID **1122916** logs `email sent` — Hourly 20:00 IST for `india_equity_learner` (after its own bind failure at 20:05:18) |
| 20:11:14 | `market/investor_reports_sent.json` mtime (hourly `…\|20` key present; `…\|19` absent) |
| 20:39:16 | Hand instance `KernelStopping` (`atlas.log.1`) |
| 20:39:17 | systemd starts final instance |
| 20:39:26–27 | PID **1233554** starts schedules; “Atlas is ready”; holds `:8000` |
| 20:39:46 | Hand instance “Atlas stopped” |

Counts from `journalctl -u atlas` over the window:

| Metric | Count |
|--------|------:|
| Unique `atlas[PID]` values | 173 |
| `Started atlas.service` | 172 |
| `address already in use` | 172 |
| `Atlas is ready` | 172 |
| `starting service: scheduler/schedules/workers/recovery` (each) | 172 |
| `RecoveryStarted` / `RecoveryCompleted` / `recovery failed` | 172 each |
| `drain timeout` | 124 |
| `TaskCompleted` events | 99 |
| `TasksRecovered` / `recovered N interrupted` | 10 each |
| Lifetime of failing launches | min 8 s, median 43 s, max 48 s; sum ≈ 1.66 h of overlapping boot work |

---

## Check results

Classification per plan: `no effect` · `effect found` · `cannot determine`.

### 1. Boot count, PIDs, lifetimes, exit codes, services started

**Verdict: effect found** (operational incident; expected for F17).

- Evidence: journal timeline above; each failing launch started the full service set (clock → … → health_monitor), including side-effecting `scheduler`, `schedules`, `workers`, `recovery`, before bind failure.
- Exit pattern: `status=3/NOTIMPLEMENTED` after bind failure (172×); original PID 1928 exited `signal/KILL`.
- Final owner after containment: PID 1233554 (verified still sole `atlas serve` at audit time).

### 2. Log lines from non-main PIDs / what duplicates did

**Verdict: effect found.**

- Evidence: 99 `TaskCompleted` events and 10 task-recovery cycles logged under crash-loop PIDs; 124 drain-timeout abandonments; 172 recovery runs that logged `recovery failed (4 steps)`.
- No journal hits in-window for `paper_trading` fills, `BUY`/`SELL` trade mails, or Zerodha token/IMAP processing (see checks 5–6).
- Note: many copies log `Atlas API listening on http://127.0.0.1:8000` *before* `Errno 98`. That line is **not** proof the copy owned the port; bind failure follows. Do not treat “listening” as singleton proof (relevant to Step 0B L2).

### 3. Scheduler / task rows (created, claimed, started, completed, abandoned)

**Verdict: cannot determine** (DB unreachable from agent namespace).

- Attempted: `psql -h 127.0.0.1 -p 5432 -U atlas -d atlas` → connection refused; `/var/run/postgresql` absent in this namespace; `pg_lsclusters` reports cluster “down” here while host process list shows Postgres 18 and Atlas DB sessions.
- Indirect journal evidence (not a substitute for table rows): repeated abandon + recover; `TaskCompleted` under crashing PIDs. **Do not infer “no duplicate claims”.**
- **Remediation SQL (operator, read-only, when host DB is reachable):**

```sql
-- Window in timestamptz (IST offset +05:30)
-- Adjust column names after \d scheduler.tasks / task_runs

SELECT status, count(*)
FROM scheduler.tasks
WHERE created_at >= '2026-10-12 18:36:19+05:30'
  AND created_at <  '2026-10-12 20:39:17+05:30'
GROUP BY 1
ORDER BY 1;

SELECT status, count(*)
FROM scheduler.task_runs
WHERE started_at >= '2026-10-12 18:36:19+05:30'
  AND started_at <  '2026-10-12 20:39:17+05:30'
GROUP BY 1;

SELECT status, count(*)
FROM system.recovery_runs
WHERE started_at >= '2026-10-12 18:36:19+05:30'
  AND started_at <  '2026-10-12 20:39:17+05:30'
GROUP BY 1;
```

### 4. `task_failures.jsonl` rows in the window

**Verdict: no effect** (for this file).

- Path: `/data/atlas_data/investment/ops_health/task_failures.jsonl`
- Evidence: file mtime **2026-10-08 06:40:50 IST**; last lines dated `2026-10-08` (`retention_prune:no_handler`). No rows with timestamps inside the F17 window.

### 5. Mail / investor-report idempotency

**Verdict: effect found.**

| Observation | Evidence |
|-------------|----------|
| Hourly **20:00** mail sent during crash loop | Journal `2026-10-12T20:05:25+05:30` PID **1122916** `atlas.notify.email` subject `[Atlas][india_equity_learner] Hourly 20:00 IST — 2026-10-12` — same PID had `Errno 98` at 20:05:18 |
| Hourly **19:00** missing | `market/investor_reports_sent.json` hourly keys for 2026-10-12: hours 08–18 and **20**; **no `…\|19`**. No journal `email sent` for Hourly 19:00 |
| Idempotency key for hour 20 | Present once (`india_equity_learner\|2026-10-12\|20`); no duplicate keys in the JSON list |
| File mtime | `investor_reports_sent.json` mtime **20:11:14 IST** (inside window) |
| Evening EOD | Sent **before** window (`16:14:26` PID 1928); evening key `india_equity_learner\|2026-10-12` already present |

Interpretation: mail idempotency prevented a *second* 20:00 send after the key was written, but it did **not** prevent a non-primary (bind-failed crash-loop) process from sending the first 20:00 mail. Hour 19 was skipped entirely.

### 6. Zerodha token-mail / IMAP

**Verdict: no effect** (on durable local token/Zerodha state files); IMAP mailbox flags **cannot determine**.

- Journal in window: **0** lines matching `token|imap|zerodha` (case-insensitive).
- File mtimes: **0** paths under `/data/atlas_data` matching `*zerodha*` / `*token*` / `*kite*` / `*imap*` with mtime in the window (including `investment/market_data_provider/token_email_pending.json`, `zerodha_health.json`).
- No evidence of token exchange or “marked seen” local writes. Remote IMAP `\Seen` / UID state was **not** inspected (no mailbox access from this audit).

### 7. Database writes (`sim.trades`, cash, decisions, …)

**Verdict: cannot determine.**

- Same connectivity limit as check 3.
- Journal: **0** fill / BUY / SELL / `paper_trading` trade lines in the window → supports a *hypothesis* of no new fills, but does not prove absence of other DB writes (task rows, recovery_runs, decision packets, etc.).
- **Operator SQL (read-only):**

```sql
SELECT count(*) AS trades_in_window
FROM sim.trades
WHERE created_at >= '2026-10-12 18:36:19+05:30'
  AND created_at <  '2026-10-12 20:39:17+05:30';

SELECT count(*) AS decisions_in_window
FROM decision.decisions
WHERE created_at >= '2026-10-12 18:36:19+05:30'
  AND created_at <  '2026-10-12 20:39:17+05:30';

SELECT count(*) AS cash_movements_in_window
FROM sim.cash_movements
WHERE created_at >= '2026-10-12 18:36:19+05:30'
  AND created_at <  '2026-10-12 20:39:17+05:30';
```

### 8. Data-dir files modified in the window

**Verdict: effect found.**

`find` / mtime scan: **1,418** files with `18:36:00 ≤ mtime < 20:39:17`.

| Bucket | Count | Notes |
|--------|------:|-------|
| `agent_kernel/ops_consume_receipts/` | 865 | Exactly **173 × 5** task types (`host_guard_tick`, `fundamental_summary_publish`, `lab_loop0_s11_canary`, `embed_backfill`, `provider_health_tick`). Cadence tracks the crash loop. Sample receipt `reused_existing: true` (identity-first schedule registration) |
| `investment/decisions/revisits/` | 205 | Decision revisit appends during window |
| `market/bars/` | 188 | Batch mtimes ≈ 20:19–20:28 (living instance / late loop) |
| `investment/decisions/observations/` | 73 | e.g. `news_event` rows with `created_at` inside window |
| `investment/decisions/attributions/` | 40 | Attribution artifacts |
| `investment/switch_learning/india_equity_learner/` | 19 | Switch-learning JSON |
| Other (learning_intelligence, world_state, cognitive, nightly_cognition, self_model, storage linkedin export versions, watchlists, discovery, feed_failures, logs rotate, `investor_reports_sent.json`, …) | remainder | Mixed; includes mail keyfile and cognitive cycle outputs around 20:11 |

Attribution of each file to hand instance vs crash-loop copy is **not** always possible from mtime alone; the 865 receipts matching launch×task identity are the clearest crash-loop fingerprint.

### 9. Ops-health incidents / events in the window

**Verdict: effect found** (absence of detection is the effect).

- File: `investment/ops_health/2026-10-12.json`
- Incidents/events/alerts in that file are all **morning** F&O readiness / Zerodha login (before 05:00 UTC). **None** open or fire in the 18:36–20:39 IST window.
- `open_incidents`: `[]` at audit read.
- Self-diagnosis / ops-health **did not** raise a multi-instance or crash-loop incident for F17.
- Heartbeat/`updated_at` later moved to `2026-10-12T15:33:27+00:00` (21:03 IST) under the healthy post-containment instance — outside the incident window for event purposes.

---

## Remediation items (for §7 status board)

| ID | Item | Priority |
|----|------|----------|
| R1 | Implement Step **0B** single-instance protection before any further deploy/restart | P0 (already gated) |
| R2 | Operator read-only SQL for checks 3 and 7; append results to this doc or §13 when done | P1 |
| R3 | Decide whether to send / note the **missed Hourly 19:00** report (reporting only; do not invent numbers) | P2 |
| R4 | Watchdog / ops-health must detect multi-instance and crash-loop bind failures (feeds L6) | P0 with 0B |
| R5 | Review retention for `ops_consume_receipts` flood (865 files / ~2 h) | P2 |
| R6 | Treat “Atlas API listening” logs as non-proof of port ownership until L2 binds first | doc / 0B |

No ledger/trade remediation identified from journal evidence; **confirm with R2**.

---

## Environment limitation (audit honesty)

This Step 0A run executed inside an agent namespace that:

- can read `/data/atlas_data` and `journalctl -u atlas`;
- can see host PIDs (`atlas serve` 1233554, Postgres 1866);
- **cannot** open host Postgres (`127.0.0.1:5432` connection refused; no unix socket dir visible);
- **cannot** open host HTTP `:8000`.

Therefore “cannot determine” on DB checks is an **access** limit, not evidence of cleanliness.

---

## Exit condition

All nine checks documented with evidence and an explicit verdict. Effects found: mail anomaly (hour 19 miss / hour 20 from crash-loop PID), large file-write footprint, scheduler recover/abandon noise, ops-health non-detection. DB-side confirmation deferred to operator SQL (R2).
