# Trade trace — COALINDIA.NS / 2026-09-24

- **script:** `trace_trade.v1`
- **git_sha:** `fe3d009`
- **generated_at_ist:** `2026-10-12T21:24:47.517255+05:30`
- **lab:** `india_equity_learner`
- **portfolio_id:** `40d5cf03-e312-45d0-a3d4-b93ac44a76f7`
- **seed_trade_id:** `0d9a5313-cf68-4dd6-b883-002e21313023`
- **db_mode:** `dump:/data/atlas/docs/traces/_db_dump/swing`
- **entry:** `0d9a5313-cf68-4dd6-b883-002e21313023` BUY 19.0 @ 424.55 (2026-09-24T15:31:16.004264+05:30)
- **exit:** `013fa880-909a-4ccb-96ab-edf86995a5cd` SELL 19.0 @ 409.8 (2026-10-09T10:49:46.194196+05:30)

## First blocking dependency

**DECISION_EVIDENCE** — fields: order_intent; gap classes: PERSISTENCE

## Cells

| Dim | Step | Field | Status | Gap | Value | Note |
|-----|------|-------|--------|-----|-------|------|
| IDENTITY | 1 | round_trip_pair | OK |  | `{"entry_id": "0d9a5313-cf68-4dd6-b883-002e21313023", "exit_id": "013fa880-909a-4ccb-96ab-edf86995a5cd", "candidates":...` | unique equal-quantity buy/sell pair on symbol+portfolio+day |
| IDENTITY | 1 | quantities | OK |  | `{"entry_qty": 19.0, "exit_qty": 19.0, "entry_side": "buy", "exit_side": "sell"}` |  |
| ACCOUNTING | 7 | stored_realized_pnl | OK |  | `-280.25` | stored sell realized_pnl is exit-fee net (F18); check = (exit-entry)*qty - exit_fee |
| ACCOUNTING | 7 | fees | OK |  | `{"entry_fee": 0.0, "exit_fee": 0.0, "profile": "paper_demo"}` | zero-fee paper_demo expected for this lab profile |
| ACCOUNTING | 7 | return_on_cost_roc_v1 | CALCULATED |  | `-3.4743` | entry_cost=8066.45; round_trip_net=-280.25 |
| ACCOUNTING | 7 | stored_realized_return_pct | NOT_APPLICABLE |  | `null` | cash equity has no F&O lab_v1 prediction return field; roc.v1 calculated above |
| DECISION_LINKAGE | 3 | entry_decision | OK |  | `{"decision_id": "3f962391-4762-43ac-b0f7-681754e56cbc", "action": "buy", "symbol": "COALINDIA.NS", "why": "Chose 'buy...` | entry decision linked |
| DECISION_LINKAGE | 2 | entry_prediction | NOT_APPLICABLE |  | `null` | cash equity control-rule trade has no F&O lab_v1 prediction file; engine decision why is the record |
| DECISION_LINKAGE | 3 | entry_decision_packet | OK |  | `{"matches": 1}` | packet found |
| DECISION_LINKAGE | 6 | exit_decision | OK |  | `{"decision_id": "f1a64240-49bd-44d2-8db9-87a7ee98768f", "action": "sell", "why": "Chose 'sell:COALINDIA.NS' (score 1....` | exit decision linked |
| DECISION_LINKAGE | 6 | exit_trigger | OK |  | `{"source": "exit_decision.why", "why": "Chose 'sell:COALINDIA.NS' (score 1.8915, high confidence). SMA fast (418.3700...` | cash equity: exit trigger is the engine sell decision why (no F&O integrity flatten) |
| DECISION_EVIDENCE | 1 | entry_pack_snapshot | NOT_APPLICABLE |  | `null` | F&O pack snapshot not applicable to cash equity; entry evidence is engine decision + marks |
| DECISION_EVIDENCE | 4 | order_intent | MISSING | PERSISTENCE | `null` | no order-intent record on paper path (A6); fill price/qty are execution facts, not intent records |
| DECISION_EVIDENCE | 5 | underlier_session_context | OK |  | `{"alias": "COALINDIA.NS", "prior_close": 424.55, "day_open": 422.0, "day_close": 422.0, "open_to_close_pct": 0.0, "cl...` | session context only — not entry-to-exit underlier path (A8) |
| DECISION_EVIDENCE | 5 | underlier_open_to_close_pct | CALCULATED |  | `0.0` |  |
| DECISION_EVIDENCE | 5 | underlier_close_to_close_pct | CALCULATED |  | `-0.6006` |  |
| DECISION_EVIDENCE | 5 | underlier_entry_to_exit_path | OK |  | `{"entry_price": 424.55, "exit_price": 409.8, "move_pct": -3.4743, "entry_at_ist": "2026-09-24T15:31:16.004264+05:30",...` | cash equity: fill prices are the asset path endpoints (not a separate underlier) |
| DECISION_EVIDENCE | 5 | iv_greeks | NOT_APPLICABLE |  | `null` | IV and option Greeks not applicable to cash-equity trades |
| ATTRIBUTION | 8 | stored_attribution_status | OK |  | `"unknown_explicit"` | stored label reported verbatim |
| ATTRIBUTION | 8 | trace_attribution_state | OK | ATTRIBUTION | `"PARTIAL"` | classified per §4.1 |
| LEARNING | 9 | hypothesis | MISSING | LEARNING | `null` | observation-style lesson text is not a named hypothesis |
| LEARNING | 10 | validation_test | MISSING | LEARNING | `null` | no validation test defined |
| LEARNING | 9 | learning_story | OK |  | `{"story_id": "c3a53305-ed38-4372-9b09-cc5fe0fec7b8", "cause": {"status": "unknown_explicit", "helped": [], "hurt": []...` |  |
| LEARNING | 9 | fel_features | OK |  | `{"null_fields": {}, "keys_sample": ["kind", "as_of", "symbol", "laboratory_id", "features", "target", "experience_id"...` | FEL features present |
| LEARNING | 9 | thesis_tracker_instrument_class | OK |  | `{"symbol": "COALINDIA.NS", "horizon": "long_term", "hypothesis": "Coal India operates in Oil Gas & Fuels. The busines...` | thesis tracker present for cash-equity symbol |
| ACCOUNTING | 7 | lab_day_pnl_kpi | OK |  | `-9502.999841308654` | lab-level day_pnl (all symbols); not this trade alone |

## Gap summary

| Status | Gap | Dimension | Count |
|--------|-----|-----------|------:|
| CALCULATED |  | ACCOUNTING | 1 |
| CALCULATED |  | DECISION_EVIDENCE | 2 |
| MISSING | LEARNING | LEARNING | 2 |
| MISSING | PERSISTENCE | DECISION_EVIDENCE | 1 |
| NOT_APPLICABLE |  | ACCOUNTING | 1 |
| NOT_APPLICABLE |  | DECISION_EVIDENCE | 2 |
| NOT_APPLICABLE |  | DECISION_LINKAGE | 1 |

## Raw sources

- `db` `sim.trades:0d9a5313-cf68-4dd6-b883-002e21313023` sha256=`—` mtime_ist=`—` original_ts=`2026-09-24T10:01:16.004264+00:00`
- `db` `sim.trades:013fa880-909a-4ccb-96ab-edf86995a5cd` sha256=`—` mtime_ist=`—` original_ts=`2026-10-09T05:19:46.194196+00:00`
- `calculated` `roc.v1 = round_trip_net / (qty*entry_price + entry_fee) * 100` sha256=`—` mtime_ist=`—` original_ts=`—`
- `db` `decision.decisions:3f962391-4762-43ac-b0f7-681754e56cbc` sha256=`—` mtime_ist=`—` original_ts=`2026-09-24T10:01:15.320418+00:00`
- `file` `/data/atlas_data/investment/decisions/by_day/india_equity_learner/2026-09-24.jsonl` sha256=`dffc9b13b801b78968f2fd05176a106c6c89658075411ffc26ea9a19dc58ecff` mtime_ist=`2026-09-24T16:16:29.272075+05:30` original_ts=`—`
- `db` `decision.decisions:f1a64240-49bd-44d2-8db9-87a7ee98768f` sha256=`—` mtime_ist=`—` original_ts=`2026-10-09T05:19:46.079909+00:00`
- `file` `/data/atlas_data/market/bars/COALINDIA.NS.json#bars[2026-09-24]` sha256=`36ced394f879df43d0283117615ee8479791f7f7b6c2f271f2b3ccf7cefd0708` mtime_ist=`2026-10-12T21:16:18.093887+05:30` original_ts=`2026-09-24T00:00:00+00:00`
- `calculated` `(close-open)/open*100` sha256=`—` mtime_ist=`—` original_ts=`—`
- `calculated` `(close-prior_close)/prior_close*100` sha256=`—` mtime_ist=`—` original_ts=`—`
- `file` `/data/atlas_data/investment/learning/india_equity_learner/2026-10-09.jsonl#EXPERIENCE.attribution` sha256=`00606ec5f312f5a3e756698812a134a5f3c6a5c7b40cc9eecee0113f0402fd64` mtime_ist=`2026-10-09T14:52:25.774855+05:30` original_ts=`—`
- `file` `/data/atlas_data/investment/learning/india_equity_learner/2026-10-09.jsonl` sha256=`00606ec5f312f5a3e756698812a134a5f3c6a5c7b40cc9eecee0113f0402fd64` mtime_ist=`2026-10-09T14:52:25.774855+05:30` original_ts=`—`
- `file` `/data/atlas_data/investment/learning/india_equity_learner/2026-10-09.jsonl#LEARNING_STORY` sha256=`00606ec5f312f5a3e756698812a134a5f3c6a5c7b40cc9eecee0113f0402fd64` mtime_ist=`2026-10-09T14:52:25.774855+05:30` original_ts=`—`
- `file` `/data/atlas_data/investment/fel/datasets/india_equity_learner/DS-E-paper-round-trip-india_equity_learner.jsonl` sha256=`346d63d36edc3451b6205f7fc932b576593451085d478c5f04b8bffb450aa136` mtime_ist=`2026-10-09T11:05:31.593649+05:30` original_ts=`—`
- `file` `/data/atlas_data/investment/thesis_tracker/market_intelligence/COALINDIA.NS.json` sha256=`7d77fe6f1918463c6e6ed9dde2e27a05f09d859c1c49e45ebcc8d858cd0209c5` mtime_ist=`2026-10-09T10:49:46.238929+05:30` original_ts=`—`
- `file` `/data/atlas_data/market/trading_kpis/india_equity_learner/2026-09-24.json#kpis.day_pnl` sha256=`c65f9f51030d693fa06a1377c809d2a6049f3545a9826796af4ec4b60207842d` mtime_ist=`2026-09-24T23:59:45.515163+05:30` original_ts=`—`

## Appendix — discovery and hand verification (2026-10-12)

**Most recent closed equity-swing round trip** (`india_equity_learner`):

| Field | Value |
|-------|-------|
| Symbol | COALINDIA.NS |
| Entry IST | 2026-09-24 15:31:16 | trade `0d9a5313…` | decision `3f962391…` |
| Exit IST | 2026-10-09 10:49:46 | trade `013fa880…` | decision `f1a64240…` |
| Qty | 19 @ 424.55 → 409.8 |
| Realized | −₹280.25 |
| Method | most recent sell with realized_pnl; FIFO single-lot; no fills of this symbol between entry and exit |

| # | Cell | Independent check | Result |
|---|------|-------------------|--------|
| 1 | `stored_realized_pnl` | `(409.8−424.55)×19 − 0 = −280.25` | PASS |
| 2 | `return_on_cost_roc_v1` | `−280.25 / 8066.45 × 100 = −3.4743%` | PASS |
| 3 | Entry/exit IST dates | 2026-09-24 → 2026-10-09 | PASS |
| 4 | `entry_decision` | buy; SMA10>SMA30 margin +2.10%, RSI 55.4 | PASS |
| 5 | `exit_decision` | sell decision_id linked; SMA crossunder in why | PASS |

Note: COALINDIA had many other fills in the calendar span; the dump used for pairing is the **explicit discovered pair** only (AMBIGUOUS avoided per A28). IV/Greeks = NOT_APPLICABLE.

Data-dir writes from this run: **0**.
