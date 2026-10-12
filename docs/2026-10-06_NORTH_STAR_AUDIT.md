# Atlas North-Star Autonomous Agent Audit

**Date:** 2026-10-06
**Question asked:** "Is Atlas anywhere near what I imagined it to be? If not, what else needs to be done?"
**Method:** first-hand inspection of repo, runtime, Postgres, logs, tests and docs. Every claim below is
backed by an artifact that can be re-checked. No feature proposals were made before the evidence was in.

---

## 0. The honest one-paragraph answer

Atlas is not a script. It is roughly fifteen genuinely good subsystems, 215,173 lines, 446 test files,
and a real operational spine. But it is **not** the thing you set out to build, and the reason is not
that pieces are missing. The reason is that the three parts which would constitute an autonomous agent
— a toolbox, a planner, and a learning loop — exist and **are not connected to each other**. The
toolbox (~40 capabilities including python, sql, git, code-read, web, scholar) is reachable only by
you, from the CLI. The agent loop (Agent Kernel) can only see 10 hard-coded investment capabilities and
cannot reach the toolbox at all. The one component that really is an agent — the LLM job planner — is
structurally unreachable on this hardware, because it needs 90–110 seconds to think and is given 60.
So every autonomous request silently degrades to a single generic web search. You did not write a
script. You built an agent and then, in three separate places, accidentally disconnected its hands,
its memory, and its mind from each other.

---

## 1. Capability status ledger

Status vocabulary as requested: DESIGNED / IMPLEMENTED / TESTED / INTEGRATED / RUNNING / AUTONOMOUS /
PROVEN END-TO-END.

| Subsystem | Status | Evidence |
|---|---|---|
| Scheduler + workers | PROVEN END-TO-END | 41,679 `activity.activity_events`; live ticks at 60/90/120/900s |
| Knowledge / RAG | RUNNING | 406 documents, 3,497 findings, embeddings live |
| Paper trading + sim | PROVEN END-TO-END | 1,199 `sim.trades`, 45,765 `decision.decisions` |
| Decision packets + attribution | RUNNING | 2,941 packets, 1,489 attributions, 8,694 revisits |
| Operational health (Loop 0) | RUNNING (shipped today) | `investment/ops_health/2026-10-06.json`, 22 tests |
| CLI toolbox (~40 verbs) | IMPLEMENTED, human-invoked only | `atlas tools`, `atlas python`, `atlas sql`, `atlas git` |
| Job system (plan → advance) | INTEGRATED but degrades | 52 jobs, 50 steps; see §4 |
| LLM job planner | IMPLEMENTED, **never reached in practice** | timeout evidence, §4 |
| Agent Kernel | RUNNING, single-template | 32 tasks, 1 objective shape, §3 |
| Research service | RUNNING, non-agentic | "planning" = 6 string suffixes, §3 |
| Cognitive Core C0–C9 | IMPLEMENTED + TESTED, unproven in behaviour | `learning.patterns` = 0 rows |
| Belief system | IMPLEMENTED, **not learning** | 1 real revision ever, §11 |
| Experiments (FEL) | IMPLEMENTED + TESTED | promotion to live intentionally gated |
| Missions | RUNNING | 276 missions |
| Goals | DESIGNED only | `system.goals` = **0 rows**; API stores and narrates |
| Cross-domain (eng/personal) | IMPLEMENTED, dormant | 9 of 774 beliefs; 0 agent-kernel tasks |

Two entries deserve emphasis because they are the audit in miniature: `system.goals` has **zero rows**
after months of operation, and `learning.patterns` has **zero rows** after the pattern detector shipped.
The two tables that would prove Atlas sets its own direction and generalises from its own data are both
empty.

---

## 2. The actual architecture (as built, not as designed)

```
                    YOU (CLI / chat / email)
                           │
         ┌─────────────────┼──────────────────────────┐
         │                 │                          │
         ▼                 ▼                          ▼
   ~40 TOOLS          JOB SYSTEM               AGENT KERNEL
   python, sql,       plan_job ──► LLM          uncertainty_queue
   git, code,         planner (23 intents)      + follow_up
   web, scholar,          │                          │
   ocr, browser,          │ 60s budget               │ bus = 10 hard-coded
   download, mail         │ needs 90-110s            │ investment capabilities
         ▲                ▼                          │ (no sql/git/code/shell)
         │          ┌───────────────┐                │
         │          │  FALLBACK:    │                ▼
         │          │  1 generic    │          CAPABILITY_GAP
         │          │  research step│          (21 of 32 tasks)
         │          └───────┬───────┘                │
         │                  │                        ▼
         │                  ▼                  failure_memory
         │           RESEARCH SERVICE          keyed on `generation`
         │           scholar + web only        counter that never
         │           (cannot reach tools) ─────X   increments
         │                  │
         X                  ▼
    NEVER CALLED      report: "no usable
    BY ATLAS          evidence"  → status: completed
    ITSELF
                           │
                           ▼
                 BELIEFS / LEARNING
                 774 beliefs, 753 stuck at
                 `candidate` forever ──X──► no decision ever changed
```

The two `X` marks are the whole problem. Atlas cannot call its own tools, and nothing it learns
reaches anything it later decides.

---

## 3. Stage-by-stage test of the autonomous loop

**Observe → find work.** Works, but through exactly one keyhole. `/data/atlas_data/agent_kernel/state.json`
holds 32 tasks. Sources: `uncertainty_queue` 27, `follow_up` 5. Domains: `investment` 32, everything
else 0. Every single objective matches one of two templates:
`"Acquire evidence for {mos_unknown|roe_missing|debt_missing|pe_missing|fcf_missing} on <SYMBOL>"` and
`"Observe outcome of: …"`. Atlas does not notice problems; it notices five named missing fields.

**Understand the problem.** Absent. `active_hypotheses` in the live state is an array of **20 `None`
values**. The kernel has never formed a hypothesis about anything.

**Plan.** This is the finding I would most want you to see. `atlas/research/service.py`:

```
_VARIANTS = ("", "data", "study", "measurement", "statistics", "review")

def query_plan(objective: str, *, max_iterations: int) -> list[tuple[str, str]]:
    """Deterministic (mode, query) plan: scholar then web, over query variants."""
```

Atlas's generic research "plan" is the objective string with six suffixes appended, crossed with two
search providers. There is no decomposition, no choice of method, no notion that a question might be
answered by reading a file. This is string concatenation named planning.

**Discover and select capability.** `atlas/agent_kernel/bus.py::default_catalog()` registers exactly
ten capabilities: local_market_store, knowledge_search, structured_provider, web_search, news_search,
research_scientist, alternative_source, python_calculation, experience_lookup, cognitive_core. Seven of
the ten are tagged `("investment",)`. There is **no sql, no git, no code-read, no shell, no file-read**.
Note especially that `python_calculation` is documented as "Deterministic calculation from already
retrieved inputs" — even the Python capability cannot fetch anything. The acquisition order is a
hard-coded ladder, `_ACQUIRE_FOR` in `planner.py`, one list per missing field.

**Execute.** 21 of 32 tasks are `CAPABILITY_GAP`. A representative task attempted 8 capabilities and
recorded all 6 failures as `:known_failure` with `last_error: "lane_busy"` and `retry:
"on_capability_change"`.

**Verify.** Partially real — the confidence layer does emit `INSUFFICIENT` honestly, which is the one
thing that saved the north-star test from being a silent lie.

**Remember / learn / update beliefs / choose next question.** See §11. Short answer: writes, never reads.

### The lane-busy trap

`known_failure()` in `atlas/agent_kernel/planner.py` returns a cached failure unless
`generation > row.generation`. The `generation` counter only increments in four places: `bus.put()`,
`set_available()`, `_set_external()` on change, and `kernel.bind_web_search()`. None of those fire
because the LLM lane was briefly busy. So a transient "LLM lane busy (1/2)" during market hours is
recorded as a **permanent** capability failure, and the task's own retry condition —
`on_capability_change` — can never be satisfied. Atlas has taught itself that it is incapable of things
it is fully capable of, and the memory is self-sealing.

### The fake-success ledger

`atlas/agent_kernel/kernel.py:611-631` handles skipped known-failures by writing a search record with
`result_count=0` and `status` set from the skip reason. In the live state, **23 of 31 external searches
have `query: ""`, `status: "SUCCESS"`, `error: "SUCCESS"`, `result_count: 0`.** A search that never
happened is logged as a successful search. Any metric built on that ledger is meaningless, and this is
also an observability gap: we cannot currently prove what Atlas searched.

---

## 4. The real "give Atlas a problem" test

I gave Atlas a problem it was objectively well-equipped to solve, naming no API, dataset or method —
only the problem and the fact that local evidence existed:

> `atlas job start "Investigate why the Atlas scheduler repeatedly failed tasks today with a JSON
> serialization error. Use the local logs and database to find the root cause, verify it, and state
> your conclusion."`

Job `b738dad3-878c-43e5-bb35-18efdfb821b2`. What happened, from the artifacts:

| Time | Event |
|---|---|
| 13:18:42 | job created |
| 13:19:42 | "planned 1 step(s)" — exactly 60.0s later, the planner timeout |
| 13:19:54 | "finalized: completed" |

Service log, same window:

```
planner LLM decomposition failed (OllamaError: request to /api/chat failed: timed out);
using deterministic fallback plan
planned job ... (1 step(s), fallback)
```

Result: `status: completed`, `overall_confidence: INSUFFICIENT`, `documents_count: 0`,
`documents_bytes: 0`. The report reads "I searched but gathered no usable evidence … after 0 round(s)."
The prior-knowledge lookup returned an unrelated HBLPOWER fundamentals finding.

Scored against your criteria: it did **not** choose its own approach, did **not** use the logs it was
explicitly pointed at, did **not** use the database, did **not** try an alternative after the first
path failed, and did **not** tell you what capability it needed. It reported `completed` for work that
never touched the problem. The honest "I tried A, B and C" report you asked for was not produced
because **A, B and C were never tried** — there was only ever one option.

### Correction, and it is worse than "did not"

My first reading of this was that Atlas *chose* not to use the logs and the database. That was wrong,
and the truth is more fundamental. **Atlas has no capability that can read either one.** Verified
directly:

- **`sql.query` cannot reach Atlas's own database.** It is a read-only **SQLite** tool "confined to a
  sandbox root" (`atlas/plugins/sql_plugin.py:1-11`). The docstring is explicit that Postgres is future
  work: *"Default backend is stdlib SQLite; the backend seam lets Postgres/others drop in later via
  config."* Every one of the ~20 queries I used for this audit hit Postgres. Atlas cannot run a single
  one of them.
- **`fs.read` cannot reach Atlas's own logs.** The filesystem sandbox root is `paths.documents` =
  `/data/atlas_data/documents` (`atlas/plugins/filesystem_plugin.py:103-110`), and escaping it raises
  `PluginError`. The logs are at `/data/atlas_data/logs/atlas.log`. Out of reach by construction.

So when I told Atlas "use the local logs and database to find the root cause", I asked for two things
it is **structurally incapable of**, and it did not say so — it ran a web search and reported
`completed`. The honest answer it should have given ("I need a capability that can read my own
database and my own logs; I have neither") is exactly the output you specified in your brief, and it is
the output the system cannot currently produce.

This also corrects my own recommendation. Unifying the capability registry (J1) would **not** have
fixed this test, because unification only exposes tools that exist. Two capabilities have to be
*built*, and they are small: a read-only Postgres introspection tool (the backend seam is already
there) and a log-read tool scoped to `paths.logs`. That is now P0 item 1.

### Why the planner timed out — I measured it

This is the hardware truth, and it changes the recommendation at the end:

| Model | Wall time | Output | Rate | Produced a usable plan? |
|---|---|---|---|---|
| `qwen3:4b` (configured) | **90.3 s** | 512 tokens (budget exhausted) | 5.7 tok/s | **No** — burned the entire budget on hidden reasoning, emitted no content |
| `llama3:latest` (8B) | **107.5 s** | 334 tokens | 3.1 tok/s | **Yes** — valid JSON, correctly chose `sql_query` against task logs |

Two conclusions. First, the configured planner model cannot produce a plan at all within any budget,
let alone 60s — the timeout is not the primary bug, the model choice is. Second, and more hopefully:
**llama3:8b got the plan right.** Asked the same question that defeated the live system, it correctly
decided to query the task log table. The reasoning needed for your vision is already achievable on
your own box. What is not achievable is doing it in 60 seconds at 3 tok/s with no GPU.

---

## 5. Autonomy measured, not output

| Dimension | Measurement | Score |
|---|---|---|
| Did Atlas choose the problem? | 32/32 tasks from one 5-field template | **No** |
| Did Atlas choose the method? | 6 string suffixes × 2 providers | **No** |
| Did Atlas choose the tools? | 10 fixed capabilities, no sql/git/code | **No** |
| Did Atlas adapt after failure? | 21/32 permanent `CAPABILITY_GAP` | **No** |
| Did Atlas verify itself? | `INSUFFICIENT` emitted honestly | **Partly** |
| Did Atlas learn? | 1 belief revision ever, a smoke test | **No** |
| Did Atlas generate the next question? | `active_hypotheses` = 20 × `None` | **No** |
| Did Atlas keep working unattended? | Yes — ticks never stop | **Yes** |
| Did Atlas report capability needs? | "known_failure", not "I need X" | **No** |

Atlas has high *activity* autonomy and near-zero *decision* autonomy. It is extremely good at running
forever. It has never once chosen what to do.

---

## 6. Which model is Atlas?

> **Atlas is currently closest to Model B — a workflow engine — with two genuine islands of Model C
> (autonomous task agent) and the scaffolding, but not the behaviour, of Model E.**

Not A: it is persistent, scheduled, stateful and runs unattended; it is far past a chatbot.
Not C overall: a task agent selects its own means. Atlas's means are hard-coded ladders and six string
suffixes, and the one component that genuinely selects means (the LLM planner) is unreachable.
The islands that *are* Model C: the **job planner when it succeeds** (it really does pick intents and
tools from a 23-intent space), and **Loop 0 / ops_health**, which detects, diagnoses, recovers, retries
with spacing, escalates and records a lesson without being told how.

I want to be precise about why this is not harsh. Model B with real C islands after a few months of
solo work is a strong engineering result. The gap between B and D is not another 200,000 lines; §15
argues it is wiring.

---

## 7. Islands of capability, and where the chain breaks

Five islands, each individually good:

1. **Toolbox** — python, sql, git, code, web, scholar, ocr, browser, download, mail.
2. **Job system** — LLM planner over 23 intents, workspaces, confidence, reports.
3. **Agent Kernel** — task state machine, failure memory, experience recording.
4. **Cognitive Core C0–C9** — patterns, hypotheses, FEL bridge, validator, belief revision, reflection.
5. **Loop 0** — operational detection, recovery, escalation, lesson capture.

The chain breaks in exactly four places:

- **Break 1 (Kernel → Toolbox).** The bus has 10 entries; the toolbox has 40. The kernel literally
  cannot name `sql`, `git`, `code` or `shell`, so it cannot try them, so it reports a capability gap
  for work it could do. This is the single highest-value break.
- **Break 2 (Planner → Reality).** 60s budget, 90–110s need. Always fallback.
- **Break 3 (Research → Local evidence).** `research()` can only use `scholar` and `search`. A question
  about Atlas's own logs is routed to the public internet.
- **Break 4 (Learning → Decisions).** 753 beliefs permanently `candidate`; nothing reads them.

Fix those four joins and four of the five islands become one loop. No island needs to be rebuilt.

---

## 8. Equity Lab as first proving ground

Honest verdict: Equity Lab is the best-developed part of Atlas and simultaneously the reason Atlas is
not general. `atlas/investment/` is **89,081 lines across 222 files — 41% of the entire codebase**. The
next largest package is `workers` at 17k. Seven of ten bus capabilities are tagged `investment`. All 32
kernel tasks are `domain: investment`. 758 of 774 beliefs are `domain: market`.

Equity Lab proved the *mechanics* — evidence→decision→outcome→attribution works, 45,765 decisions and
8,694 revisits are real. It did not prove the *agent*, because every generic mechanism got implemented
as an equity mechanism. The proving ground became the product.

---

## 9. Is Atlas too rule-driven?

Yes, and here is the cleanest demonstration. The learned beliefs are generated by a three-branch
formula. Of 753 candidate beliefs:

| confidence | count | branch |
|---|---|---|
| 0.499 | 336 | "direction missed" |
| 0.421 | 309 | "direction inconclusive" |
| 0.579 | 90 | "direction matched" |

735 of 753 "beliefs" carry one of three identical float values. The same statement text appears up to
**48 times** verbatim (e.g. "IDEA.NS thesis weaken at 1d: expected down, observed up"). This is not
belief formation with accumulating evidence; it is an `if/elif/else` writing log lines into a table
called `beliefs`. Nothing merges, nothing generalises, nothing strengthens.

The LLM is used for summarisation, narration, and chat. It is not used for the decisions that would
require judgement — which is the inverse of your design intent, where deterministic code guards
*safety* and the model supplies *judgement*.

The sharpest single example: **chat routing uses no LLM at all.** `Planner.plan` walks an ordered list
of regexes and the first match wins (`atlas/planner/planner.py:1099-1125`). "Investigate why X
underperformed" becomes one `RESEARCH` intent because it matched a pattern containing the word
*investigate*. The model is never asked what the sentence means.

---

## 10. Cross-domain generality

The abstractions are honestly domain-neutral — `missions`, `jobs`, `beliefs.domain`, `personal_repo`,
`engineering_mentor` all exist and work. The usage is not:

- `beliefs.beliefs` by domain: market 758, cross 7, engineering 5, personal 4.
- All 9 non-market beliefs are hand-written `seed.*` rows from you. Atlas has produced **zero**
  engineering or personal beliefs of its own.
- Agent Kernel tasks in non-investment domains: **0**.
- `beliefs.consultations` by domain: market 25,174 — engineering 7, personal 3.

So: generality is designed and implemented, and has never once run. Notably, the engineering domain is
where Atlas would be most useful to you soonest, because the evidence (repo, logs, DB, tests) is local,
free, unlimited and needs no market hours — and today's scheduler bug proves there is real work there.

---

## 11. The learning loop — the most important test

> *Can a previous experience materially influence a later decision without a developer manually
> modifying the rules?*

**No. Not once, in Atlas's entire operating history.** This is the strongest finding in the audit and
it is a single query:

```
select action, count(*) from beliefs.revisions group by 1;
  action=create | 770
  action=revise |   1
```

That one revision, inspected:

```
belief_id=166e16b7...  revision_no=1  action=revise  actor=reasoning
reason=smoke mind-change        confidence 0.78 -> 0.74
created_at=2026-08-11 16:19:37
```

The only belief revision that has ever occurred in Atlas was a **smoke test**, two months ago. Every
other belief has exactly one revision, which is its own creation (`revs per belief: n=1, count=771`).

Separating the five things you correctly said are not the same:

| Layer | Status | Evidence |
|---|---|---|
| Data storage | **Excellent** | 41,679 activity events, 45,765 decisions, 1,199 trades |
| Experience storage | **Good** | 378 `learning.experiences`, 646 `learning.events` |
| Learning | **Absent** | `learning.patterns` = **0 rows**; `component_observations` = **0 rows** |
| Belief revision | **Absent** | 1 revision ever, and it was a smoke test |
| Behavioral influence | **Absent** | see below |

On behavioral influence, the numbers are unambiguous. `beliefs.influence` has 774 rows — one per
belief, auto-created, `active=true`, and 753 of them target the string `"general"`, which nothing
consumes. Of 25,241 belief consultations, only **29 distinct beliefs** were ever consulted, and
**22,960 of them (91%) hit one single operator-written seed**, `seed.market.advice_before_hard_influence`.
582 of 774 beliefs have never been consulted at all. 301 of 378 experiences have `bias_enabled=False`
and so cannot influence anything by construction. 274 of 378 have `corroboration_count=0`.

Every belief that actually influences Atlas's behaviour was written by you. Every belief Atlas wrote
itself is inert. The loop is open at the top: experience → storage → ✗.

Why: there is no promotion path with teeth. Beliefs are born `candidate`, promotion requires validated
learnings, validation requires patterns, and the pattern detector has produced zero rows — partly
because it only shipped recently, and partly because with 2 symbols and a handful of closed positions
there is not yet enough data to clear any threshold. The C0–C9 work was correct; it was built on a
foundation (sample size) that cannot yet feed it.

---

## 12. Failure as a first-class experience — the Zerodha/F&O incident

Scored twice: as the system behaved this morning, and as it behaves after today's Loop 0 deployment.

| Step | Before Loop 0 | After Loop 0 |
|---|---|---|
| 1. Detect the failure | **No** — 29/29 packs read `expiry_missing` all session, silently | **Yes** — state model, `futures_master_missing` |
| 2. Understand downstream impact | **No** | **Yes** — names the failed dependency |
| 3. Attempt recovery | **No** — a pre-login `[]` was pinned for the day | **Yes** — 3 attempts, 90s spacing |
| 4. Refresh dependents after recovery | **No** | **Yes** — O2 invalidate → refresh → READY/DEGRADED |
| 5. Try an alternative path | **No** | **No** — still single-source |
| 6. Recognise the lab cannot evaluate today | **No** | **Yes** — `FNO_DEGRADED` |
| 7. Alert the operator | **No** | **Yes** — P0 email, 7-field template |
| 8. Record failure as experience | **No** | **Partly** — `experience.jsonl`, deterministic lesson text |
| 9. Avoid repeating it | **No** | **Partly** — the specific cache bug cannot recur; the class can |

So steps 1–4 and 6–7 went from No to Yes in one day. That is real progress and it is the part of today
that genuinely moved toward your vision — Loop 0 is Atlas's first component that detects, diagnoses,
recovers and escalates on its own.

**Zero trades on 2026-10-06 was not success.** Classified against your taxonomy, it was
**stale/invalid data** (a `[]` futures master cached pre-login) causing **capability unavailable**
(the F&O lab could not evaluate any contract), compounded by an **infrastructure failure** (51 daily
`set is not JSON serializable` checkpoint errors) and an **observability failure** (the logs omitted
worker IDs, so the failing worker could not be identified). Genuine "no opportunity" was never
established, because nothing was ever evaluated.

The deeper point: the incident went unnoticed for a full session not because detection was hard, but
because **nothing in Atlas was responsible for asking "did I actually do my job today?"** Loop 0 is now
that thing, for F&O. Nothing yet asks it for research, learning, or the kernel.

---

## 13. Why Atlas is not there yet — root causes

For each gap: the classification, and your harder question — why the development approach produced it.

**G1. The agent cannot reach its own tools.** *Integration + control-flow + architecture.*
Two capability registries were built independently: `CAPABILITY_CATALOG` for human jobs and
`bus.default_catalog()` for the kernel. **Why:** the toolbox was built first, for you, at the CLI. The
kernel was built later, for investment, and needed capabilities *now*, so ten were hand-listed rather
than derived from the existing registry. Nothing ever forced the two to converge, because no test and
no feature ever required the kernel to run a SQL query. The duplication was cheap at the time and is
now the main thing standing between Atlas and autonomy.

**G2. The planner cannot think in the time allowed.** *Operational + architecture.*
60s budget; 90–110s need; the configured 4B model produces no usable output at any budget. Two config
lines tell the whole story, and they contradict each other:

```
config/defaults.yaml:70   timeout: 300           # CPU inference under memory pressure can exceed 120s
config/defaults.yaml:146  planner_timeout: 60.0  # planner-role wall-clock; then deterministic fallback
config/defaults.yaml:147  planner_num_predict: 512
```

The general LLM budget is already 300s, with a comment acknowledging that CPU inference exceeds 120s.
The planner — the single most expensive thought in the system — was then given **60s**, less than half
the figure the same file calls normal. And `num_predict: 512` is precisely the budget `qwen3:4b`
exhausted on hidden reasoning before emitting any content, so even an infinite timeout would return
nothing. **Why:** both limits were set to keep responses short and interactive, which is right for
chat and wrong for planning. The deterministic fallback then absorbed every failure silently, so the
mismatch never surfaced as an error — the safety net prevented anyone from discovering the fall.

**G3. Research cannot see local evidence.** *Architecture + knowledge.*
`research()` is wired to `scholar` and `search` only. **Why:** the research service was built for the
"read the literature" use case, where the answer genuinely is on the internet. "Investigate my own
system" was never a target, so local evidence was never a provider — even though `sql`, `git` and
`code` already existed as tools.

**G4. Learning is written and never read.** *Learning + integration.*
753 beliefs permanently `candidate`; 91% of consultations hit one operator seed.
**Why:** the pipeline was built in write-order — record experiences, then patterns, then hypotheses,
then revision — and each stage was tested by asserting that it *wrote* the right row. No test ever
asserted that a later decision *differed* because of an earlier experience. Write-path tests pass with
an open loop. This is the gap most directly caused by the development method.

**G5. Failure memory is self-sealing.** *State + learning.*
Transient `lane_busy` is cached as permanent, gated on a `generation` counter that effectively never
moves. **Why:** failure memory was designed to prevent wasteful retries — a real problem. But failure
*classes* were never distinguished: transient, capability-absent, and genuine-impossibility all take
the same path. The retry key chosen (`on_capability_change`) is unobservable for the failures that
actually occur.

**G6. One objective template, one domain.** *Scheduling + domain-coupling.*
32/32 tasks from five missing-field names. `system.goals` = 0 rows.
**Why:** task generation was implemented as a consumer of `uncertainty_queue`, which is an equity
fundamentals artifact. Problem discovery was thereby *defined* as "a fundamentals field is missing."
Any other kind of problem has no door into the kernel.

**G7. Hypotheses are never formed.** *Architecture + knowledge.*
`active_hypotheses` = 20 × `None`. **Why:** the kernel's loop is acquire-evidence-for-a-known-gap, which
needs no hypothesis. The hypothesis engine was built later, in the cognitive layer, and reads closed
trades rather than kernel tasks. Two hypothesis concepts now exist in different packages, and neither
is in the autonomous path.

**G8. Success is reported for work that failed.** *Verification + observability.*
A job with 0 documents and `INSUFFICIENT` confidence is `completed`; skipped searches log
`status: SUCCESS` with an empty query. **Why:** `completed` was defined as "the pipeline ran without
raising," which is the right definition for a workflow engine and the wrong one for an agent. Nothing
compared the result against the objective.

**G9. Safety is fine; authority is the issue.** *Safety/authority — partial, in your favour.*
I specifically checked whether gates block research, and they do not. Fail-closed PLC.A, `never_orders`,
F&O isolation and FEL promotion gating all restrict *orders*, not *investigation*. The constraint on
Atlas's research is capability reach (G1/G3), not safety. **Do not loosen a single safety gate.**

**G10. Cross-domain generality never exercised.** *Domain-coupling + scheduling.*
**Why:** 41% of the code is in `atlas/investment/`. Each new generic need was met by the nearest
equity-shaped implementation because that was where the data, the tests and the urgency were.

---

## 14. Maturity scores

Scale: 0 absent · 1 design only · 2 implemented but isolated · 3 integrated but deterministic/manual ·
4 autonomous and reliable · 5 autonomous, persistent, learning, cross-domain.

| # | Capability | Score | Basis |
|---|---|---|---|
| 1 | Observation | **4** | 41,679 events; ticks never miss |
| 2 | Problem discovery | **1** | one 5-field template; `system.goals` = 0 |
| 3 | Task generation | **2** | works, single source, single domain |
| 4 | Prioritization | **2** | `max_investigations_per_tick=1`, no value model |
| 5 | Planning | **1** | 6 string suffixes; LLM planner unreachable |
| 6 | Capability discovery | **1** | 10 hard-coded entries, no introspection |
| 7 | Tool selection | **1** | cannot name sql/git/code/shell |
| 8 | Research execution | **2** | web/scholar only, no local evidence |
| 9 | Experimentation | **3** | FEL is real and tested; not autonomously triggered |
| 10 | Verification | **3** | confidence honest; `completed` dishonest |
| 11 | Failure recovery | **3** | Loop 0 shipped today; F&O only |
| 12 | Human escalation | **4** | P0/P1/P2 email with impact and next action |
| 13 | Memory | **4** | Postgres + RAG + 406 docs, retrievable |
| 14 | Experience | **3** | 378 recorded, 301 with `bias_enabled=False` |
| 15 | Learning | **1** | `learning.patterns` = 0 rows |
| 16 | Belief revision | **1** | 1 revision ever, a smoke test |
| 17 | Behavioral influence | **0** in effect, **2** in code | mechanism implemented and test-covered but **unbound** at runtime — `"ReasoningService not bound"`, `lesson_refs: []` in all 24 consult states; 91% of consultations hit one operator seed |
| 18 | Reflection | **2** | C9 implemented, unproven |
| 19 | Next-question generation | **1** | `active_hypotheses` = 20 × `None` |
| 20 | Autonomous continuation | **2** | continues ticking, not continuing *work* |
| 21 | Operational reliability | **3** | Loop 0 + watchdog are good; the layer beneath has a single point of failure — see §18 |
| 22 | Cross-domain generality | **1** | 9/774 beliefs, all hand-seeded, 0 kernel tasks |

Mean is 2.1, and the mean is misleading in both directions — as you anticipated. The system is a 4 at
observing, remembering, escalating and staying alive, and a 0–1 at everything that constitutes
agency. Averaging a strong body with an absent decision layer produces a number that describes
nothing.

**Critical-path bottlenecks, in order.** Autonomy is a chain, so the chain's rating is its weakest
necessary link:

1. **#7 Tool selection (1)** and **#6 Capability discovery (1)** — nothing downstream can improve while
   the agent cannot reach its own tools. Raising this one number raises 5, 8, 9, 11 and 22 with it.
2. **#5 Planning (1)** — gated on the 90s/60s latency fact, not on code.
3. **#17 Behavioral influence (0)** — the only score that is a hard zero, and the one that decides
   whether Atlas is a learning system or a logging system.
4. **#2 Problem discovery (1)** — determines whether Atlas can ever work on anything but missing
   equity fundamentals.

Everything else is adequate or better. This is the good news buried in a bad table: **four numbers are
load-bearing, and all four are joins rather than subsystems.**

---

## 15. The minimum true autonomous Atlas

> **Yes — this is exactly that situation. Do not build another subsystem. Connect the existing ones.**

I want to state this plainly because it is the most actionable conclusion in the audit, and because the
instinct that produced 215,000 lines will want to build a sixteenth subsystem. Everything the vision
requires already exists in this repo. Nothing in §15 below is a new capability; all of it is wiring,
deletion, or a config change.

The minimum loop, four joins:

**J0 — Two capabilities that must be built, because they do not exist.** A read-only **Postgres**
introspection tool (the `SQLClient` backend seam in `atlas/sql/client.py` is already designed for
this — `sql.query` is SQLite-only today) and a **log-read** tool scoped to `paths.logs` (the `fs`
sandbox is pinned to `paths.documents`). Without these, Atlas cannot examine its own behaviour at all,
and no amount of wiring changes that. This is the only item in §15 that is genuinely new code, and it
is perhaps 200 lines.

**J1 — One capability registry.** Delete `bus.default_catalog()`'s hard-coded list; derive the bus from
the existing `CAPABILITY_CATALOG` so that `sql`, `git`, `code`, `file_read`, `python` and the two new
J0 capabilities become things the kernel can name and therefore try. *Wiring, not new code.*

**J2 — Constrain the planner's output with a JSON schema.** Measured, and it supersedes my earlier
advice to switch models and raise the timeout (see §20). Passing a JSON schema as Ollama's `format`
makes **the model Atlas already uses, on the hardware you already own**, produce a correct multi-tool
plan in **46.8 s / 233 tokens — inside the existing 60 s budget.** One parameter. No model change, no
timeout change, no GPU.

**J3 — Honest completion with an alternatives ladder.** A job whose confidence is `INSUFFICIENT` and
whose document count is 0 must not be `completed`. It must be `CAPABILITY_GAP` and must emit the report
you specified: "I tried A because __. A failed because __. I then tried B … therefore I need capability
X." That requires the attempt ladder to be recorded, which J1 makes possible, and `_record_search` to
stop writing `SUCCESS` for searches that never ran. *Small code change in a known place.*

**J4 — Bind the learning loop, don't build it.** This is the item that changed most once the evidence
was in, and it changed in your favour. The behavioural-influence mechanism **already exists and is
test-covered**: `trading/strategy.py:135` calls `_apply_lesson_influence`, which calls
`lesson_influence.apply_to_options`, which **mutates `opt.score`** (bounded at ±0.25) and can therefore
flip a buy into a hold. There is a parallel path for universe ranking via `experience_bias_map`. The
loop is not missing — **it is unbound at runtime.** Today's live consult states say so literally:
`"ReasoningService not bound"` appears in every state in
`/data/atlas_data/market/decision_consults/default/2026-10-06.json`, with `lesson_refs: []` in all 24
recorded states across 8 days, and zero non-zero L2 deltas.

So J4 is four bindings, not a subsystem: bind `ReasoningService` into the consult path; merge the
duplicate outcome rows into keyed beliefs so `match_lessons` can hit them; promote
`candidate`→`active` on corroboration; and add the one test that does not exist today — *given
experience E, a later decision D differs from what it would have been without E.* That test is the
definition of your vision, and nothing currently asserts it.

If only one of the four is done, do J1. If two, J1 and J2 — together they turn the north-star test from
"1 generic web search, 0 documents, reported complete" into an agent that queries its own task log.

---

## 16. Priorities

### P0 — prevents Atlas from being the autonomous agent at all
0. **F1–F3 — stop the CLI from killing the recurring engine** (§18). This jumps the queue: autonomy is
   meaningless if any `atlas status` can silently stop all scheduled work for an unbounded period.
1. **J0 — build the two missing self-inspection capabilities**: read-only Postgres and log read
   (§4, §15). Atlas currently cannot read its own database or its own logs by any path. ~200 lines.
2. **J1 — unify the capability registry.** The kernel must be able to name every tool you can.
2. **J2 — planner latency and model.** 300s budget, `llama3:8b`, off-hours planning. Measured, not guessed.
3. **J3 — no false `completed`.** Honest capability-gap reporting with the attempts ladder.
4. **Let the kernel read local evidence.** Add `sql`/`code`/`log_read` as research providers (follows from J1).
5. **Fix the self-sealing failure memory.** Classify transient vs permanent; expire transient failures by time.

### P1 — needed to make autonomy reliable
6. One belief promotion path that runs, with the behavioural-difference test (J4).
7. A second task source besides `uncertainty_queue` — operator goals (`system.goals` is empty and the
   API already exists) and Atlas's own open questions.
8. Dedupe the outcome-row "beliefs" into keyed, accumulating beliefs.
9. Extend Loop 0's "did I actually do my job today?" question from F&O to research, learning and the kernel.
10. Install the ops watchdog timer (prepared, awaiting your approval).

### P2 — later
11. Hypothesis formation inside the kernel loop (unify the two hypothesis concepts).
12. Cross-domain activation — engineering first, since the evidence is local and free.
13. Autonomous experiment triggering from validated patterns.

### STOP BUILDING
- **No new cognitive layers.** C0–C9 is implemented and tested; it has produced 0 patterns. Adding C10
  cannot help. Prove C3 fires once before extending it.
- **No new investment subsystems.** 41% of the codebase is already there. Nothing in §15 needs more.
- **No new strategy, indicator or data source** (your existing freeze — it remains correct).
- **No new dashboards or reports** until there is autonomous work to display.
- **Do not train your own LLM.** See below.
- **No more write-path tests** for the learning loop. One behavioural test is worth all of them.

---

## 17. The acceptance test

A single test, run from a cold start with no hints. Atlas passes only if **all** criteria hold.

**Setup.** Introduce a real, locally-diagnosable defect (as today's `set is not JSON serializable` was).
Tell Atlas nothing about where to look.

**Prompt.**
> "Something is wrong with Atlas's task execution. Find out what, prove it, and tell me what you would
> change. If you cannot, tell me exactly what capability you need."

**Pass criteria.**
1. Atlas chose its own approach; no API, dataset or method was named by the operator.
2. Atlas used **at least two different capability types** (e.g. log read + SQL, or grep + python).
3. Atlas used **local evidence**, not only web search.
4. If the first approach failed, Atlas tried a second, and the attempt ladder is recorded.
5. The conclusion is **specific and correct** — names the file and the mechanism.
6. Atlas **verified** its own conclusion against evidence rather than asserting it.
7. If it failed, the output is the honest form: "I tried A because __, it failed because __; I tried B
   …; therefore I need capability X" — and the status is `CAPABILITY_GAP`, never `completed`.
8. The run is fully reconstructible from artifacts; no search is logged `SUCCESS` with an empty query.
9. Atlas recorded an experience, and that experience is **retrievable and applicable** to a future
   similar problem.
10. Atlas generated **its own** next question, unprompted.
11. Nothing in the run required you to edit a rule, a ladder or a config.
12. Re-run with a *different* defect in a *different* domain (engineering, not equity) — it still passes.

Today, the same test scored **0 of 12**. Criteria 1–5 fail on the bus and the planner timeout; 7–8 on
the false `completed` and the fake-success ledger; 9–10 on the open learning loop; 12 on domain
coupling. After J1+J2+J3 I would expect 1–8 to be reachable; J4 addresses 9–11; 12 is the P2 work.

---

## On "even if it takes creating my own LLM"

**Don't. It is the one thing in your plan that would not help, and it would cost you a year.**

The evidence is in §4. `llama3:8b`, already on your disk, asked the exact question that defeated the
live system, **correctly decided to query the task log table**. The reasoning you need is already
present on this machine. What is absent is 107 seconds of permission to use it, and a bus that would
let the resulting plan run `sql`.

Your actual constraint is measured and mundane: 24 CPU cores, ~8 GB free RAM, **no GPU**, 3–6 tokens
per second, a 60-second budget and 2 LLM lanes. Training a model would not change one of those numbers
— it would make them worse, and a model you train on this hardware would be far weaker than
`llama3:8b`, which already suffices.

In priority order, if you want more reasoning: (1) raise the planner timeout and switch the model —
free, today; (2) plan off-hours, when no lane contention exists — free; (3) add a GPU, which turns 3
tok/s into 60+ and makes a 20–30B model viable — a few hundred dollars and the single highest-leverage
purchase available to this project; (4) use a hosted model with reliable tool-calling for planning only,
keeping all data and execution local. Training your own belongs at position (5), and position (5) is
not needed.

The honest summary of your own question: you did not write a script, and you do not need a new mind for
Atlas. You built the body, the memory, the senses and the safety of the thing you imagined, and then
gave its mind sixty seconds and ten tools. Four joins — §15 — is the distance between what is on this
disk and what you set out to build.

---

## 18. Postscript — the audit validated itself, live, during the audit

While preparing the external watchdog for installation I dry-ran it once. It returned
`{"ok": false, "open": ["heartbeat_stale"]}`, and it was right. Atlas's recurring engine had been dead
for 45 minutes (18:21–19:06 IST) while `systemctl status atlas` reported `active (running)` and the
process looked perfectly healthy.

The chain, fully verified and recorded in `docs/2026-10-06_OPERATIONAL_HEALTH_LOOP0.md` §7: the Atlas
CLI is not a client of the running service — `atlas status` **boots a second full kernel** against the
same database, claims tasks belonging to the live service, and fails them with
`no handler registered for task_type '…'`. One of the tasks it killed was `schedule_tick`, the only
thing that advances `next_run_at`. With it dead, **none of the 107 enabled schedules ever became due
again** — they froze 2,613 seconds overdue. Loop 0 could not alert, because Loop 0 runs *inside*
`provider_health_tick`, which was one of the frozen schedules. There have been **164 such failures
since 2026-07-11.** Recovery was accidental: the next `atlas status` re-registered the schedules and
unstuck the clock.

Three things follow, and they are a fair summary of the whole audit.

**The watchdog earned its place before it was even installed.** The one component built today whose
entire job is to be outside Atlas and distrust it caught, on its first run, a fault that had been
silently stopping work for three months. "Fail loudly when recovery is not successful" was the right
principle.

**Observability was the real defect, not reliability.** Atlas was not broken in a way anything could
see. The service was green, the process was alive, the logs showed no errors, and the work had stopped.
This is §13's G8 and the observability gap in their purest form, and it is why "zero trades" must never
be read as success.

**And this is exactly the problem Atlas should have solved for itself.** A 45-minute gap in its own
task table, with the cause sitting in its own `scheduler.task_runs.error` column, discoverable by one
SQL query it already has a tool for. I found it in four queries. Atlas, given the same question an hour
earlier, ran one web search and reported `completed`. The distance between those two outcomes is not
intelligence and it is not more code — it is a bus with ten hard-coded entries and a planner given
sixty seconds. That is the gap, and it is closeable.

---

## 19. Four parallel deep audits — what they changed

Four independent audits ran in parallel with the first-hand work above: the agent/cognition layer, the
tools/execution layer, the learning/belief layer, and cross-domain generality. They confirmed the
central thesis and corrected three of my conclusions. The corrections are recorded here because two of
them change what to do first.

### Correction 1 — Atlas cannot inspect itself at all (§4, §15 J0)

Covered above. `sql.query` is SQLite-in-a-sandbox, `fs.read` is pinned to `paths.documents`. There is
no path from Atlas to its own Postgres or its own logs. My original J1 ("unify the registry") was
insufficient; J0 now precedes it.

### Correction 2 — the learning loop is unbound, not absent (§11, §15 J4)

Also covered above, and this is the most hopeful correction in the audit. A real deterministic
lesson→score path exists and is test-covered. Runtime shows it inert: `"ReasoningService not bound"`,
`lesson_refs: []` in 24/24 consult states, 49 L5 validation candidates with **0 reaching VALIDATED**,
and C7's `accept_revision` / `belief_context_for_decision` called **only from tests**. The gap is
integration, not architecture — which makes it a far smaller job than "build a learning system."

### Correction 3 — the domain coupling is a dependency inversion, not just a size imbalance (§8, §13 G10)

I had reported that 41% of the code lives in `atlas/investment/`. The sharper finding is the direction
of dependency: **41 modules outside `atlas/investment/` import it, across 441 import statements.**
Platform code depends on the domain, not the reverse. Concretely, `reasoning/reflection.py` imports
`atlas.investment.cognitive_budget`; `core/resources/manager.py` reads investment LLM lanes;
`goals/service.py`, `planning/service.py` and `kernel/bootstrap.py` all import investment.

There is also **no Lab abstraction**. `laboratory_id` is documented as "a 1:1 alias of IL.10
`portfolio_key`" (`atlas/investment/laboratory.py:1-6`) — a portfolio key, not a domain contract. The
entire autonomous research loop (uncertainty queue, curiosity, hypothesis engine, FEL, L5 validation,
learning objects, cognitive cycles) lives under `atlas/investment/` and is keyed to symbols, bars and
fundamental unknowns like `pe_missing`. So "add an Engineering Lab beside the Equity Lab" is not
configuration; it requires a neutral domain protocol and the removal of that inversion. This moves
cross-domain generality firmly into P2 and justifies the STOP BUILDING list.

### Confirmations that strengthen existing findings

**Chat routing uses no LLM whatsoever.** `Planner.plan` walks an ordered `_RULES` list of regexes;
first match wins, else `REACT` or `ANSWER` (`atlas/planner/planner.py:1099-1125`). So "investigate why
X underperformed" becomes a single `RESEARCH` intent by pattern match. This belongs in §9 as the
cleanest evidence that Atlas is rule-driven where it should be reasoning.

**A genuine ReAct tool loop does exist** — the model sees `ToolRegistry.describe()` and emits
`{"tool": ..., "args": ...}` (`atlas/agents/react_agent.py:96-140`). This is the second real island of
agency alongside the job planner. But `max_iterations` defaults to **3**, which is too shallow for
multi-step investigation, and it is only reachable when the regex router falls through to `REACT`.

**Arbitrary code execution is real and safe.** `python.run` is a genuine subprocess sandbox with
network blocked by default. There is no `exec`/`eval` on user code and no shell for agents. The
Agent Kernel's `python_calculation` is *not* this — it is one hard-coded ratio over stored evidence
(`kernel.py:910-920`), which confirms my §3 reading.

**Mission types are a closed set.** 37–38 built-in templates; instantiating an unknown one raises
`TemplateError`. There is no runtime path to define a new mission type, so Atlas cannot invent a new
kind of long-running work for itself.

**`run_agent` is dead code** — registered as a scheduler handler in bootstrap with no call site that
ever enqueues it.

**Failure memory does suppress retries**, confirming G5 from the other direction
(`kernel.py:714-726`).

### What none of this changes

The verdict stands: **Model B with islands of C.** If anything the four audits make the core claim
stronger, because they show the subsystems are individually better built than I credited — a real
ReAct loop, a real sandbox, a real lesson→score mechanism, a real validation ladder — and that the
reason none of it adds up to an autonomous agent is, in every single case, a missing or unbound
connection rather than a missing idea.

That is the finding to hold onto. Five audits looked at this system from five directions and none of
them found a part of your vision that was conceptually wrong or absent. They found a toolbox that
cannot see itself, a planner that is not given time to think, a learning loop with its wire
unplugged, and a platform that depends on its own first domain. Those are four problems with known
locations, and not one of them requires a new mind for Atlas.

---

## 20. The planner measurement, done properly — and a correction I owe the record

My first planner measurement was unfair to Atlas, and `atlas/llm/ollama_provider.py:95-99` is where I
should have looked first. The code already knows qwen3 leaves `content` empty and promotes `thinking`
into it, and it already passes `think: false`. My raw API call did neither. So I re-ran the test with
Atlas's real settings, and then kept going until I found what actually fixes it.

All runs: same system prompt, same objective ("investigate the scheduler JSON serialization error,
use the local logs and database"), `temperature: 0`, CPU-only, no GPU.

| Model | `think` | `num_predict` | `format` | Time | Tokens | Usable plan? |
|---|---|---|---|---|---|---|
| `qwen3:4b` | (unset) | 512 | none | 90.3 s | 512 | **No** — no content at all |
| `qwen3:4b` | false | 512 | none | 88.8 s | 512 | **No** — prose, never reaches JSON |
| `qwen3:4b` | false | 1536 | none | **277.8 s** | 1536 | **No** — still narrating at 1536 tokens |
| `qwen3:4b` | false | 512 | `"json"` | 18.3 s | — | **No** — echoed the prompt back as JSON |
| **`qwen3:4b`** | **false** | **700** | **JSON schema** | **46.8 s** | **233** | **YES** |
| `llama3:latest` (8B) | false | 700 | JSON schema | 81.3 s | 227 | YES |
| `llama3:latest` (8B) | (unset) | 512 | none | 107.5 s | 334 | Yes (duplicated a step) |

The plan `qwen3:4b` produced with a schema, verbatim intents: `git_status` → `sql_query` →
`web_search` → `research` (analyse the local logs) → `ask_knowledge`. That is a competent
investigation plan, and `sql_query` plus log analysis is exactly what was needed to find the bug.

**The finding.** The bottleneck was never the model, the hardware, or the timeout. It was that the
planner asked for JSON in English and hoped. Unconstrained, a 4B model at 5.5 tok/s narrates
indefinitely and never emits the array — 1536 tokens and still going. Grammar-constrained by a schema,
the same model on the same CPU answers correctly in **233 tokens and 46.8 seconds, inside the 60-second
budget that is already configured.**

**Token efficiency dominates token speed.** This is the engineering lesson worth keeping. `qwen3:4b` is
1.8× faster per token than `llama3:8b` and was useless, because it needed 6.6× more tokens and still
failed. Constraining the output space cut tokens 6.6× and converted failure into success. On a
CPU-only host, every future LLM integration in Atlas should be judged on *tokens required*, not
tokens per second.

**Corrections to my own earlier advice in this document.** §15 J2 originally said "raise the planner
timeout to 300 s and switch to `llama3:8b`." Both would work, and both are now unnecessary. Keep
`qwen3:4b`, keep the 60 s budget, add the schema. The `num_predict: 512` cap also stops being a
problem, because a schema-constrained answer needs 233. This is the cheapest P0 item in the audit and
the only one that is a single parameter.

**What this does and does not fix.** It makes the planner work, which unblocks the agent layer — that
is large. It does not give Atlas a tool that can read its own Postgres or its own logs (J0), so the
plan above would still fail at execution on steps 2 and 4. The plan is now correct; the hands are
still missing. J0 and J2 are both required, and J2 just became trivial.

---

## 21. The learning sample — correcting myself once more, and the one gap code cannot close

I was about to assert that Atlas trades two symbols and therefore cannot learn. That was wrong, and
checking it changed the conclusion. The actual numbers:

| Measure | Value |
|---|---|
| Distinct symbols in `sim.trades` | **44** |
| Total sim trades | 1,199 |
| Closed round trips (`sell`/`exit`) | **573** |
| `decision.decisions` | 45,765 |
| `decision.attributions` | 1,489 (2026-08-09 → 2026-10-06) |
| **`decision.observations` (outcome-labelled)** | **80** |

So the trading history is respectable. The binding constraint is **not** symbol count and **not** trade
count — it is that only **80 decisions have outcome observations attached**, against 45,765 decisions
and 573 closed round trips. The learning loop is starved at the *labelling* step, not the *activity*
step. Concentration makes it thinner still: `IDEA.NS` (480), `HBLPOWER.NS` (291) and `COALINDIA.NS`
(183) are 80 % of all trades, so 80 observations do not represent 44 independent symbols.

Set against the thresholds — `MIN_GROUP_N=3`, `MIN_SPLIT_DELTA=0.5`, `REPLICATION_PASSES=2`,
`DEFAULT_SESSIONS_N=5` — 80 concentrated observations explain the 49 L5 candidates with **0 VALIDATED**
and `learning.patterns` = 0 rows far better than any code defect. The thresholds are not wrong; they
are honest, and they are not yet satisfiable.

**Data hygiene note.** `sim.trades` contains obvious test symbols — `AAA` (14), `TRD` (14), `OKK` (12).
Any pattern detector run over this table will treat them as real instruments. They should be excluded
or purged before the learning loop is bound, or the first "learning" Atlas does will be about `AAA`.

**Why this is the gap code cannot close.** Binding the learning loop (J4) makes it *able* to learn.
It does not create evidence. At the current rate of outcome labelling, equity learning will stay empty
for many months. This is the strongest argument for **engineering as the first real domain** — not
because it is easier, but because it is the only domain where Atlas can generate hundreds of labelled
outcomes per week at zero cost and no market-hours dependency. Today alone produced two: the checkpoint
`set` serialization bug and the CLI-kills-the-scheduler bug. Equity gives Atlas a few labels a week;
its own source tree and runtime give it as many as it wants.

---

## 22. Resource awareness as a first-class design principle

Added at the operator's request: **Atlas must know that it runs on a small machine and plan
accordingly.** This is not a limitation to hide; it is a constraint to reason with, and §20 shows that
respecting it is what made the planner work.

The envelope, measured: 24 CPU cores, ~15 GB RAM with ~8 GB available, **no GPU**, Ollama at **3–6
tokens per second**, 2 LLM lanes with a live-trading reservation during market hours.

Principles that follow:

1. **Budget tokens, not seconds.** A 60-second timeout is a proxy; the real currency is tokens
   required. Every LLM call site should declare an expected token cost and be measured against it.
2. **Constrain every structured output with a schema.** §20: 1536 tokens and failing became 233 tokens
   and correct. This is the single highest-leverage habit available on this hardware.
3. **Prefer deterministic computation to inference.** Atlas already does this well; the error was the
   opposite one — using the LLM for narration and regexes for judgement.
4. **Do expensive thinking when the machine is idle.** Planning, reflection and learning belong in the
   overnight window, not in the market-hours lane. The scheduler already supports this.
5. **Declare degradation, never hide it.** The planner's silent fallback is what concealed this bug for
   months. A capability that degrades must say so in its result, which is J3.
6. **Report the resource reason in capability gaps.** "I could not plan this because planning needs
   ~900 tokens and the lane was reserved for live trading" is a useful answer. "known_failure" is not.

---

## 23. P0 implemented, and the north-star test re-run

Shipped the same day as the audit: J0a, J0b, J2 and F2/F3. 22 new tests in
`tests/test_self_inspection_j0.py`; deployed on PID 2547995.

### What was built

**J0a — Atlas can read its own database.** `atlas/sql/postgres_backend.py` adds a
`PostgresBackend` behind the `SQLBackend` seam that already existed, plus a
`RoutingBackend` so `source="atlas"` reaches Atlas's own Postgres while every other
source keeps the SQLite sandbox. Four safety layers: the existing read-only statement
guard, a `READ ONLY` transaction, a per-query `statement_timeout`, and refusal of
credential catalogs with redaction of secret-named columns. `source="atlas.scheduler"`
scopes to a schema.

**J0b — Atlas can read its own logs.** `atlas/plugins/logs_plugin.py` adds
`logs.list` / `logs.tail` / `logs.search`, confined to `paths.logs`, with secret
redaction on every emitted line. Logs are the one place a credential appears by
accident and their whole purpose is to be quoted into reports and prompts, so
redaction is mandatory rather than optional. `token_count` and `token_len` survive
deliberately — sizes are diagnostics, not secrets.

**J2 — the planner is grammar-constrained.** `_decompose_schema()` is derived from
`_VALID_INTENTS` and `CAPABILITY_CATALOG`, so it cannot drift from the validator.
`planner_timeout` 60 → 180 s and `num_predict` 512 → 700.

**F2/F3 — the recurring clock can no longer be killed.** An unknown handler now
*releases* the task back to pending without consuming a retry, instead of marking it
permanently failed, because not knowing how to run a task is this process's limitation
rather than the task's fault. And because a frozen `schedule_tick` cannot repair itself
through a schedule, the scheduler's own worker loop re-seeds the clock after a sustained
idle window — the one place recovery can live without a circular dependency.

### The test, before and after

Identical prompt both times: *"Investigate why the Atlas scheduler repeatedly failed
tasks today with a JSON serialization error. Use the local logs and database to find the
root cause, verify it, and state your conclusion."*

| | Before (job `b738dad3`) | After (job `b370b60a`) |
|---|---|---|
| Planner outcome | timed out at 60.0 s, **fallback** | **`source=llm`** |
| Steps | 1 | 4–6 |
| Plan | one generic `research` | `recall` → **`sql_query`** → `react` → `remember` |
| Touched Atlas's own data | **No** | **Yes** — `sql_query` ran against `source="atlas"` |
| Documents gathered | 0 | n/a — it queried state instead |
| Reported | `completed` | `running`, then stepwise |

With `args` required by the schema, the planner now emits an executable statement:

```sql
SELECT task_id, task_type, status, error, started_at, worker_id
FROM scheduler.task_runs
WHERE status = 'failed' AND error LIKE '%JSON serial...
```

That is, to within a column name, **the query I wrote by hand to find the bug.** Atlas
now plans its own diagnosis.

### What the fix exposed — honest remaining gaps

Fixing the planner moved the failure one layer down, which is the expected shape of
progress and worth recording precisely:

1. **A step with no arguments was marked `done`.** The first schema-constrained run
   planned `sql_query` with empty `args`, so the step answered "What SQL query should I
   run?" and completed successfully. Requiring `args` in the schema fixes the planner
   side; the executor side is still wrong, and that is **J3**: a step that did not do its
   work must not report success.
2. **The planner duplicates steps** (two identical `sql_query` entries) and invents
   plausible-but-wrong columns (`task_type` lives on `scheduler.tasks`, not
   `scheduler.task_runs`). A failed query returns an honest `error`, so this is
   self-correcting in principle — but only once the `react` step can see the error and
   retry, which is the alternatives ladder in J3.
3. **J1 is untouched.** This work fixed the *job* path. The Agent Kernel's bus still has
   10 hard-coded entries and still cannot name `sql`, `logs`, `git` or `code`, so the
   autonomous loop cannot use any of what was built today. That is the next item.

### Immediate dividend

The moment `source="atlas"` worked, one query found something the audit had missed and
the logs could not show:

```
task_type     | error                                              | n
worker_tick   | TypeError: Object of type set is not JSON serializable   | 1523
worker_tick   | TypeError: Object of type UUID is not JSON serializable  |   19
```

Two things there. The true scale was **1,523** occurrences, not the ~51/day estimated
from log sampling; and the failing task type was **`worker_tick`** all along — §5 of the
Loop 0 doc records that it "could not be identified, because the log omits worker IDs."
The database had the answer the whole time. Both counts stop at 09:55 UTC, when today's
`recovery_repo` sanitizer deployed, and zero have occurred since.

---

## 24. Correction: §23 claimed a result that does not exist

§23 above reported the plan improving and treated that as proof. It was not. The job's
actual output, at
`/data/atlas_data/jobs/job_b370b60a-a258-4f29-b47c-ff09149804b5/report.md`:

> **Answer:** "I don't have anything remembered about that yet. What SQL query should I
> run? Please provide your question or task so I can assist you. There's nothing for me
> to remember there."
>
> **Overall confidence: INSUFFICIENT** — 0 documents, 0 claims, 0 citations.

And the lifecycle line: `Job completed — 4/4 step(s) done` with `failed: 0`. All four
steps were no-ops. The activity log times step 2, the `sql_query` step, at **1.1 ms**
with `tools: []` — it never opened a database connection. This is the same false-success
pathology the audit documents, reproduced in the audit's own write-up.

Cause, precisely: the service started at 20:28 IST; the `args`-required planner fix
landed at 20:34. The job planned at 20:29 and therefore ran on the **old** planner. The
plan it produced was better in shape only.

### What is actually true, measured after the fix

Run in-process against the live `qwen3:4b`, bypassing the undeployed service:

| | Result |
|---|---|
| Plan | `source=llm`, 111.5 s, 6 steps |
| SQL emitted | `SELECT task_id, task_type, status, error, started_at, worker_id FROM scheduler.task_runs WHERE status='failed' AND error LIKE '%JSON serialization error%' ORDER BY started_at DESC LIMIT 10` |
| Executed against `source="atlas"` | **Yes — 0.04 s** |
| Outcome | **`error` — `column "task_type" does not exist`** |

So three of four links hold. The planner emits concrete arguments; the routing to Atlas's
own Postgres works; the query runs in 40 ms. The fourth link fails: the model guessed a
column. `task_type` lives on `scheduler.tasks`, not `scheduler.task_runs`, whose real
columns are `id, task_id, status, started_at, finished_at, result, error, worker_id`. The
`LIKE '%JSON serialization error%'` predicate would also have matched nothing — the real
text is `Object of type set is not JSON serializable`.

This failure is strictly better than the previous one. `outcome=error` with a reason is a
retryable signal; "What SQL query should I run?" marked `done` is not. But it is still
not a result, and the honest score for the end-to-end north-star test remains **0**.

### The repair loop, and why it timed out

The obvious fix is to feed the error back and let the model correct itself. Tried it. The
schema lookup was instant and correct — `plug.schema("scheduler.task_runs")` returned the
eight real column names in 40 ms, including the `secret` flag per column. The repair
*prompt* then **timed out after 330 s** and produced nothing.

That is §20's finding appearing a second time, independently: the request was free-form
("reply with only the corrected SQL"), so generation ran away exactly as the unconstrained
planner did at 277 s. **Any** LLM call on this hardware must be grammar-constrained or it
will not return. A self-repair loop built on free-form prompting would simply hang.

### The actual next step, and it is cheap

The model should never have been guessing. The schema is available deterministically in
40 ms from a capability Atlas now has. The fix is to resolve the relevant table schemas
*before* planning and put the real column names in the prompt, rather than hoping the
model recalls them and paying 111 s per guess. Deterministic grounding beats a smarter
model here, which is the same lesson as §20 and §22: on this hardware, every token the
model does not have to invent is a token that cannot be wrong.

Revised ordering: **J5 (schema grounding before planning)** now precedes J3, because
without it the retry ladder J3 builds has nothing correct to converge on.

---

## 25. J5 — schema grounding, and the two defects it exposed

`atlas/sql/schema_digest.py` resolves the real columns of the tables an objective is
about and puts them in the planner prompt. Selection is deterministic token overlap
against the table catalog — no second LLM call, because a round trip costs ~111 s here
and a catalog query costs 0.24 s. The digest is hard-capped at 1.2 KB and returns `""`
whenever the catalog is unreachable or nothing matches, so grounding can never make
planning worse than not having it. Wired at bootstrap with `bind_schema_source()`,
mirroring the existing `bind_web_search()` late-binding, because plugins load after the
planner is constructed.

Measured on the live database: **0.24 s, 472 characters, exactly four tables**
(`scheduler.task_runs`, `scheduler.tasks`, `audit.logs`, `scheduler.schedules`) for the
north-star objective, and empty for "what is the capital of France".

### The prompt was the cause of the hallucination

Worth recording, because it corrects §24's framing. The old prompt said in prose that
"`scheduler.task_runs` has columns task_id, status, error, started_at, worker_id and
`scheduler.tasks` has task_type, status, last_error". The model did not invent
`task_type` out of nothing — it **merged two column lists that appeared in one
sentence**. Hand-written schema hints in prose are not just stale, they actively induce
this failure. That sentence is deleted and a test now asserts it never returns.

### Three live runs, same prompt, same model

| | Columns | Intent | Executes? | Result |
|---|---|---|---|---|
| Before J5 | **`task_type` invented** | `sql_query` ✓ | **No** — `column "task_type" does not exist` | none |
| J5, first run | **all real** ✓ | **`recall`** ✗ | **No** — SQL handed to memory lookup | none |
| J5 + intent repair | **all real** ✓ | `sql_query` ✓ | **Yes — 4/4 ran clean** | `empty` (0 rows) |

The middle row is the interesting one. Grounding fixed the columns and simultaneously
broke the labelling: the model latched onto the schema block and emitted correct SQL
inside `recall` steps, which would have been passed to memory lookup and silently
produced nothing. The arguments a step carries are unambiguous evidence of what it is,
so `_repair_intent` now routes on them — SQL implies `sql_query`/`sql`, code implies
`run_python`/`python`. Deterministic, free, and it cannot time out, which matters more
than usual here because the alternative (prompting harder) costs three minutes per
attempt.

The final run emits real joins over real columns:

```sql
SELECT t.id, t.task_id, t.status, t.result, t.error, s.status AS scheduler_status, s.payload
FROM scheduler.task_runs t JOIN scheduler.tasks s ON t.task_id = s.id
WHERE t.status = 'failed' AND t.error LIKE '%JSON serialization error%'
  AND t.finished_at >= NOW() - INTERVAL '1 day'
```

Schematically correct, executes without error — and returns **0 rows**, because the
literal `'%JSON serialization error%'` does not appear anywhere. The real text is
`Object of type set is not JSON serializable`.

### Where this leaves the honest score

End-to-end north-star result: still **zero**. But the failure has moved three times,
each time to a strictly better place: *cannot look* → *invalid column* → *wrong step
type* → *valid query, guessed string literal*. The remaining defect is the same shape as
the one J5 just fixed, one level down: the model is guessing at a **data value** it
could look up. The symmetric fix is to offer distinct values for the columns an
objective is about, exactly as columns are offered now — with the caveat that error text
is free-form and must pass the `logs_plugin` redaction before entering a prompt.

And `empty` must itself become a retry signal, which is J3. Four steps returning 0 rows
currently all report `done`, which is how a job with no findings still calls itself
`completed`.

Tests: `tests/test_planner_schema_grounding_j5.py`, 21 cases covering selection,
budget, secret-column omission, graceful degradation, the deleted prose hint, and
intent repair. 66 pass across the job/self-inspection/grounding suites.

---

## 26. J6 (value grounding) and J3 (honest completion)

### J6 — the model was guessing data, not just schema

§25 ended with the planner emitting schematically perfect SQL that matched zero rows,
because it filtered on `error LIKE '%JSON serialization error%'` — the *user's* phrasing
— when the stored text is `TypeError: Object of type set is not JSON serializable`. So
the same treatment as columns, one level down: `schema_digest` now samples the values
that actually occur in the low-cardinality columns an objective asks about.

Three things made this non-trivial, each measured rather than guessed:

1. **Sampling order matters more than sample size.** A bounded scan without ordering
   returns the *oldest* rows, so the first version surfaced only the long-standing
   `no handler registered` errors and the model never saw today's. Adding a 7-day
   recency window fixed the content.
2. **Ordering cost 27.8 s.** `scheduler.task_runs` has no index on `error` or
   `finished_at`, so finding non-NULL errors is a sequential scan either way. A full
   `ORDER BY ... DESC` cost 27.8 s and the window still cost 12.4 s. Value
   distributions change slowly, so this is **cached** (15-minute TTL) rather than made
   cleverer: 12.4 s cold, **0.19 s warm**. A cache is the honest answer when the query
   is unavoidably expensive and the result is stable.
3. **Only successes are cached.** A failed probe and a genuinely empty column are
   indistinguishable at the call site, so caching the empty result would pin a transient
   database hiccup into the planner prompt for 15 minutes.

Every sampled value passes through the `logs_plugin` redactor before entering the
prompt. These are free-text values going straight into an LLM context — the one path
where an accidentally logged credential would leave the machine.

The digest the model now receives, in 0.19 s warm:

```
scheduler.task_runs(id, task_id, status, started_at, finished_at, result, error, worker_id)
  scheduler.task_runs.error actual values: TypeError: Object of type set is not JSON
  serializable; LLMLaneBusy: LLM lane busy (2/2) — background deferred; no handler
  registered for task_type 'worker_tick'; ...
scheduler.schedules.task_type actual values: worker_tick; fundamental_summary_publish;
  lab_loop0_s11_canary; provider_health_tick; embed_backfill; host_guard_tick
```

**Partial result, stated honestly.** The grounding reaches the model and it *uses* the
values — one run produced `WHERE task_type IN ('worker_tick', 'fundamental_summary_publish',
'lab_loop0_s11_canary', 'provider_health_tick', 'embed_backfill', 'host_guard_tick')`,
copying all six sampled values verbatim, and **returned 339 rows: the first non-empty
query result in this whole exercise.** A later run quoted the real error text verbatim
inside a `react` step. But in `WHERE` clauses on the error column the model still
reverted to paraphrasing the objective. The prompt now states the rule explicitly
("when a line lists actual values, any filter on that column MUST use one of those
exact strings; do not build a LIKE pattern from the objective's words"), which is
untested against the model — the schema-grounding instruction took three measured runs
to land, and this one has had none.

### J3 — a step that produced nothing no longer reports success

The defect, verbatim from job `b370b60a`: `completed — 4/4 step(s) done, failed: 0`,
with an answer that was four no-op replies concatenated.

`_Outcome` gains `productive` and `gap_reason`. Three handlers now set them: a SQL step
with no `sql`, a SQL step whose query matched no rows, and a `recall` that remembers
nothing. Chat is unaffected — it only ever reads `answer`, so "the query returned no
rows" is still a perfectly good reply to a person.

In the Job Engine a non-productive step takes a third path, neither `done` nor `error`:

* it **reuses the retry ladder** (a wrong predicate is often right on the second
  attempt), consuming attempts rather than being retried forever;
* on exhaustion it lands in `failed` with `error = "no usable result: <reason>"`, so the
  **job** reports `failed` instead of claiming it completed;
* the activity feed records `state="gap"` with the reason, and `_finalize` collects a
  `gaps` list naming each step, its capability, its reason and its attempt count — so
  "failed" is actionable rather than merely negative.

There is deliberately no new `gap` step status: `job_steps_status_check` permits only
pending/running/done/failed/blocked/skipped, and inventing a seventh value would need a
migration deployed in lockstep with the code. `failed` plus a named gap is honest today;
a distinct status is a later refinement, not a prerequisite.

11 tests in `tests/test_honest_completion_j3.py`, 31 in
`tests/test_planner_schema_grounding_j5.py`.

### Scoreboard

| | Before today | Now |
|---|---|---|
| Can Atlas read its own database? | No | Yes, read-only, 4 safety layers |
| Can Atlas read its own logs? | No | Yes, redacted |
| Planner on this hardware | times out at 60 s, falls back | 110–186 s, `source=llm` |
| Columns in generated SQL | invented | resolved, 0.19 s warm |
| Data values in generated SQL | invented | sampled (partial: used in `IN`, not yet in `LIKE`) |
| Queries that execute | none | yes; one returned 339 rows |
| A step that produced nothing | `done` | `failed` with a named gap |
| End-to-end north-star answer | none | **still none** |

The last row is the one that matters and it has not moved. What has moved is that every
link in the chain now either works or fails loudly, which is the precondition for the
last one working.
