# Atlas Learning Integrity — Clean Labs, Then Capital Allocation

> **Status:** 🔒 **LOCKED — Phase 6 in code** (operator 2026-08-20)  
> **Codename:** `OI-LINT0`  
> **Evidence day:** NSE session **2026-08-19** (all three labs woke)  
> **Parents:** [`ATLAS_CLOSED_LOOP_LAB_WAKE_PLAN.md`](ATLAS_CLOSED_LOOP_LAB_WAKE_PLAN.md) ·
> [`UNIVERSE_TRIAGE_AND_OPPORTUNITY_SWITCHING_PLAN.md`](UNIVERSE_TRIAGE_AND_OPPORTUNITY_SWITCHING_PLAN.md) ·
> [`PROFESSIONAL_LABORATORY_CYCLE_PLAN.md`](PROFESSIONAL_LABORATORY_CYCLE_PLAN.md) ·
> [`MARKET_LABORATORY_EVIDENCE_AND_ATTRIBUTION_PLAN.md`](MARKET_LABORATORY_EVIDENCE_AND_ATTRIBUTION_PLAN.md) ·
> [`RELIABLE_LEARNING_DATASET_DISCUSSION.md`](RELIABLE_LEARNING_DATASET_DISCUSSION.md) ·
> [`ATLAS_PERSISTENT_SELF_AND_BELIEF_CORE_PLAN.md`](ATLAS_PERSISTENT_SELF_AND_BELIEF_CORE_PLAN.md) ·
> [`JUDGMENT_PIVOT_DISCUSSION.md`](JUDGMENT_PIVOT_DISCUSSION.md)  
> **Connect, do not rebuild:** OI-UTS0 · OI-MTL0 · OI-EVID-NET0 · OI-CURIOSITY0 · OI-WSO0 · OI-F2 temporal · OI-DAV0 · L1 E[R] prototype · LOOP0 L0–L5  
> **Does not reopen:** AGENT-1 freeze · SELF0 **Phase 5 size/side influence** · SMA/RSI control auto-mutation · inventing PE/FCF/MoS/news · OI-FEED-1M · AtlasNet live NN · a second Yahoo/news product  
> **Unit of truth:** lab contracts + **best use of the next rupee** (challenger vs book vs cash) + contradiction records + prediction-error experiences — not tick counts, dossier counts, IQ 53.5, or “confidence: high”

---

## 0. Operator thesis (LOCKED)

Atlas is **no longer a dead system**. 19 Aug proved the loop **executes**.

Two uncomfortable truths followed:

1. **Integrity.** Parts of the decision architecture are disconnected. That produced actions Atlas cannot logically justify (FNO bought Bosch; CIPLA/ASTRAL thesis said WATCH while the engine bought; intraday carried overnight).
2. **Economy.** We have **over-invested in machinery around learning** (research, ranking, revisit, attribution, belief, memory, mail) and **under-built the mechanism that turns learning into opportunity selection**. Atlas is becoming good at **describing what it did**. It is not yet good at answering: **of everything I could own right now, what is the best place for my next ₹1?**

**North star — scientific honesty:**

> Atlas is not rewarded for activity. Atlas is rewarded for converting evidence and experience into justified belief updates while preserving uncertainty when evidence is insufficient.

**North star — economic objective (the actual product):**

> Build an increasingly capable autonomous investment intelligence that learns from evidence and experience, identifies superior opportunities, allocates capital to them, manages risk, and improves its expected risk-adjusted return over time.

Research reports, beliefs, paper trades, and chat are **means**. They are not the objective.

The investor loop (missing middle today):

```text
WHOLE OPPORTUNITY SET (~190)
        ↓
FIND BEST OPPORTUNITIES
        ↓
COMPARE AGAINST CURRENT BOOK + CASH
        ↓
EXPECTED RETURN / RISK / CONFIDENCE
        ↓
ALLOCATE CAPITAL
        ↓
MANAGE POSITION
        ↓
LEARN FROM OUTCOME (prediction → actual → error)
        ↓
IMPROVE NEXT RANKING / E[R]
        ↺
```

**Do not** respond to 19 Aug by “trade more.” More ASTRAL round-trips with a WATCH thesis and an overnight book only contaminates experiences.

**Do not** add another major subsystem. UTS, E[R] prototype, MTL, Evidence Network, curiosity, WSO, temporal knowledge, and DAV already exist. **Connect them around capital → opportunity → decision → outcome → learning.**

**Do not** treat `switch_blocked_missing_er` as an annoying reason Atlas isn’t trading. It is the **central missing capability**: without E[R], CIPLA vs ASTRAL vs BOSCH vs NAUKRI vs **cash** cannot be compared economically.

---

## 0b. Ultimate objective vs four intelligences

SELF0 identity / knowledge / beliefs / experiences / reasoning / memory stays the **shared cognitive architecture**.

Each intelligence has a **different objective** on that architecture:

| Intelligence | Goal |
|--------------|------|
| Market | Increase **risk-adjusted capital growth** |
| Engineering | Solve engineering problems better over time |
| Personal | Help the user achieve their goals better |
| Chat | Access accumulated knowledge, beliefs, experiences, reasoning |

This plan is **Market**. Do not optimize Market for “good emails” or “66 belief consultations.” Optimize for: **given everything Atlas currently knows, what is the best use of available capital — and how confident are we that we know that?**

Metric correction:

| Activity metric (weak) | Investor metric (required) |
|------------------------|----------------------------|
| 61 dossiers researched | Did those dossiers raise P(capital → best available opportunity)? |
| 14 decision evaluations | Did Atlas evaluate **best alternatives vs book vs cash** and allocate accordingly? |
| 66 belief consultations | Did a **justified** belief change subsequently **improve a decision**? |
| 666 ticks | Clean **experiences** with prediction error |

---

## 1. What 19 Aug actually proved (evidence, not prose)

| Lab | Woke? | Honest result | Integrity failure |
|-----|-------|---------------|-------------------|
| `india_equity_learner` | Yes | CIPLA×15 + Eicher×2, cash ~₹17.1k, equity ~₹54.45k, total P&L ~−₹548. One CIPLA add (+2). Daily marks 2/2. Packets, revisits, IRA queued. | Thesis/identity vs BUY; PLC.A fail-closed on challengers (legitimate **and** E[R] missing). Cash idle vs 188 names **unasked**. |
| `equity_intraday_learner` | Yes | Yahoo **5m** store: ASTRAL 206 / IDEA 205 / BOSCH 200 / WELCORP 76 (09:15–15:15). Buys/sells on SMA10. | **Not flat EOD** — ASTRAL×5 after close. Thesis WATCH vs technical BUY. |
| `india_fno_learner` | Yes | **L4 happened:** NIFTY×25 @ 24,154.90 at 09:17. | **~5s later** exploratory switch sold NIFTY, bought **BOSCHLTD×2**. KPI +₹2,420 is **Bosch cash mark**, not F&O / not index-proxy P&L. |

Mail, ticks, 5m persist, throttling (≤3 names, 429 cooldown), and honesty language (ranking untrusted, revisions=0, FNO not F&O) all worked.

Ollama `/api/chat` failed MEM.1 text (12×). Yahoo 429 overnight. Morning hypothesis skipped (cognitive budget 0). Belief consultations 66, **material revisions 0**. Evidence delta: **news=0, policy=0**; CIPLA/Eicher timeline lanes unknown. Policy context last seen stale (e.g. 2026-07-29 vs later market date).

That is a **successful wake**, then **three architectural integrity bugs**, a **missing capital-allocation question**, and **world/event evidence that exists as lanes but is not a decision-time stream**.

---

## 2. Three failures that must be architecture, not observability

Observability (“oops, I bought Bosch”) is already good. **Architecture** makes the illegal state **impossible**.

### 2.1 🔴 FNO laboratory contamination

UTS opportunity-switch is **generic**. It evaluated cash names inside `india_fno_learner` and **destroyed the L4 experiment**.

**Invariant (hard):**

```text
india_fno_learner
  → only index-proxy / F&O instruments (NIFTY, later BANKNIFTY, later true contracts)
  → cash equities (BOSCH, CIPLA, ASTRAL, IDEA, …) → REJECT
  → opportunity_switch MUST NOT propose or execute cash challengers
```

`skip_cash_alts_for_lab` already skips cash **next_alts**. It did **not** bind **switch**. That is the bug.

KPI / evening / mail must keep the label **NIFTY index-proxy laboratory performance**. Never “F&O performance.” Bosch marks in this book are **contamination**, not alpha.

### 2.2 🔴 Thesis / identity / engine contradiction

19 Aug:

| Layer | CIPLA | ASTRAL |
|-------|-------|--------|
| Linked thesis | WATCH — not BUY; MoS unknown | WATCH — not BUY; MoS unknown |
| Identity | Hospital-network copy (wrong) | (usable or not — still WATCH) |
| Engine | SMA10 medium BUY | SMA10 medium BUY, repeated |
| Gate language | research gate allowed | research gate allowed |
| Fill | BUY ×2 (add to book) | BUY/BUY/SELL/BUY/BUY |

“Research gate allowed” is **misleading** if it means “MVR file exists,” not “thesis stance permits the trade.”

**Required decomposition on every fill packet:**

```text
Technical signal     = BUY | HOLD | SELL
Fundamental thesis   = BUY | WATCH | AVOID | INVALID | ABSENT
Research confidence  = …
Identity             = VALID | QUARANTINED
Risk / PLC / hours   = PASS | FAIL
Lab policy           = which layer wins
Challenger vs book   = KEEP | HOLD | ROTATE | CASH  (swing; after E[R])
Final decision       = …
Contradiction        = none | listed
```

**Lab policies (LOCKED):**

| Lab | If technical BUY and thesis WATCH |
|-----|-------------------------------------|
| Intraday | **BUY allowed** — this lab is a technical-control experiment. Packet must say so. |
| Swing | **HOLD** (or explicit `add_to_incumbent` only if identity VALID and thesis does not AVOID). New names: thesis WATCH does not promote to BUY. After Phase 3B, **rotate** only via challenger + threshold, not SMA alone. |
| FNO | Thesis/cash names **do not apply**. Instrument gate first. |

Wrong CIPLA identity → **THESIS INVALID / QUARANTINED**. Still may mark/hold the existing book. Must not use hospital-network prose as evidence.

Philosophy correction for swing (after integrity + E[R]): Atlas does **not** need to prove “CIPLA is bad” to leave CIPLA. The question is **is there something materially better after costs and uncertainty?** CIPLA valid ≠ CIPLA best. Do **not** swing to daily churn (see §3b thresholds).

### 2.3 🔴 Intraday book is not intraday

5m feed is real. Carrying ASTRAL overnight **contaminates** P&L, duration, attribution, and next-open.

**Invariant (hard):**

```text
IST 15:20–15:25  (before cash close; never wait for 15:30 idle)
  → flatten ALL equity_intraday_learner positions (paper sells)
  → write EXPERIENCE / EOD outcome per name
  → cash-only overnight
```

No exceptions. Personality `flat_eod` is currently **advice**; it must be a **gate**.

---

## 3. Decision hierarchy (per laboratory)

Integrity and eligibility still wrap everything. **Swing’s economic center** is capital allocation, not the SMA engine.

```text
WORLD / EVENT STREAM (timestamped; unknown stays unknown)
        ↓
State builder (facts / unknowns / identity / thesis / book / cash)
        ↓
Contradiction detector
        ↓
LLM reasoner  — EVENTS ONLY, structured JSON, advice-only
        (thesis / uncertainty / catalysts / what would change E[R])
        ↓
E[R] + confidence + risk + liquidity + portfolio fit   (crude + honest)
        ↓
CAPITAL ALLOCATION
  incumbents vs best challengers vs CASH
        ↓
Deterministic engine — hours, instruments, PLC, size, flatten, switch threshold
        ↓
Paper fill
        ↓
Outcome observer → prediction error → attribution → experience → belief / E[R] update
```

LLM **never** places an order. LLM **never** mutates SMA/RSI.  
`decision_advice: DO_NOT_OVERRIDE_RULE_ENGINE` is the default.

Fast loop = every tick (deterministic).  
Cognitive loop = learning events only (new fill, exit, large move, new fundamental, news/policy event, falsifier, identity mismatch, LLM failure, challenger advantage crossing threshold).

666 paper ticks must not become 666 Ollama calls.

Strategy engines (SMA/RSI, PLC exits) are **inputs** to allocation in swing. They are **the experiment** in the intraday lab. They are **not** the FNO lab (instrument gate first).

---

## 3b. Capital Allocation Engine (elevate; do not replace UTS)

UTS already has challengers, `expected_return`, `risk_adjusted_score`, and “null E[R] ⇒ no switch.” That is the right **shape**. It is not yet the daily **investor question**.

Every swing session Atlas must be able to fill a table like (numbers illustrative; **unknown stays blank, not 0**):

| Asset | E[R] | Confidence | Risk | Portfolio fit | Opportunity score | Role |
|-------|------|------------|------|---------------|-------------------|------|
| CIPLA | … | … | … | incumbent | … | holding |
| EICHER | … | … | … | incumbent | … | holding |
| BOSCH | … | … | … | challenger | … | vs CIPLA |
| Cash | ~rf / 0 excess | high | none | residual | … | **always a challenger** |

**Every holding has one best challenger. Cash has a best opportunity.**

```text
Current position  vs  best challenger
        ↓
challenger advantage  ?  costs + uncertainty margin + turnover penalty + min improvement
        ↓
KEEP | HOLD (≈) | ROTATE
```

If Atlas cannot answer **why CIPLA instead of BOSCH (or cash)**, it is not managing a portfolio.

**Anti-churn (LOCKED):** ROTATE only if advantage **exceeds** transaction costs + uncertainty margin + tax/turnover penalty + confidence floor + minimum expected improvement. Patient when patience is **economically** rational — not because a field is missing **and we pretend the question was asked**.

**E[R] v1 (crude + honest is better than missing):**

```text
E[R] ≈ technical + fundamental + valuation + catalyst − risk penalties
       with er_basis, er_completeness, confidence
```

Later (after world stream): add company/sector/policy events, relative strength vs NIFTY/sector/peers, historical analogue median, LLM thesis assessment, past Atlas prediction error, opportunity cost vs book.

L1 prototype already exists (`expected_return_prototype.py`). **Wire it as the comparison currency** for swing challengers; do not invent a second model. Incomplete inputs → low `er_completeness`, **not** silent 0%.

---

## 4. What “I learned X” is allowed to mean

Atlas may say **learned** only if all of these exist:

evidence + prior state + hypothesis/decision + **stated prediction (E[R] or analogue)** + new observation + outcome + attribution + **prediction error** + updated belief **or** explicit rule / E[R] candidate

Otherwise it must say **observed**, **unknown**, or **hypothesis**.

Do **not** conclude “ASTRAL went up after SMA crossed, therefore SMA works.” Conclude: **when these conditions, predicted X, realized Y, error Z, candidate reason**.

Four things Market intelligence must eventually learn:

1. **What makes an asset good** (business / quality)  
2. **What makes an opportunity attractive now** (timing)  
3. **What makes a position better than another** (relative / opportunity cost)  
4. **What makes Atlas’s own predictions wrong** (calibration)

LLM unavailable ≠ belief unchanged. Status must be **UNREVIEWED** (`LLM_UNAVAILABLE`), rescheduled. Do not fabricate BRE.2 text.

Consultations without revisions remain **activity without changed judgment**.

---

## 5. Four learning tracks (never one IQ number)

| Track | Question | 19 Aug status |
|-------|----------|----------------|
| **A Strategy** | Did SMA/RSI/stops have expectancy **in this lab**? | Thin; ASTRAL round-trips contaminated by overnight + WATCH thesis |
| **B Market** | Why did the name move? | news=0, policy=0, bars attribution often “could not determine” |
| **C Atlas** | Did reasoning notice contradiction, unknown, LLM miss? | Honesty good; revisions 0 |
| **D Relative opportunity** | Did this asset outperform / underperform NIFTY, sector, peers, **current holdings**, and **cash** — and why? | **Missing as a first-class object.** Ranking exists; daily “next ₹1” does not. |

Dashboard / evening **lead** with: best allocation vs book vs cash, experiences, contradictions, resolved unknowns, closed lab experiments, LLM reliability, **prediction errors** — **not** 1982 `mark_only`, not process 7.5/10, not maturity 53.5 as “intelligence.”

Split operator-facing confidence:

| Label | Meaning |
|-------|---------|
| System health | workers/mail/feeds up |
| Data confidence | marks / 5m / Yahoo 429 / news-policy freshness |
| Ranking confidence | **LOW** until trusted |
| Allocation confidence | **LOW** until E[R] + challenger table exists |
| Strategy evidence | **THIN** until closed trades / lab |
| Thesis confidence | **VERY LOW** until identity+FCF/MoS |

Do not print a single `confidence: high` next to “ranking not trustworthy.”

---

## 5b. World / Event Intelligence (connect MTL · Evidence Network · curiosity · temporal)

Atlas is **not** “looking at the web” in the investor sense. Lanes exist; decision-time stream does not.

| World | Status | Gap |
|-------|--------|-----|
| Historical **prices** | Substantially present (OHLCV, bootstrap, RS, depth ok) | Used for bars/ranking, **not** analogue → conditional expectation |
| News / web | Architecture can represent; **news stays queued**; open books **news=0 / unknown** | OI-EVID-NET0 remaining: real company news/commentary |
| Government / policy | Static context exists (Budget, PLI, …) | Stale (e.g. 2026-07-29); not a **living policy timeline** |
| LLM | Façade / budget / roles exist | Consultations without revisions; Ollama failures; not event-packet scientist |

**Do not** build `Yahoo news → LLM → sentiment` as a product.

**Do not** create a new top-level subsystem.** Strengthen:

- OI-MTL0 timelines (news + policy lanes already unknown-honest)  
- OI-EVID-NET0 / WSO  
- OI-CURIOSITY0 (news queued ≠ done)  
- OI-F2 temporal (`valid_from` / `valid_until` / truth_kind) — **mandatory** on market events  
- OI-DAV0 / LQ causal attribution  
- IRA evidence hierarchy  

### Event types (living timeline)

```text
WORLD
  ├── Company: results, guidance, orders, M&A, management, litigation, capacity, products
  ├── Sector: demand, commodity, competition, regulation, capacity, sector index
  └── Government / macro: Budget, RBI, SEBI, ministries, tax, tariffs, PLI, rates, infra
        ↓
EVENT TIMELINE (chronological)
        ↓
LLM ANALYSIS (bounded packet)
        ↓
DECISION-TIME STATE → E[R] / challenger / HOLD
```

Policy must be **events** (announce → clarification → notification → industry response → company commentary → price reaction), not a static list.

**Relative to the market (Track D):** a positive pharma policy is not “pharma good.” Compare NIFTY vs sector vs CIPLA vs DRREDDY vs SUNPHARMA. Under-reaction vs peers is an **opportunity signal**, not a slogan.

### Historical analogue engine (after clean labs)

Current state (RSI, sector RS, NIFTY, PE, event class) → retrieve similar **past** states → 30/60/90d return **distribution** + sample size + dispersion. LLM **interprets cases**, does not invent the distribution. Honest: “median +5.2% 30d, n=14, wide.”

Policy class analogues the same way (e.g. 11 comparable PLI-like events → who benefited).

### Event → impact attribution (never news-up ⇒ news caused it)

```text
EVENT → expected impact → sector → names → actual move → relative move
     → evidence strength → causal | likely | possible | unsupported | unknown
```

Unknown remains unknown.

### Source hierarchy (reuse IRA; enforce at ingest)

| Tier | Examples | Role |
|------|----------|------|
| 1 Primary | Ministries, Budget, RBI, SEBI, NSE/BSE, filings, IR, official results | May become evidence |
| 2 High-quality secondary | Reuters, Bloomberg, major financial press, reputable institutions | May become evidence with provenance |
| 3 Discovery | aggregators, blogs, social, forums | **Research question only** — never auto-evidence |

### Timestamps (mandatory for market-event learning)

Every evidence object: `observed_at`, `published_at`, `valid_from`, `valid_until`, `source`, `source_tier`, `retrieved_at`.

A decision at 19 Aug 09:30 may use **only** information available **before** 09:30. No future leakage into historical lessons.

### LLM packet (extend Phase 3; still advice-only)

Include: price/technical, relative (NIFTY/sector/peers/holdings/cash), fundamentals, historical analogues, company/sector/government events, thesis, prior belief, falsifiers, position, **best challengers**.

Ask: what changed; what matters; what contradicts; what is unknown; causal vs correlated; research next; **did E[R] assessment change**; what would falsify.

JSON out: existing fields **plus** `er_advice` (not an order), `challenger_view`, `event_attribution_class`.

---

## 6. Implementation order (LOCKED — do not reorder Phase 1 before the rest)

Do **not** parallelize Phase 3–6 with Phase 1. **Clean experiments first**, then world model, then LLM on that model, then prediction-error learning. Integrity order from the 19:29 plan **stands**. Phases 3–5 are **amended** to include world/events and capital allocation — by **wiring existing OI items**, not new products.

```text
Phase 1   Laboratory integrity                    ✅
Phase 2   Knowledge / thesis integrity            ✅
Phase 3   LLM scientist (events, structured I/O)  ✅
Phase 3A  Market world / event stream             ✅
Phase 3B  Capital allocation / challenger / E[R]  ✅
Phase 4   Learning objects + prediction error      ✅
Phase 5   Curiosity + evidence verify              ✅
Phase 6   Learning-first evening report            ✅ this landing
Phase 4   Learning objects + prediction error + Track D
Phase 5   Decision-value curiosity + evidence verify (incl. news drain)
Phase 6   Learning-first evening (allocation table above the fold)
```

Phase 3A/3B may be **specified** in parallel with Phase 3 design, but **must not ship before Phase 1 is live**. Crude E[R] for swing comparison may land in 3B as soon as Phase 1–2 stop contaminating books.

### Phase 1 — Laboratory integrity (must land before next RTH if possible)

1. FNO **instrument allowlist** at buy, switch, and alt injection. Cash equity → reject + journal `lab_instrument_rejected`.
2. Disable **opportunity_switch execute** for cash challengers in FNO (evaluate-only optional, execute never).
3. Intraday **mandatory flatten** 15:20–15:25 IST; packet `eod_flatten`; no overnight qty.
4. Per-lab **strategy contract** on the packet (`technical_only` vs `thesis_gated` vs `index_proxy_only`).
5. Optional operator void of Bosch in FNO (restore cash / proxy lot) — **explicit operator command**, not silent.
6. Tests: FNO cannot fill `BOSCHLTD.NS`; intraday positions empty after simulated 15:25; swing still can hold CIPLA overnight.

### Phase 2 — Knowledge integrity

7. Company **identity validation** before thesis may influence swing (sector / business type vs symbol).
8. Mismatch → `THESIS_INVALID` quarantine; do not feed hospital-network prose into CIPLA decisions.
9. Stance model: BUY / WATCH / AVOID / INVALID / ABSENT on every packet.
10. Contradiction object `technical_buy_vs_fundamental_watch` (and identity mismatch).

### Phase 3 — LLM reasoning (advice-only)

11. Bounded **research packet** (not the whole DB; include challengers + event lanes when present).
12. Structured JSON out: `belief_changed`, `new_stance`, `contradictions`, `unknowns`, `research_tasks`, `decision_advice`, later `er_advice`.
13. Roles in **one** prompt: analyst / skeptic / researcher / teacher.
14. Timeout → retry once → `LLM_UNAVAILABLE` / UNREVIEWED / reschedule. No fake “unchanged.”
15. Cognitive budget: events only.

Does **not** turn Ollama into a second buy signal. Does **not** unfreeze Phase 5 size/side.

### Phase 3A — Market world intelligence (strengthen existing)

16. Living **company-news** pipeline into MTL / Evidence Network (empty → unknown, not invented).  
17. Living **government/RBI/SEBI** event pipeline (not a stale policy blurb).  
18. Enforce **source tier** + **temporal fields** on ingest.  
19. Event → expected impact → relative reaction → attribution class (hook DAV/LQ).  
20. Historical **analogue** retrieval (price+regime+event class) — distribution, not a point forecast.

### Phase 3B — Capital allocation (strengthen UTS + L1)

21. Daily **challenger table**: each holding + cash vs best alternative; opportunity score.  
22. Emit / persist **prototype E[R]** with completeness; missing E[R] is a first-class unknown, not a silent HOLD.  
23. **Switch threshold** object (costs + uncertainty + min improvement) — ROTATE only when exceeded.  
24. Packet fields: `best_challenger`, `challenger_advantage`, `allocation_action` (KEEP/HOLD/ROTATE/CASH).  
25. Curiosity priority: unknowns that could **change the next-rupee decision**.

### Phase 4 — Learning objects

26. `LEARNING_EVENT` kinds: fill, exit, unexpected move, new fundamental, **news/policy event**, contradiction, falsifier, strategy failure, missed opportunity, LLM failure, **challenger crossed threshold**.
27. `EXPERIENCE`: context → decision → predicted E[R] → action → outcome → error → evidence → attribution → lesson → belief / model update (or UNREVIEWED).
28. Attribution required on closed lab experiments (intraday EOD flatten counts as close).
29. Separate lessons: strategy / market / thesis / Atlas / **relative opportunity** (five fields).

### Phase 5 — Research intelligence

30. Curiosity: research only if resolving the unknown **could change allocation**.  
31. Verify extracts (FCF, D/E, promoter, identity, **Tier-1 events**) before belief write. Unknown > invented.  
32. Keep PLC.A fail-closed until required fields exist for **new swing names**.  
33. Drain **news** curiosity from queued → evidence or explicit unknown.

### Phase 6 — Reports

34. Evening/hourly header: **allocation table** (book vs challengers vs cash) · experiences · prediction errors · revisions · contradictions · research resolved/remaining · closed trades · LLM failures · news/policy freshness · what to investigate tomorrow.  
35. Tick histograms and `mark_only` **below the fold**.  
36. Never lead with IQ / process score as if they were edge.

---

## 7. Already in the tree (do not rebuild)

| Piece | Status | Gap vs this plan |
|-------|--------|------------------|
| L4 index-proxy lot | Landed | Switch sold it for Bosch |
| L5 5m ≤3 | Landed | No EOD flatten |
| L2 consult advice-only | Landed | 66 consults, 0 revisions; not event-gated |
| L3 outcome_check | Landed | Thin evidence_delta; LLM fail |
| L1 E[R] prototype | Landed | Not the daily comparison currency vs book vs cash |
| UTS switch / challengers | Landed | Cash not a first-class challenger; missing E[R] blocks without asking the economic question; FNO switch unbound |
| `skip_cash_alts_for_lab` | Landed | Does not bind UTS switch |
| PLC.A fail-closed | Landed | Keep |
| SI.1 identity pack | Landed | Not a hard thesis quarantine |
| OI-MTL0 news/policy lanes | Landed | Empty → unknown; **not a living stream** |
| OI-EVID-NET0 | Partial | Real company news/commentary remaining |
| OI-CURIOSITY0 | Partial | News stays queued |
| OI-F2 temporal | Landed | Not mandatory on market events |
| DAV / LQ attribution | Landed | news/policy “could not determine” |
| Experience integrity | Landed | Activity inflation still in mail |
| MEM.1 / cognitive budget | Landed | LLM text failed; budget 0 skipped morning |
| Control SMA/RSI | Locked | Stay V1 until sample + operator approve |

---

## 8. Explicit non-goals (this cycle)

- More fills as a success metric  
- Letting LLM change size/side (SELF0 Phase 5)  
- Silent SMA/RSI replacement  
- 1-minute feed (OI-FEED-1M after two **clean 5m + flat EOD** sessions)  
- Loosening PLC.A to “make swing move”  
- Treating FNO Bosch P&L as strategy evidence  
- Yahoo-news sentiment bot  
- A new “World Intelligence product” disconnected from MTL / Evidence Network  
- Daily rank-churn without switch thresholds  
- AGENT-1 (still two consecutive clean STAB0 equity sessions — integrity failures on FNO/intraday do **not** unblock AGENT-1)

---

## 9. Definition of done for the next clean sessions

**After Phase 1 (integrity day):** not 10k ticks. **Five or six clean experiences**, for example:

1. Technical signal → trade → **same-lab** outcome → attribution (intraday, flattened)  
2. Research question → evidence → thesis revision **or** still unknown  
3. Contradiction → recorded → lab policy applied  
4. Exit / EOD flatten → strategy lesson (Track A) without claiming market causality  
5. LLM failure → UNREVIEWED, not “no change”  
6. FNO: proxy lot **held or exited only to another allowed underlier** — never cash equity  

**After Phase 3B (allocation day), add:**

7. Table: incumbents + cash + one challenger each, with E[R] or explicit unknown  
8. At least one KEEP/HOLD/ROTATE that cites **challenger advantage vs threshold** (including “advantage < costs → HOLD”)  
9. One prediction vs realized (even if error is “unknown cause”)

If those are traceable in packets + journal, the day beats 19 Aug’s 666 ticks.

---

## 10. Discussion notes (operator ↔ implementer)

**Agreed**

- Wake succeeded; next **code** is still Phase 1 integrity — then connect existing machinery to **next-rupee allocation**, not more modules.  
- FNO isolation and intraday flatten remain **P0** and precede LLM-scientist and news pipelines.  
- Thesis and engine must be **peers with an explicit winner**, not a silent merge.  
- “Learned” is a high bar; include **prediction error** when claiming market learning.  
- Control strategy stays V1.  
- `missing_er` is a **capability gap**, not a nudge to trade anyway.  
- News/policy/government/historical analogues belong **in this file** (Phase 3A), not a sibling plan.  
- Track D (relative opportunity) is first-class.

**Clarifications (locked here)**

- Swing CIPLA +2 is still a **BUY** that must show the decomposition (add-to-incumbent vs new name). It does not get a free pass because the book already held CIPLA.  
- Intraday **may** buy WATCH names **only** with `lab_policy=technical_only` on the packet. Intraday is **not** the capital-allocation lab.  
- Completing IRA for CIPLA FCF is **Phase 5 curiosity**, not a reason to delay Phase 1 flatten/isolation.  
- Voiding Bosch in FNO is operator-gated; code path is reject-future, not auto-wipe unless asked.  
- Crude E[R] with `er_completeness` beats waiting for a perfect model.  
- ROTATE philosophy ≠ prove incumbent wrong; **also** ≠ churn on daily rank.  
- SELF0 remains shared cognition; Market’s objective is risk-adjusted capital growth.

**First code slice (this landing)**

Phase 1 items 1–4 + tests, plus the stronger invariants:

- Lab identity is immutable for the lifetime of a position (create / switch / replace).
- EOD flatten acceptance includes paper sell, realized P&L, experience/outcome, qty=0, next-morning no carry-in.

**Phase 1.5 operator void (2026-08-19):** FNO Bosch/NIFTY contamination wiped via `scripts/void_fno_contamination.py --apply` (not a market sell).

**Phase 3 (this landing):** bounded research packet · four roles in one prompt · `DO_NOT_OVERRIDE_RULE_ENGINE` · retry twice then `UNREVIEWED`/`LLM_UNAVAILABLE` (not “belief unchanged”) · queue on fill, drain off-path.

**Phase 6 (this landing):** learning-first evening header (allocation · experiences · prediction error · closed trades · contradictions · revisions · research · LLM failures · news/policy · investigate tomorrow) · tick histogram + IQ below the fold.

---

## 11. Revised work order (operator 19:43 — still Phase 1 first in code)

| Pri | Work | Why |
|-----|------|-----|
| **P0** | FNO isolation | Prevent contaminated experiments |
| **P0** | Intraday EOD flatten | Prevent contaminated experiences |
| **P0** | Thesis/technical contradiction on packet | Prevent unjustified decisions |
| **P1** | Company identity quarantine | Prevent wrong research |
| **P1** | Living company-news pipeline (MTL/EVID) | Biggest evidence hole (`news=0`) |
| **P1** | Living government/RBI/SEBI events | Policy too static/stale |
| **P1** | Historical analogue engine | Bars exist; conditional learning does not |
| **P1** | Relative opportunity / challenger vs cash | Opportunity cost is the economic hole |
| **P1** | LLM research scientist on **curated packets** | Interpret evidence; not “should I buy” |
| **P1** | Event → outcome attribution | Learn why without inventing causality |
| **P1** | Prototype E[R] as comparison currency | Without it, 190 names cannot compete with CIPLA/cash |
| **P2** | Closed-loop experience (prediction error) | Convert outcomes into reusable knowledge |
| **P3** | Strategy experiments (SMA/RSI contribution) | After enough **clean** experiences |
| **P4** | ML/NN | Only after enough clean experiences + export gate |

P1 rows after identity are **design/connect** work under Phases 3A–3B. They do **not** jump the Phase 1 code queue.
