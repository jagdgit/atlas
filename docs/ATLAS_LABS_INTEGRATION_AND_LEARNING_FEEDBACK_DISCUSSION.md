# Atlas Labs Integration & Learning Feedback Engine

> **Status:** 🔒 **MASTER IMPLEMENTATION PLAN** — 2026-09-21 rev 16 (clean experiences: swing wash-lock + F&O Phase 2 adapter on SMA/RSI V1, FNO-P2-001. RL frozen. Step 11 proven.)  
> **Codename:** `OI-LAB-LOOP0`  
> **Purpose:** Single tracker for *connecting* Atlas’s existing components into a closed,
> measurable, persistent learning loop. Not a new product. Not a license to add more AI.  
> **Parents (do not reopen / do not fork):**  
> [`ATLAS_NOW_CLOSED_LOOP_ROADMAP.md`](ATLAS_NOW_CLOSED_LOOP_ROADMAP.md) ·  
> [`ATLAS_FEATURE_EXPERIMENT_LABORATORY_PLAN.md`](ATLAS_FEATURE_EXPERIMENT_LABORATORY_PLAN.md) ·  
> [`ATLAS_LEARNING_AUDIT_AND_HISTORICAL_INTELLIGENCE_DISCUSSION.md`](ATLAS_LEARNING_AUDIT_AND_HISTORICAL_INTELLIGENCE_DISCUSSION.md) ·  
> [`ATLAS_MDPH_AND_LEARNING_LOOP_DISCUSSION.md`](ATLAS_MDPH_AND_LEARNING_LOOP_DISCUSSION.md) ·  
> [`ATLAS_DATA_PLANE_AND_INFERENCE_INTEGRITY_PLAN.md`](ATLAS_DATA_PLANE_AND_INFERENCE_INTEGRITY_PLAN.md) ·  
> [`ZERODHA_LIVE_MARKET_DATA_INTEGRATION.md`](ZERODHA_LIVE_MARKET_DATA_INTEGRATION.md) ·  
> [`ATLAS_FUNDAMENTAL_EVIDENCE_ACQUISITION_PLAN.md`](ATLAS_FUNDAMENTAL_EVIDENCE_ACQUISITION_PLAN.md) ·  
> [`RELIABLE_LEARNING_DATASET_DISCUSSION.md`](RELIABLE_LEARNING_DATASET_DISCUSSION.md) ·  
> [`SCREENER_FUNDAMENTALS_IMPORT.md`](SCREENER_FUNDAMENTALS_IMPORT.md) ·  
> [`OPEN_ITEMS.md`](OPEN_ITEMS.md) ·  
> **Next:** [`ATLAS_TRADE_LOOP0_ACCEPTANCE_AND_WEEKEND_STAMP_DISCUSSION.md`](ATLAS_TRADE_LOOP0_ACCEPTANCE_AND_WEEKEND_STAMP_DISCUSSION.md) — NSE/XBRL vertical slice + correctness + hourly FI mail (no code until §15 lock). Parent loop: [`ATLAS_OPERATIONAL_TRADING_LOOP_AND_FNO_UNIVERSE_DISCUSSION.md`](ATLAS_OPERATIONAL_TRADING_LOOP_AND_FNO_UNIVERSE_DISCUSSION.md)  
> **Connect, do not rebuild:** `zerodha_feed` · MDPH · `data_plane_contract` · `bar_store` ·
> FEA / UQ · DI packets · `learning.experiences` · FEL · Learning Auditor · lab_contracts ·
> PLC.A/B · evidence_completeness · `KnowledgeService.retrieve` · `finding_embeddings` ·
> RagAgent · Next-₹1 (advice-only)  
> **Does not reopen:** live orders · adding capital · silent SMA/RSI mutation · LLM → BUY/SELL ·
> RL on raw prices · AtlasNet live NN · loosening WATCH / MoS / PLC.A / F&O isolation ·
> dumping every trade into pgvector · a second brain / second experience database

**Explicit principle:**

> Atlas does not need more intelligence components right now. It needs the components
> it already has to form a closed, measurable, persistent learning loop.

---

## 0. Three separate problems (do not mix)

| # | Problem | Layer | Headline evidence 2026-09-17 |
|---|---------|-------|------------------------------|
| 1 | Trading labs lack a reliable, complete **data plane** | A | Steps 1–4 in code (FEA wiring, Zerodha persist, nearest NIFTY FUT, dated 5m tape). Live stamp still needs bounce + Kite session. |
| 2 | Trading **experience → learning** loop is disconnected | B/C | Intraday can fill; swing 0 fills (PLC.A/thesis). **Steps 5–7 in code:** `blocked_buy` · round-trip reward · paper JSONL → FEL cash-baseline. **Steps 8–10 in code** (chunk RAG + findings tier). RL must not start. |
| 3 | **Persistent intelligence** is broken at RAG/embedding | D | **M4 Steps 1–2 + 4–5 LIVE PASS** PID **323438**. Two-symbol canary **frozen**. Do not retune ranking, expand publisher, or edit RAG. **HBLPOWER N1 replay LOCKED.** Remaining bottleneck is NSE/XBRL **coverage + edge cases** (not this symbol). |

Even if a lab learned something today, Atlas must still **prove** that learning is available to the LLM tomorrow. **M4-RAG-LIVE Step 1** proved that path. **Step 4** is the fundamentals → validated finding bridge (implementation PASS). **Step 5 LIVE PASS + FROZEN.** Do not retune ranking. Do not expand the publisher. **HBLPOWER N1 is a locked golden replay fixture**, not more RAG work.

Auditor principle (unchanged): **stored ≠ observed ≠ understood ≠ predicted ≠ learned ≠ improved.**  
Add: **stored ≠ embedded ≠ retrievable ≠ recalled by the LLM.**

---

## 1. The loop is Atlas

Everything else is infrastructure supporting this loop.

```text
                    ┌─────────────────────┐
                    │     DATA SOURCES    │
                    │ Zerodha Yahoo       │
                    │ Screener Filings    │
                    │ Research/Web        │
                    └──────────┬──────────┘
                               ▼
                    ┌─────────────────────┐
                    │   NORMALIZED DATA   │
                    │ Market              │
                    │ Fundamentals        │
                    │ News/Research       │
                    │ F&O contracts       │
                    └──────────┬──────────┘
                               ▼
                 ┌────────────────────────────┐
                 │     TRADING LABS           │
                 │ Equity · Intraday · F&O    │
                 └────────────┬───────────────┘
                              ▼
                    FEATURE ENGINE
                              ▼
                    DECISION / STRATEGY
                    (SMA/RSI V1 = live paper control
                     until a challenger earns it)
                              ▼
                    PAPER TRADE
                              ▼
                    EXPERIENCE STORE
                    state · action · outcome · P&L · reward
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
             Statistical/FEL            RL (later)
                    └─────────┬─────────┘
                              ▼
                     VALIDATED LEARNING
                              ▼
                     KNOWLEDGE STORE
                              ▼
                         embedding
                              ▼
                         VECTOR DB
                              ▼
                             RAG
                              ▼
                             LLM
                              ▼
                    Future research / future decision
                              │
                              └──────────► new experience
```

That last arrow is the finish line. Without it Atlas is an application with AI components.

**Not the objective:** make the labs place more paper trades.  
**The objective:** data → paper experience → validated learning → retrievable tomorrow.

---

## 2. Four milestones (locked)

| ID | Name | Meaning | RL? |
|----|------|---------|-----|
| **M1** | DATA PLANE | All three labs can continuously obtain and persist the market/fundamentals/contract state they require | no |
| **M2** | EXPERIENCE / LEARNING PLANE | Every paper trade (and blocked technical BUY) becomes a complete experience with outcome + reward | no |
| **M3** | SCIENTIFIC LEARNING | Experiences → patterns → hypothesis → FEL → walk-forward → validated/rejected. E001 is the pattern (vol-accel **lost** = real knowledge) | no |
| **M4** | PERSISTENT INTELLIGENCE | Validated finding → knowledge → embedding → vector DB → RAG → LLM, proven by a restart canary | no |

RL is **after** M1–M4. Scaffolding stays dark.

---

## 3. Four workstreams (locked)

Each workstream is defined as: current state → exact broken link → required change → test → evidence of success → dependency.

Do not add a sophisticated component in a later workstream while an older connection underneath is still broken.

### WORKSTREAM A — DATA

Zerodha + fundamentals + F&O + intraday persistence.

| | |
|--|--|
| **Current state** | Zerodha Kite: `configured=true`, `token_valid=true`, MDPH **READY**. **Steps 1–4 in code:** FEA member reconcile; persist Zerodha bars; `NIFTY` → nearest NFO FUT; 5m tape split by IST session + packet `intraday_tape` ref. Live files stamp after bounce. Fundamentals store ≈ 19 screener rows. Yahoo enrich paused HTTP 429. |
| **Broken links** | (1) Zerodha API success ≠ `bar_store` write. (2) UQ PENDING ≠ FEA drain. (3) `NIFTY` ≠ FUT/CE/PE contract. (4) Intraday decision state not reconstructable next day. |
| **Required change** | Wire FEA mission so it actually ticks. Persist Zerodha historical/live into lab bar stores with honest `provider`. Contract resolver (underlying → expiry → FUT/CE/PE → strike → token). Persistent intraday tape. Do **not** loosen PLC.A. |
| **Test** | UQ task → DONE + fundamentals row. A symbol’s latest bar file `provider=zerodha` (or dual-provenance with Zerodha as session source). F&O packet names a real NFO tradingsymbol. Yesterday’s YESBANK 5m window reloadable. |
| **Evidence of success** | M1 questions in §7 answer yes. |
| **Depends on** | Nothing. **This is first.** |
| **Feeds** | Workstream B (no honest experience without reconstructable data). |

### WORKSTREAM B — TRADING EXPERIENCE

Labs + paper execution + outcomes + rewards.

| | |
|--|--|
| **Current state** | Intraday completes fill → flatten → P&L. Equity engine emits `buy:YESBANK` etc. ~77× after open; **0 fills** (PLC.A missing PE/ROE/D/E; IDEA `thesis_watch_insufficient`; WELCORP thesis AVOID). **Step 5:** gated BUYs persist as `blocked_buy` (no P&L/reward). **Step 6:** a paper close writes L10 outcome + `lab.loop0.reward.v1` (book `realized_pnl`, not RL). F&O cannot observe a contract until bounce. DI packets + `learning.experiences` JSONL. Next-₹1 DEPLOY is `advice_only` / `never_orders`. |
| **Broken links** | RAG still cannot retrieve a validated FEL finding after restart (Steps 8–11). |
| **Required change** | Automatic `trade → outcome → experience → reward` — **Step 6 landed.** Paper store → FEL — **Step 7 landed.** |
| **Test** | After one intraday round-trip: experience row has state, features, action, entry, exit, P&L, costs, reward, strategy version, evidence_lineage. Count of *useful* experiences is reportable. |
| **Evidence of success** | M2 questions in §7. |
| **Depends on** | A (tape + contracts + fundamentals coverage). |
| **Feeds** | Workstream C. |

### WORKSTREAM C — LEARNING

Experience → FEL → RL later.

| | |
|--|--|
| **Current state** | FEL E001 ran: vol-accel **worse than baseline**. E002 queued. Promotion never `live_control`. **Step 7:** rewarded paper closes become a lab-hermetic FEL dataset + `paper_round_trip` queue item; cash-baseline can reject (“this hypothesis did not survive”). Soft-bias 0.005 is not learning. RL scaffolding unused — **keep unused**. |
| **Broken links** | Validated FEL findings are not yet a RAG tier (Steps 8–10). |
| **Required change** | Connect experience store → candidate pattern → FEL — **Step 7 landed** on the existing queue/hypothesis/promotion path. Do not activate RL. |
| **Test** | A new paper-derived hypothesis can be queued like E001 and produce a promote/reject belief. |
| **Evidence of success** | M3: “this hypothesis did not survive” is a durable finding, not a log line. |
| **Depends on** | B (enough clean experiences). E001-style offline FEL may continue in parallel without waiting. |
| **Feeds** | Workstream D. |

### WORKSTREAM D — INTELLIGENCE

Knowledge → embeddings → vector DB → RAG → LLM.

| | |
|--|--|
| **Current state** | Postgres + pgvector + HNSW healthy. **Steps 8–11 in code and live.** **M4-RAG-LIVE Steps 1–2 LIVE** on PID **288870** (15:30:44 IST). Search + `rag/run` expose provenance on `F-002118`. Experience/memories still **deferred**. |
| **Broken links** | (1) ~1,258 findings still unembedded (background drain, not the canary). (2) hybrid still returns noisy knowledge chunks as hits 2–5 — frozen; do not retune ranking in this step. Memories not fused. |
| **Required change** | Step 4 **in code** (HBLPOWER + TATACHEM). Bounce to publish/embed, then re-run Step 5. Not raw XBRL. Not ranking retune. LLM still not the trader. NSE/XBRL P0 continues in parallel. |
| **Test** | §7 M4 canary (Step 1 done). Step 2: citation JSON carries the five provenance fields. |
| **Evidence of success** | M4-RAG-LIVE board in §7. |
| **Depends on** | C for *trading* findings. RAG repair (Steps 8–9) can proceed **in parallel** with A/B because the break is already in production recall. |
| **Feeds** | Future research / future decision context. Never BUY/SELL. |

---

## 4. Development order (locked)

Do not skip ahead to RL. Do not start a huge new learning system.

| Step | Work | WS | Status |
|------|------|----|--------|
| **1** | **Fix FEA runtime** — UQ → FEA worker → acquisition → store must actually run | A | 🟡 wiring: `ensure_missing_enabled_members` on kernel start |
| **2** | **Fix Zerodha persistence** — prove `Zerodha → bar_store`, not only API PASS | A | 🟡 in code: persist daily/`5m` with `provider=zerodha`; Yahoo daily prefers a live Kite session (labeled). Bounce to stamp live files. |
| **3** | **Fix F&O instrument resolver** — real FUT / CE / PE | A | 🟡 **Phase 2 adapter in code:** NIFTY same-expiry ATM CE/PE from Zerodha dump (never invented tsyms). SMA/RSI V1 remains the control; adapter maps BUY→ATM CE/PE, SELL→close. 1 lot, premium×lot, no writing, FNO-P2-001 leftover flatten. No BANKNIFTY paper. Bounce + Kite to observe live LTP. |
| **4** | **Persistent intraday tape** — every decision reconstructable later | A | 🟡 in code: 5m bars split by IST session; packet `intraday_tape` ref; `reconstruct_from_ref` reloads yesterday’s window. Bounce so live Zerodha 5m lands on dated files. |
| **5** | **Standardize Experience** — one contract, lab-specific fields; include `blocked_buy` | B | 🟡 in code: `lab_experience.py` L10 row; paper BUY gates write `blocked_buy` JSONL once/day; **no P&L/reward** (L24). **2026-09-18:** PLC.A tag `fundamentals_incomplete` now counts as `blocked_buy` (YESBANK/JUBLPHARMA/HBLPOWER were SMA-BUY + PLC.A but previously skipped). |
| **6** | **Outcome + Reward** — deterministic, versioned | B | 🟡 in code: close writes L10 entry/exit/P&L/costs/`lab.loop0.reward.v1` on the existing JSONL EXPERIENCE; `blocked_buy` still unrewarded. Book P&L only. Does not mutate SMA/RSI. |
| **7** | **Connect experiences → FEL** — scientific learning; **do not activate RL** | C | 🟡 in code: rewarded JSONL closes → lab-hermetic PIT dataset → `paper_round_trip` queue item (like E001) → cash-baseline belief. Losing book → durable `this hypothesis did not survive`. Promotion never `live_control`. F&O not mixed into equity. RL still frozen. |
| **8** | **Repair chunk embedding** — backfill 1,261 missing chunk embeddings | D | 🟡 in code: `embed_backfill` schedule (90s, 4 docs/tick) lists chunks missing embeddings for the current model and enqueues existing `embed_document`. Does not smash findings. Does not dump trades. Bounce to drain the stall. |
| **9** | **Repair dense/hybrid RAG** — fix `_dense_rows`, bounce, canary | D | 🟡 in code: `_dense_rows` embeds the query then `embeddings.search` (empty list on failure, never `None`). Hybrid falls back to lexical if dense embed/search fails. Live canary after bounce + drain. |
| **10** | **Findings = first-class RAG tier** — Documents / Findings / Memories | D | 🟡 in code: `retrieve` searches `finding_embeddings` as `tier=findings` (heads only). Not smashed into chunks. Memories/experience still deferred. Bounce so chat cites a finding. |
| **11** | **Prove learning → RAG → LLM** — one controlled restart experiment | D | 🟢 **M4-RAG-LIVE Step 1 COMPLETE** 2026-09-19 on **current** systemd PID 275877 (started 13:48:59 IST), not a pre-bounce process. See §7. |
| **12** | **Only then** RL training environment on clean historical experiences | C | 🔒 frozen until 1–11 |

Steps 8–9 may run **in parallel** with 1–4 (independent failure). They must complete before claiming M4. Step 12 is not this phase.

---

## 5. Multi-tier RAG (Step 10 conceptually locked — YES)

Do **not** force `finding_embeddings` into the existing chunk RAG system.

```text
                 RAG
                  │
       ┌──────────┼──────────┐
       ▼          ▼          ▼
   Documents   Findings   Memories
    chunks     validated   selected
               knowledge   experience
```

| Tier | Meaning |
|------|---------|
| Documents | Source material (chunk index) |
| Findings | Validated conclusions |
| Memories | Selected historical experiences — not the raw blotter |
| Structured market state | Current state, not vector memory |

Implementation: **`KnowledgeService.retrieve` now fuses document chunks and finding heads.** `finding_embeddings` stays a separate index (consolidator dedup + this RAG tier). Memories/experience remain deferred. Do **not** copy findings into `knowledge.chunks`.

Operator 2026-09-17: **YES**.

---

## 5b. Operator locks (2026-09-17 rev 3)

| Decision | Lock |
|----------|------|
| First complete loop vs first data failure | **Parallel tracks.** Steps 1–4 data/integrity; Steps 8–9 RAG independently. |
| Equity coverage | **Screener import where PLC.A requires it** (YESBANK / JUBLPHARMA / IDEA). Data-coverage repair, not a trading-policy change. Do not wait on Yahoo 429. Do not disable PLC.A. Do not use hermetic seed ratios as PLC.A-complete. |
| F&O Phase 1 | **Nearest NIFTY FUT** (tape): underlying → nearest valid FUT → expiry → tradingsymbol → token. `NIFTY` is not a tradable F&O object. |
| F&O Phase 2 | **Operator unlocked 2026-09-17. Adapter lock 2026-09-21:** SMA/RSI V1 stays the control. Adapter translates BUY underlier → ATM CE (bullish) / ATM PE (bearish); SELL closes the option. 1 lot, **no writing**, NIFTY only. Premium × lot cash debit — **not** index-proxy marks. Leftover `NIFTY26SEP23350PE` is FNO-P2-001 initial_state, not Phase-2 evidence. No BANKNIFTY. Not live. |
| Blocked BUYs | **`blocked_buy` experiences** (L24). Not trade outcomes / rewards. Capture reason, evidence state, features, strategy version, gate state. |
| Step 10 | **Findings = first-class RAG tier** (YES). |
| Swing zero fills | **Do not start here.** Do not loosen gates to look active. First implementation = Step 1 FEA runtime. |

---

## 6. Locked decisions

| ID | Decision |
|----|----------|
| L1 | Labs are experimentation environments, not three independent bots |
| L2 | Success ≠ more paper trades |
| L3 | Zerodha = Indian **market** backbone. API working ≠ production store proven |
| L4 | Yahoo / Screener / filings = **fundamentals** plane |
| L5 | Do not mix market / fundamentals / research planes |
| L6 | Provider-independent adapters → normalized Atlas contracts |
| L7 | F&O needs a contract resolver; `NIFTY` is not tradable F&O |
| L8 | Do not force F&O into the cash-equity schema |
| L9 | Every market state used to decide must be reconstructable later |
| L10 | Experience = lab + ts + instrument + state + features + action + entry/exit + P&L + costs + reward + regime + strategy version |
| L11 | Lifecycle: CREATED → OPEN → CLOSED → OUTCOME → REWARD → EVALUATED → CANDIDATE → VALIDATED → PERSISTED KNOWLEDGE |
| L12 | Not every trade becomes knowledge |
| L13 | FEL is the first learning mechanism; a single loss must not mutate strategy |
| L14 | RL after M1–M4 only; never auto-replace SMA/RSI V1 |
| L15 | LLM is not the trader |
| L16 | Vector DB holds validated knowledge, not raw trades |
| L17 | Do not loosen PLC.A / WATCH / MoS / F&O isolation |
| L18 | No live execution until the full paper validation chain |
| L19 | Integration-first; no new AI appliances |
| L20 | Reuse existing stores; no parallel brain |
| **L21** | Four workstreams A–D; do not skip a broken underlying link |
| **L22** | Development order §4 (FEA runtime first; RL last) |
| **L23** | `finding_embeddings` today ≠ RAG memory. Repair recall before claiming intelligence |
| **L24** | Blocked technical BUYs are `blocked_buy` experiences (not P&L outcomes) |
| **L25** | FEA/UQ not ticking is a **runtime wiring** bug, not “we lack a fundamentals system” |
| **L26** | Parallel tracks: data Steps 1–4 and RAG Steps 8–9 |
| **L27** | Equity PLC.A coverage = Screener/FEA data repair, never gate loosening |
| **L28** | F&O object = nearest NIFTY FUT (tape) + Phase-2 ATM CE/PE paper (operator unlocked 2026-09-17; no writing; **index universe expansion proposed** in [`ATLAS_OPERATIONAL_TRADING_LOOP_AND_FNO_UNIVERSE_DISCUSSION.md`](ATLAS_OPERATIONAL_TRADING_LOOP_AND_FNO_UNIVERSE_DISCUSSION.md) — **not implemented until that file’s §14 lock**) |
| **L29** | Findings are a first-class RAG tier (Step 10 YES; **in code** after 8–9; not chunk smash) |
| **L30** | Do not start implementation by “fixing” swing zero fills |
| **L31** | **M4-RAG-LIVE Step 1 is frozen PASS.** Do not retune hybrid ranking because hits 2–5 are noisy. Retrieval-quality is later work. |
| **L32** | RAG citations must expose `finding_id`, `document_id`, retrieval score, source, timestamp. Row counts are not the canary. |
| **L33** | RAG is memory recall; LLM is the interpreter; neither is the trader. LLM must not authorize PLC.A or BUY/SELL, and must not invent PE/ROE/D/E/FCF. |
| **L34** | Step 4 bridge is canonical fundamentals → deterministic summary → finding → embedding. No LLM interpretation of financial facts. UNKNOWN stays UNKNOWN. Conflicts stay recorded. New filing supersedes; do not mutate one forever-vector. Ranking changes only after the finding exists and still loses retrieval. |
| **L35** | Step 5 live order is publication → embedding → raw retrieval → LLM last. Do not expand the publisher past HBLPOWER+TATACHEM until both survive that pipeline. Podcast/arXiv hits are not a ranking failure until the new findings exist in the live process. **2026-09-19: survived. Slice frozen.** |
| **L36** | **HBLPOWER N1 is LOCKED** as the golden candidate-replay fixture (`tests/test_hblpower_golden_replay.py`). Future NSE changes must reproduce BEFORE INCOMPLETE / AFTER COMPLETE, locked PE/ROE/D/E/FCF, hash `ea71f0…`, `DEBT_DEFINITION`, `not_a_fill=true`, `writes_experience=false`. Do not re-engineer this symbol unless that test regresses. Replay is **not** a paper fill, reward, or learning experience. |

---

## 7. Success criteria (ask these, not “are the labs running?”)

**Equity.** Can it continuously receive data, make paper decisions, record outcomes, and learn from them?

**Intraday.** Can it continuously reconstruct intraday market state and turn completed trades into reusable experiences?

**F&O.** Can it actually observe real futures/options contracts and their state?

**Atlas (finish line).** Can a validated trading lesson from today be retrieved and used by Atlas tomorrow?

### M4 canary (Step 11)

```text
Day 1  Atlas stores: "Setup X performed poorly when regime Y was present."
       Restart Atlas.
Day 2  Ask the research agent about setup X under regime Y.
       Expected: RAG retrieves Day-1 finding → LLM receives it → LLM references it.
```

Row counts (chunks, embeddings, findings) are **not** this canary.

### M4-RAG-LIVE board (2026-09-19)

The second half of the Atlas north star is now alive **in the same running process**:

```text
             DETERMINISTIC
NSE → facts → calculations → validation → PLC.A
                                      │
                                      │
                              decision authority
                                      │
                                      X
                                    LLM

             INTELLIGENCE / MEMORY
findings → embeddings → RAG → LLM → explanation/research
```

| Step | Work | Status |
|------|------|--------|
| **1 Current-process canary** | Prove current systemd Atlas: retrieval → `F-002118` → `qwen3:4b` → cited answer | 🟢 **COMPLETE** 2026-09-19. PID **275877**, started **13:48:59 IST**. `POST /v1/knowledge/search` 200 (1.2s) hit #1 `finding:2c15a393-…` / `F-002118` sim 0.694. `POST /v1/agents/rag/run` 200 (96.2s), `retrieved=5 used=5`, 1,162 prompt tokens, Ollama `/api/chat` 200. Answer: “Setup X performed poorly when regime Y was present **[1]**.” Diagnostics 5488→5490. Fitness: 2×`knowledge_query_embed` + 1×`rag_generate`. Stamp: `/tmp/atlas_m4_canary/live.json`. |
| **2 Provenance surface** | Every RAG answer exposes `finding_id`, `document_id`, retrieval score, source, timestamp | 🟢 **LIVE** 2026-09-19 on PID **288870** (bounce 15:30:44 IST). `POST /v1/knowledge/search` 200 (0.6s) hit #1: `finding_id=2c15a393-…` `document_id=F-002118` `source=findings` `timestamp=2026-09-18T12:25:30Z` score 0.03985 / sim 0.694. `POST /v1/agents/rag/run` 200 (88.2s) citation[1] same five fields; answer cited `[1]`. Ranking unchanged (noisy knowledge hits 2–5). Stamp: `/tmp/atlas_m4_canary/step2_live.json`. |
| **3 Embedding drain** | Background-reduce ~1,258 unembedded findings | 🟡 **background, not the blocker.** Existing `embed_backfill` drains **chunks**, not findings. Must not preempt FEA. Must not make the F-002118 canary depend on drain. |
| **4 Fundamentals → RAG** | Canonical store → validate → deterministic summary → finding → embed. Not XBRL→LLM. Not ranking retune. | 🟢 **IMPLEMENTATION + LIVE PUBLISH** 2026-09-19 PID **323438**. `fundamental_summary_publish` 21:23:44 IST created **F-002148** HBLPOWER + **F-002149** TATACHEM, both `nomic-embed-text` dim 768. |
| **5 Real Atlas questions** | TATACHEM blocked / HBLPOWER PLC.A / conflicts | 🟢 **LIVE PASS** 2026-09-19 PID **323438** (bounce 21:20:40 IST). Search #1 = the new findings. LLM (`qwen3:4b`) cited `[1]` and explained. Pre-Step-4 “I don't know” was **missing knowledge**, not ranking. Podcast F-001100 is now #2. Stamp: `/tmp/atlas_m4_canary/step5_bounce_search.json` + `step5_bounce_rag.json`. |
| **6 Hard boundary** | RAG/LLM = explanation. Never PLC.A auth. Never BUY/SELL. | 🔒 locked (L15 / L33). |

Noisy hybrid hits 2–5 (knowledge chunks) are **retrieval-quality work**, not a live-path failure. Frozen under L31 / L35.

### 7.2 TRADE-LOOP0 HBLPOWER N1 (LOCKED 2026-09-19)

```text
18-Sep technical BUY packet
        ↓
isolated candidate replay
        ↓
BEFORE = PLC.A INCOMPLETE
        ↓
UQ → FEA → stored NSE/XBRL + hash
        ↓
canonical facts → deterministic calculations
        ↓
sector / identity (catalog, not XBRL)
        ↓
PLC.A reread
        ↓
AFTER = COMPLETE
```

| Item | Result |
|------|--------|
| Candidate replay | ✅ PASS |
| Fake fill avoided | ✅ `not_a_fill=true` · `writes_experience=false` |
| BEFORE isolated | ✅ live COMPLETE cannot leak backward |
| PE / ROE / D/E / FCF | ✅ 25.86 FY · 44.08% · 0.020 `atlas.debt.total_borrowings.v1` · 6,293,200,000 |
| Sector / identity | ✅ Capital Goods / HBL Power |
| Conflict | ✅ `DEBT_DEFINITION` retained |
| Golden fixture | `tests/test_hblpower_golden_replay.py` + `hblpower_replay_{canonical,prior}.xml` |

**Do not** turn this replay into `paper trade → outcome → reward`. Remaining NSE P0 is **other names and edge cases**, with HBLPOWER as the regression fixture.

### 7.1 Step 5 live protocol (locked — do not reorder)

Do not change Step 4 code before bounce. Let `fundamental_summary_publish` run naturally. Slice stays **HBLPOWER + TATACHEM**. Then verify **in this order**:

```text
1 publication   two fundamental_summary findings (HBLPOWER, TATACHEM)
                each with symbol, fundamental_as_of, evidence_as_of,
                canonical_filing_id, calculation_ids, conflicts, identity/version
2 embedding     both rows in finding_embeddings  (created ≠ retrievable)
3 retrieval     POST /v1/knowledge/search FIRST — no LLM
                "Why did HBLPOWER pass PLC.A?"
                  #1 HBLPOWER finding → bridge PASS; ranking not in question
                  #1 podcast          → bridge PASS, ranking FAIL → only then ranking
                "Why is TATACHEM still blocked?"
                  must surface INCOMPLETE / PE UNKNOWN / non_positive_eps / DEBT_DEFINITION
                  must not treat stale -3.99 as usable PE
4 LLM last      only if retrieval is correct → rag/run → qwen3:4b explains
```

XBRL must not reach the LLM as a parser. Canonical facts → validated finding → RAG → LLM.

Parallel tracks:

```text
TRACK A                         TRACK B
NSE → FEA → PLC.A              Finding → embedding
     ↑                              ↓
     │                           RAG
     │                              ↓
     └── fundamentals          qwen3:4b
                                   ↓
                              research/interpretation
```

### Per-lab dashboard (replace TaskCompleted theater)

| Metric | Meaning |
|--------|---------|
| Experiences created / closed | Loop is writing / exiting |
| Rewards | Outcome engine exists |
| Learning updates | Candidates, not promotions |
| Validated findings | FEL/statistical |
| Knowledge promoted | Entered knowledge store |
| RAG retrievals of *those* findings | Memory is used |
| Future decisions using learned knowledge | Last arrow exists |

Improvement is Level 1–7 (more data → experiences → understanding → rejected hypotheses not repeated → findings influence candidates → OOS improvement → retrieve on a new situation). P&L today vs yesterday is not the metric.

---

## 8. Evidence appendix (2026-09-17)

### 8.1 Zerodha — API vs store

| Probe | Result |
|-------|--------|
| Session / MDPH | configured, token_valid, READY |
| LTP / historical | PASS |
| `market/bars/YESBANK.NS.json` | Pre-Step-2: `"provider": "yahoo"`, `updated_at` 2026-09-17T08:06:49Z, 2478 daily bars. **Code now writes Zerodha** (daily `bar_store`, 5m `bars_intraday`) with `last_write_provider` / `history_provider`. Live files stamp after bounce + Kite session. |

**Say:** Zerodha API = working. **Zerodha → production data store = wired in code; live stamp after bounce.** Do not treat Yahoo 10y history as deleted — `history_provider` keeps it.

### 8.2 FEA / UQ — code vs process

| Piece | Present? |
|-------|----------|
| `FundamentalEvidenceWorker` + `drain_uncertainty_queue` | yes |
| Mission template `fundamental_evidence` worker_specs | yes |
| Program member ENABLED under market_intelligence | yes |
| Worker manager BATCH/NORMAL class for `fundamental_evidence` | yes |
| Live scheduler task / active worker this audit | **no** |
| UQ | `fcf_missing` PENDING |

Wiring problem. Fix is Step 1, not a new FEA product.

### 8.3 Swing fills — gates, not SMA

| Planned | SMA | Block |
|---------|-----|-------|
| YESBANK | BUY | PLC.A `pe,roe,debt_to_equity` (no fundamentals row). Research **allowed**. |
| JUBLPHARMA | BUY | same PLC.A |
| IDEA | BUY | `research_hold` `thesis_watch_insufficient` |
| WELCORP | BUY | lab_policy thesis=AVOID (this name *has* screener PE/ROE/D/E) |
| MAXHEALTH | no signal | strategy_hold |

Tick identity: `plc_a_hold` 456 = six SMA-BUY names × ~76 ticks; `lab_policy_hold` 152; `research_hold` 76 = IDEA. Last swing fill 2026-08-25. Cash ~₹55,477 flat. Intraday can buy YESBANK because PLC.A is off and lab is `technical_only`.

Hermetic research-seed ratios are **not** PLC.A-complete. Do not disable PLC.A.

### 8.3b Swing fills — 2026-09-18 (same class of gate)

Cash ₹55,477.48, 0 open, 0 fills, plan 0/5. SMA **did** fire.

| Planned / SMA BUY | Block |
|-------------------|--------|
| HBLPOWER | PLC.A `fundamentals_incomplete:pe,roe,debt_to_equity,sector` (no fund row) |
| JUBLPHARMA | PLC.A `pe,roe,debt_to_equity` (no fund row) |
| YESBANK (unplanned SMA) | same PLC.A |
| COALINDIA (unplanned SMA) | PLC.A `roe,debt_to_equity` (PE present, ratios missing) |
| IDEA | `research_hold` `thesis_watch_insufficient` |
| WELCORP | `lab_policy_hold` thesis=AVOID (has screener PE/ROE/D/E) |
| PATANJALI / TATACHEM (planned) | `engine_hold` — no SMA BUY this session; TATACHEM also later `research_forced_hold`. UQ still PENDING pe/roe/fcf/mos/identity |

Last screener import 2026-09-03, **19 symbols**. FEA did not fill the missing rows. Repair = Screener drop + FEA drain, not gate change.

### 8.4 RAG / embeddings

| Fact | Detail |
|------|--------|
| Vector infra | Postgres + pgvector + HNSW healthy |
| Chunk embed drain | `embed_backfill` → existing `embed_document` (bounce draining) |
| `finding_embeddings` | Consolidator **dedup** and **findings RAG tier** (same table, not chunk smash) |
| RagAgent | `knowledge.retrieve` → chunk index **and** findings (`LIVE_TIERS = {knowledge, findings}`) |
| `_dense_rows` | chunk index only; query embed → `embeddings.search`; `[]` on failure |
| Findings RAG | **in code:** `finding_embeddings.search` + statement lexical; `chunk_id=finding:{id}` |
| Hybrid/dense | unit canaries in `tests/test_lab_loop0_rag.py` + `tests/test_lab_loop0_findings_rag.py` |
| **M4-RAG-LIVE Step 1** | **PASS 2026-09-19** on PID 275877 (13:48:59 IST). Retrieve `F-002118` #1 → `rag_generate`/`qwen3:4b` → cited `[1]`. Diagnostics 5488→5490. |
| **M4-RAG-LIVE Step 2** | **LIVE 2026-09-19** on PID 288870. Citations expose `finding_id`, `document_id`, score, source, timestamp. Ranking frozen. |
| **M4-RAG-LIVE Step 4** | **LIVE PASS** 2026-09-19 PID **323438**. `fundamental_summary` for HBLPOWER (CONFLICT / PLC.A COMPLETE) and TATACHEM (PE UNKNOWN / PLC.A INCOMPLETE). Publisher frozen at two symbols. |
| **M4-RAG-LIVE Step 5** | **LIVE PASS + FROZEN** 2026-09-19. Search #1 = F-002148 / F-002149. Ranking frozen. |
| **TRADE-LOOP0 N1** | **PASS + LOCKED** 2026-09-19. HBLPOWER golden replay INCOMPLETE→COMPLETE. Not a fill. Not an experience. |
| Experience / memories | named, deferred, not fused |

```text
Today's learning → findings → finding_embeddings → retrieve(tier=findings)
documents → chunks → embeddings.search → retrieve(tier=knowledge)
query → hybrid fuse → RagAgent
memories/experience → still deferred
```

Memory **storage** exists. Chunk **and findings recall paths are in code**. **Step 11 / M4-RAG-LIVE Step 1 live on the current process (2026-09-19).** Finding-embed backlog remains. Memories/experience still deferred.

### 8.5 Missing connections (the actual work list)

```text
Existing: Zerodha, market stores, fundamentals, FEA, UQ, labs, paper,
          experiences, FEL, RL scaffold, knowledge store, pgvector, RAG, Ollama

Missing:
  Zerodha → persistent lab data
  FEA → UQ (runtime)
  market tape → persistent intraday experience
  F&O → actual contracts
  trade outcome → reward
  experience → learning
  validated learning → knowledge
  knowledge → embedding   (in code: embed_backfill → embed_document; bounce to drain)
  embedding → RAG         (in code: _dense_rows → embeddings.search)
  RAG → LLM               (**M4-RAG-LIVE Step 1 live** 2026-09-19 PID 275877)
  LLM/knowledge → future research
```

That is smaller than rebuilding Atlas.

---

## 9. What we will not do now

- Implement RL / PyTorch / a new learning product
- Invent another architectural component during the proof window
- Loosen swing gates so the book looks alive
- Let Next-₹1 place orders
- Treat hermetic seeds as PLC.A-complete
- Scrape Screener HTML / automate Zerodha 2FA
- Mix F&O into equity FEL datasets
- Dump every trade into pgvector
- Smash findings into the chunk index as a “quick RAG fix”
- Build a second experience database
- Increase capital or go live

---

## 10. Decision log

| Date | Decision | Notes |
|------|----------|-------|
| 2026-09-17 | Three-layer split; Zerodha backbone; FEL validates; RL later | rev 1 |
| 2026-09-17 | Swing 0 fills = PLC.A/thesis, not SMA silence | Do not disable PLC.A |
| 2026-09-17 **rev 2** | **Four workstreams A–D + Steps 1–12 locked.** Three problems: data plane, experience→learning, RAG recall. FEA runtime is Step 1. Zerodha persistence must be proven. Findings-as-tier recommended. RL frozen until 1–11. |
| 2026-09-18 **rev 5** | Swing still 0 fills: SMA BUY on YESBANK/JUBLPHARMA/HBLPOWER/COALINDIA stopped by PLC.A `fundamentals_incomplete`; IDEA `research_hold thesis_watch_insufficient`; WELCORP lab_policy AVOID; PATANJALI no SMA. **Do not loosen PLC.A.** Screener store still missing those names (last import 2026-09-03, 19 symbols). **Step 5 densify:** `fundamentals_incomplete` is a `blocked_buy` tag. **Step 11 in code:** restart canary schedule; bounce twice. |
| 2026-09-18 **rev 6** | **Step 11 LIVE COMPLETE** (finding `F-002118` retrieved after bounce×2, LLM cited `[1]`). Next work is **not** more RAG. Forensic: FEA ticks but 0 Yahoo acquires (`consecutive_blocks=1524`); UQ prunes SMA names that are not Next-₹1; PLC.A D/E has no UQ code; F&O resolver hardcodes NIFTY. Discussion only: [`ATLAS_OPERATIONAL_TRADING_LOOP_AND_FNO_UNIVERSE_DISCUSSION.md`](ATLAS_OPERATIONAL_TRADING_LOOP_AND_FNO_UNIVERSE_DISCUSSION.md). **Do not implement until that file §14 is locked.** |
| 2026-09-19 **rev 7** | **M4-RAG-LIVE Step 1 COMPLETE** on systemd PID 275877 (13:48:59 IST): 2 retrievals after bounce (5488→5490), `F-002118` #1 sim 0.694, `POST /v1/agents/rag/run` 200 in 96.2s, `qwen3:4b` cited `[1]`. Stronger than 2026-09-18 because it is this process, not pre-bounce. **Do not retune ranking** for noisy hits 2–5. **Step 2:** provenance surface (`finding_id`, `document_id`, score, source, timestamp) — in tree, ranking unchanged. FEA continues in parallel. LLM still not the trader. |
| 2026-09-19 **rev 8** | Bounce 15:30:44 IST → PID **288870**. **M4-RAG-LIVE Step 2 LIVE:** search + `rag/run` citations expose `finding_id`, `document_id`, score, source, timestamp for `F-002118`. Ranking unchanged. Next is Step 3 embed drain (background) / Step 5 real questions after bounce-proven provenance. LLM still not the trader. |
| 2026-09-19 **rev 9** | **Step 5 real questions RAN** on PID 288870. A HBLPOWER PLC.A / B TATACHEM blocked / C conflicts: all three LLM answers “I don't have that information.” **Usefulness FAIL, boundary PASS** (no invented PE, no BUY/SELL). Canonical store already has HBLPOWER PE/ROE/D/E/sector and TATACHEM PE=null + `DEBT_DEFINITION`; those facts are **not** in RAG (only “is a listed company” findings). **Do not retune ranking.** Next implementation = Step 4 validated summaries → RAG. NSE/XBRL P0 continues. Step 3 drain stays background. |
| 2026-09-19 **rev 10** | **Step 4 IN CODE.** Bridge is canonical fundamentals store → deterministic `fundamental_summary` → finding → `finding_embeddings`. Slice = HBLPOWER + TATACHEM only. LLM does not interpret financial facts; UNKNOWN stays UNKNOWN (TATACHEM PE ≠ -3.99 ≠ 0); conflicts stay recorded (HBLPOWER 93.72 vs 25.86). New filing supersedes the old finding. **Do not retune ranking** until the live process has those findings. NSE/XBRL P0 continues. Bounce, then re-run Step 5. |
| 2026-09-19 **rev 11** | Operator: Step 4 = **implementation PASS**. TATACHEM EPS −74.42 correctly not embedded (not on canonical store). Stale PE −3.99 stays invalid. Lifecycle = same snapshot no-op / new filing_id new finding. **Step 5 protocol locked:** publication → embedding → raw retrieval first → LLM last. Ranking only if HBLPOWER finding exists and still loses to the podcast. Do not expand to 27. NSE/XBRL P0 independent. |
| 2026-09-19 **rev 12** | Bounce 21:20:40 IST PID **323438**. Publisher 21:23:44 IST created F-002148/F-002149 and embedded both. Search: HBLPOWER PLC.A → **F-002148 #1**; TATACHEM blocked → **F-002149 #1** (PE UNKNOWN / non_positive_eps; stale −3.99 not usable). LLM cited `[1]`. Podcast is #2. **Ranking is not the failure.** Do not expand to 27 until operator asks. NSE/XBRL P0 independent. |
| 2026-09-19 **rev 13** | **M4 Step 5 FROZEN.** Do not touch ranking, hits 2–5, publisher expansion, LLM prompts, or RAG scoring. Next = TRADE-LOOP0 HBLPOWER candidate replay (UQ → FEA → stored XBRL → PLC.A reread). Not a fake fill. |
| 2026-09-19 **rev 14** | **HBLPOWER N1 PASS + LOCKED** as golden replay fixture. Isolated BEFORE INCOMPLETE → AFTER COMPLETE (PE 25.86 FY, ROE 44.08%, D/E 0.020, FCF 6,293,200,000, `DEBT_DEFINITION` kept). `not_a_fill` · `writes_experience=false`. Do not re-engineer HBLPOWER unless `test_hblpower_golden_replay` regresses. Remaining NSE P0 = other names + edge cases. M4 still frozen. RL frozen. |
| 2026-09-21 **rev 16** | Operator: open F&O Phase 2 as a **controlled experiment**, not “let F&O trade.” **P0-A** swing wash-lock (`wash_lock.py`): all-in switch that would breach PLC.B name cap is blocked; same-IST-day re-entry after a sale is blocked. PLC.A unchanged. **P0-B** FNO-P2-001: leftover PE recorded then flattened as boundary; SMA/RSI V1 remains control; adapter maps to NIFTY ATM CE/PE, 1 lot, premium×lot, packet carries underlying/future/option marks. No BANKNIFTY, no writing, no live orders, no RL. P0-C still needs one uncontaminated round-trip → FEL. Attribution (unknown_explicit_cause) stays P1. |
| 2026-09-20 **rev 15** | **PROOF WINDOW.** Do not invent another component. Do not start RL. Atlas serve PID **1973** (15:03 IST restart): Step 11 retrieval **PASS** (`F-002118` #1). F&O packet **PASS** (`NIFTY26SEPFUT` 29-Sep lot 65). Swing `blocked_buy` **PASS** (9 on 18-Sep; gates not loosened). Chunk embeddings **0 remaining** (1669/1669). Finding-embed backlog 1258 stays background. UQ: TATACHEM `pe_missing` is PE UNKNOWN by design; `mos_unknown` is IRA not Yahoo. **Still unproven:** one *new* intraday EXPERIENCE → CLOSE → REWARD → FEL after this wiring. |
| 2026-09-17 **rev 4** | Operator: many days of F&O evidence already exist — **implement ATM CE/PE now and correct from results**. Phase 2 in code: underlier SMA → buy ATM CE (bullish) / ATM PE (bearish) / exit the other on flip. 1 lot at premium. No writing. No BANKNIFTY. Option fills are not index-proxy marks. L4 NIFTY proxy remains fallback only when ATM unresolved. Live orders still off. |
| 2026-09-03 | FEL E001 vol-accel lost | Keep as validation pattern |
| 2026-09-03 | MDPH live-required pause; no silent Yahoo | Unchanged; backbone extends it |
| 2026-08-24 | Zerodha ≠ PE/FCF | Unchanged |

---

## 11. Related Open Items

| OI | Relation |
|----|----------|
| `OI-LAB-LOOP0` | **This file** — master implementation plan |
| `OI-FEA0` | FEA **code** exists; **Step 1 is make it tick** |
| `OI-ZERODHA0` | LTP/quote scaffolding; **Step 2 persist in code** (`bar_store` / `bars_intraday`) |
| `OI-MDPH0` | Provider health; live-required pause |
| `OI-DATA-PLANE0` / `OI-WEB-EVID0` | Completeness; Zerodha ≠ PE |
| `OI-FNO-CONTRACT` | Risk isolation (landed). **Step 3:** nearest NIFTY FUT tape + ATM CE/PE paper in code |
| `OI-INTRADAY-FLAT` | Flatten works; **Step 4 5m tape persist/reload in code** |
| `OI-LAB-LOOP0` Step 5 | **`blocked_buy` JSONL in code** (`lab_experience.py`); not P&L; not pgvector |
| `OI-LAB-LOOP0` Step 6 | **Round-trip reward in code** (`lab.loop0.reward.v1`); book P&L; no SMA/RSI mutation |
| `OI-LAB-LOOP0` Step 7 | **Paper experiences → FEL in code** (`paper_round_trip`); cash-baseline; never `live_control`; not RL |
| `OI-LAB-LOOP0` Steps 8–9 | **Chunk embed backfill + `_dense_rows` in code**; bounce to drain |
| `OI-LAB-LOOP0` Step 10 | **Findings RAG tier in code** (`finding_embeddings` searched; not smashed into chunks). Memories deferred. |
| `OI-LAB-LOOP0` Step 11 / M4-RAG-LIVE | **Steps 1–2 + 4–5 LIVE PASS** PID **323438**. **FROZEN.** Do not retune ranking or expand to 27. |
| `OI-FEL0` | E001/E002 continue; paper kind is an additional queue consumer |
| `OI-LEARN-AUDIT0` | Will measure §7 |
| `OI-DI0` / `OI-LI0` | Extend packets/labs; do not replace |
| Stage 3B RAG | Steps 8–11 **in code**; **M4-RAG-LIVE Steps 1–2 live-proven 2026-09-19** (PID 288870). |
| `OI-TRADE-LOOP0` | **N1 HBLPOWER PASS + LOCKED** golden fixture. Remaining: other names + NSE edge cases. Hourly FI mail. F&O F is P1. |

---

## 12. One-line north star

> Make one laboratory reconstruct what it saw, complete a paper experience with a reward, validate that lesson scientifically, and prove the LLM can retrieve it after a restart. Zerodha is the market tape. Screener/Yahoo are the books. FEL is the science. RAG is memory recall. The LLM is the interpreter. None of them is the trader.
