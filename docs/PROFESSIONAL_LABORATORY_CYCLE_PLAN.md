# Professional Laboratory Cycle — Observation, Thesis Gates & Multi-Lab Ops

> **Status:** ✅ **FINALIZED FOR IMPLEMENTATION** (operator-approved direction 2026-08-08)  
> **OI:** `OI-PLC0`  
> **Date:** 2026-08-08  
> **Does not reopen:** DI.1–7 · LI.1a–6 · LQ.1–9 architectures (reuse seams)  
> **Control strategy:** Keep SMA/RSI (`sma_cross_rsi`) as India Equity Laboratory control — no strategy mutation / AtlasNet train this cycle  
> **Partial already landed:** PLC.E (F&O/intraday pack align) · PLC.F (career + market status chat, no Ollama)

---

## 0. Verdict (why this cycle exists)

Atlas is a **structured investment laboratory**, not a toy paper bot. Architecture and honesty are strong (≈9.5–10). Weak scores are **data density and decision quality wiring**:

| Area | Score (review) | This cycle targets? |
|------|----------------|---------------------|
| Architecture / honesty / durability | 9.5–10 | Protect — do not rewrite |
| Research quality | 5 | Partial — thesis trigger + sector-first why |
| Continuous observation | 4 | **Yes — Phase C** |
| Learning from outcomes | 4 | **Yes — evolution richness + sells** |
| Autonomous improvement | 3 | No — precursor data only |
| NN readiness | 2 | No — gates stay |

**North star:** Atlas is an **investment researcher that happens to trade**, not a trading bot that occasionally researches.

**Learning unit:** hypotheses (not trades alone). Every buy creates a checkable hypothesis; revisits and exits judge it.

---

## 0.1 Non-negotiables (carry forward)

1. Never invent PE / FCF / MoS / observations / attributions.  
2. Laboratory hermeticity — no KPI/prior bleed across `india_equity_learner` / `equity_intraday_learner` / `india_fno_learner`.  
3. SMA/RSI remains the **control** lane; new gates and exits are additive reason codes.  
4. AtlasNet / live NN remain **prep-only** until LQ.9 §8.2 + DI.7 sample gates clear.  
5. Evening digests stay honest: distinguish **not due yet** vs **mission idle** for revisits.

---

## 1. What is already shipped (do not rebuild)

- Decision packets · timeline · denser revisits (LQ.2) · observation store + Host Guard marks  
- Hypothesis store + APIs (not auto-wired on buy)  
- Tier-C Yahoo enrich + rate gate (LQ.7)  
- Exit attribution infer + feature drivers (LQ.4) when sells exist  
- Sector intelligence path (SI / LQ.1)  
- Multi-ledger labs registry  

**Ops reality today:** 5 swing holdings, 0 sells, 16 revisits pending / 0 done (mostly **not due yet**), fundamentals store = 3 names (not the open book), research dossiers ≈20% coverage / confidence capped.

---

## 2. Phased implementation

### Phase A — Buy quality (control SMA + fund + thesis) · `PLC.A`

**Keep:** SMA fast>slow + RSI acceptable as technical trigger.

**Add hard (fail-closed) buy conditions:**

| Code | Requirement | Honest hold reason if missing |
|------|-------------|-------------------------------|
| A1 Technical | Existing SMA/RSI | unchanged |
| A2 Fundamental sanity | PE, ROE, debt/equity present **and** sector identified | `fundamentals_incomplete` / `sector_unknown` |
| A3 Thesis trigger | One explicit sector-aware reason in packet `reasons_for` (not only “researched”) | `thesis_trigger_missing` |

**Wire:** `paper_trading` / research gate consumes fundamentals store + dossier sector; Tier-C enrich remains feeder, **not** a silent bypass.

**Done when:** New swing buys either satisfy A1–A3 or journal a clear hold reason; evening “why we own X” shows thesis trigger text when bought under PLC.A.

**Tests:** hermetic — buy blocked without PE; buy allowed with stub fund+thesis+SMA; control tag still `sma_cross_rsi`.

**Status:** ✅ code landed (`plc_buy_gates.py` · wired in `paper_trading` · learner preset `plc_a_gates: true`). Live books may need mission config refresh / restart to pick up preset.

---

### Phase B — Richer exits + labeled failure · `PLC.B`

**Keep:** SMA crossunder exit as one lane.

**Add exit reason codes (sim proposals):**

- `thesis_broken` · `valuation_excessive` · `better_opportunity` · `concentration` · `earnings_deterioration` · `stop_loss` · `trailing_stop` · `time_stop`

Every material sell must set **one primary failure cause** (map exit code → LQ.4 taxonomy; do not invent on winners).

**Done when:** At least two non-SMA exit paths fire in hermetic tests; attribution `failure_cause` set on loss exits; evening surfaces primary cause.

**Status:** ✅ code landed (`plc_exits.py` · paper_trading overlay · learner `plc_b_exits: true` · evening rules + cause lines).

---

### Phase C — Daily open-book observation engine · `PLC.C`

**Priority:** open positions first (not vanity watchlist marks).

For each open book symbol, once per session day (Host Guard budgeted), record a structured observation pack:

| Block | Fields (honest unknowns OK) |
|-------|------------------------------|
| Market | close, return, volume Δ, RS vs NIFTY (if bars), volatility band |
| Fundamentals | PE / PB / mcap snapshot if known; earnings proximity if known |
| News / policy | company / sector / macro / gov deltas when providers have them |
| Thesis | strengthening / unchanged / weakening (rule or revisit heuristic — never invent) |
| Confidence | ↑ / ↓ / unchanged vs prior packet |

Reuse observation kinds; **compose** into one daily open-book row cited by revisits.

**Done when:** Evening “Under observation” cites today’s pack IDs; open books get packs even if watchlist is quiet; budget never starves Host Guard.

---

### Phase D — Hypothesis-first learning · `PLC.D`

On every buy:

1. `create_hypothesis` — e.g. “SYMBOL outperforms NIFTY over 90d because \<thesis trigger\>”  
2. Stamp `hypothesis_id` on Decision Packet  
3. Schedule checks at **7d / 30d / 90d / exit** (evolution worker or sibling tick)  
4. Verdicts only with ≥3 linked observations (existing gate)

**Done when:** Live buys create hypotheses; digests show hypothesis status; ML export / AtlasNet prep can count links without force override.

---

### Phase E — Evolution honesty + multi-lab Monday ops · `PLC.E`

1. Evening copy: `revisits_due_today` vs `pending_future` vs `completed` — stop implying mission dead when 0 done and all future.  
2. Deepen `what_changed` on due revisits (thesis / valuation / policy / early-vs-wrong) using observation packs.  
3. **Monday readiness** (ops + small code):

| Lab | Monday expectation |
|-----|-------------------|
| `india_equity_learner` | Continue control SMA lane; PLC gates roll out behind flags if needed |
| `equity_intraday_learner` | Active Decision Simulation + cash; apply `intraday` personality; session risk mentor; same NSE cash hours |
| `india_fno_learner` | `allowed_assets=["futures"]`, `market_session=nse_fno`, **explicit instruments** (no cash auto-universe), lot/margin pack |

Aug 10 2026 is a normal NSE session (not a holiday).

---

### Phase F — Chat reliability + DB-backed status · `PLC.F`

**Symptom:** Console Chat returns LLM timeout after ~60s. Logs: `httpx.ReadTimeout` on Ollama. Root cause: open questions use `Intent.ANSWER` (`interactive_timeout=60s`) while Ollama is saturated (`max_concurrency=1`) by market/research load.

**Principle:** Operator “what did you learn / status” questions must read **durable stores + Postgres Goals** — never wait on the chat LLM.

| Item | Work | Status |
|------|------|--------|
| F1 Career status | `Intent.CAREER_STATUS` → morning brief | ✅ |
| F2 Market status | `Intent.MARKET_STATUS` → labs + fundamentals + research count + Goals learner narrative | ✅ |
| F3 Honest LLM timeout copy | Points to status phrases + background research | ✅ |
| F4 Ops | Restart Atlas after deploy | operator |
| F5 (next) Knowledge DB path | Expand ASK_KNOWLEDGE for “what do we know about X in Atlas” when findings exist — still no invented facts | ✅ |
| F6 (next) Optional Ollama health preflight | Fail fast (&lt;3s) when runner saturated instead of 60s hang on ANSWER | ✅ |

**Done when:**  
- “what did you learn on market intelligence…” and “…career intelligence…” return in &lt;2s  
- Sessions still persist in conversation DB  
- Generic chat may still timeout under load, with recovery phrases that hit F1/F2

**Non-goal:** Replacing Ollama; making ReAct the default interactive path; inventing market edge in chat.

---

## 3. Explicit non-goals

- Rewriting SMA periods / RSI thresholds as “learned” parameters  
- Live NN trading or AtlasNet train  
- Mixing lab outcome stats  
- Fake revisit completions before `due_ist`  
- Autonomous F&O universe ranking (operator instruments only)

---

## 4. Coding order (FINAL)

| Order | Phase | Deliverable | Status |
|------:|-------|-------------|--------|
| 0 | **E + F** | Monday lab pack align + chat status (career/market) | ✅ partial |
| 1 | **A** | Hard buy gates: fund sanity + thesis trigger (SMA control kept) | ✅ code |
| 2 | **C** | Daily open-book observation packs | ✅ code |
| 3 | **D** | Hypothesis-on-buy + 7/30/90/exit | ✅ code |
| 4 | **B** | Richer exits + primary failure cause | ✅ code |
| 5 | **E remainder** | Evening revisit honesty (due vs pending vs done) | ✅ code |
| 6 | **F5–F6** | Knowledge-DB ask path + fast Ollama busy detect | ✅ code |

---

## 5. Success metrics (6–8 weeks)

- Open-book daily observation coverage ≥80% of holding-days  
- New buys: ≥95% have fund sanity **or** explicit block reason  
- 100% of new buys have `hypothesis_id`  
- Revisits: completed count rises after day1+ due dates (not stuck at 0 forever)  
- ≥30 closed attributable exits on swing lab before any strategy-mutation discussion  
- Intraday + F&O: at least one in-session tick journal per lab on first open Monday after repair (fills optional; idle-from-misconfig = fail)  
- Career **and** Market status chat phrases return &lt;2s without Ollama; LLM timeout copy names busy-host recovery  

---

## 6. Implementation kickoff checklist

- [x] Plan finalized (`OI-PLC0` / this doc)  
- [x] PLC.E registry repair path + F&O/intraday create_book alignment  
- [x] PLC.F career + market deterministic chat  
- [x] PLC.A buy gates (fund + thesis trigger)  
- [x] PLC.C daily open-book observation packs (`open_book_packs` · market_observer · evening cite)  
- [x] PLC.D hypothesis-on-buy + 7/30/90/exit checks (`plc_hypothesis` · paper_trading · evolution)  
- [x] PLC.B richer exits + failure_cause (`plc_exits` · paper_trading · evening)  
- [x] PLC.E remainder — revisit due/future/done honesty + deepened what_changed  
- [x] PLC.F5–F6 — ASK_KNOWLEDGE expand + LLM lane busy fail-fast  
- [x] `systemctl restart atlas.service` (operator 2026-08-08/09)  
- [x] Start missing `fundamentals_enrich` + `decision_evolution` missions (2026-08-09)  
- [x] Yahoo chart TTL cache (5m) to reduce IP heat vs fundamentals crumb  
- [ ] Mon open: confirm Yahoo; F&O/intraday session tick journals
- [x] PLC.E wake: `^NSEI` caret durable load · F&O instrument self-heal · BANKNIFTY→^NSEBANK
- [ ] After restart: F&O session note shows marks (not only `market_data:yahoo` gaps)  
- [ ] Yahoo getcrumb recovery **or** Screener Tier B PE import for open books  

_PLC coding complete; ops = Mon verify + fundamentals data path._
