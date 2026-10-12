# 2026-10-06/07 — What was built, and what it changes about Atlas

A single record of one working session. Written for the operator: every item says what
it **does**, what it **changes**, and what it **does not** solve.

Companion documents: `2026-10-06_NORTH_STAR_AUDIT.md` (§23–26 cover this work) and
`2026-10-06_OPERATIONAL_HEALTH_LOOP0.md` (§7–8c cover the incidents).

**Deployed:** PID 363274, `2026-10-08 06:41:35 IST`. All code below is live.

---

## 1. The one-paragraph version

Atlas could not look at itself. It had no way to query its own database or read its own
logs, and its job planner timed out on every objective and silently fell back to a
one-step plan. Both are fixed: Atlas now reads its own Postgres and logs under
read-only, redacted, bounded access, and the planner produces real multi-step plans with
executable SQL in 110–186 s on CPU. Along the way three production defects surfaced — a
frozen scheduler clock, a 100%-full root filesystem, and 184 duplicate schedules — and
the last of those turned out to be the root cause of the first two.

**The honest bottom line:** the end-to-end "investigate yourself and report" test still
does not produce a finished answer. Every link in the chain now either works or fails
loudly, which is the precondition for it working, but it is not the same as working.

---

## 2. Capabilities Atlas did not have before

### J0a — Atlas can read its own database
`atlas/sql/postgres_backend.py`

**Adds:** `source="atlas"` in any `sql.query` call now reaches Atlas's own PostgreSQL.
`source="atlas.scheduler"` scopes to one schema. Implemented behind the `SQLBackend`
protocol that already existed, so nothing else changed shape.

**Changes:** before this, asking Atlas "why did your scheduler fail today, use the
database" was *structurally impossible* — `sql.query` only spoke SQLite inside a
sandbox, so Atlas silently ran a web search instead. A system that cannot query its own
state cannot diagnose itself.

**Safety, four layers:** the existing `is_read_only` statement guard runs before the
backend is reached; the session is opened `READ ONLY` so a guard bypass still cannot
write; `statement_timeout` is set per query so a bad join cannot pin a connection the
live service needs; credential catalogs (`pg_authid`, `pg_shadow`, …) are refused and
secret-looking *column names* are redacted. `token_count` and `token_len` are
deliberately exempt — sizes are diagnostics, not secrets.

**Immediate payoff:** the first query found something the logs could not show. The
set-serialization error had occurred **1,523** times, not the ~51/day estimated from log
sampling, and the failing task type was `worker_tick` — which §5 of the health doc had
recorded as "could not be identified, because the log omits worker IDs". The database
had the answer all along.

### J0b — Atlas can read its own logs
`atlas/plugins/logs_plugin.py`

**Adds:** `logs.list`, `logs.tail`, `logs.search`, confined to `paths.logs`, bounded at
2,000 lines / 500 matches / 2,000 chars per line.

**Changes:** redaction is applied to **every** emitted line, not optionally. Logs are the
one place a credential appears by accident, and their whole purpose is to be quoted into
reports and prompts. Rule order is load-bearing: the auth-scheme pattern must run before
the key/value pattern, or `Authorization: Bearer <token>` redacts the word "Bearer" and
leaves the token.

---

## 3. The planner: from "always fell back" to real plans

### J2 — grammar-constrained decoding
`atlas/jobs/planner.py`

**Adds:** a JSON schema derived from `_VALID_INTENTS` and `CAPABILITY_CATALOG` (so it
cannot drift from the validator), passed as `format` to Ollama. `args` is required.
`planner_timeout` 60 → 180 s, `num_predict` 512 → 700.

**Changes:** this is the measurement that mattered. Same prompt, same model, CPU-only:

| config | time | tokens | usable? |
|---|---|---|---|
| unconstrained, 512 | 88.8 s | 512 | no — prose |
| unconstrained, 1536 | 277.8 s | 1536 | no — still narrating |
| **schema-constrained, 700** | **46.8 s** | **233** | **yes** |

**Token cost, not token rate, was the binding resource.** Unconstrained, `qwen3:4b`
narrates past 1536 tokens without ever emitting the array. The fix was never a bigger
model or a GPU; it was not letting the model write prose.

### J5 — the planner stops guessing column names
`atlas/sql/schema_digest.py`

**Adds:** before planning, the real columns of the tables an objective is about are
resolved and put in the prompt. Selection is deterministic token overlap — no second LLM
call, because a round trip costs ~111 s here and a catalog query costs 0.24 s. Capped at
1.8 KB; returns nothing when the catalog is unreachable, so it can never make planning
worse.

**Changes:** and it corrected my own diagnosis. The old prompt listed the columns of
`scheduler.task_runs` and `scheduler.tasks` **in one sentence**, and the model merged
them, emitting `task_type` on the wrong table. Hand-written schema hints in prose do not
just go stale, they *induce* this failure. That sentence is deleted and a test asserts it
never returns.

**Also adds `_repair_intent`:** with the schema in the prompt the model produced correct
SQL but labelled the steps `recall`, which would have handed queries to memory lookup and
silently produced nothing. A step's arguments are unambiguous evidence of what it is, so
SQL now implies `sql_query`/`sql` and code implies `run_python`/`python`. Deterministic,
free, and it cannot time out — which matters when the alternative is three minutes per
attempt.

### J6 — the planner stops guessing data values

**Adds:** a bounded, recency-windowed, redacted sample of the values that actually occur
in the low-cardinality columns an objective asks about.

**Changes:** three things had to be measured rather than assumed. Sampling *order*
mattered more than size — an unordered bounded scan returns the oldest rows, so the first
version showed only months-old errors and the model never saw today's. Ordering cost
27.8 s because `scheduler.task_runs` has no index on `error`; a 7-day window cost 12.4 s;
so it is **cached** with a 15-minute TTL — 12.4 s cold, **0.19 s warm**. Only successes
are cached, because a failed probe and an empty column are indistinguishable at the call
site and caching the failure would pin a transient hiccup into the prompt.

**Result, stated precisely:** the grounding reaches the model and it uses the values. One
run emitted `WHERE task_type IN (...)` copying all six sampled values verbatim and
returned **339 rows — the first non-empty query result of the whole exercise.** Another
quoted the real error text verbatim in a reasoning step. But on the error column the
model still sometimes paraphrases the objective into a `LIKE` pattern. The prompt now
forbids that explicitly; that instruction is **untested against the model**.

### J3 — a step that produced nothing no longer reports success
`atlas/jobs/service.py`, `atlas/services/assistant_service.py`

**Adds:** `productive` and `gap_reason` on `_Outcome`. Three handlers set them: a SQL
step with no `sql`, a SQL step whose query matched no rows, and a `recall` that remembers
nothing.

**Changes:** job `b370b60a` logged `completed — 4/4 step(s) done, failed: 0` while its
answer was four no-op replies concatenated and its SQL step ran for 1.1 milliseconds
without opening a connection. Now a non-productive step takes a third path: it reuses the
retry ladder (a wrong predicate is often right on the second attempt), and on exhaustion
lands in `failed` with `error = "no usable result: <reason>"`, so the **job** reports
`failed` instead of claiming success. `_finalize` collects a `gaps` list naming each
step, capability, reason and attempt count, so "failed" is actionable rather than merely
negative.

Chat is unaffected — it only reads `answer`, so "the query returned no rows" is still a
fine reply to a person. There is deliberately no new `gap` status: the DB
`job_steps_status_check` permits six values and a seventh would need a migration
deployed in lockstep.

---

## 4. Three production defects

### F2/F3 — the recurring clock can no longer be killed
`atlas/scheduler/service.py`, `atlas/repositories/task_repo.py`, `atlas/kernel/bootstrap.py`

**The incident:** `atlas status` boots a second kernel, which claims tasks it has no
handlers for, fails them permanently, and kills `schedule_tick`. All 107 schedules froze
for 45 minutes while the service reported healthy. 164 occurrences since 2026-07-11.

**Adds:** an unknown handler now *releases* the task back to pending without consuming a
retry — not knowing how to run a task is this process's limitation, not the task's fault.
And because a frozen `schedule_tick` cannot repair itself through a schedule, the
scheduler's own worker loop re-seeds the clock after a sustained idle window, which is the
only place recovery can live without depending on the thing it repairs.

**Proved in production, by accident.** A test run of mine claimed two live `worker_tick`
tasks; the handler was missing; both tasks show `status=completed` with
`retry_count=0`. Before F3 that was the 45-minute outage.

### O6 — the root filesystem hit 100%
`atlas/ops/retention.py`

**The incident:** 796 MB free on `/`, Postgres failing queries with `DiskFull`. Atlas's
database was 40 GB, of which three tables held **~37 million rows each** since
2026-07-11.

**Root cause:** `config/defaults.yaml` has carried `audit: retention_days: 90` from the
beginning. Grepping the codebase for `retention_days` returns exactly one hit — the
declaration itself. **Nothing read it.** The scheduler tables had no setting at all. It
would not have helped anyway: the oldest row was 88 days old against a 90-day window.

**Adds:** a `RetentionManager` registered as `retention_prune` on an hourly schedule.
Dry-run by default (`retention.enabled: false`) because this deletes history
irreversibly — it reports counts at WARNING and changes nothing. Batched at 20 K rows per
transaction, because one `DELETE` over 37 M rows would hold a transaction open for the
whole run and write WAL faster than it clears, which on a full disk is as likely to hurt
as help. Only `scheduler.tasks` is pruned, since `task_runs.task_id` is
`ON DELETE CASCADE`. Only `completed` and `cancelled` are eligible: `pending`/`running`
are live work and `failed` rows are the evidence that diagnosed the F3 outage.

**A second finding inside it:** all 37,329,934 `audit.events` rows are `status='pending'`
with `processed_at` NULL. **Nothing has ever consumed an audit event.** 99% are
`TaskCompleted`. The obvious guard `processed_at IS NOT NULL` was therefore a permanent
no-op, so eligibility keys on event *type* instead, listing the four telemetry types
explicitly so `DecisionMade` and any future type are retained by default.

**Corrected recommendation.** I first proposed enabling the prune. The operator pushed
back — *"i see ~370gb available … i do not want to lose anything important"* — and was
right. `/d` is a **285 GB volume that is 1% used**, 270 GB idle, which I had not looked
at. Atlas does not have too much data; Postgres is on the one small volume. **The correct
fix is to move the Postgres data directory to `/d` or `/data`**, which keeps every row
and frees 40 GB on `/`. Retention is hygiene, not rescue, and stays disabled.

For the record, pruning would have been safe: **36,514,453 of the 36.8 M eligible rows
are `schedule_tick` with an empty payload `{}`** — bare clock ticks containing no
information.

### F5 — 184 duplicate schedules, and the root cause of the other two

**Found at the very end,** when the new `retention_prune` schedule registered **five
times** and inherited the bug.

Schedule registration is not idempotent, so every kernel boot — including every test run
and every `atlas status` — adds another copy:

| task_type | enabled before | distinct payloads | enabled after |
|---|---|---|---|
| `fundamental_summary_publish` | 24 | **1** | 1 |
| `lab_loop0_s11_canary` | 24 | **1** | 1 |
| `provider_health_tick` | 24 | **1** | 1 |
| `embed_backfill` | 21 | **1** | 1 |
| `host_guard_tick` | 20 | **1** | 1 |
| `retention_prune` | 5 | **1** | 1 |
| `worker_tick` | 71 | 71 | 71 — left alone |

**This closes the loop on the whole session.** One distinct payload and one interval
across all duplicates means every copy was doing identical redundant work — roughly 24×
the intended tick rate. That is why there are 36.5 M `schedule_tick` rows, which is why
the database reached 40 GB, which is why the disk filled. The disk-full incident was a
*symptom* of F5.

**Done:** 108 redundant schedules disabled (keeping the oldest of each, which preserves
behaviour exactly). Enabled schedules went from **185 → 77**.

**Not done:** `worker_tick` has 71 *distinct* `worker_id` payloads — stale per-worker
entries for workers that no longer exist. Needs care, left for the operator. And the
registration code itself is still not idempotent, so duplicates will return on the next
multi-kernel boot. F1 (below) is the real prevention.

---

## 5. What is still open

| item | why it matters |
|---|---|
| **Move Postgres to `/d`** | The actual fix for the disk. 270 GB idle. Loses nothing. Needs root + brief downtime. |
| **F1** — CLI/tests boot a second kernel | The cause of F3's outage *and* F5's duplicates. F2/F3 contain the damage; F1 prevents it. |
| **`worker_tick` schedules** | 71 enabled, one per historical worker. Needs judgement about which are live. |
| **Stop the audit firehose** | A `TaskCompleted` row per tick that nothing reads is 36.5 M rows. Retention mops up; not writing it is the cure. |
| **J1** — unify the capability registry | All of §2 is reachable from *jobs* only. The Agent Kernel's bus still has 10 hard-coded entries and cannot name `sql`, `logs`, `git` or `code`, so the autonomous loop cannot use any of it. **This is the highest-leverage item left.** |
| **End-to-end north-star answer** | Still none. The plan is right, the queries execute; the final synthesis is not there yet. |

---

## 6. Verification

**Tests:** 60 new — `test_self_inspection_j0.py` (22), `test_planner_schema_grounding_j5.py`
(31 incl. J6), `test_honest_completion_j3.py` (11), `test_retention_o6.py` (18). 184 pass
across every subsystem touched. Lints clean.

**Regression check:** the full suite reports 46 failures. These were verified **not mine**
by running the identical 46 test IDs in a pristine `git worktree` at `HEAD` and getting
the same result. They are a pre-existing `WorkerManager._config_repo` attribute error,
Ollama timeouts caused by my own planner runs saturating the 2-lane limit, and
market-closed states in the phase e2e tests.

**Live health after deploy:** PID 363274, active, 0 restarts, 2,336 task runs in 10
minutes, 0 overdue schedules, labs and paper trading ticking, watchdog on its 5-minute
cycle.

**Housekeeping:** a baseline git worktree remains at `/data/atlas_data/tmp_baseline/atlas`
(25 MB, safe to remove — cleanup outside the workspace was blocked). Nothing was
committed or pushed.

---

## Addendum — 2026-10-08: the hourly mail did not know what it was holding

### What the operator saw

```
India equity (swing) [india_equity_learner]
  Cash ₹27,408.50 · holdings unavailable · equity unavailable
  Positions: (none)
```

No P&L line appeared at all. The reasonable reading of this mail is "Atlas has lost
track of its own book". That was not true: `india_equity_learner` held **2 open
positions (COALINDIA.NS qty 19, HBLPOWER.NS qty 13)** in `sim.positions` in Postgres
the entire time. The book was intact; the mail discarded it.

### Root cause

Three separate defects, all in the "timely delivery" path added to keep evening SMTP
from stalling on a 429'd Yahoo feed.

**1. `skip_live_marks` was implemented as "do not touch Postgres".**
`atlas/workers/investor_reports.py` sets `lean = bool(send_evening or send_hourly)` and
passes it as `skip_live_marks`, which gated *two* blocks in `_portfolio_doc`:

- the `ensure_portfolio` block, which resolves `sim_portfolio_id`, and
- the `snapshot` block, which produces positions, holdings, equity and P&L.

The registry stores `sim_portfolio_id: None` for all three labs (the id lives in
Postgres and is resolved per boot). Skipping the first block therefore left `pid` as
`None`, which skipped the second block as a consequence. Everything except `cash`
vanished — and `cash` survived only because it is read from `persona.capital` in the
registry, never from the book. This is why the cash figures looked plausible while
every other number read "unavailable".

The intent was "do not wait on *Yahoo*". The implementation was "do not read
*Postgres*". Postgres is local and these reads measure ~40 ms; Yahoo is the remote,
rate-limited dependency. Only the market-marks fetch is now skipped.

**2. The report omitted the P&L line instead of reporting that it had no P&L.**
`format_three_lab_books_section` emitted the line only `if pnl is not None or tot is
not None`. With both absent the row disappeared, making "today's P&L was not computed"
indistinguishable from "today's P&L was flat". The line is now always emitted, and
`total_pnl` is reconstructed from `realized_pnl + unrealized_pnl` when the
contribution-adjusted metrics step did not run.

**3. A flat, idle book reported its day P&L as unknown.**
`_add_cash_and_pnl_metrics` returned `day_pnl = None` whenever there were no fills and
no marks. For a book with **no open positions**, the day's P&L is exactly zero and is
knowable without any market mark. That case now reports `0.00` with a note.

### Also fixed: a process-global rate gate leaking across data dirs

The Yahoo cooldown fail-fast added earlier in this session called
`get_yahoo_rate_gate()`, which is a **process-global singleton that ignores its
`data_dir` argument** once any caller has bound it. The worker was therefore answering
"is Yahoo cooling down?" for whichever data directory initialised first rather than its
own. It now constructs a `YahooRateGate` bound to `self._data_dir`; because the
cooldown lives in a file that the gate reads on construction, this honors exactly the
same cooldown as the shared instance without depending on construction order. This was
caught by `test_investor_worker_resolves_live_book_after_restart`, which had begun
failing only while the real feed happened to be in cooldown.

### What it changes for Atlas

The hourly and evening mails now report the real book, valued at average cost and
labelled as such, instead of claiming ignorance. Verified live against Postgres:

```
India equity (swing) [india_equity_learner]
  Cash ₹27,408.50 · holdings ₹17,946.45 · equity ₹45,354.95
  P&L today unavailable (market close marks missing) · total -9,645.05
  Positions (2):
    · COALINDIA.NS: qty=19.0 avg=424.55
    · HBLPOWER.NS: qty=13.0 avg=760.0
NIFTY index-proxy (F&O lab) [india_fno_learner]
  Cash ₹113,125.18 · holdings ₹0.00 · equity ₹113,125.18
  P&L today +0.00 · total +13,125.18
India equity (intraday 5m) [equity_intraday_learner]
  Cash ₹49,455.43 · holdings ₹0.00 · equity ₹49,455.43
  P&L today +0.00 · total -544.57
```

No strategy, sizing, or order path was touched. This is reporting only.

### Known remaining limitation (stated, not hidden)

For a lab **with open positions**, `P&L today` still reads "unavailable (market close
marks missing)" in the timely path, because the day's move genuinely cannot be computed
without a previous close and today's mark, and the timely path deliberately does not
fetch them. The honest fix is a marks read restricted to the **local durable bars
store** (never triggering a Zerodha/Yahoo fetch); `MarketReader.bars_for` currently
prefers the durable store but may still fall through to the network, so it cannot be
used unmodified here. Not attempted in this pass.

### Tests

`tests/test_lab_book_visibility.py` — 13 new tests covering: the timely path resolves
`sim_portfolio_id`, reports holdings/equity/positions/total P&L, still skips the market
marks, and labels the valuation honestly; the full path is unchanged; the P&L line is
always present; `total_pnl` is reconstructed but never overwritten; a flat idle book
reports zero while a held book without marks stays honest about not knowing.

`tests/test_cognitive_c0_nightly_cognition.py` — fixed a wall-clock dependency in
`test_tick_outside_all_windows_still_reports_idle`. It read `datetime.now()`, so run
inside the real 07–10 morning window it took the `send_morning` branch instead of the
idle branch it claims to test. It now closes every window through config. Note the
worker reads these bounds as `cfg.get(...) or <default>`, so a `0` is falsy and
silently restores the real window — the test uses non-zero impossible hours.

Suite status for the touched area: **503 passed, 7 failed**, and all 7 failures were
confirmed to be pre-existing — 6 reproduce identically on a pristine `HEAD` worktree,
and the seventh (`test_phase_d_e2e`) never imports `investor_reports` or the report
formatter and fails on `market nse_equity closed (before_open)` at 07:30 IST.
