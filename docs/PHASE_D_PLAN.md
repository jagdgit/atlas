# Phase D — Decision Engine + applied persistent Missions (implementation plan)

> **Open items / leftovers / known issues:** tracked centrally in **[`docs/OPEN_ITEMS.md`](OPEN_ITEMS.md)**
> (Phase-D items will be `OI-D*`). When this plan says "deferred", the actionable item lives there.
>
> **Status:** 🟡 **DRAFT — ready to start D-Core (2026-07-19).** Derived from `docs/ATLAS_OS_ROADMAP.md`
> §5.5 (**Decision Engine — Kernel Service**), §6 (Phase D), §8 (`decision.decisions`), and §9 Q1/Q7
> (deterministic core, operator-created missions). Builds on **Phase 0** (Storage, Asset Store,
> Capability Registry, Clock, durable event bus + `audit.events` + Notifier), **Phase A** (Missions +
> arbitration fields, Workers + WorkerManager, Scheduler, Configuration, Templates), **Phase B**
> (Engineering Intelligence), and **Phase C** (Global Knowledge OS, Consolidator, Coverage, **Policy
> store**, Personal Intelligence, Owner Knowledge Mission). **Phases 0/A/B/C are complete.**
>
> **Operator decisions confirmed (2026-07-19):** (1) build **D-Core** (Decision Engine + human-gate +
> RM arbitration) **no-compromise first**, then the **Paper-Trading mission (simulation-only)** as the
> flagship end-to-end gate; other watchers are follow-ons. (2) **one engine, many missions** — a
> generic typed `Decision` core with **per-mission-type deterministic `decision_rule` plugins**.
> (3) the human-approval gate **records every decision** but **requires approval only for
> side-effecting/external actions** (a unified approval queue exists, ready for when real-world actions
> arrive; simulation + retrieval flow freely). (4) Paper Trading uses a **pluggable `MarketDataReader`
> with a deterministic fixture/replay feed first**; a live feed is a config-swappable reader later.
>
> **Goal:** give Atlas the **shared brain** every Mission asks — *"what should I do next?"* — that
> combines Research + Engineering + Personal + **Policy arbitration** into an explainable, journaled,
> **recommend-only** `Decision` (deterministic core; LLM writes narrative *why* prose only), and prove
> it end-to-end with one long-running applied Mission (Paper Trading, simulation-only) that survives
> reboots, is live-configurable, notifies, and journals explainable decisions.
>
> **Not in Phase D:** real-money trading (simulation only, ever, in this phase); autonomous
> world-changing actions without an operator gate (P14); Atlas-proposed Missions (operator-created
> only, Q1); remote access (deferred); hot/warm/cold tiering (single-disk, deferred).

---

## 0. Guiding constraints (from the constitution, §3)

- **Decision Engine is a Kernel Service (R2), not an intelligence.** Every Mission needs "what next?";
  the engine belongs to Atlas itself and is shared by all Missions. It **consumes** the three
  Intelligences + Policy; it does not replace them.
- **P9 everything is explainable.** Every `Decision` is the canonical *"Explain this"* payload:
  `action, why (rule), evidence_refs, knowledge_refs, experience_refs, config_ref, decision_rule,
  model_versions, confidence, alternatives_rejected`, journaled to `decision.decisions`. Nothing the
  engine outputs is a black box.
- **Q7/A5 deterministic core, LLM narrative-only.** All *choices* are deterministic (rules + scoring)
  so decisions are reproducible and auditable (critical for trading). The LLM is used **only** to
  render the human-readable narrative of an already-made decision; it never picks the action.
- **P14 (new, proposed) — Atlas recommends; the operator decides.** No autonomous behavior change
  that acts on the world without a human gate. The engine **recommends**; side-effecting actions become
  **approval proposals** the operator confirms; everything is **reversible** and journaled. (Formalizes
  the existing "No autonomous behavior change without a human gate" principle.)
- **P10 no irreversible action without the operator.** Paper Trading is **simulation-only** — a virtual
  portfolio, never a broker order. Even so, decisions are journaled and the gate mechanism is wired for
  the day a real-world action is introduced.
- **P12/P13 knowledge is global + cumulative.** Decision outcomes that constitute learning (e.g. a
  strategy's realized P&L) flow back as **experiences** through the C.6 consolidator — one engine
  strengthening global knowledge, never a private per-mission memory.
- **P6 everything configurable + versioned.** Each Mission's decision behavior is driven by its
  **versioned mission config** (strategy params, risk constraints, instrument allow/deny, intervals);
  a `Decision` records the exact `config_version` it used.
- **P1 durability / P4 design-for-failure.** Applied missions are Persistent Workers on the Phase-A
  framework (short-task + checkpoint, supervised by the Worker Manager); a `kill -9` mid-run resumes
  from the last checkpoint, and the Scheduler's self-re-enqueue keeps them running across reboots.
- **A7 resource arbitration.** Cross-mission contention resolves by **weighted effective priority +
  hard budget caps** (no preemption yet); deadline urgency and importance act as boosts/tiebreaks.
- **P15 (new) — capability-gap honesty.** When the engine cannot choose an action because a needed
  capability/reader/data-source/rule is **absent**, it emits a **`capability_gap` recommendation**
  (naming exactly what is missing), journaled + notified to the operator — never a fabricated action.
  A gap is a recommendation to extend Atlas, not a guessed result.

---

## 1. Locked decisions (DD*)

| # | Decision | Rationale |
|---|----------|-----------|
| **DD1** | **D-Core first, then Paper Trading (sim-only) as the flagship e2e**; other watchers follow. | The Decision Engine is the reusable spine; prove it on the roadmap's stated acceptance mission before fanning out. |
| **DD2** | **One engine, many missions:** a generic typed `Decision` core + a **`DecisionRule` plugin registry** keyed by mission type. | Matches R2 (one shared engine); per-type deterministic scoring stays isolated + testable. |
| **DD3** | **Human-gate = record-all, approve-only-side-effecting.** Every decision is journaled; a `requires_approval` decision creates an **approval proposal**; simulation/retrieval decisions apply freely. | P14 without paralysing safe, reversible, sim-only work; the gate is ready when real-world actions arrive. |
| **DD4** | **Deterministic core; LLM narrative-only** (Q7/A5). Confidence is a deterministic function of score margin, not an LLM guess. | Reproducible, auditable, safe for trading. |
| **DD5** | **Policy becomes arbitration here.** The engine consumes `PolicyService.retrieval_influence`/`advice_influence` as **signed, bounded scoring terms** ("prefer RSI first"), not just retrieval nudges. | The C.5 store was built to *influence*; Phase D is where influence becomes a decision input (roadmap R5 note). |
| **DD6** | **Paper Trading market data = pluggable `MarketDataReader`, fixture/replay first.** OHLCV enters through the **Asset → Reader → Artifact** pipeline (P8/P11); a live feed is a config-swappable reader later. | Hermetic + deterministic tests now; no new pipeline; live data is additive. |
| **DD7** | **Cross-mission RM arbitration = weighted priority + hard budget cap** (A7), no preemption. Consume `budget`/`deadline`/`importance` beyond today's `max_concurrent_tasks`. | Start simple, refine empirically; avoids the complexity/risk of preemption. |
| **DD8** | **Decisions are global + journaled; learning flows back as experiences** (C.6), not private memory. | P12/P13 — one cumulative knowledge layer. |
| **DD9** | **Capability-gap honesty (P15):** a missing rule/reader/data-source/tool yields a surfaced `capability_gap` recommendation, never a fabricated action or a swallowed error. | Operator asked to be told what Atlas can't do so it can be extended; honesty over hallucination. |

---

## 1a. Building blocks (BB*) & cross-cutting rules (CC*)

- **BB-D1 `DecisionRequest`/`Decision` contracts** in `atlas/decision/contracts.py` — typed, versioned,
  serialisable; `Decision` is the full P9 record.
- **BB-D2 `DecisionRule` protocol + registry** — `score(request, context, influences, refs) ->
  list[ScoredOption]` (deterministic); registered per mission type (mirrors the reader/worker
  registries).
- **BB-D3 `decision.decisions`** (migration `0039`) — append-only journal of every decision (P9).
- **BB-D4 Approval gate** (`atlas/decision/approvals.py` + `decision.approvals`, migration `0040`) —
  `propose → approve/reject → apply → revert`, reversible + journaled (P14).
- **BB-D5 Mission arbiter** — cross-mission allocation from `effective_priority` + budget/deadline
  (A7), consumed by the WorkerManager/Scheduler admission path.
- **BB-D6 `MarketDataReader`** (`atlas/readers/market_data.py`) — fixture/replay OHLCV → artifact.
- **BB-D7 Virtual portfolio store** (`sim.portfolios`/`positions`/`trades`, migration `0041`) —
  sim-only accounting; applies decisions, computes realized/unrealized P&L.
- **CC-D1** Deterministic-only choices; LLM strictly behind a `narrate(decision)` seam that always
  falls back to deterministic prose (never blocks a decision).
- **CC-D2** Every decision resolves its inputs via the **capability registry** (not imports), so the
  engine is decoupled from concrete intelligences.
- **CC-D3** `model_versions` on every decision come from the **Capability Registry** (P2), never
  hardcoded.
- **CC-D4** Idempotent, resumable workers; a decision tick is bounded and checkpointed.

---

## 2. D-Core — the shared brain (built no-compromise first)

### D.1 — Decision Engine skeleton  ·  migration `0039`  ·  ✅ DONE
> **Delivered:** `atlas/decision/` (`contracts.py` — `DecisionRequest`/`ScoredOption`/`Decision` +
> `derive_confidence` softmax-margin confidence + action kinds `recommend`/`hold`/`capability_gap`;
> `rules.py` — `DecisionRule` protocol + `DecisionRuleRegistry` + `CapabilityGap` + the
> `apply_policy_influence` helper (DD5); `engine.py` — `DecisionEngine.decide` deterministic choice,
> policy folding, P9 record assembly, `requires_approval` on side-effecting options (P14), the honest
> `hold` and `capability_gap` outcomes (P15), and an LLM `narrator` seam that always falls back to
> deterministic prose). Persistence: migration `0039_decision.sql` (`decision.decisions`) +
> `DecisionRepository` (record/get/list/list_gaps). Tests: `tests/test_decision_engine.py` (9 hermetic
> — top-option choice + full P9 record, confidence margins, no-rule gap, rule-raised gap, hold,
> approval flag, policy reorder, narrator fallback, influence helper) + `tests/test_decision_repo.py`
> (2 live-DB — record/read-back + gap backlog). Not wired into bootstrap/API/CLI yet — that's D.5.

- **New** `atlas/decision/`: `contracts.py` (`DecisionRequest(mission_id, mission_type, config_version,
  context, now)`, `ScoredOption`, `Decision` = full P9 record), `engine.py` (`DecisionEngine`,
  `VERSION`), `rules.py` (`DecisionRule` protocol + `DecisionRuleRegistry`).
- `DecisionEngine.decide(request) -> Decision`: load mission + active config → gather refs → resolve
  the mission-type `DecisionRule` → deterministic scoring → assemble `Decision` (top option = `action`,
  losers = `alternatives_rejected`, deterministic `confidence` from score margin) → **persist to
  `decision.decisions`** → emit a `DecisionMade` event.
- Migration `0039_decision.sql` — `decision.decisions` (id, mission_id, config_id, mission_type,
  action JSONB, why, decision_rule, rule_version, evidence_refs/knowledge_refs/experience_refs JSONB,
  model_versions JSONB, confidence, confidence_score, alternatives_rejected JSONB, requires_approval,
  status, created_at).
- **Capability-gap outcome (P15):** if no `DecisionRule` is registered for the mission type, or a rule
  reports a required capability/reader/data-source is absent, the engine returns a `Decision` with
  `action.kind = "capability_gap"` naming what's missing (and consulting the Capability Registry),
  rather than raising or fabricating — journaled + emitted as a notable event for the operator.
- **Acceptance:** a trivial registered rule (e.g. a `hello`/echo rule) produces a persisted, fully
  provenance-stamped `Decision`; a mission type with **no** rule yields a `capability_gap` decision
  (not an error); hermetic unit tests for scoring, confidence, the P9 record shape, and the gap path.

### D.2 — Intelligence + Policy composition (arbitration)  ·  ✅ DONE
> **Delivered:** `atlas/decision/context.py` — `IntelligenceContext`, a lazy, read-only access layer
> over Engineering (`list_findings`/`recommend`/`search`), Personal (`profile`/`skills`) and Research
> (`research`) + raw knowledge, resolved from injected capabilities (CC-D2). Reaching for an
> unavailable intelligence raises `CapabilityGap` → an honest `capability_gap` decision (P15). The
> `DecisionRule.score` protocol now takes `(request, context)`; `DecisionEngine` builds the context
> per-decision and injects the three intelligences (`engineering`/`research`/`personal`/`knowledge`,
> any may be `None`). Policy arbitration (DD5) folds signed influence into scoring and is named in the
> `why` (P9). Tests: `tests/test_decision_composition.py` (5 hermetic, stubbed intelligences —
> findings+profile refs on the decision, policy `prefer` flips equally-scored options, complete
> decision with the LLM off, and two capability-gap paths). Wiring into bootstrap is D.5.

- The engine assembles decision inputs from the three Intelligences via capabilities:
  Engineering (`IntelligenceService.recommend`/`list_findings`), Research (`ResearchService.research`
  where a mission needs fresh facts), Personal (`PersonalService.profile` for
  preferences/constraints), and **Policy** (`retrieval_influence`/`advice_influence`) folded in as
  **signed, bounded scoring terms** (DD5) so "prefer/avoid/trust/distrust" actually reorders options.
- Deterministic scoring assembles `knowledge_refs`/`experience_refs`/`evidence_refs`; the LLM `narrate`
  seam (CC-D1) renders the human `why` prose from the already-chosen action, with deterministic
  fallback.
- **Acceptance:** given fixed inputs, a policy `prefer X` **verifiably** lifts option X above an
  equally-scored Y and the rule id appears in the decision's explanation; LLM-off still yields a
  complete decision. Hermetic tests with stubbed capabilities.

### D.3 — Human-approval gate  ·  migration `0040`  ·  ✅ DONE
> **Delivered:** `atlas/decision/approvals.py` — `ApprovalService` (the P14 human gate) +
> `ApplierRegistry`/`ActionApplier` protocol + `ApprovalError`, over `decision.approvals`
> (migration `0040`; single-row state machine `proposed → approved → applied → reverted`, or
> `→ rejected`, with `before`/`after` snapshots for reversibility). `propose(decision)` opens the gate
> **only** when `decision.requires_approval` (DD3 — read/advice/sim bypass it); `approve`/`reject`
> record who/when; `apply` runs the mission-type's registered `ActionApplier`, capturing before/after
> so `revert` can restore prior state; every transition emits an event (P9). Approving something with
> **no registered applier** raises an honest `ApprovalError` (the P15 boundary — add the applier).
> `DecisionEngine` gained an optional `approvals` dep and **auto-proposes** on a side-effecting
> decision. Tests: `tests/test_approvals.py` (10 hermetic — full lifecycle, reject blocks apply,
> illegal transitions, no-applier honesty, pending queue, engine auto-propose only for side-effecting)
> + `tests/test_approval_repo.py` (2 live-DB — lifecycle + snapshots, pending queue). Wiring into
> bootstrap + the operator API is D.5.

- **New** `atlas/decision/approvals.py` (`ApprovalService`) + migration `0040_decision_approvals.sql`
  (`decision.approvals`: id, decision_id, mission_id, action JSONB, status
  ∈ `proposed|approved|rejected|applied|reverted`, requested_at, decided_by, decided_at, note,
  before/after JSONB for reversibility).
- `propose(decision)` (auto-created when `decision.requires_approval`), `approve/reject`, `apply`
  (via a registered `ActionApplier` for the mission type), `revert` — all journaled (P9/P14),
  reversible. Non-side-effecting decisions skip the gate (DD3).
- **Acceptance:** a `requires_approval` decision creates a `proposed` approval and does **not** apply
  until `approve`; `apply` then `revert` restores prior state; a sim/retrieval decision bypasses the
  gate. Hermetic tests.

### D.4 — Cross-mission Resource Manager arbitration (A7)  ·  ✅ DONE
> **Delivered:** `atlas/core/resources/arbiter.py` — `MissionArbiter` (+ `MissionDemand`,
> `ArbitrationVerdict`, `demand_from_mission`), the cross-mission layer that complements the machine-
> level `ResourceManager`. It scores each competing mission by `effective_priority` + a **bounded
> deadline-urgency boost** (grows toward the deadline; full when overdue) + **anti-starvation aging**
> (each deferral raises standing, reset on admission), with **importance** then `mission_id` as
> deterministic tiebreaks. Pure `rank`/`select` prove the ordering under contention; the stateful
> `try_admit`/`release` gate enforces **hard per-mission caps** (`max_concurrent_tasks`) and an optional
> **global** concurrency cap. Wired into `WorkerManager.worker_tick` (replacing the ad-hoc per-mission
> in-flight gate); a missing/uncapped mission is admitted exactly as before (back-compatible). Machine-
> level `ResourceManager.can_admit` is left intact as the complementary layer (cost/RAM/LLM), not
> re-litigated here. Tests: `tests/test_arbiter.py` (10 hermetic — priority order, deadline urgency,
> overdue, importance/id tiebreaks, select slot-filling + hard-cap skip, per-mission + global gate,
> aging-not-starved, projection; + 1 live-DB through a real `WorkerManager` proving a lower mission is
> deferred under a global cap and ticks once the slot frees). Two existing worker tests updated to the
> arbiter's state. Registering the arbiter as a kernel capability is folded into D.5 wiring.

- Add a **mission arbiter** feeding admission: extend the WorkerManager/Scheduler admission path (and
  `ResourceManager.can_admit`) to weigh **`effective_priority` + hard per-mission budget caps**, with
  deadline urgency as a bounded boost and `importance` as a tiebreak. Consumes the `budget`/`deadline`/
  `importance` fields that exist on `mission.missions` but are unused today (only `max_concurrent_tasks`
  is honoured now).
- **Acceptance:** under contention two missions with equal load but different priority/deadline get
  allocated in the expected order; a mission over its hard budget cap is deferred, not starved
  indefinitely. Hermetic tests on the arbiter; a live-DB test through the WorkerManager.

### D.5 — Surfaces + wiring  ·  ✅ DONE
> **Delivered:** `DecisionEngine` + `ApprovalService` + the cross-mission `MissionArbiter` are now
> **kernel services** — built in `bootstrap.py` (engine composes policy/engineering/research/personal/
> knowledge; `versions_provider` stamps real capability versions; approvals auto-propose on
> side-effecting decisions), registered on the container and the capability registry (`kind="kernel"`),
> and the shared arbiter is injected into the `WorkerManager`. REST (`tags=["decision"]`, D.5):
> `GET /v1/decision/decisions` (+ `?mission_id/mission_type/action_kind`), `GET .../decisions/{id}`
> (the full P9 "explain this" record), `GET .../gaps` (P15 backlog), `GET .../approvals` (+ `?status`),
> `GET .../approvals/{id}`, and `POST .../approvals/{id}/approve|reject|apply|revert` (illegal
> transitions → 409). Engine gained read passthroughs (`list_decisions`/`get_decision`/`list_gaps`);
> `ApprovalActionRequest` schema added. CLI: `atlas decision list|show|gaps` and
> `atlas approvals list|pending|show|approve|reject|apply|revert`. Tests: `tests/test_api.py`
> (+8 — list/filter, explain round-trips the full P9 record, 404, gaps, approval lifecycle, 409, auth)
> and `tests/test_cli.py` (+5 — decision list/gaps/show, approval lifecycle, illegal transition). Live
> `build_application()` smoke confirms all three resolve with real capability versions.

- Wire `DecisionEngine` + `ApprovalService` into `atlas/kernel/bootstrap.py` (container +
  **capability registry**, `kind="kernel"`); register any `decision_tick` handler if needed.
- API: `GET /v1/decision/decisions` (+ `/{id}` = the "Explain this" payload), `GET/POST
  /v1/decision/approvals`, `POST .../approve|reject|apply|revert`. Schemas in `atlas/api/schemas.py`.
- CLI: `atlas decision` (list/explain) + `atlas approvals` (list/approve/reject/apply/revert).
- **Acceptance:** hermetic API + CLI tests; the explain payload round-trips the full P9 record.

---

## 3. D-Missions — applied persistent missions (on the foundations)

### D.6 — Paper-Trading Mission (simulation-only)  ·  migration `0041`  ·  **flagship e2e**
- **`MarketDataReader`** (`atlas/readers/market_data.py`, BB-D6): fixture/replay OHLCV asset → artifact
  (Asset→Reader→Artifact, P8/P11); config-swappable to a live feed later (DD6).
- **Indicator extraction** (`atlas/trading/indicators.py`): deterministic SMA/EMA/RSI/MACD/… → signals
  fed as `DecisionRequest.context` (ephemeral; not knowledge candidates).
- **`StrategyDecisionRule`** plugin (BB-D2): deterministic entry/exit rules → `Decision`
  (`buy|sell|hold` + sized), **policy-influenced** (instrument allow/deny, prefer/avoid) and
  **constraint-bounded** (max position, max exposure) from the versioned mission config + live operator
  inputs (`worker.inputs`).
- **Virtual portfolio** (BB-D7, migration `0041_sim_trading.sql`: `sim.portfolios`/`positions`/`trades`)
  — applies decisions (sim is not world-side-effecting → flows freely, DD3), tracks cash/positions and
  realized/unrealized P&L.
- **Learning loop:** realized outcomes per strategy flow back as **experiences** (C.6 consolidator),
  growing confidence over time (P13).
- **`PaperTradingWorker`** (`atlas/workers/paper_trading.py`): each tick → read market data → indicators
  → `DecisionEngine.decide` → apply to virtual portfolio → journal the explainable decision → notify on
  notable events (fills, drawdown, targets). Bounded, checkpointed, reboot-safe.
- **`paper_trading` template** filled in (`atlas/missions/templates/builtins.py`), with config schema
  (instruments, strategy params, risk constraints, interval, feed selection) in
  `atlas/configuration/schemas.py`.
- **Acceptance (the Phase-D gate):** point the mission at a fixture feed → it runs many ticks producing
  explainable journaled decisions, updates the virtual portfolio, respects a live operator constraint
  (e.g. "don't trade SYM"), respects a policy (`avoid SYM2`), **survives reboot** (resumes from
  checkpoint), is **config-versioned** (an edit bumps the version and is picked up), and **notifies** on
  a notable event. Live-DB e2e + hermetic unit tests per component.

### D.7 — Research Watcher
- A `research_watcher` worker driving `ResearchService.research` on a schedule → summaries into the
  Knowledge OS; Decision Engine ranks/what-to-read-next; notify on notable findings. Reuses D-Core.

### D.8 — Job Watcher
- A `job_watcher` worker: sources → normalize postings (as assets/readers) → match against
  **Personal** profile + Policy → ranked matches → notify. Recommend-only (drafting, never applying).

### D.9 — Technology / Security Watcher
- A `technology_watch` / `security_monitoring` worker: dependency/CVE/breaking-change feeds → findings →
  Decision Engine prioritization → notify. (Two thin templates over one worker pattern.)

### D.10 — Atlas Self-Improvement Watcher
- A `self_improvement` worker over `atlas/eval/` benchmarks/regressions → findings + recommended
  actions (gated), surfaced on the Operations Dashboard.

### D.11 — Phase-D end-to-end gate
- One integration test proving a Decision-driven Mission (Paper Trading) running across reboots,
  live-configurable, policy-arbitrated, notifying, with every decision provenance-stamped (P9),
  gated where side-effecting (P14), and reversible; plus the per-item hermetic tests from D.1–D.10.

---

## 4. Proposed data-model additions

| Migration | Adds | Slice |
|-----------|------|-------|
| `0039_decision.sql` | `decision.decisions` (full P9 decision journal) | D.1 |
| `0040_decision_approvals.sql` | `decision.approvals` (human-gate: propose/approve/apply/revert) | D.3 |
| `0041_sim_trading.sql` | `sim.portfolios` / `sim.positions` / `sim.trades` (virtual portfolio) | D.6 |

> Market data enters through the existing **Asset Store** (fixtures as assets), so no dedicated
> market-data table; indicators/signals are ephemeral decision context. Watchers D.7–D.10 reuse
> existing schemas (knowledge/findings, personal, coverage) unless a specific need emerges.

---

## 5. Sequencing & method

Land each slice as its own commit with: (1) migration (if any) → (2) code → (3) hermetic tests →
(4) a live-DB smoke/e2e where it touches the DB → (5) doc update in this plan, exactly as Phases A/B/C.
D-Core (D.1→D.5) ships before any applied mission; Paper Trading (D.6) is the flagship gate; D.7–D.11
are incremental follow-ons.

---

## 6. Open items / deferrals (seed `OI-D*`)
- **OI-D1** Live market-data feed (real provider) as a swappable `MarketDataReader` (DD6 defers to
  fixtures first).
- **OI-D2** RM arbitration refinements beyond weighted-priority + hard cap (preemption, fair-share) —
  A7 says refine empirically.
- **OI-D3** Watchers D.7–D.10 are scoped but land after the Paper-Trading gate.
- **OI-D4** Real-world side-effecting appliers (e.g. actually posting a job application draft) stay
  behind the approval gate and are **out of scope** until explicitly requested (P14).

---

> **D.1 ✅ DONE** (`atlas/decision/` + `0039` + 11 tests). **D.2 ✅ DONE** (`IntelligenceContext`
> composition + policy arbitration + 5 tests). **D.3 ✅ DONE** (`ApprovalService` + `ActionApplier` +
> `0040` + 12 tests): propose → approve/reject → apply → revert, reversible + journaled (P14), gate
> bypassed for read/advice/sim (DD3). **D.4 ✅ DONE** (`MissionArbiter` + WorkerManager admission +
> 11 tests): effective_priority + deadline urgency + importance + hard/global caps + anti-starvation
> aging (A7). **D.5 ✅ DONE** (bootstrap capability wiring of decision/approvals/arbiter + decision/
> approval REST API + `atlas decision`/`atlas approvals` CLI + 13 tests). **D-Core complete. Next:
> D.6 — Paper-Trading Mission (simulation-only), the flagship D-Missions e2e.**
