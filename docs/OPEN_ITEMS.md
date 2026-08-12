# Atlas — Open Items, Leftovers & Known Issues

> **Purpose.** A single, living registry of *everything deferred* — intentional deviations, deferred
> features, tech/test debt, and known flakes — so nothing gets lost between phases. Each item has an
> **ID**, a **status**, where it was **introduced**, and the **target** phase/owner. Items are closed
> by referencing their ID in the commit/plan that resolves them.
>
> Companion to `ATLAS_OS_ROADMAP.md` (principles/architecture) and the `PHASE_*_PLAN.md` docs
> (per-phase scope). When a plan says "deferred", the actionable item lives **here**.
>
> **Last updated:** 2026-08-11 night — **OI-SELF0 Phase 4 landed** (Living RAG / identity-first chat). Soft influence (Phase 5) still deferred.

Legend — **Status:** 🔴 open · 🟡 partial/mitigated · 🟢 done · ⚪ won't-do/by-design
· **Priority:** P1 (do soon) · P2 (should) · P3 (nice-to-have)

---

## 1. Phase C leftovers (active)

These were introduced during Phase C and are the most likely to be picked up next.

| ID | Status | Pri | Item | Introduced | Target |
|----|--------|-----|------|-----------|--------|
| OI-C1 | 🟢 | P2 | **Relocate `DerivedArtifactStore` + `ReaderRegistry`** to `atlas/artifacts/` + `atlas/readers/registry.py`; engineering re-exports kept. | C.2b | closed OI-C1 |
| OI-C2 | 🟢 | P2 | **Unify the Reader Registry** — document/conversation registered with `text`/`sections`/`tables` axis (VERSION 2.0.0). | C.2b | closed OI-C2 |
| OI-C3 | 🟢 | P2 | **Unified-pipeline idempotency on the non-embed path.** `ingest_text` short-circuits when status is already `chunked`/`embedded` (no re-chunk). | C.2c | closed EX/OI-C3 |
| OI-C4 | 🟢 | P2 | **Back-fill existing documents to assets lazily.** `IngestionService.backfill_orphan_documents` + Owner Knowledge tick drain; `GET /v1/knowledge/orphans`, `POST /v1/knowledge/backfill-assets`, `atlas backfill-assets`. | C.2c | closed OI-C4 |
| OI-C5 | 🟢 | P2 | **Wire `IngestionService` + `CandidateConsumer`.** Bridge CLI/`POST /v1/ingest`; scheduled `candidates_drain` + `candidates_prune`; live `EmbeddingIdentityResolver` on consolidator. | C.2c / C.3g | closed OI-C5 |
| OI-C8 | 🟢 | P2 | **Scheduled *reader-version* re-extraction (A10).** Owner Knowledge ticks call `mark_stale_for_reextraction` + `IngestionService.reingest_asset(force=True)`. | C.4c | closed OI-C8 |
| OI-C10 | 🟢 | P3 | **Richer experience signal + revert-retraction.** Dependency-package signal from manifests ✅. Revert peels that project's ``source_id`` from shared experiences (`ExperienceWriter.retract_source` + `CodeStoreSink.revert`); archives when no supporters remain. | C.6c/C.6d | closed OI-C10 |
| OI-C11 | 🟢 | P2 | **Personal auto-inference: proficiency + timeline years + heuristic professional.** Skills get graded `proficiency`; stated `years` feed timeline tenure; role/publication heuristics from Experience text. Full CV / Research-finding professional auto-inference still deferred. | C.7b | closed OI-C11 |
| OI-C9 | 🟢 | P3 | **Policy scoping beyond `global`.** Retrieval, Decision Engine, planning notes, and Policy Engine admit `domain:*` / `mission:*` / `mission_type:*` scopes (plus always-`global`). Search accepts optional `policy_scope` / `mission_id`. Hard-`DELETE` via `DELETE /v1/policy/rules/{id}` and `atlas policy delete`. | C.5b/C.5d | closed OI-C9 |
| OI-C6 | 🟢 | — | **Prose "distilled findings" from documents.** Was deferred from C.2 by design (must flow through the Consolidator). ✅ Resolved by C.3g (`ProseKnowledgeExtractor` → `CandidateConsumer` → `consolidate`). | C.2c | closed C.3g |
| OI-C7 | 🟢 | P3 | **Migration-number placeholders.** Registry through `0050` (OI-SELF0 Belief Core). Prior: `0049` LQ.2 timeline density. **Next free slot: `0051`**. | C.2 | updated SELF 2026-08-11 |

| OI-C12 | 🟢 | P3 | **Personal/Owner SPA dashboard view.** Console `/ui` Personal panel: coverage bars, skills/timeline/professional/identity with P9 "why", Confirm/Reject for inferred facts, Infer + draft-resume actions over `/v1/personal/*`. | C.8d | closed OI-C12 |
| OI-C13 | 🟢 | P3 | **Conversation → experience extraction.** `build_conversation_experiences` distills owner-stated skills from user turns; `IngestionService` writes them when `source=conversation` + `extract_findings` (Owner Knowledge). | C.8a | closed OI-C13 |

---

## 1c. Phase D (complete — seeded from `docs/PHASE_D_PLAN.md`)

Scope cuts recorded at plan time; remaining rows are post-Phase-D deferrals / follow-ons.

| ID | Status | Pri | Item | Notes |
|----|--------|-----|------|-------|
| OI-D1 | 🟢 | P2 | **Live market-data feed** — `asset_replay` default; Yahoo opt-in; **Alpha Vantage + Polygon live** when env keys set; NSE/BSE remain ToS-gated skeletons + CapabilityGap. | MI.3 · `atlas/trading/adapters.py` | closed OI-D1 |
| OI-D2 | 🟢 | P3 | **RM arbitration beyond weighted-priority + hard cap** — soft fair-share usage penalty on MissionArbiter (OI-D2). Preemption of *running* ticks remains out of scope (single-process; release-on-finish). | A7 | closed OI-D2 |
| OI-D3 | 🟢 | P2 | **Phase D complete** (D.1–D.11 ✅), including applied watchers + e2e gate. | PHASE_D §3 |
| OI-D4 | ⚪ | — | **Real-world side-effecting appliers** (e.g. actually submitting a draft) stay behind the P14 approval gate — out of scope until explicitly requested. | PHASE_D DD3/P14 |
| OI-CI0 | 🟢 | P1 | **Career Intelligence CI.0–CI.5 implemented** (Observer one-step ingest, CKG/Opportunity Score, Career Research BATCH, board adapters + CapabilityGaps, learning plans, gated-apply stub). Operator self-ingests LinkedIn export when ready. Optional later: CI.1c browser, live board HTTP, Experience OS WHY depth. Plan: [`CAREER_INTELLIGENCE_PLAN.md`](CAREER_INTELLIGENCE_PLAN.md). | 2026-08-03 |

---

## 1d. Future maturity directions (post-Phase-D — deferred by review discipline)

> **Intentionally deferred architectural directions. NOT part of the Phase-D implementation contract;
> they must not influence current implementation unless explicitly promoted into a future phase.**

From the 2026-07-19 external architecture review (rated ~9.9/10). **Endorsed but intentionally
deferred** — execute the roadmap before adding new top-level concepts; revisit after Phase D or when
implementation exposes a genuine limit. Mirrored in `ATLAS_OS_ROADMAP.md` §13.

| ID | Status | Pri | Item | Notes |
|----|--------|-----|------|-------|
| OI-F1 | 🟢 | P3 | **Decision Knowledge** — paper-trade Decision→outcome journals stamp `decision_id` + enable soft-bias on profit/loss (`atlas/decision/knowledge.py`); reuses OI-MP5 Decision Engine exp-bias. Flat outcomes stay advice-only. | Experience consolidator (C.6) | closed OI-F1 |
| OI-F2 | 🟢 | P3 | **Temporal Knowledge layer** — `truth_kind` historical/current/predicted on findings via `valid_from`/`valid_until` + provenance (`atlas/knowledge/temporal.py`); MCA annotates; paper trading partitions fact vs predicted context. No new DB. | Freshness stays orthogonal | closed OI-F2 |
| OI-F3 | 🟢 | P3 | **System Introspection mission** — `IntrospectionService` + `system_introspection` worker aggregates knowledge/uncertainty/reader failures/mission cost/policy blocks/gaps/improve-next; `GET /v1/introspection/report`. | Generalizes D.10 + P15 without replacing them | closed OI-F3 |
| OI-F4 | 🟢 | P3 | **Standardized post-decision feedback loops** — `atlas/decision/feedback.py` convention; paper trading + job/tech watchers journal Recommendation→Outcome→Difference→Learning (hermetic `outcome_feedback` inputs). | ≥2 applied missions; no new store | closed OI-F4 |
| OI-F5 | 🟢 | P2 | **Capability-gap honesty (P15)** — Decision Engine `capability_gap` + `GET /v1/decision/gaps` + registry `self_report_gaps` (`GET /v1/capabilities/gaps`, `atlas capability-gaps`). | closed F5 |

---

## 1e. Media Reader Family (frozen — `docs/MEDIA_ACQUISITION_PLAN.md`)

Post–Phase D. Triggered by a live YouTube run that failed at **Acquire** (no transcript /
`robots.txt` / 0 B) — honest P15 failure, thin Reader strategies. Extends the **Media Reader
family** + reusable `ReaderStrategyChain` only; no new Intelligence. Operator-approved 2026-07-21
(strategy-chain generalized; Metadata Reader; media non-special). **Plan frozen — start M.1.**

| ID | Status | Pri | Item | Notes |
|----|--------|-----|------|-------|
| OI-M0 | 🟢 | P1 | **Media Reader Family plan complete** (M.1–M.7 ✅) — strategy chain, metadata, Asset-first readers, optional Whisper, provider-agnostic fetch, research wiring + e2e gate. | `MEDIA_ACQUISITION_PLAN.md` · gate `tests/test_media_acquisition_gate.py` |
| OI-RH0 | 🟢 | P1 | **Media Report Honesty** — Research acquire-stop (RH.1–RH.4). | `MEDIA_REPORT_HONESTY_PLAN.md` |
| OI-MO0 | 🟢 | P1 | **Media learn orchestration** — planner/orchestrator/report honesty validated (V4). | `MEDIA_ORCHESTRATION_PLAN.md` |
| OI-RH1 | 🟢 | P1 | **Job report honesty** — waiting + Next Action. Stop investing. | `MEDIA_REPORT_HONESTY_AMENDMENT.md` |
| OI-AC0 | 🟢 | P1 | **Acquisition + learning report** — BA.v2, AL1–AL5, LR1–LR8 shipped. Remaining: Whisper ops; AL6 later. | `MEDIA_ACQUISITION_CLOSURE_PLAN.md` · `MEDIA_ASSET_LIFECYCLE_PLAN.md` · `MEDIA_LEARNING_REPORT_PLAN.md` |
| OI-LR0 | 🟢 | P1 | **Learning Report** — media.learn jobs render Learning Report (not Research INSUFFICIENT). LS1 capability summary + OC1 reason codes done. | `MEDIA_LEARNING_REPORT_PLAN.md` · `tests/test_learning_report.py` |
| OI-STT0 | 🟢 | P1 | **speech_to_text (Whisper)** — installed in venv + `plugins.speech.enabled` in local.yaml. Knowledge categories + metadata-vs-spoken honesty shipped. First live spoken run still needed (model download on first use). | `docs/SPEECH_TO_TEXT_OPS.md` · `config/local.yaml` |
| OI-KE0 | 🟢 | P1 | **Knowledge Extraction** — KE.2.4–2.7 ✅. KG.1 derived graph ✅. | `docs/MEDIA_KNOWLEDGE_EXTRACTION_PLAN.md` |
| OI-KV0 | 🟢 | P1 | **Knowledge Verification (V5)** — KV.0–KV.10 ✅. | `docs/KNOWLEDGE_VERIFICATION_PLAN.md` |
| OI-MP0 | 🟢 | P1 | **Mission Philosophy** — Layer 1 vs Layer 2; kinds; lifecycle; experience shape. | `docs/ATLAS_MISSION_PHILOSOPHY.md` |
| OI-MP1 | 🟢 | P1 | **Experience journal** — Experience OS first-class (`GET /v1/experience/shape`, `POST /v1/experience/journal`). | EX.1 |
| OI-MI0 | 🟢 | P1 | **Market Intelligence Program** — MI→KG→MCA + platform PA gaps ✅. **Next:** governance / ops polish. | `docs/MARKET_INTELLIGENCE_MISSIONS_PLAN.md` |
| OI-IL0 | 🟢 | P1 | **Autonomous Investment Learner** — IL.1–11 + OX ✅; F&O packs, holidays, **filings refs**. Optional: live ToS filing clients. | `docs/AUTONOMOUS_INVESTMENT_LEARNER_PLAN.md` §14–20 | filings 2026-07-26 |
| OI-IIP0 | 🟢 | P1 | **Investment Intelligence Platform** — IIP.1–9 ✅. | `docs/INVESTMENT_INTELLIGENCE_PLATFORM_PLAN.md` |
| OI-DI0 | 🟢 | P1 | **Decision Intelligence** — **DI.1→DI.7 shipped** (migrations `0045`–`0048`). Full stack: packets→timeline→obs→attr→KPIs→fundamentals→process→meta→gated ML export. DI.7 blocked until ≥300 trusted closed per strategy_tag (or override). **No live NN trading.** | [`DECISION_INTELLIGENCE_LEARNING_PLAN.md`](DECISION_INTELLIGENCE_LEARNING_PLAN.md) · playbook | 2026-08-05 |
| OI-LI0 | 🟢 | P1 | **Learning Intelligence & Market Laboratories** — **PLAN LOCKED · LI.1a–LI.6 ✅**. Labs, evidence, observations, DI hardening, Learning Intelligence, AtlasNet **prep only** (`live_nn_trading=False`). New ideas → new OI items. Hermeticity §0.2. | [`LEARNING_INTELLIGENCE_AND_MULTI_LEDGER_PLAN.md`](LEARNING_INTELLIGENCE_AND_MULTI_LEDGER_PLAN.md) · `tests/test_laboratory_li*.py` | 2026-08-08 |
| OI-MLQ0 | 🟢 | P1 | **Market Laboratory Evidence & Attribution Quality** — PLAN LOCKED. **LQ.1–LQ.9** ✅ (sector · timelines · news · causal · calibration · regime · Tier C · KPI honesty · AtlasNet hard-gate). AtlasNet remains prep-only until §8.2 clears in prod. Does **not** reopen DI/LI. | [`MARKET_LABORATORY_EVIDENCE_AND_ATTRIBUTION_PLAN.md`](MARKET_LABORATORY_EVIDENCE_AND_ATTRIBUTION_PLAN.md) | 2026-08-08 |
| OI-PLC0 | 🟡 | P1 | **Professional Laboratory Cycle** — code ✅. **PLC.E wake ✅** (caret `^NSEI` durable load · F&O/intraday config self-heal · BANKNIFTY alias). Ops: restart Atlas; Mon open verify F&O marks + intraday session ticks. | [`PROFESSIONAL_LABORATORY_CYCLE_PLAN.md`](PROFESSIONAL_LABORATORY_CYCLE_PLAN.md) · `test_plc_e_lab_wake` | 2026-08-10 |
| OI-UTS0 | 🟢 | P1 | **Universe Triage & Opportunity Switching** — **UTS.A–G ✅** (allocator + memory + learning loop). Improvement plots deferred. | [`UNIVERSE_TRIAGE_AND_OPPORTUNITY_SWITCHING_PLAN.md`](UNIVERSE_TRIAGE_AND_OPPORTUNITY_SWITCHING_PLAN.md) | 2026-08-09 |
| OI-DAV0 | 🟢 | P1 | **Decision Attribution densify (causes)** — **complete.** DAV.1 helped/hurt/unknown · evening operator brief · RS vs sector Yahoo index (NIFTY fallback) · FCF cashflow-derive + priority enrich · named news · bar+event regimes · sizing **journal** (proposals only). Strategy edits stay proposals-only. Sizing *policy* learning waits for sample growth (see OI-DAV-SIZE). | `causal_attribution` · `sector_benchmarks` · `sizing_learning` · evening | 2026-08-09 |
| OI-EXP0 | 🟡 | P0 | **Experience Integrity** — write-path: 1 identical routine HOLD/switch_blocked per symbol+reason per IST day. Evening still overstated “Decisions frozen” until OI-RLD0 metrics land. News demotion → unproven (not demote) until coverage. Folded into OI-RLD0. | `experience_integrity.py` · paper_trading · evening · meta/IQ | 2026-08-09 |
| OI-CWS0 | 🟡 | P0 | **Cognitive Work Scheduler** — IRA-gated research_task ✅ · DCA drain ✅ (structural ≠ agenda done). | `cognitive_work.py` · JUDGMENT §4b–4c | 2026-08-11 |
| OI-DCA0 | 🟡 | P0 | **Daily Cognitive Agenda** — morning publish + CWS progress + evening section ✅. Live verify next morning mail. | `daily_cognitive_agenda.py` · `test_judgment_dca_jis` | 2026-08-11 |
| OI-HOURLY0 | 🟡 | P0 | **Hourly digests IST 08–20** — code + IR config `hourly_digests` ✅ · Atlas restarted. Verify first live hourly mail next IST hour. | investor_reports · `format_hourly_activity_report` | 2026-08-11 |
| OI-LEDGER-UI0 | 🟢 | P0 | **Market UI ledger tables (all labs)** — `GET /v1/market/labs/ledgers` + Market panel ✅ (3 labs live). | app.js · routes | 2026-08-11 |
| OI-HIST-BARS | 🟡 | P0 | **Historical bar bootstrap** — ~43 dense · NIFTY50 seeds · soft-defer · skip permanent fails. | `historical_bars*` · JUDGMENT §0b | 2026-08-11 |
| OI-JDG0 | 🟡 | P0 | **Judgment Pivot LOCKED** (amendments B+C). Primary metric: **Belief Revisions/week**. Next: BRE densify → full JIS → J5. | [`JUDGMENT_PIVOT_DISCUSSION.md`](JUDGMENT_PIVOT_DISCUSSION.md) §0b–0c | 2026-08-11 |
| OI-SELF0 | 🟡 | P0 | **Persistent Self Phases 1–4 ✅** — Belief Core · Experience loop · Reflection · **Identity Living RAG chat**. Soft influence (Phase 5) deferred until ~100 trusted revisions. BRE choke-point densify still open. | plan · `test_self0_*` | 2026-08-11 |
| OI-SELF-ID | 🟢 | P0 | Identity + Living RAG chat ✅ (`identity_chat` · assistant bind · why/mind-change benchmarks · `/v1/reasoning/living-rag`). | under OI-SELF0 |
| OI-SELF-BELIEF | 🟡 | P0 | Postgres Belief Engine ✅ | under OI-SELF0 |
| OI-SELF-SEED | 🟢 | P0 | 21 operator seed beliefs ✅ | under OI-SELF0 |
| OI-SELF-REASON | 🟡 | P0 | Reasoning façade ✅ — BRE worker choke-point migration still open. | under OI-SELF0 |
| OI-SELF-EXP | 🟡 | P0 | Experience learning-loop ✅ | under OI-SELF0 |
| OI-SELF-REFLECT | 🟡 | P1 | Nightly reflection ✅ | under OI-SELF0 |
| OI-JIS0 | 🟡 | P0 | **JIS** — Belief Revisions today/7d on evening ✅. Calibration/components still gated by thin sample. Not P&L. | `format_jis_revisions_section` · JUDGMENT §6 | 2026-08-11 |
| OI-EXP-LANE0 | 🔴 | P1 | **Measure-only experiment lanes** — V1 control vs one challenger (Judgment Month **J5**). Compare; never silent adopt. Deferred until J1–J3 signal. | under OI-JDG0 | 2026-08-11 |
| OI-RLD0 | 🟡 | P0 | **Reliable Learning Dataset v1** — honesty ✅. Remaining folds into Judgment Month J1–J2 (history, FCF, news attribution). | RLD · [`JUDGMENT_PIVOT_DISCUSSION.md`](JUDGMENT_PIVOT_DISCUSSION.md) | 2026-08-11 |
| OI-DAV-SIZE | 🔴 | P2 | **Sizing learning policy** — use `sizing_learning` journal (confidence→size→outcome) to propose trade_fraction bands. No auto-mutation until sample gate + operator approve. | deferred from OI-DAV0 | 2026-08-09 |
| OI-MKT-COV | 🟡 | P0 | **Market sensor coverage** — CAP.1 ✅. J1 bootstrap **in flight** (last close densified to 2026-08-11 for kicked symbols). Live session_fresh still Yahoo-fragile. | `bar_store` · OI-HIST-BARS | 2026-08-11 |
| OI-MTL0 | 🟢 | P1 | **Market Timeline (open books MVP)** — densify ✅: durable NIFTY + sector RS (`^CNXPHARMA`/`^CNXAUTO`/…), evening NIFTY/RS lines, obs→news/policy wiring (empty headlines stay unknown). Persist `market/timelines/{lab}/{day}.jsonl`. FCF still operator/Screener. Expand watchlist later (D5). | RLD §3.6 · `tests/test_mtl0_market_timeline.py` | 2026-08-09 |
| OI-GENE0 | 🟡 | P2 | **Decision genealogy** — **GENE.1 ✅**. Lesson→next densify under Judgment Month J3. Required before AtlasNet (B21/D6). | `decision_genealogy.py` · JDG | 2026-08-11 |
| OI-BRE0 | 🟡 | P0 | **Belief Revision** — BRE.4 fixed ✅ · **J3 evening four-answers ✅**. Material BRE.2 revises still need real evidence_delta. | BRE plan · JUDGMENT §0b | 2026-08-11 |
| OI-EVID-NET0 | 🟡 | P0 | **Evidence Network** — E0–E2 ✅ · **J2 densify ✅** (`OPEN_BOOK_CRITICAL_FIELDS` · packs · evening WSO stamp). Remaining: Screener ROIC/promoter · real company news/commentary. | `fundamentals` · `open_book_packs` · JUDGMENT §0b | 2026-08-11 |
| OI-LLM-OS0 | 🟢 | P1 | **LLM windows + roles** — BRE.3 decide ✅ · BRE.4 morning ✅ · **BRE.5 global ✅** (Market first; Career/Engineering later). | `decide_rationale` · `morning_hypothesis` · `global_mind` | 2026-08-10 |
| OI-WSO0 | 🟡 | P0 | **World State Objects** — BRE.1 shells ✅ (unknowns + uncertainty ledger + revision log). Semantic text awaits BRE.2 LLM. | `world_state.py` | 2026-08-10 |
| OI-MEM-LLM0 | 🟡 | P1 | **Memory distill** — **MEM.1 ✅** episodic→semantic/procedural structural layers (+ optional LLM text). Mentors/evening read; advice-only. | `memory_distill.py` · BRE plan Phase 4 | 2026-08-10 |
| OI-COG-BUDGET0 | 🟡 | P0 | **Cognitive Budget** — scoring + nightly pass cap ✅ (used by CUR.1 / BRE.2). | `cognitive_budget.py` | 2026-08-10 |
| OI-META-COG0 | 🟡 | P2 | **Meta-cognition** — **META.1 ✅** reasoning-pattern ledger (free-text tags; reliability; evening). Vocab gate at 50 revisions (A8). | `meta_cognition.py` · BRE plan Phase 6 | 2026-08-10 |
| OI-CURIOSITY0 | 🟡 | P0 | **Active Curiosity** — CUR.1 ✅ · **J4 densify ✅** (`drain_queue_work` → IRA for data gaps; persist statuses; news stays queued). | `curiosity.py` · CWS · JUDGMENT §0b | 2026-08-11 |
| OI-CF0 | 🟡 | P1 | **Counterfactual Learning** — **CF.1 ✅** schedule on buys · evaluate +30d · evening beat/matched/lost. Ops: wait for horizon fills. | `counterfactual_learning.py` · BRE plan §1.8 | 2026-08-10 |
| OI-UNCERT0 | 🟡 | P0 | **Uncertainty Ledger** — on WSO (BRE.1). Deterministic sets `data` from gaps; other dims await LLM. | `world_state.py` | 2026-08-10 |
| OI-EVID0 | 🟢 | P1 | **IRA Evidence Plan** — **frozen/shipped** (F0–F5). Snapshots, incremental refresh, hierarchy, sufficiency, valuation path, claim→evidence. | `docs/IRA_NEXT_LEAP_EVIDENCE_PLAN.md` |
| OI-OPS1 | 🟢 | P1 | **ARMF** — A–E frozen (C10 soft-focus deferred; Phase F goals deferred). Capacity, cleanup idempotent, archive lane, Ops summary first paint. | `docs/OPS_STARVATION_CLEANUP_AND_MARKET_FOCUS_PLAN.md` |
| OI-SI0 | 🟢 | P1 | **Sector Intelligence** — SI.1–6 frozen (identity → packs → strategy → path branch → distinctiveness → Why A vs B). Operate under paper trading; deepen compare later if needed. | `docs/SECTOR_INTELLIGENCE_AND_RESEARCH_STRATEGY_PLAN.md` · [`ATLAS_RESEARCH_AND_EXECUTION_ROADMAP.md`](ATLAS_RESEARCH_AND_EXECUTION_ROADMAP.md) |
| OI-IL-OX | 🟢 | P1 | **Orchestration / UX** — OX.1–4 ✅ (preview/start now/API; `system.goals`; `GET /v1/goals/{id}/progress` + `GET /v1/learner/status`). | §14.4–14.6 | OX.4 shipped |
| OI-MP2 | 🟢 | P1 | **Split paper trading** — `decision_simulation` is primary; `paper_trading` remains compat alias. | `OI-MI0` |
| OI-MP3 | 🟢 | P1 | **Daily Learning Governance Report** — `GET /v1/governance/daily` + `learning_governance` mission. | MP3 |
| OI-MP4 | 🟢 | P3 | **Engineering Mentor Mission** — weekly engineering-judgment lessons from repo/architecture Experiences → Experience OS (`engineering_mentor` template + worker; soft-bias default). | Philosophy | closed OI-MP4 |
| OI-PM0 | 🟢 | P3 | **Personal Mentor Mission** — weekly owner/career judgment lessons → Experience OS (`personal_mentor`); Personal Intelligence Program now stub-free. | Programs | closed OI-PM0 |
| OI-MP5 | 🟢 | P2 | **Missions teach missions** — Investment Mentor journals → optional soft-bias (default on) → Decision Engine Experience nudge + Decision Simulation `advice_for` / strategy mentor bias (MI.7). | Philosophy MP6 | closed OI-MP5 |
| OI-PA0 | 🟢 | P1 | **Atlas Platform Architecture** — SETTLED master (Programs→Missions→Workers; Memory/Planning/Policy/Capability/Scheduler gaps tracked below). | `docs/ATLAS_PLATFORM_ARCHITECTURE.md` |
| OI-PA-PLAN | 🟢 | P2 | **Planning OS** — goal → gaps → compare → risk → decide (`GET /v1/planning/plan`). | PA.1 |
| OI-PA-MEM | 🟢 | P2 | **Memory hierarchy** — working / session / long_term ↔ Knowledge / Experience (`GET /v1/memory/hierarchy`). | MEM.1 |
| OI-PA-POLICY | 🟢 | P2 | **Policy Engine** — soft influence + hard forbid/limit (`POST /v1/policy/evaluate`). | PA.2 |
| OI-PA-CAP | 🟢 | P2 | **Capability Registry enrichment** — needs/aliases/inspect (`POST /v1/capabilities/needs`). | CAP.1 |
| OI-PA-SCHED | 🟢 | P3 | **Scheduler hierarchy** — Program → Mission → Worker (`GET /v1/scheduler/hierarchy`). | SCHED.1 |
| OI-PA-WM | 🟢 | P1 | **World Models framework** — registry + indian_markets + solar_plant stub. | WM.1 |
| OI-PA-MCA | 🟢 | P1 | **Mission Context API** — Knowledge + Graph + World Models + Experience; Decision Simulation cites. | MCA.1 |
| OI-BA0 | 🟢 | P2 | **Browser → Asset** — BA.1b + BA.v2 (opt-in yt-dlp) done. BA.v2+ later. | `MEDIA_BROWSER_ACQUISITION_PLAN.md` · `atlas/ingestion/youtube_media_obtain.py` |
| OI-M1 | 🟢 | P1 | Official YouTube captions API — executable when `plugins.youtube.api_key` set (download may still need OAuth). | `atlas/transcripts/official_captions.py` |
| OI-UI0 | 🟢 | P1 | **Job UI live updates** — sequential poll (no race) + SSE `job.activity`/`job.step_blocked`/`job.finalized` refresh; static `/ui` assets served with `Cache-Control: no-cache` so deploys do not require a hard-refresh. | `atlas/web/` · `app.js` | closed OI-UI0 |
| OI-M2 | 🟢 | P3 | Speaker diarization on transcripts — `speaker_diarization` capability + label-preserving engine; P15 gap when off/no labels; MediaIngestor enrich hook. | ML diarization later behind same seam | closed OI-M2 |
| OI-M3 | 🟢 | P3 | Streaming / live caption ingest — `live_caption_ingest` chunk buffer → VTT/transcript; P15 gap when off. | No livestream socket client | closed OI-M3 |
| OI-M4 | ⚪ | — | CCTV / continuous video missions. | out of scope until requested |
| OI-M5 | 🟢 | P3 | Cloud STT providers — `CloudSttEngine` seam (`engine: cloud`); credential-gated stub, no live HTTP; P15 gap without key / until provider wired. | Live OpenAI/Deepgram deferred | closed OI-M5 |
| OI-M6 | 🟢 | P3 | **Video frames → Image/OCR** — `video_frame_extract` + `VideoFramesReader`; Fake extract→OCR; P15 gap when off/ffmpeg missing. | Timeline alignment deferred | closed OI-M6 |
| OI-M7 | 🟢 | P3 | Reuse `ReaderStrategyChain` for non-media — Document PDF `pdf_text_layer` → `pdf_ocr` with `strategies_tried`. | CAD/git follow-ons | closed OI-M7 |

---

## 2. Cross-cutting test / infra debt

| ID | Status | Pri | Item | Notes |
|----|--------|-----|------|-------|
| OI-T1 | 🟢 | P1 | **Live-DB tests share one Postgres with no teardown.** Session autouse cleanup + `atlas-db test-clean` deactivate `/tmp/pytest%` `learning.repositories` and delete matching `asset.assets` / pending `source=test` events (OI-T3). | closed OI-T1 |
| OI-T2 | 🟢 | P2 | **`test_event_lifecycle` flake.** `list_pending` gains optional `source=`; the test scopes to `source='test'` so >100 pending system events cannot hide it. Dispatcher still oldest-first globally. | closed OI-T2 |
| OI-T3 | 🟢 | P3 | **`atlas-db test-clean` / cleanup helper** for shared-dev-DB pytest residue (`--dry-run` supported). | closed OI-T3 |

---

## 3. Deferred by design (carried from earlier phases)

Tracked for completeness; these are intentional scope cuts, not accidental debt.

| ID | Status | Pri | Item | Source |
|----|--------|-----|------|--------|
| OI-B1 | 🟢 | P2 | **JS/TS call-graph resolution.** Tree-sitter collects `call_expression` sites; graph resolves unique / same-file / `this`→`self` edges (OI-B1). Go/etc. remain symbols/imports only. | PHASE_B §BB5/BB10 | closed OI-B1 |
| OI-B2 | 🟢 | P2 | **Partial / per-file re-ingest.** RepoWatcher Detect builds file blob manifests; Policy may choose `partial_ingest`; `learn_repository(paths=/drop_paths=)` merges re-parsed files into the prior artifact (same stores). Large/first/forced ticks stay full. | PHASE_B §B.6 | closed OI-B2 |
| OI-B3 | 🟢 | P2 | **Knowledge Conflict Resolver.** Contested findings get `quality.conflict` why-records; `GET /v1/knowledge/contested` + `POST .../resolve` (hold/supersede/reactivate); DecisionRule `knowledge_conflict` recommends options. Still one Knowledge OS — no parallel conflict DB. | PHASE_B "not building" | closed OI-B3 |
| OI-B4 | 🟢 | P3 | **Additive readers:** CAD / MATLAB / PLC / UML / PSpice registered as all-false-coverage stubs in the unified Reader Registry (`default_domain_stub_readers`, VERSION 2.1.0). No parsers yet. | PHASE_B "not building" | closed OI-B4 |
| OI-A1 | 🟢 | P3 | **Cron schedules.** `scheduler.schedules.kind` + `cron_expr` (migration `0042`); `ScheduleService.register_cron_schedule` / worker `cron_expr` / template `worker_specs.cron`. Interval + continuous unchanged. | PHASE_A §A (schedules) | closed OI-A1 |
| OI-A2 | 🟢 | P3 | **Job-advance priority threading** through the scheduler. `plan_job` / `advance_job` stamp `Mission.effective_priority` when `job.mission_id` is set (same A7 formula as schedules). | PHASE_A | closed OI-A2 |
| OI-A3 | 🟢 | P3 | **Resource caps:** `llm_units_per_window` (+ optional `llm_window_seconds`) and `ram_mb` host reserve enforced on the MissionArbiter / WorkerManager tick gate (OI-A3). Machine RM remains the global complement. | PHASE_A | closed OI-A3 |
| OI-X1 | ⚪ | — | **Remote access + hot/warm/cold storage tiering.** Hardware-gated; single-disk for now. | ROADMAP / PHASE_B |

---

## 4. Recently closed

| ID | Item | Closed by |
|----|------|-----------|
| OI-DAV0 | Decision Attribution densify (causes) — seams complete. | 2026-08-09 densify cycle |

| OI-M6 | **Video frames → OCR** — frame extract capability + reader. | `f69a439` |
| OI-M5 | **Cloud STT seam** — pluggable cloud engine stub behind SpeechEngine. | `a05c5c1` |
| OI-M3 | **Live caption ingest** — chunk buffer → transcript/VTT. | `325caae` |
| OI-M2 | **Speaker diarization** — capability + label-preserving enrich + P15 gap. | `3b41768` |
| OI-F4 | **Post-decision feedback loops** — Recommendation→Outcome→Difference→Learning convention. | `39fbfcd` |
| OI-F3 | **System Introspection** — aggregate self-analysis mission + report API. | `709bb4c` |
| OI-F2 | **Temporal Knowledge** — historical / current / predicted via validity + MCA. | `39c88a7` |
| OI-F1 | **Decision Knowledge** — Decision→outcome → bias-enabled Experience soft-bias. | `7a3ede3` |
| OI-B4 | **Additive domain stub readers** — CAD/MATLAB/PLC/UML/PSpice registry stubs. | `ba2c93f` |
| OI-D2 | **Fair-share arbitration** — soft recent-admit penalty; no preemption. | `7b7a349` |
| OI-C7 | **Migration-number honesty** — registry through `0042`; next free `0043`. | `2dde699` |
| OI-A3 | **Resource caps** — `llm_units_per_window` + `ram_mb` on MissionArbiter tick admit. | `86438ad` |
| OI-A2 | **Job-advance priority threading** — plan/advance tasks inherit mission effective_priority. | `a68daf5` |
| OI-A1 | **Cron schedules** — 5-field crontab on `scheduler.schedules` + claim advance. | `7facc54` |
| OI-C10 | **Experience evidence-retraction on revert** — peel repo_uid from shared experiences; archive if alone. | `2393b65` |
| OI-B3 | **Knowledge Conflict Resolver** — conflict quality + list/resolve API + DE rule. | `3602eab` |
| OI-B2 | **Partial / per-file re-ingest** — file Detect + `paths=` merge into prior artifact. | `a5975aa` |
| OI-B1 | **JS/TS call-graph resolution** — tree-sitter call sites + heuristic edges. | `3fb8f3c` |
| OI-PM0 | **Personal Mentor Mission** — owner/career weekly lessons; Programs stub-free. | `4742c4c` |
| OI-MP4 | **Engineering Mentor Mission** — weekly judgment lessons → Experience OS. | `005b8c6` |
| OI-C12 | **Personal/Owner SPA dashboard** — `/ui` Personal panel + coverage/confirm/infer/draft. | `6835729` |
| OI-D1 | **Live market-data feed** — Yahoo + Polygon/AV live clients; NSE/BSE skeletons. | `df2d71b` |
| OI-C11 | **Personal proficiency + timeline years + heuristic professional.** | `869ec44` |
| OI-C13 | **Conversation → experience extraction** — `build_conversation_experiences` + ingest wire. | `7f35a28` |
| OI-T1/T2/T3 | **Live-DB test hygiene** — session cleanup + `atlas-db test-clean`; `list_pending(source=)`. | `44dd079` |
| OI-MP5 | **Missions teach missions** — mentor soft-bias + Decision Engine Experience nudge. | `9d22b66` |
| OI-UI0 | **Job UI live updates** — sequential poll + SSE refresh; `/ui` no-cache headers. | `efc7091` |
| OI-RH0 | **Media Report Honesty** (acquire-stop UX: NOT_APPLICABLE, Research blocked, operator strategies). | RH.1–RH.4 / `tests/test_media_report_honesty.py` |
| OI-M0 | **Media Reader Family plan** (M.1–M.7) — Asset-first media Readers, optional Whisper, provider-agnostic fetch, research wiring + e2e gate. | M.7 / `tests/test_media_acquisition_gate.py` |
| OI-G1 | **`.gitignore` silently ignored `atlas/{documents,knowledge,models}` source packages** (unanchored runtime-data rules) — 25 core source files were untracked. Anchored the rules to the repo root; source now tracked. | commit `57deac9` (2026-07-19) |
| OI-C6 | Prose "distilled findings" from documents — now flow document → candidate → Consolidator → finding. | C.3g commit `4595ee8` (2026-07-19) |
| (bug) | **`UNIQUE(canonical_id)` blocked the finding revision model** on the live DB (revise reused canonical_id). Relaxed to `UNIQUE(canonical_id, revision)`. | C.3e migration `0033` / commit `58f7c78` |
| (bug) | **Consolidator spuriously revised on subset re-observation.** Re-observing an already-known source on a multi-source finding (incoming supporting ⊆ existing, body unchanged) deferred to the transition machine, which saw the differing supporting-set and spawned a revision that discarded accumulated evidence. `_accumulate` now returns an explicit no-op. Surfaced by C.6 shared-identity experiences. | C.6d commit `2ed3771` |

---

_When you close an item, move it to §4 with the resolving commit, and flip its status to 🟢._
