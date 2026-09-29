# A0 — Agent Kernel

> **Status:** implemented, 2026-09-29  
> **Tests:** `tests/test_agent_kernel_a0.py` (10 pytest cases; acceptance checks A0.1–A0.15 are not one case each) and `tests/test_agent_kernel_web_search.py` (8 pytest cases)  
> **Scope:** advice, research, and observation only

The Agent Kernel is Atlas’s first persistent operating loop. It watches for missing decision evidence, investigates with capabilities Atlas already has, and either resolves the question or writes down why it cannot.

It does not place orders, change strategy, allocate capital, or promote its own conclusions into validated lessons.

---

## Operating loop

Each tick follows one path:

```text
OBSERVE
  ↓
IDENTIFY WORK / UNCERTAINTY
  ↓
PRIORITIZE
  ↓
PLAN
  ↓
USE AVAILABLE CAPABILITIES
  ↓
INVESTIGATE / EXECUTE
  ↓
VERIFY
  ↓
RECORD RESULT
  ↓
LEARN FROM RESULT
  ↓
UPDATE STATE
  ↓
SCHEDULE NEXT WORK
```

One investigation runs at a time. A failed task stays on disk with a reason, the capabilities that were tried, the last error, what is still missing, and the next action. The same task resumes when the missing capability appears. A later plan does not repeat an approach that already failed for the same reason.

State lives in `{data_dir}/agent_kernel/state.json`. A restart loads that file and continues.

---

## What the kernel owns

The kernel owns observation, work detection, priority, task creation, planning, capability selection, execution orchestration, verification, failure handling, persistence, retry and defer decisions, and next-work scheduling.

It does not own:

* market strategy
* trading decisions
* LLM-generated BUY/SELL
* domain calculations as a source of truth (it may run a deterministic calculation from cited inputs)
* evidence truth
* learning promotion
* capital allocation

Cognitive Core is a tool. It interprets an evidence packet. It does not place orders. Buy/sell language in a Core reply is stripped before the result is stored. Lessons written from a cycle are provisional. `validated_lesson` stays false.

Existing pieces are reused: the uncertainty queue, local bar and research files, the capability catalog, JobPlanner when an objective has no evidence ladder, Cognitive Core, Experience OS when it is wired, and the activity journal. The kernel does not add a second planner, a second experience database, or a second cognitive core.

---

## Capability ladder

For each missing requirement the planner walks:

| Level | Capability | What it uses |
|------:|------------|----------------|
| 0 | `local_market_store` | Durable bars, evidence-completeness, research files |
| 1 | `knowledge_search` | Knowledge / local research dossier |
| 2 | `structured_provider` | Structured market or fundamental payload |
| 3 | `web_search` / `news_search` | External evidence when enabled |
| 4 | `research_scientist` | Existing research loop |
| 5 | `alternative_source` | A different source for the same requirement |
| 6 | `cognitive_core` | Interpretation only, after evidence is collected |
| 7 | capability gap | Honest stop |

Also available to the planner: `python_calculation` and `experience_lookup`.

A sector name is not a historical price series. Relative strength is calculated only when both price history and a sector series are present. A null PE stays missing. Manufactured evidence is rejected and the task ends `FAILED`.

Level 3 calls Atlas's existing search plugin (`atlas.plugins.search_plugin`, DuckDuckGo HTML provider) when `allow_external` is true and that client is configured. There is no separate news-search provider, so `news_search` stays `CLIENT_NOT_CONFIGURED` instead of being treated as web search. Snippets are not copied into prices, PE, or sector series.

---

## Priority

Work is not FIFO.

| Class | Meaning |
|-------|---------|
| P0 | Integrity, safety, data corruption, an active decision blocker, an unresolved critical outcome |
| P1 | Information that can change an active decision, including material unknowns from the uncertainty queue |
| P2 | Useful knowledge, stale knowledge, follow-up outcome checks |
| P3 | Curiosity and background enrichment |

If any P0–P2 work is runnable, P3 waits. Each waiting task keeps `RETRY_SCHEDULED` (or another non-silent status) plus a next action.

---

## Task statuses

Every task reaches one of:

```text
SUCCESS
PARTIAL
BLOCKED
CAPABILITY_GAP
WAITING_FOR_EVENT
DEFERRED
RETRY_SCHEDULED
FAILED
ABANDONED
PLANNING_FAILED
UNVERIFIED
```

`ACTIVE` is only the in-progress mark during a tick.

Non-success records include:

```text
reason
attempt_count
attempted_capabilities
last_error
missing_requirement
next_action
next_retry_at
```

Verification failures are `PARTIAL` or `UNVERIFIED`, not `SUCCESS`. If the planner cannot produce a safe plan, the status is `PLANNING_FAILED` with an explanation.

Lineage stored on a task, when the ids exist:

```text
episode_id → work_id → decision_id → cognitive_result_id
          → prediction_id → experience_id → learning_record_id → lesson_id
```

---

## Modes

| Mode | Behavior |
|------|----------|
| `tick` | One investigation. This is the worker default. |
| `event` | Run the highest-priority due task immediately. |
| `deep` | Up to two investigations. |
| `wait` | Sleep until a retry time, a capability change, or new observed work. |

The worker service class is batch, with a 10-minute interval, so it does not compete with realtime market workers.

---

## Where the code lives

| Path | Role |
|------|------|
| `atlas/agent_kernel/kernel.py` | Operating loop |
| `atlas/agent_kernel/planner.py` | Deterministic ladder; JobPlanner only when there is no evidence ladder |
| `atlas/agent_kernel/bus.py` | Capability descriptors and the evidence bus |
| `atlas/agent_kernel/local_evidence.py` | Read-only local bars, research dossier, completeness |
| `atlas/agent_kernel/web_search.py` | Thin adapter over the existing `SearchPlugin` (`search_web` → DuckDuckGo). Not a second search stack. |
| `atlas/agent_kernel/safety.py` | Refuses order and strategy-control capabilities; strips orders from Core advice |
| `atlas/agent_kernel/models.py` | Work records, statuses, lineage |
| `atlas/agent_kernel/eod.py` | Evening-report section |
| `atlas/agent_kernel/worker.py` | Persistent worker `agent_kernel` |
| `tests/test_agent_kernel_a0.py` | Acceptance checks A0.1–A0.15, covered by 10 pytest cases |
| `tests/test_agent_kernel_web_search.py` | Production `web_search` wiring: resolve, provenance, gap, no request when disabled, resume, safety |

Wiring:

* Worker registered in `atlas/kernel/bootstrap.py`
* Mission template `agent_kernel` in `atlas/missions/templates/builtins.py`
* Market Intelligence program member, so an already-running program gains it on the next boot
* Config in `config/defaults.yaml` under `agent_kernel`
* Evening digest in `atlas/investment/reports.py` adds **Autonomous agent** when `agent_kernel/state.json` exists

Default config:

```yaml
agent_kernel:
  enabled: true
  action_scope: advice_research_observation
  mode: tick
  max_investigations_per_tick: 1
  allow_external: true
  never_orders: true
```

An action scope outside advice / research / observation is refused. The worker will not tick as `live_orders`.

---

## What the tests demonstrated

`tests/test_agent_kernel_a0.py`:

| Check | Result |
|-------|--------|
| A0.1 Observation | An inbox file creates work. No operator job is required. |
| A0.2 Priority | A P1 decision blocker runs before a P3 curiosity item. |
| A0.3 Planning | The HBLPOWER question becomes a multi-step ladder plan. |
| A0.4 Routing | One investigation uses local store, knowledge, web, calculation, and Cognitive Core. |
| A0.5 Web | When sector history is withheld, web search is attempted. |
| A0.6 Verification | `UNVERIFIED` and `PARTIAL` are distinct from `SUCCESS`. |
| A0.7 Honest failure | Missing sector history becomes `CAPABILITY_GAP` for `durable_sector_OHLCV_provider`. No relative-strength number is written. |
| A0.8 No silent wait | Non-success tasks carry a reason and a next action. |
| A0.9 Failure memory | The same failed scenario does not call web search again. The reason cites the previous failure. |
| A0.10 Recovery | Supplying the sector series resumes the same task id. |
| A0.11 Experience | Gap and success both write a provisional experience. |
| A0.12 Cognitive Core | A reviewed interpretation is stored. BUY/SELL text is removed. |
| A0.13 Restart | A new kernel process loads the capability-gap task from disk. |
| A0.14 Production slice | COALINDIA: local bars (424.1), sector name from the research dossier, cited news, missing PE recorded, then completion when a cited PE arrives. Outcome observation is scheduled. |
| A0.15 Safety | `broker_order` is refused. Worker scope `live_orders` is refused. |

The COALINDIA slice uses the same loop as production, with fixture files shaped like the live bar store, research dossier, evidence-completeness record, and uncertainty queue. It does not place a trade.

`tests/test_agent_kernel_web_search.py` covers the live capability path: resolve when a search client is configured, provenance on a real query shape, a task that needs web evidence, a recorded gap when the provider is down, no network call when `allow_external` is false, resume of the same task when the provider returns, and refusal of order capabilities. One case calls the existing DuckDuckGo provider.

---

## Evening report

When kernel state exists, the evening digest includes:

```text
AUTONOMOUS AGENT

Current objective
Completed autonomous tasks
Investigations
Successful resolutions
Failed investigations
Capability gaps
New hypotheses
Experiences created
Lessons proposed
Waiting for
Next autonomous action
```

Reports with no kernel state omit the section.

---

## What a live tick will do

On boot, Market Intelligence reconciliation starts the `agent_kernel` mission if that program is already running.

A tick observes at most one HIGH pending uncertainty-queue item, plus anything dropped in `agent_kernel/inbox`. It tries local files first. If the required series or fundamental is absent, it records a capability gap and a provisional experience. It does not invent the missing number. With `allow_external` true, `web_search` calls the existing search plugin and stores the query, provider, URLs, and status on the task. `news_search` stays unavailable until a separate news provider exists.

PLC.A, SMA/RSI V1 control, paper/live isolation, and the LLM never-orders rule are unchanged. The kernel has no order path.

---

## Operating observation (2026-09-29 night)

Implementation, tests, and this document close the question “is the Agent Kernel implemented?” No further Agent Kernel task is open tonight. Let the worker run.

The next proof is tomorrow’s evening digest, read as an operating trace, not as a “feature exists” confirmation, and not as a git diff. The question that section should answer:

```text
Did Atlas independently observe a real uncertainty
  → investigate with the capabilities it actually has
  → obtain and verify evidence
  → record the result
  → schedule what happens next?
```

That trace is the **AUTONOMOUS AGENT** block: current objective, completed tasks, investigations, resolutions and failures, capability gaps, experiences, and the next autonomous action. Active implementation work stays on the equity horizon audit and F&O attribution.
