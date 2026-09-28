 # Atlas Data Plane & Inference Integrity — Tracking Plan

> **Status:** 🟡 active (operator LOCK 2026-08-24 evening)  
> **Trigger:** Monday 24 Aug live day — intraday worked, emails showed phantom **+₹19,260** day P&L, Yahoo 429 storms, open-book PE/ROE missing, scientist LLM saturation, BATCH workers starved 14–27h.  
> **Paid market data:** deferred (operator will consider later). Fix free-Yahoo + Screener/hermetic paths first.  
> **Follow-on (2026-08-25):** live-market day_pnl honesty + open-book web→scientist — [`OI-WEB-EVID0`](ATLAS_LIVE_MARKET_AND_WEB_EVIDENCE_PLAN.md).

---

## 1. Problem map (how the failures connect)

```
Yahoo overuse (charts + crumb + enrich share one IP)
        ↓ 429 cooldown (consecutive_blocks → 700+)
Stale daily bars (123/202 still Friday) + enrich paused
        ↓
No durable PE/ROE/FCF on WELCORP / IIFL / PRAJIND / IDEA
        ↓
E[R] completeness stuck ~0.45 → HOLD / switch blocked (not “thesis finished”)
        ↓
Scientist LLM burns sole CPU lane all night (~467 calls)
        ↓
Overnight densify skips LLM; BATCH enrich/thesis starve 17–27h
        ↓
Emails show technical buys + phantom day P&L → trust break
```

Trading (paper ticks) can look healthy while the **learning / data plane is dead**.

---

## 2. Incident detail — 2026-08-24

### 2.1 Phantom day P&L (+₹19,260 then vanished)

| Fact | Value |
|------|--------|
| Lab | `equity_intraday_learner` |
| Email snapshot | P&L today **+19,260** · total **−95** · WELCORP×3 marked **2311.90** (Friday daily) |
| Real story | Same-day WELCORP round-trips; book ~flat vs ₹50k |

**Root cause:** `_add_cash_and_pnl_metrics` used  
`sell_pnl = qty × (sell − previous_close)`.  
Same-day round-trips then add spurious `qty × (mark − previous)`.  
Fri−Thu WELCORP gap ≈ **₹306.70** × ~63 round-tripped shares ≈ **₹19,260**.

**Why it vanished:** After 15:20 flatten, positions empty → no marks → code set `day_pnl = None`.

**Fix:** ✅ landed `investor_reports._compute_day_pnl` — sells realize vs **mark**; flat books still report closed-day P&L. Tests: `tests/test_day_pnl_round_trip.py`.

### 2.2 Yahoo rate-block (structural)

| Fact | Value |
|------|--------|
| Gate | `investment/fundamentals/yahoo_rate_gate.json` |
| Live | `consecutive_blocks≈731`, backoff **900s**, last HTTP **429** |
| Session reads | mostly `durable_bar_store` / `_stale`; few `yahoo_network` |
| Daily bars | **79/202** Monday · **123 stale** (97 on Fri 21) |

**Who shares the IP:** paper charts, 5m intraday, hist bootstrap, quoteSummary enrich, getcrumb.

**Operator decision:** no paid feed **now**. Permanent free-path discipline required.

### 2.3 Open-book fundamentals missing

| Symbol | In fundamentals store? | Role 24 Aug |
|--------|------------------------|-------------|
| WELCORP.NS | ❌ | Cash + intraday primary |
| IIFL.NS | ❌ | Next-₹1 / challenger |
| PRAJIND.NS | ❌ | Prior incumbent |
| IDEA.NS | ❌ | Intraday name |
| EICHERMOT.NS | ✅ (Screener 9 Aug) | Prior |

Store still ≈ **18 NIFTY** Screener rows from 9 Aug. Enrich: `fetched:0`, `paused:true`, `remaining:3`. E[R] completeness **0.45**; missing `sector_rs`, `valuation`, `belief`, `experience`.

### 2.4 LLM saturation + starvation

| Signal | 24 Aug |
|--------|--------|
| Fitness rows | ~994 (467 scientist) |
| `lane_busy` | ~107 |
| Concurrency | **1** (CPU policy Stage 7 locked) |
| Scientist notes | 9 active · 3 REVIEWED · 3 `failed_non_json` · 1 AttributeError |
| Overnight densify LLM | skipped (`low_llm_deferred_default`) |
| Starved workers | `thesis_outcome` ~27h · `decision_meta_learning` ~25h · `fundamentals_enrich` ~17h · `government_intelligence` ~14h |
| Archive | 2/2 congested |

---

## 3. Permanent fix backlog (operator-approved)

Legend: ✅ done · 🔧 this bounce · 🟡 next · ⚪ deferred

| ID | Item | Pri | Status |
|----|------|-----|--------|
| DP-PNL1 | Day P&L round-trip honesty + flat-book P&L | P0 | ✅ code |
| DP-LLM1 | Raise `llm.max_concurrency` (fuller CPU) **with RTH reserve for chat/market** | P0 | ✅ code |
| DP-LLM2 | Scientist daily LLM hard cap + RTH drain throttle | P0 | ✅ code |
| DP-YAH1 | RTH: background Yahoo (enrich/hist) hard-yield; never steal live marks | P0 | ✅ (hermetic sync on yield/cooldown) |
| DP-YAH2 | Single Yahoo priority: open-book marks ≫ enrich ≫ universe scrape | P0 | ✅ code |
| DP-FUND1 | Open-book hermetic/sector-proxy sync when Yahoo paused | P0 | ✅ code |
| DP-FUND2 | After-close enrich as NORMAL (anti-starve); RTH stays BATCH | P0 | ✅ code |
| DP-FUND3 | Screener open-book weekly ritual (operator) | P1 | ✅ helper + docs |
| DP-BATCH1 | Archive must not block market enrich all evening | P1 | ✅ code |
| DP-THESIS1 | Technical BUY vs WATCH dossier / MoS unknown gate | P1 | ✅ code |
| DP-PAID1 | Licensed market data | P2 | ⚪ later |

---

## 4. LLM concurrency policy (LOCK 2026-08-24)

**Before:** `max_concurrency=1` (CHAT-INFER0 Stage 7 — never auto-raise).

**Now (operator LOCK):**
- Default **`max_concurrency=2`** — use more of the CPU host.
- During **NSE RTH (09:15–15:30 IST):** reserve **≥1** slot for **chat + market** only. Research/background may use leftover capacity only (fail-fast if reserve would be eaten).
- Outside RTH / overnight densify window: both slots usable by research when free; chat/market still may wait (protected).
- Paid GPU / higher N: revisit after fitness shows queue_wait + generate_ms acceptable.

Honesty: two CPU Ollama jobs can contend for RAM; if load1 stays >~16 or interactive chat >120s, drop back to 1 or keep 2 with stricter RTH reserve.

---

## 5. Live activity during market hours (non-negotiable)

While NSE cash session is open:

1. Paper labs (equity / intraday / F&O) keep tick slots (existing market capacity floor).
2. LLM: chat/market reserved slot (DP-LLM1).
3. Yahoo: hist bootstrap + fundamentals enrich **hard-pause** (already + reinforced).
4. Scientist drain: **max 1 pass / tick**, daily cap — no overnight-scale LLM during RTH.
5. Emails: honest day P&L (DP-PNL1).

---

## 6. Open-book fundamentals guarantee

Every `qty>0` holding and Next-₹1 destination must have, within 24h of entry:

- Durable row in `fundamentals/market_intelligence.json`, **or**
- Explicit hermetic `sector_proxy` sync with `method=sector_proxy`, **or**
- Operator Screener import

Never leave WELCORP-class names with zero store row while capital is deployed.

When Yahoo cooldown armed: still run hermetic sync (no network).

---

## 7. Scientist LLM hard cap

| Window | Cap |
|--------|-----|
| Per IST day / lab | **12** LLM enrich attempts (configurable) |
| Per drain tick (RTH) | **1** pass |
| Per drain tick (overnight) | **2–3** passes |
| Schedule from ACPs (RTH) | max **2** new pending |
| Schedule from ACPs (overnight) | max **4** |

Retriable failures still count toward the daily attempt budget so we cannot spin forever on `failed_non_json`.

---

## 8. Yahoo discipline (no paid feed yet)

1. RTH: only live lab marks + ≤3 intraday 5m names (existing L5 budget).
2. After close: open-book enrich first (3 symbols / tick).
3. Sunday early window: rest of watchlist (existing weekly).
4. On 429: cooldown; do not probe fallbacks that burn IP.
5. Success resets `consecutive_blocks` (existing).

---

## 9. Verification checklist (next session)

- [ ] Bounce loaded `max_concurrency≥2`; Ops / health shows new limit  
- [ ] During RTH: chat joke or status still returns; research may `lane_busy`  
- [ ] Hourly mail day P&L not absurd vs total P&L  
- [ ] WELCORP (or current holding) appears in fundamentals store (proxy or Yahoo)  
- [ ] `fundamentals_enrich` `last_tick_at` advances after close (not 17h starve)  
- [ ] Scientist fitness today ≪ 467 unless operator raised cap  
- [ ] Yahoo gate `consecutive_blocks` not climbing during RTH  

---

## 10. Code touch list (this implementation)

| Area | Files |
|------|--------|
| Day P&L | `atlas/workers/investor_reports.py` · `tests/test_day_pnl_round_trip.py` |
| Concurrency + RTH reserve | `config/defaults.yaml` · `atlas/investment/llm_lanes.py` · `atlas/core/resources/manager.py` · `atlas/llm/cpu_policy.py` |
| Scientist caps | `atlas/investment/incumbent_scientist.py` · paper/overnight call sites |
| Enrich anti-starve + hermetic | `atlas/workers/fundamentals_enrich.py` · `atlas/workers/manager.py` |
| Yahoo priority | `atlas/investment/yahoo_fundamentals.py` · `fundamentals.py` · hist bootstrap |
| Evening archive clamp | `atlas/core/resources/host_guard.py` · `config/defaults.yaml` |
| Thesis WATCH gate | `atlas/investment/research/service.py` · `programs.py` · paper gate default |
| Screener ritual | `open_book_screener_ritual.py` · `SCREENER_FUNDAMENTALS_IMPORT.md` · API |
| Tracking | this doc · `docs/OPEN_ITEMS.md` pointer |

---

## 11. Honesty

- Simulation / paper only (P10).  
- Sector-proxy ratios are **not** filings truth.  
- Raising concurrency does **not** invent PE/FCF.  
- Paid data remains the durable path for full-universe freshness; this plan makes the free path **honest and prioritized**, not infinite.
