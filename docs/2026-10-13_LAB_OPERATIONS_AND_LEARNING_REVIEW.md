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
| Exits | **Managed every tick (after restart):** −40% premium stop, trend reversal against the option, on the held contract's own LTP whether or not it is still ATM; no same-day re-entry after such an exit. Then `fno_lab_v1_experiment_close` from 15:20. Mark: option LTP → last mark → avg cost (labeled). Before this fix a held strike that drifted off ATM idled as `legacy_non_atm_option` until the flatten |
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
| Trend | `sma_margin`, `sma_fast`, `sma_slow`, slope of SMA, `macd` hist | all | computed; `sma_margin` in FEL rows since `82af44e` (F&O); slope/MACD not yet |
| Momentum / mean reversion | `rsi`, 1/5/20-day return, distance from 20-day high/low | all | partly |
| Volatility | ATR%, realised vol 10/20d, **India VIX** | all | no |
| Option | **IV (ATM), IV rank, delta, theta, vega, DTE**, premium/spot, CE–PE skew, bid/ask spread | F&O | **yes since `82af44e`** (IV/Greeks Black-Scholes-derived from the traded premium, r = 6.5%); IV rank needs history; bid/ask no |
| Positioning | OI and OI change, PCR, futures basis | F&O | no |
| Time | minutes since open, minutes to close, day-of-week, expiry week | all | F&O yes since `82af44e`; equity derivable |
| Market regime | NIFTY trend/margin, breadth, sector RS | all | partly (ranking) |
| Liquidity | volume vs 20-day avg, spread | intraday, F&O | partly |
| Fundamentals / research | PE, ROE, D/E, sector, thesis stance, E[R] prototype | swing | yes |
| Book / risk | cash %, open experiments, exposure, correlation of open positions | all | partly |
| Outcome target | net P&L after realistic cost / premium at risk (F&O) or / notional (equity); MAE/MFE | all | P&L yes, MAE/MFE no |

## 5. Trade emails — why decisions are missing

The fill email (`reports.format_trade_report`) prints a "Decision detail" block from the **engine** decision dict (rationale, confidence, rule…). For F&O the actual decision is the **overlay** (why PE, which strike, spot, margin, RSI, capital budget, E[R]/p) and for sells the **exit reason + entry link + outcome vs prediction**; those live in trade lineage / entry prediction and are not passed to the mailer. Fix (P3 in OI-DELI0, now possible because lineage is live): render a "Decision chain" block from `trade_lineage` + `load_entry_prediction(prediction_id)`.

**Built (`45d85dd`, live after restart)** — `atlas/investment/decision_chain_mail.py`, shown in every fill email above the engine "Decision detail":

- **BUY**: control rule action + decision id, overlay (e.g. `v1_buy_atm_pe`) + decision id, reasons for/against from the decision packet, the stated prediction (E[R], p, horizon, model, marked *uncalibrated* for the control-signal model), thesis and key evidence (`sma_margin`, right, premium), prediction id.
- **SELL**: exit reason in plain words (`premium_stop`, `underlier_reversal`, `premium_target`, session close-out, EOD flatten), exit decision id, the entry (qty, price, time, decision id — "linked on the sell" or "matched by symbol" for pre-P0.5 rows), minutes held, the prediction made at entry, **outcome vs prediction** (price return, direction RIGHT/WRONG, error), and **learning eligibility** (after-close exits say NOT eligible).
- Missing lineage is printed as "Not recorded", never filled in. Lineage rows now also keep `exit_timing`.

Example rendered from today's real records (NIFTY26OCT22500PE): bought 65 @ 249.3 at 09:21 expecting E[R] +8.0% (p 0.70, uncalibrated); held 498 min; closed by session close-out after the market; price return −58.2% → direction WRONG, error −66.2%; NOT eligible for learning.

## 6. Next actions (in order)

| # | Action | Owner | When |
|---|--------|-------|------|
| 1 | Restart to load everything in §7 that says "needs restart": `sudo systemctl restart atlas` | Operator | Tonight, before 09:15 on 2026-10-14 |
| 2 | Tomorrow 09:30 / 12:00 / 15:25: confirm `host_guard` status shows `admitted_market_critical` for both labs and `deferred_critical_ticks_total` ≈ 0; F&O ≤ 2 open experiments; flatten fires 15:20–15:30 | Agent (read-only) | 2026-10-14 |
| 3 | ~~Decide F&O cash~~ — **decided: keep ₹85.7k**, no deposit, ledger unchanged | Operator | Done |
| 4 | ~~2026-09-21 swing churn~~ — **quarantined** (137 rows). Root cause traced: a loop, not a same-symbol switch — switch IDEA→HBLPOWER (adv ≈ +10%) → `plc_b_concentration` immediately sold HBLPOWER → SMA re-bought IDEA → switch again, ~136× at ₹760 (zero P&L each). **Already fixed on 2026-09-28** (`c97f2a6`): same-day re-entry lock (`wash_lock.reentry_blocked`) and `challenger_breaches_concentration` now gate the switch buy. No recurrence since (0 swing buy/sell fills 2026-09-25 → 10-13) | Agent | Done |
| 5 | ~~Ollama: unload during 09:00–16:00~~ — **withdrawn** (see §8): the LLM is not in the trading or learning path, and the Host Guard market-critical lane (`8057120`) admits lab ticks with Ollama resident. Keep Ollama; watch the new `lab:*:ticks` alert. Only if that alert fires with `host_pressure` again: cap LLM concurrency in market hours rather than unloading | Agent (watch) | From 2026-10-14 |
| 6 | ~~Held-option exit rules~~ — **built**: every tick, any held Lab v1 option on the underlier (ATM or not) is checked on its own live LTP: exit at −40% premium (`premium_stop`) or when the trend flips against it (`underlier_reversal`); profit target available but off. No exit without a live mark. No same-day re-entry on that underlier after a managed exit. Session flatten 15:20 still closes the rest. **All of these numbers, plus max open positions and the cash reserve, live in one operator file: `/data/atlas_data/investment/fno/lab_v1_risk_settings.json`** (read every tick; out-of-range values are ignored with a warning; it overrides `lab_v1_policy.json`) | Agent | Live after restart |
| 7 | Alerting: ~~staleness alerts must not auto-resolve at session end~~ — **fixed**: the F&O worker incident counted "any pack today" as recovery, so morning packs "verified" the 15:30 RESOLVED mail. Now only a pack written after the incident opened counts; otherwise it ends `UNRESOLVED_OPERATOR_ACTION_REQUIRED`. ~~"Admitted lab ticks in session" check~~ — **built** for all three labs (§7, `27c4890`): P0 email when a lab has no admitted in-session tick for 20 min (from 09:35), naming the deferral cause; never self-resolves at the close; evening digest lists admitted/deferred ticks per lab | Agent | Live after restart |
| 8 | ~~Decision chain in trade emails (§5)~~ — **built** (`45d85dd`) | Agent | Live after restart |
| 9 | ~~Switch review must not mint SELL decisions when session is closed~~ — **fixed** (`29d38fd`): a recommended switch that cannot execute now (session closed, execution disabled, per-tick cap) is recorded as a HOLD packet with `switch_not_executed:<reason>`; the review and its ROTATE recommendation stay recorded. Same noise was 50–153 phantom SELLs/day on 2026-09-21..24 | Agent | Live after restart |
| 10 | ~~FEL rows: add `sma_margin`; F&O feature capture~~ — **built** (`82af44e`): every F&O entry stores IV, delta, gamma, theta/day, vega, DTE, expiry week, moneyness, premium/spot, CE–PE skew, minutes since open / to close, RSI, SMAs, `sma_margin`; carried to EXPERIENCE and FEL rows. Still not captured (no data feed): India VIX, OI/OI change, PCR, bid/ask, futures basis | Agent | Live after restart; VIX/OI need a feed |
| 11 | Realistic cost profile for learning evaluation on all labs (keep zero-fee ledger separate — F18) | Agent | OI-DELI0 P0.2/P0.3 |
| 12 | Propensity logging on every decision (needed for any bandit evaluation) | Agent | R0 |
| 13 | Re-assess RL at ≥ 30 eligible independent days per lab | Operator + agent | ~6–8 weeks |
| 14 | **F&O shadow trades (built 2026-10-13, `atlas/investment/fno_shadow.py`)** — every BUY signal blocked by the capital budget or cash, with a READY data pack, opens a counterfactual entry at live LTP (≤ 1 per underlier per day); closes on the 15:20 flatten clock at live LTP. After-close / missed / no-mark closes are `NOT_EVALUABLE`. Store: `investment/fno/shadow/<lab>/<day>.jsonl`; never touches ledger, lineage or the paper round-trip dataset. Assumes no slippage/fees (optimistic). Evening email "F&O real vs shadow" section built (`f8bdd69`). Next: same for equity labs | Agent | Live after restart |

Why not more capital instead: cash does not create independent observations. Signals are daily-bar, positions are capped, and same-day trades share one market move. Shadows add labelled examples for free; only more trading days add independent ones.

R2 (DB-level checks for the 2026-10-12 duplicate-instance window) remains open.

## 7. Everything changed on 2026-10-13 (code, data, settings)

The running service was restarted on `d9a99a9`. Everything after that is committed but **not live until the next operator restart**.

### 7.1 Code commits

| Commit | What it does | Live? |
|--------|--------------|-------|
| `8057120` | Host Guard **market-critical lane** (`paper_trading`, `portfolio_ledger`, weekdays 09:00–16:00 IST: 128 MB tick need vs 2048 MB floor; others keep 512 vs 2560). F&O close-out from **15:20** (was 15:30). Exits after 15:30 stamped `learning_eligible: false`. Learning **quarantine** manifest + FEL filter. Entry prediction keeps its original `recorded_at`. Incident doc + this review | Yes |
| `ca84377` | Records operator decisions (keep F&O cash ₹85.7k; quarantine 2026-09-21 swing churn) | Doc |
| `d9a99a9` | F&O cash reserve based on `max(starting_cash, net_contributed_capital)` | Yes |
| `1afa1e2` | **F&O shadow trades** (counterfactual entries for capital/cash-blocked BUYs on READY packs) — `atlas/investment/fno_shadow.py` | After restart |
| `f8bdd69` | Evening email: **F&O real vs shadow** section | After restart |
| `9506ab2` | **Managed exits for held options** every tick: premium stop, trend reversal, optional target; no same-day re-entry after a managed exit | After restart |
| `259649e` | **One operator risk-settings file** for F&O exits and capital limits (§7.3) | After restart |
| `05e7286` | Ops alert fix: F&O worker incident recovers only on a pack written **after** the incident opened (today's 15:30 "RESOLVED" was false) | After restart |
| `27c4890` | **Per-lab tick admission ledger + stale-lab P0 alert** (§7.4) | After restart |
| `c2afba1` | This change log and doc updates | Doc |
| `45d85dd` | **Decision chain in trade emails** (§5): why it bought, why it sold, outcome vs prediction, learning eligibility; lineage keeps `exit_timing` | After restart |
| `a402745` | Docs for the decision chain | Doc |
| `29d38fd` | Switch review records an unexecutable switch as HOLD, not SELL (§6 #9) | After restart |
| `e13cad1` | Docs for the switch fix | Doc |
| `82af44e` | **F&O decide-time feature capture** (§4 feature table, §6 #10): `atlas/investment/fno_features.py` | After restart |

### 7.2 Data changes (all append-only; no ledger edits)

| What | Where | Effect |
|------|-------|--------|
| Quarantined the 10 F&O round trips closed 17:34–17:42 on 2026-10-13 (`after_session_close_exit`) | `investment/integrity/learning_quarantine/india_fno_learner.jsonl` | FEL F&O rows 49 → 39. Ledger P&L −₹64,476.75 unchanged (honest hold-to-close accounting) |
| Quarantined 137 HBLPOWER.NS `switch_exploratory` rows of 2026-09-21 (`switch_churn_zero_information`) | `investment/integrity/learning_quarantine/india_equity_learner.jsonl` | Swing FEL rows 137 → 10 |
| Created the F&O risk-settings file with current defaults | `investment/fno/lab_v1_risk_settings.json` | No behaviour change until edited |

A quarantine is undone by appending a `release` row for the same experience id; nothing is deleted.

### 7.3 F&O risk settings — the one file to edit

`/data/atlas_data/investment/fno/lab_v1_risk_settings.json` — read every tick (no restart once `259649e` is loaded). Out-of-range or malformed values are ignored, the default is kept, and a warning is logged. It overrides the older `lab_v1_policy.json`. `auto_top_up` is always off.

| Key | Default | Allowed | Meaning |
|-----|---------|---------|---------|
| `exit.premium_stop_pct` | 0.40 | 0.05–0.95 or `null` | Exit when the premium is this fraction below entry |
| `exit.premium_target_pct` | `null` (off) | 0.05–10 or `null` | Exit when the premium is this fraction above entry |
| `exit.exit_on_underlier_reversal` | `true` | bool | Exit a PE when the trend turns up / a CE when it turns down |
| `exit.no_reentry_same_day_after_managed_exit` | `true` | bool | No new entry on that underlier the same day after a managed exit |
| `capital.max_open_option_experiments` | 2 | 1–10 | Max open option positions |
| `capital.cash_reserve_fraction_of_starting` | 0.30 | 0–0.9 | Cash kept untouched, fraction of contributed capital |

### 7.4 Lab tick health check (closes the gap that hid today's outage)

- **Ledger** `investment/ops_health/lab_ticks/<day>.json`: per lab — admitted ticks, in-session ticks, last in-session tick, worker id; per worker — deferred ticks by cause (`host_pressure`, `schedule`, `budget`, `reservation`) and the last reason (e.g. the RAM numbers). Written by `paper_trading` (start of each admitted tick) and `WorkerManager._record_wait` (each deferral). Counters only, never a trading input.
- **Alert**: from 09:35 to 15:30 on trading days, any lab seen today or on the previous recorded day with no admitted in-session tick for **20 min** → P0 `lab:<lab>:ticks`, emailed once, with the deferral cause in WHY.
- **Resolution**: only an admitted in-session tick after the incident opened marks it `RECOVERED_VERIFIED` (`admitted_tick_confirmed`). If the session ends first it becomes `UNRESOLVED_OPERATOR_ACTION_REQUIRED`, never "RESOLVED".
- **Evening digest** (Operational Health section): `Lab ticks in session — <lab>: admitted N, deferred M, last HH:MM`.
- On today's data this would have emailed a P0 for both F&O and swing at ~11:35 naming `host_pressure`.

### 7.5 Tests added or changed

`tests/test_host_guard.py` (critical lane), `tests/test_fno_lab_v1.py` (15:20 flatten, eligibility, quarantine → FEL), `tests/test_fno_closed_loop_dataset.py`, `tests/test_fno_shadow.py`, `tests/test_fno_managed_exit.py` (incl. risk-settings file), `tests/test_ops_health_loop0.py` (morning packs must not verify an afternoon outage), `tests/test_lab_ticks.py`, `tests/test_decision_chain_mail.py`, `tests/test_switch_packet_action.py`, `tests/test_fno_features.py`. Pre-existing failures unrelated to this work: 3 in `tests/test_workers.py` (budget/throttle), present at HEAD before these changes.

### 7.6 Checks for 2026-10-14 (agent, read-only)

| Time IST | Check |
|----------|-------|
| 09:30 | Service on `82af44e` or later; first F&O entry prediction has `decide_time_features.iv`; no swing `sell` packets with `fill_trade_id: null` recorded overnight; `host_guard` shows `admitted_market_critical`; `lab_ticks/2026-10-14.json` has in-session ticks for all three labs |
| 12:00 | No `lab:*:ticks` incident; `deferred_critical_ticks_total` ≈ 0; F&O ≤ 2 open; any managed exit has a `premium_stop` / `underlier_reversal` lineage code; shadows only on capital/cash blocks |
| 15:25 | F&O close-out ran between 15:20 and 15:30; every exit `learning_eligible: true` |
| Any fill | Fill email has a "Decision chain" block; SELLs show "linked on the sell" (P0.5 entry link) rather than "matched by symbol" |
| Evening | Email shows the F&O real-vs-shadow section and per-lab tick lines |

## 8. Ollama (the local LLM): what it does, and why it stays loaded

Question raised 2026-10-13: "if we unload Ollama, how will Atlas be intelligent, cognitive, autonomous and learn?" Answer: **it stays loaded.** The earlier "unload in market hours" action is withdrawn.

**What the LLM is for today.** `qwen3:4b` (Q4, ~3.5 GB resident, CPU only, `keep_alive` 5 min) writes language: research/thesis enrichment, incumbent "scientist notes" (ICR5; ≤ 2 drain passes per lab tick in session, more off-hours), mentor and engineering-mentor workers, overnight densify, chat.

**What the LLM is not for.** No trading decision and no learning step calls it:

| Step | How it is decided |
|------|-------------------|
| BUY / SELL / HOLD | SMA10/30 + RSI14 rule and the lab gates (§1–§2) — deterministic |
| F&O strike, sizing, budget, exits | ATM overlay, capital budget, risk-settings file — deterministic |
| Prediction at entry | `fno_lab_v1_control_signal.v1` formula — deterministic |
| Learning (EXPERIENCE → FEL → L3–L5) | Recorded outcomes, error, attribution, statistics vs cash — deterministic |

So "intelligence" in the sense that changes tomorrow's trades comes from **clean, independent, feature-rich outcomes** (§3–§4), not from the LLM being resident. The LLM makes Atlas *explain* better; the evidence makes it *learn*.

**Why unloading is not needed.** The outage was the RAM gate, not the LLM: every tick needed 3,072 MB free, and with Ollama (~4 GB) + browser + IDE resident the host had ~2.8 GB. Since `8057120`, lab and ledger ticks in market hours need only 128 MB above a 2,048 MB floor; at the time of writing the host shows ~5.4 GB available with Ollama loaded. Research and LLM-heavy workers keep the stricter gate and yield first under pressure — which is the right priority (a missed thesis note can wait; a missed exit cannot).

**Safeguard instead of unloading.** The per-lab tick alert (§7.4) reports any lab with no admitted tick for 20 min and names the cause. If it ever fires with `host_pressure` while Ollama is busy, the next step is to cap LLM concurrency during 09:15–15:30 (one request at a time, smaller context), not to remove it.
