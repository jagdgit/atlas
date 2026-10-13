# Incident 2026-10-13 — trading labs starved by the host RAM gate; F&O closed 2h after market close

| | |
|--|--|
| Severity | P0 (all three paper labs lost the trading session) |
| Window | ~11:15 → 17:35 IST (labs effectively absent for the rest of the session) |
| Detected by | Operator (labs "stopped"); one correct ops alert at 12:18 IST that was later auto-resolved while still stale |
| Ledger impact | F&O day P&L **−₹64,476.75** (kept — accounting truth). Equity labs: no fills |
| Learning impact | 10 F&O experiences written from a process-invalid day → **quarantined** (not deleted) |
| Status | Permanent fixes coded + tested, need operator restart (`sudo systemctl restart atlas`) |

---

## 1. What happened (timeline, IST)

| Time | Event | Evidence |
|------|-------|----------|
| 06:00–07:07 | Zerodha `LOGIN_REQUIRED` → live labs paused; token renewed, session OK at 07:07 | `atlas.log` emails 06:00, 06:02, 07:07 |
| 09:21–09:24 | F&O lab bought **10 ATM puts on 10 different underliers** in ~3 minutes (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK, BHARTIARTL). ₹1,47,600 of premium — the whole cash book | trade lineage; 10 BUY emails |
| 09:24 → | F&O cash exhausted → every further tick is `insufficient cash` / `capability_gap` (181 no-fill reasons) | KPI `top_no_fill_reasons` |
| ~09:20–11:15 | Equity swing + intraday labs ticked, made only HOLD decisions (`engine_hold`, `lab_policy_hold`, `fundamentals_incomplete`) | decision timeline by hour |
| **~11:15 → 17:35** | **Host Guard deferred every worker tick.** Free RAM ≈ 2.7–3.0 GB; the gate needs `reserve 2560 MB + tick 512 MB = 3072 MB`. ~6,000 deferral lines, each paper lab ~300+ deferrals | journal `host_pressure` |
| 11:32 | "Morning investment plan" mailed — 3+ hours late (starvation) | email log |
| 12:18 | Ops P0: "Last F&O pack 65 min ago" — **this alert was correct** | email log |
| 15:30 | Ops "RESOLVED — Last F&O pack 255 min ago" — **auto-resolved while still stale** (the session ended, the symptom did not) | email log |
| 15:30 | NSE close. 10 option positions still open, unmanaged since ~09:24 | — |
| 17:34–17:42 | First admitted F&O tick → overdue `session_flat` close: 10 SELLs at Zerodha last traded LTP (≈ the 15:30 close print) | lineage; 10 SELL emails |
| 18:10 | Evening digest + Hourly 18:00 (the only hourly mails besides 11:00) | email log |

Equity labs: **0 fills all day**. `india_equity_learner` reports 1,185 `session_closed` idle reasons (ticks outside hours) and almost no in-session ticks after 11:15. `equity_intraday_learner` made one decision all day (10:xx).

## 2. Root causes

### RC1 — One admission gate for 30 workers, sized for background research (primary)
`HostGuardService.can_run_tick()` asked `ResourceManager.can_admit_tick(expected_ram_mb=512, reserve_mb=2560)` for **every** worker type. 30 active workers compete; only 2 are trading labs (+ `portfolio_ledger`). When free RAM sat between ~2.6 and 3.0 GB — normal on this desktop with Ollama (~4 GB) + Firefox + Cursor resident — **nothing** was admitted, so a paper-trading tick (≈ tens of MB of real work) was refused for six hours. Deferral is "never drop the job", but for a market-hours lab a 6-hour deferral *is* dropping the job.

Yesterday's plan protected the labs from *process* failure (single-instance lock, Step 0B) but not from *capacity* starvation: no lane distinguished "trading lab during NSE hours" from "batch research".

### RC2 — F&O close-out only happens inside an admitted tick, at/after 15:30
`must_flatten_experiments` started at 15:30, i.e. exactly when the market stops being tradeable. Any delay (starvation, a slow tick, a restart) pushes the exit into after-hours, where the "exit price" is just the last print.

### RC3 — No live position management for held options
Once an ATM option is held and spot moves, the held strike is no longer the ATM strike → overlay returns `legacy_non_atm_option` / `hold_aligned_option` → **no exit rule runs**. Positions are carried to the session flatten regardless of what happens. (Still open — see next actions.)

### RC4 — Correlated entry swarm with no capital budget
Ten same-direction PE buys on highly correlated underliers in 3 minutes, sized "1 lot each", consumed 98% of the cash. Effectively one bet on "market down today", taken ten times. (Fixed yesterday evening — capital budget, commit `d6b1203`; live after restart.)

### RC5 — Monitoring auto-resolves on session end
The F&O-pack-staleness alert resolved at 15:30 because the session closed, not because packs resumed. The operator therefore saw "RESOLVED" while the lab had not run for 4+ hours.

Exact mechanism: `ops_health` treated `packs > 0` (any pack file for the day) as "pack_write_confirmed". Packs from before 11:15 satisfied that at 15:30. Fixed: recovery now requires `latest_pack_at > incident.opened_at`; regression test `test_morning_packs_do_not_verify_afternoon_worker_outage`.

## 3. Verdict on the post-close F&O sells

| Question | Answer |
|----------|--------|
| Were the entries real paper fills? | **Yes.** Live Zerodha option LTP, in session, 09:21–09:24. |
| Is the exit price real? | It is the **last traded price** (≈ 15:30 close print) — a true mark, not invented, not avg-cost. |
| Is the P&L "real"? | **Yes as accounting**: −₹64,476.75 is what a *hold-to-close* of those 10 puts produced (the puts lost 17%–58% of premium, consistent with underliers rising plus same-day time decay). It is **not** a tradeable exit: at 17:35 nothing can be sold on NSE. |
| Should the ledger be reset? | **No (recommended).** The ledger is authoritative and the number is economically honest (≈ mark-to-close). Rewriting it would invent history. A cash *top-up* is a separate operator decision and must be a journaled adjustment, never an edit. |
| Can Atlas learn from it? | **No.** The process was invalid: unmanaged for ~6 h, correlated swarm, exit after close, E[R]=8% is an `uncalibrated_default`. Training on it would teach "PE buys lose ~45%" from one market day counted ten times. |
| What was done | 10 experiences **quarantined** in `investment/integrity/learning_quarantine/india_fno_learner.jsonl` (reasons: `exit_after_session_close`, `unmanaged_position_host_starvation`, `correlated_entry_swarm`). Ledger, lineage, EXPERIENCE rows untouched. FEL F&O round-trip sample: 49 → 39 on next rebuild. |

| Symbol | Buy (IST) | Buy ₹ | Sell (IST) | Sell ₹ | Qty | P&L ₹ |
|--------|-----------|------:|------------|-------:|----:|------:|
| NIFTY26OCT22500PE | 09:21 | 249.30 | 17:40 | 104.10 | 65 | −9,438.00 |
| BANKNIFTY26OCT55300PE | 09:22 | 672.80 | 17:35 | 404.90 | 30 | −8,037.00 |
| FINNIFTY26OCT25050PE | 09:22 | 421.95 | 17:36 | 190.45 | 60 | −13,890.00 |
| MIDCPNIFTY26OCT13650PE | 09:23 | 198.35 | 17:39 | 122.70 | 120 | −9,078.00 |
| RELIANCE26OCT1160PE | 09:23 | 19.25 | 17:41 | 14.85 | 500 | −2,200.00 |
| TCS26OCT2200PE | 09:23 | 50.00 | 17:42 | 23.00 | 225 | −6,075.00 |
| INFY26OCT1040PE | 09:23 | 31.90 | 17:38 | 17.60 | 400 | −5,720.00 |
| HDFCBANK26OCT710PE | 09:24 | 10.00 | 17:37 | 8.25 | 650 | −1,137.50 |
| ICICIBANK26OCT1340PE | 09:24 | 18.95 | 17:38 | 11.90 | 700 | −4,935.00 |
| BHARTIARTL26OCT1780PE | 09:24 | 18.30 | 17:36 | 9.95 | 475 | −3,966.25 |
| **Total** | | **₹1,47,600 deployed** | | | | **−₹64,476.75** |

Book after the day: cash ₹85,727.93, net contributed ₹1,00,000, lifetime P&L −₹14,272 (−14.3%).

## 4. Permanent fixes (code in this change set)

| # | Fix | Where | Effect |
|---|-----|-------|--------|
| F1 | **Market-critical admission lane.** `paper_trading` and `portfolio_ledger` ticks on weekdays 09:00–16:00 IST are admitted with a 128 MB tick need against a 2048 MB floor (generic: 512 MB vs 2560 MB). Research/batch workers keep the old gate. Denials are tagged `market_critical:` and counted separately (`deferred_critical_ticks_total`). | `atlas/core/resources/host_guard.py` (hg.1.4), wired in `kernel/bootstrap.py`; config `resources.critical_tick_ram_mb`, `resources.critical_reserve_mb` | On 2026-10-13 numbers (≈2.8 GB free) labs would have been admitted all day; research would still yield. The OS still keeps ≥2 GB free. |
| F2 | **F&O close-out starts 15:20 IST** (no new entries from 15:20; flatten while NSE is still trading). | `fno_lab_v1.FNO_FLAT_AFTER` | Ten minutes of tradeable window for the exits, matching the equity intraday lab. |
| F3 | **Late exits are never learning.** Every experiment_close is stamped `learning_eligibility` by execution time; a close at/after 15:30 or before 09:15 is `eligible: false, reasons: [exit_after_session_close]`, on the attribution, the learning packet and the EXPERIENCE row; lineage carries `exit_timing`. | `fno_lab_v1.exit_learning_eligibility`, `paper_trading._flatten_fno_lab_v1_experiments`, `learning_objects.record_from_trade_close` | A repeat of today cannot contaminate learning, even if starvation recurs. |
| F4 | **Learning quarantine** (append-only manifest, releasable). FEL round-trip dataset skips quarantined + ineligible rows; F&O closed-loop rows carry `learning_eligible`. | `atlas/investment/learning_quarantine.py`, `fel/experiments/paper_round_trip.py`, `fno_closed_loop_dataset.py` | Operator can exclude a bad day without rewriting history. |
| F5 | Capital budget (yesterday, `d6b1203`): ≤2 open option experiments, 30% starting-cash reserve, never auto-top-up. Reserve base corrected to `max(starting_cash, net_contributed)` in `d9a99a9`. | `fno_lab_v1.evaluate_option_buy_budget` | Ends the 10-underlier swarm. |
| F6 | **Managed exits for held options (RC3)**, `9506ab2`: every tick, each held Lab v1 option is checked on its own live LTP — premium stop (default −40%), trend reversal, optional target; no same-day re-entry after a managed exit. Values in the operator file `investment/fno/lab_v1_risk_settings.json` (`259649e`). | `fno_lab_v1.evaluate_held_option_exit`, `paper_trading._fno_managed_exit` | A held put cannot ride a reversal unmanaged until the close. |
| F7 | **Alert can no longer falsely resolve (RC5)**, `05e7286`: the F&O worker incident verifies recovery only on a pack written after it opened. | `ops_health._pack_written_since_open` | Today's 15:30 "RESOLVED" would have stayed UNRESOLVED. |
| F8 | **Per-lab tick admission check (RC5)**, `27c4890`: ledger of admitted/deferred ticks per lab; P0 after 20 min without an admitted in-session tick, naming the deferral cause; no self-resolve at close; digest line per lab. Covers the equity labs, which had no alert at all today. | `atlas/investment/lab_ticks.py`, `ops_health.assess_lab_ticks`, `WorkerManager._record_wait` | On today's data: P0 for F&O and swing at ~11:35 with cause `host_pressure`. |

Tests: `tests/test_host_guard.py` (critical lane in session, generic gate for research + after hours, the 2026-10-13 RAM scenario), `tests/test_fno_lab_v1.py` (15:20 flatten, eligibility, quarantine → FEL filter), `tests/test_fno_managed_exit.py`, `tests/test_ops_health_loop0.py::test_morning_packs_do_not_verify_afternoon_worker_outage`, `tests/test_lab_ticks.py` (today's starvation replayed).

## 5. Still open (not fixed by this change)

1. ~~RC3 held-option exit management~~ — fixed (F6).
2. ~~RC5 alert semantics~~ — fixed (F7, F8).
3. **Host memory** — Ollama (~4 GB) resident during market hours. Unload/keep-alive=0 during 09:00–16:00, or move LLM work after 16:00.
4. **Trade emails lack the decision chain** (see review doc §5).

F1–F5 are live (service restarted on `d9a99a9`). F6–F8 need the next operator restart. Full change log: review doc §7.
5. **Equity swing pre-market noise** — 10 `switch_exploratory` SELL decisions on HBLPOWER.NS recorded 01:32–02:18 IST (market closed, none executed). Switch review should not mint SELL decisions outside the session.

See `docs/2026-10-13_LAB_OPERATIONS_AND_LEARNING_REVIEW.md` for per-lab mechanics, learning, RL assessment and the full next-action list.
