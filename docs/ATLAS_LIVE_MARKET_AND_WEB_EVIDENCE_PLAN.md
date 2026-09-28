# Atlas Live Market + Web Evidence for Scientist — Plan

> **Status:** 🟡 **DISCUSSION → implement Phase A first** (operator 2026-08-25 evening)  
> **Codename:** `OI-WEB-EVID0` (+ live-market densify on `OI-DATA-PLANE0`)  
> **Parents:** [`ATLAS_DATA_PLANE_AND_INFERENCE_INTEGRITY_PLAN.md`](ATLAS_DATA_PLANE_AND_INFERENCE_INTEGRITY_PLAN.md) ·  
> [`ATLAS_LEARNING_INTEGRITY_PLAN.md`](ATLAS_LEARNING_INTEGRITY_PLAN.md) · intelligence catalog  
> **Trigger:** Tue 25 Aug — swing sold WELCORP (concentration); day P&L looked “empty”; Google full of stock pages but Atlas news store only PIB policy RSS.

---

## 0. Operator thesis (proposed LOCK)

**Live market first.** Perception (marks, tips, day P&L) must be honest during NSE hours.

**Web second — but not Google scrape.** Atlas already has DuckDuckGo search + downloader for *research missions*. Market/scientist must reuse that spine with **hard bounds**, durable evidence, and scientist evaluation — **not** unbounded HTML crawling of Moneycontrol/Screener/random SERPs.

```text
Live marks / tips (Yahoo paced)
        ↓
Open-book PE/FCF (Screener import ‖ Yahoo enrich ‖ hermetic proxy)
        ↓
Web evidence (search snippets → durable observations)   ← NEW spine
        ↓
Scientist (ICR.5) evaluates packet — advice only
        ↓
gate_buy / PLC.A / ACP (still refuse BUY on unknown MoS)
```

Honesty: web snippets are **`evidence_candidate`**, never invented PE/FCF, never auto-BUY.

---

## 1. Problem map (why it feels broken)

| Symptom | Real cause |
|---------|------------|
| “No P&L today” after swing sell | Fri→Mon gap already marked **Mon day_pnl (+₹2237)**; Tue sell @ Mon close ≈ **₹0** new day edge; flat book showed **`null`** |
| “Google has data, Atlas doesn’t” | Market path **refuses HTML scrape**; news = **PIB RSS** (policy), not company wires |
| Scientist “doesn’t see” the company | Packet gets RSS/policy + bars; **no symbol-matched web hits** in store |
| Swing sits in cash | `when_available` MoS + missing PE — **correct gate**; web news alone must not unlock BUY |

---

## 2. Non-negotiables (LOCK)

1. **No ToS HTML scrape** of Screener.in, NSE member pages, or paywalled terminals as a dependency.  
2. **No inventing** PE/FCF/headlines. Empty → `unknown_explicit`.  
3. **RTH:** live marks + paper ticks win Yahoo IP; web densify is **BATCH / after close** (or tiny budget).  
4. **Scientist** remains advice-only (ICR.5); web evidence attaches to packets — never places orders.  
5. **BUY still needs MoS/valuation path** (DP-THESIS1). Web news densifies *judgment*, not the PE gate.

---

## 3. Live market densify (same sprint)

| ID | Item | Pri | Status |
|----|------|-----|--------|
| LM-PNL1 | Flat book after today’s sells: day_pnl **`0.0`** (not `null`) when day_trades exist; show realized vs mark honestly | P0 | ✅ code |
| LM-PNL2 | Email/KPI copy: if sell @ prior close, one-liner *“realized overnight/gap already in prior day_pnl”* | P1 | ✅ via `day_pnl_note` |
| LM-YAH | Keep DP-YAH1/2; tip refresh open-book first after close | P0 | ✅ policy |
| LM-FUND | Screener ritual for open/plan names (operator) | P0 | ✅ helper |

---

## 4. Web evidence phases

### Phase A — Open-book web search densify (ENABLE NOW) ✅ first-slice

**What:** For open books ∪ morning plan symbols (cap **3–5**/tick):

1. Query via existing **`web.search` / DuckDuckGo**  
   e.g. `{SYMBOL} NSE` / `{company} stock news`  
2. Persist top **K≤5** hits as `news_event` observations:  
   `title`, `url`, `snippet`, `retrieved_at`, `source=duckduckgo_search`, `source_tier=3`, `evidence_class=evidence_candidate`, `open_book=true`  
3. Overnight densify + optional evening worker call this path  
4. `attach_world_evidence` attaches `web_search` lane to scientist packet  

**Shipped:** `open_book_web_evidence.py` · overnight wire · world_evidence lane · tests.

**What we do *not* do in A:** download full article HTML; scrape Screener; raise scientist cap; auto-fill PE from web.

### Phase B — Bounded fetch of allow-listed publishers

Operator-configured domain allow-list (e.g. `pib.gov.in`, later verified IR pages). Downloader → extract text → claim candidates. Still no Google SERP scrape of random domains.

### Phase C — Licensed / paid

News API and/or paid market data (DP-PAID1). Replaces fragile Yahoo + thin RSS.

---

## 5. Scientist loop (how evaluation works)

```text
ACP / EXIT_REVIEW / open book
        ↓
schedule_scientist_notes
        ↓
packet = ACP + world_evidence (bars + RSS + NEW web hits) + fundamentals gaps
        ↓
reason_scientist (LLM, ICR.5 budget)
        ↓
REVIEWED notes → UI / evening — still no orders
```

Daily cap **12** stays until fitness says otherwise. Web densify must not schedule 100 notes/night.

---

## 6. Success criteria

**Live market**

- [ ] During RTH: open-book marks refresh when Yahoo allows  
- [ ] After concentration sell: KPI shows day_pnl `0.0` or honest prior-day note — not silent `null` with sells_today≥1  
- [ ] Swing can BUY only when MoS/path allows (Screener/Yahoo PE)

**Web + scientist**

- [ ] Open-book symbol has ≥1 durable web observation after evening densify (or explicit `unknown_news` after attempt)  
- [ ] Scientist packet cites those URLs/titles when present  
- [ ] No unbounded crawl; Ops shows query count / denials  

---

## 7. Code touch list (Phase A + LM-PNL1)

| Area | Files |
|------|--------|
| Day P&L flat honesty | `atlas/workers/investor_reports.py` · tests |
| Open-book web densify | `atlas/investment/open_book_web_evidence.py` (new) |
| Overnight wire | `atlas/investment/overnight_densify.py` |
| World evidence | already reads observations — verify open_book filter |
| Tracking | this doc · `docs/OPEN_ITEMS.md` |

---

## 8. Honesty

- DuckDuckGo snippets ≠ filings truth.  
- PIB RSS ≠ Welspun Corp wire.  
- Enabling web search **does not** replace Screener PE import for MoS.  
- “Works on live market” = honest marks + gates + P&L — not “trade like a discretionary human reading Google.”
