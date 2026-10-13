# Atlas paper labs — how they trade, what they see, when they learn, and whether RL is warranted

Date: 2026-10-13 · Scope: the three paper laboratories · Companion incident: `docs/incidents/2026-10-13_LAB_STARVATION_AND_POST_CLOSE_FNO_FLATTEN.md` · Plan: `docs/2026-10-12_DECISION_EVIDENCE_LEARNING_INTEGRITY_PLAN.md` (OI-DELI0)

All three labs are **paper simulations** — no broker orders. All three share one control strategy (SMA10/SMA30 + RSI14). What differs is the instrument, the bar interval, the gates and the exits.

---

## 1. Shared spine (every lab)

1. Worker type `paper_trading`, tick every **300 s**, admitted by Host Guard → mission arbiter → reservations.
2. Session check (`nse_equity` / `nse_fno`, 09:15–15:30 IST, Mon–Fri, holidays). Closed ⇒ mark prices only, no decision.
3. Fetch bars → `compute_indicators`: `price`, `sma_fast`(10), `sma_slow`(30), `rsi`(14), `macd` (computed, **unused** by the rule).
4. `StrategyDecisionRule` V1:
   - `margin = (sma_fast − sma_slow) / sma_slow`
   - **BUY** if `margin > 0` and `rsi < 70` (or RSI missing) and size > 0
   - **SELL** if `margin < 0` and `rsi > 30` and holding
   - It is a **level** rule (sign of the margin), not a crossover event, despite the "crossed above" rationale text.
   - Score = `1.0 + 5·|margin|`; bounded lesson / mentor nudges can move scores but cannot create a BUY/SELL.
5. Lab-specific gates → `apply_trade` (fees by broker profile) → decision packet + trade lineage → on close: EXPERIENCE + LEARNING_STORY + FEL row.

## 2. Per-lab reference

### 2.1 `india_equity_learner` — cash equity swing

| Aspect | Value |
|--------|-------|
| Capital | Net contributed ₹55,000 · today cash ₹35,195, equity ₹44,460, 1 open position, lifetime −₹10,540 |
| Hours | 09:15–15:30 IST; **overnight holding allowed**; no EOD flatten |
| Universe | ≤ 20 ranked names (M0 watchlist, fallback NIFTY50), open positions first; if no buy, up to 12 "next alternatives"; switch challengers from opportunity queue (≤ 40) |
| Bars | Yahoo **daily (1d)**, 100 bars. Decides **once per daily bar** — later ticks are `mark_only` |
| Other data | Fundamentals (PE, ROE, D/E, sector; FCF tracked as unknown), research thesis + MVR, ranking (momentum 0.32, liquidity 0.22, quality 0.15, policy 0.13, research 0.10, experience 0.08), E[R] `prototype_v1` (momentum 0.30, sector RS 0.20, valuation 0.20, quality 0.15, belief 0.075, experience 0.075; ±12% scale). News contributes 0 until cited |
| Buy gate order | wash lock (no same-day re-entry) → lab instrument → lab policy (thesis AVOID/INVALID or quarantined ⇒ HOLD) → ICR0 (adds need an ACP decision) → policy engine → research gate (MVR + thesis required, MoS soft) → **PLC.A** (PE/ROE/D/E/sector present + thesis trigger) → portfolio gate → pack validation → fees |
| Constraints | ≤ 12 names; 18% target per name (hard 40% via `max_exposure_pct`); 15% minimum cash; 35% sector cap; whole shares (1-share min lot allowed) |
| Fees | `zerodha` sim: brokerage 0.03% cap ₹20, STT 0.1% on sell, exchange 0.00325%, GST 18%, stamp 0.015% on buy |
| Exits | SMA sell; PLC.B: stop −8%, trailing −10% from peak after +2%, time stop 90 days, concentration, valuation excessive (PE ≥ 55 or ≥ 1.75× industry), thesis broken, earnings deterioration; **opportunity switch** (≤ 1/tick, cold-start bar **5%** advantage after 100 bps cost — never relaxes because `exploratory_turnover_ok` is always on) |
| Today | 0 fills. HOLDs: `engine_hold` 16, `lab_policy_hold` 2, `fundamentals_incomplete` 2, switch blocked 2. Plus 10 SELL decisions on HBLPOWER.NS 01:32–02:18 IST with market closed (not executed — recording noise) |

### 2.2 `equity_intraday_learner` — cash equity intraday

| Aspect | Value |
|--------|-------|
| Capital | Net contributed ₹50,000 · cash ₹49,376 · lifetime −₹624 |
| Hours | 09:15–15:30; **no new buys from 15:20**; `eod_flatten` sells everything from 15:20 |
| Universe | **≤ 3 symbols per tick** (Yahoo budget), open positions first; no next-alternatives |
| Bars | **5-minute** bars (Zerodha preferred; on `LOGIN_REQUIRED` a *labeled* Yahoo fallback) |
| Other data | Lab policy `technical_only`; research gate still applies (learner); PLC.A/PLC.B disabled. No IV, no order book, no volume features |
| Constraints | Cash-limited only (no name/exposure caps set); whole shares; `paper_demo` fees (0) by default |
| Exits | SMA sell (`sma_crossunder`), `eod_flatten` at 15:20 (mark: position mark → last mark → avg cost) |
| Today | 1 decision (HOLD) all day; 160 `capability_gap`, 90 `intraday_yahoo_budget` |

### 2.3 `india_fno_learner` — F&O Lab v1 (ATM option overlay)

| Aspect | Value |
|--------|-------|
| Capital | Net contributed ₹1,00,000 · cash ₹85,728 after today (−₹64,477 day) · lifetime −₹14,272. **Finite — never auto-topped-up** |
| Hours | NSE F&O 09:15–15:30. **New (after restart): no new entries and close-out from 15:20**; options never held overnight |
| Universe | 4 indices (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY) + 30-stock F&O seed ≈ 34 underliers per tick; cash names rejected |
| Bars | Underlier **daily (1d)** bars for SMA/RSI (same rule as equity, on the underlier) |
| Option data | Zerodha NFO master (FUT + OPT), nearest unexpired FUT expiry → ATM strike (steps: NIFTY/FIN 50, BANKNIFTY 100, MIDCP 25), CE & PE LTP, underlier spot. Pack READY needs spot, master, expiry, ATM, session open, CE and PE LTP all fresh (≤ 180 s) |
| Not used | **IV, Greeks, OI, volume, bid/ask spread, days-to-expiry, VIX** — none enter the decision |
| Mapping | Bullish margin → BUY 1 lot ATM **CE**; bearish margin → BUY 1 lot ATM **PE**; SMA reversal while holding → SELL; RSI ≤ 30 with bearish margin → HOLD. Writing options is forbidden |
| Constraints | 1 lot per experiment; **≤ 2 open option experiments**; keep **30% of starting cash** in reserve; refuse if cash < premium × lot; never auto-top-up |
| Prediction | `build_entry_prediction`: `strength = min(1, |margin|/0.005)`; E[R] = 1%–8% of premium; p = 0.45–0.70; horizon `session_flat`; **`uncalibrated_default`** — a formula, not a model |
| Exits | SMA reversal on an ATM-held option; `fno_lab_v1_experiment_close` (session flat). Mark: option LTP → last mark → avg cost (labeled). **Gap:** once spot moves, a held strike stops being ATM and the lab idles it (`legacy_non_atm_option`) — no stop, no target, no time exit until the flatten |
| Today | 10 PE buys in 3 minutes (swarm, before the capital budget existed), unmanaged after ~11:15 due to starvation, closed 17:34–17:42 after market close |

## 3. What Atlas records, and when it really learns

**Today Atlas records; it does not learn in the sense of changing tomorrow's decisions.**

| Stage | What is written | Changes a future decision? |
|-------|-----------------|----------------------------|
| Decision | Decision packet (`di.packet.1`), trade lineage (entry/overlay/exit decision ids, prediction id, evidence snapshot) | No |
| Close | EXPERIENCE (prediction, outcome, error, attribution, five lesson tracks) + reward (`net_paper_pnl_inr`, `mutates_strategy: False`) | No |
| Story | LEARNING_STORY (`belief_update: unchanged`, `next_decision_change: none_stated` unless gated) | No |
| FEL | `DS-E-paper-round-trip-<lab>` rows; mean reward vs cash; `MIN_SAMPLE = 3`; promotion never → `live_control` | No |
| F&O closed loop | Joined prediction → fill → exit → movement → attribution row | No |
| L3 → L4 → L5 | L3 chain-complete → L4 candidate + subsequent test → **L5 only after 5 subsequent sessions validate** | Belief files only, `advice_only` |
| Soft nudges | Validated lesson (score ±0.25 cap), mentor keyword bias, experience soft bias 0.08, thesis priors after ≥ 20 outcomes | Scores/ranking only — never SMA/RSI, sizing, capital |

Nothing on the paper path rewrites `sma_fast/sma_slow/rsi_period`, sizing, thresholds or capital. Switch-threshold and sizing "learning" are proposals with `apply: False`.

### When does real learning start?
A lesson can change behaviour only after **all** of the following are true:

1. **Clean evidence** — closes are learning-eligible (in-session exit, no quarantine), decision chain complete (OI-DELI0 P0.4–P0.7 — now live after restart), prediction stated with an id.
2. **Independent samples** — not 10 correlated closes from one day. Count *independent market days × setups*, not rows.
3. **A stated hypothesis with a baseline** — e.g. "bearish-margin ATM PE beats cash after costs over session_flat".
4. **Out-of-sample validation** — L5 subsequent test over ≥ 5 later sessions, or a FEL walk-forward.
5. **An explicit promotion** — operator applies the change (FEL never promotes to live control by itself).

Current eligible sample after quarantine:

| Lab | Rows | Distinct days | Wins | Comment |
|-----|-----:|-------------:|-----:|---------|
| `india_fno_learner` | 39 | 6 | 23 | Each day is ~one correlated market bet; effectively ~6 observations |
| `equity_intraday_learner` | 40 | 13 | 23 | Cleanest series, but ≤ 3 names/tick and zero fees |
| `india_equity_learner` | 10 | 5 | 3 | Was 137: 137 HBLPOWER.NS `switch_exploratory` sell-and-rebuy exits on 2026-09-21 (72 @ ₹760, P&L ₹0.00 each) **quarantined** as `switch_churn_zero_information` (operator decision 2026-10-13) |

The swing lab therefore has almost no learning evidence: 10 closes across 5 days.

Realistic timeline if the labs run cleanly every session from now: first defensible L5-type statements on the intraday lab in **~3–4 weeks**; F&O in **~6–8 weeks** (needs ~25–30 independent days with the new capital limit); swing equity in **months** (few closes per week by design).

## 4. Is reinforcement learning warranted?

**Not yet — but a contextual bandit is the right next step once the data is clean, and full RL only later for F&O exits.**

Why not now:
- **Sample size**: ~6–13 independent days per lab. RL needs thousands of episodes; even a bandit needs ~30+ independent observations per arm before it beats a fixed rule.
- **Reward quality**: today's reward is raw INR with `paper_demo` zero fees on two labs, the return denominator issue (P&L ÷ exit notional) and post-close exits. A policy would optimise artefacts.
- **State is thin**: F&O decides with no IV/Greeks/DTE — the features that explain option P&L. RL cannot learn from data the agent never sees.
- **Non-stationarity + hermeticity**: three labs, different instruments and horizons — no shared MDP.
- `rl_policy` exists only as a reserved model id (`available() → False`).

Recommended path:

| Phase | What | Gate to start |
|-------|------|---------------|
| R0 (now) | Fix data: in-session exits, quarantine, realistic cost profile on all labs, F&O feature capture (below), held-option exit rules | — |
| R1 | **Offline contextual bandit** per lab over a small discrete action set. F&O: {skip, ATM CE, ATM PE} × {0.5, 1 lot}. Intraday: {skip, buy} per name. Off-policy evaluation (IPS/doubly-robust) against the SMA/RSI rule using logged propensities | ≥ 30 eligible independent days in the lab; propensity logging added |
| R2 | Bandit as a **paper challenger** next to V1 (separate book), never live control | R1 beats V1 out-of-sample after costs |
| R3 | Sequential RL only for **F&O exit timing** (hold/exit each tick — the place where the sequential structure matters) | R2 positive over ≥ 2 months; intraday option ticks recorded |

### Features to capture first (state for R1)

| Family | Features | Labs | Available today? |
|--------|----------|------|------------------|
| Trend | `sma_margin`, `sma_fast`, `sma_slow`, slope of SMA, `macd` hist | all | computed; `sma_margin` **dropped** from FEL rows |
| Momentum / mean reversion | `rsi`, 1/5/20-day return, distance from 20-day high/low | all | partly |
| Volatility | ATR%, realised vol 10/20d, **India VIX** | all | no |
| Option | **IV (ATM), IV rank, delta, theta, vega, DTE**, premium/spot, CE–PE skew, bid/ask spread | F&O | **no** |
| Positioning | OI and OI change, PCR, futures basis | F&O | no |
| Time | minutes since open, minutes to close, day-of-week, expiry week | all | derivable |
| Market regime | NIFTY trend/margin, breadth, sector RS | all | partly (ranking) |
| Liquidity | volume vs 20-day avg, spread | intraday, F&O | partly |
| Fundamentals / research | PE, ROE, D/E, sector, thesis stance, E[R] prototype | swing | yes |
| Book / risk | cash %, open experiments, exposure, correlation of open positions | all | partly |
| Outcome target | net P&L after realistic cost / premium at risk (F&O) or / notional (equity); MAE/MFE | all | P&L yes, MAE/MFE no |

## 5. Trade emails — why decisions are missing

The fill email (`reports.format_trade_report`) prints a "Decision detail" block from the **engine** decision dict (rationale, confidence, rule…). For F&O the actual decision is the **overlay** (why PE, which strike, spot, margin, RSI, capital budget, E[R]/p) and for sells the **exit reason + entry link + outcome vs prediction**; those live in trade lineage / entry prediction and are not passed to the mailer. Fix (P3 in OI-DELI0, now possible because lineage is live): render a "Decision chain" block from `trade_lineage` + `load_entry_prediction(prediction_id)`.

## 6. Next actions (in order)

| # | Action | Owner | When |
|---|--------|-------|------|
| 1 | Restart to load fixes F1–F4 + yesterday's P0.5–P0.7 + capital budget: `sudo systemctl restart atlas` | Operator | Tonight (after 16:00) |
| 2 | Tomorrow 09:30 / 12:00 / 15:25: confirm `host_guard` status shows `admitted_market_critical` for both labs and `deferred_critical_ticks_total` ≈ 0; F&O ≤ 2 open experiments; flatten fires 15:20–15:30 | Agent (read-only) | 2026-10-14 |
| 3 | ~~Decide F&O cash~~ — **decided: keep ₹85.7k**, no deposit, ledger unchanged | Operator | Done |
| 4 | ~~2026-09-21 swing churn~~ — **quarantined** (137 rows). Root cause to fix: switch review re-selling and re-buying the same name at the same price (add same-symbol / zero-advantage guard) | Agent | Guard: next code slice |
| 5 | Ollama: unload during 09:00–16:00 (keep-alive 0) or schedule LLM work after close | Operator/agent | This week |
| 6 | Held-option exit rules (premium stop, underlier reversal, time stop) instead of idling `legacy_non_atm_option` | Agent | Next code slice |
| 7 | Alerting: staleness alerts must not auto-resolve at session end; add "admitted lab ticks in session" health check | Agent | Next code slice |
| 8 | Decision chain in trade emails (§5) | Agent | After 6–7 |
| 9 | Switch review must not mint SELL decisions when session is closed | Agent | Small fix |
| 10 | FEL rows: add `sma_margin`; F&O feature capture (IV/Greeks/DTE/VIX/OI) into the entry snapshot | Agent | R0 |
| 11 | Realistic cost profile for learning evaluation on all labs (keep zero-fee ledger separate — F18) | Agent | OI-DELI0 P0.2/P0.3 |
| 12 | Propensity logging on every decision (needed for any bandit evaluation) | Agent | R0 |
| 13 | Re-assess RL at ≥ 30 eligible independent days per lab | Operator + agent | ~6–8 weeks |
| 14 | **F&O shadow trades (built 2026-10-13, `atlas/investment/fno_shadow.py`)** — every BUY signal blocked by the capital budget or cash, with a READY data pack, opens a counterfactual entry at live LTP (≤ 1 per underlier per day); closes on the 15:20 flatten clock at live LTP. After-close / missed / no-mark closes are `NOT_EVALUABLE`. Store: `investment/fno/shadow/<lab>/<day>.jsonl`; never touches ledger, lineage or the paper round-trip dataset. Assumes no slippage/fees (optimistic). Next: same for equity labs; a shadow-vs-real comparison in the evening email | Agent | Live after restart |

Why not more capital instead: cash does not create independent observations. Signals are daily-bar, positions are capped, and same-day trades share one market move. Shadows add labelled examples for free; only more trading days add independent ones.

R2 (DB-level checks for the 2026-10-12 duplicate-instance window) remains open.
