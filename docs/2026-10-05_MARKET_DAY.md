# 5 October 2026 — market day notes

Paper session only. Live orders stayed off. SMA/RSI V1, PLC.A, and the kernel ladder were not changed.

## Why live work ran late

The cash session ends at 15:30 IST. Lab v1 options are supposed to be flat by then, and the evening digest is due from 15:45.

What happened:

- A paper tick that started before 15:30 kept walking the universe. Flatten runs at the start of a tick, so the walk already in progress did not stop. The next tick began the closes at 15:43.
- Each close waited on a scientist review before the fill email. Eight paper sells then landed one by one from 15:43 to 16:00.
- After 15:30 the market program floor dropped from 3 slots to 1 while two paper ticks were still in flight. Further market work, including the investor-report worker, was deferred with `program_floor market_intelligence inflight=2/1 reserved_for_peers=2`.
- Hourly notes for 15:00, 16:00, and 17:00 did not go out. Morning and hourly notes through 14:00 did go out. The evening digest for 5 October finally sent at ~20:50 IST (standalone timely path) after UI rebuild hung on live portfolio/Yahoo marks. Last prior evening digest on record was 1 October.
- The console stopped accepting HTTP around 14:44 while the same process kept the paper workers alive. Nothing was listening on port 8000. A new process started at 15:28 and `/health` and `/ui/` returned 200.

Buy emails during the session were prompt: the four morning calls around 11:13–11:19, and the four puts around 12:55–12:57.

## Priority path added

The running process does not have this until it is restarted.

- When the flatten clock is due, the F&O walk stops and closes open option lots on that symbol, instead of finishing the rest of the universe first.
- All session-flat sells and their fill emails finish before any scientist call. Reviews and experience rows still run, after the mail.
- From **07:00 IST** (morning digest) through cash hours and on to **23:00 IST** on weekdays, market intelligence keeps the higher slot floor (3 of 4), so morning mail, close-out, or evening-digest catch-up is not refused just because the cash-session flag is off.
- Evening/hourly builds use a timely path: no live Yahoo marks, no Postgres blotter wait, no research-digest stall, so SMTP can leave even when Yahoo is 429'd.
- The investor-report worker is admitted as realtime during that same window, so it ranks with market work instead of batch research.

## What Atlas recorded today, and what it can use later

These rows are evidence. They do not change SMA/RSI, PLC.A, capital allocation, or order authority. `belief_update` on the F&O closes is `unchanged`.

Canonical closed-loop join for the eight RTs: see [`2026-10-05_P1_P5_PROGRAM.md`](2026-10-05_P1_P5_PROGRAM.md) (P1) and
`investment/fno/closed_loop/india_fno_learner/2026-10-05.jsonl`.

F&O lab, eight paper round-trips, all flattened, book flat (`flat_ok`, no overnight options). Each close has a stated entry expectation and a computed prediction error:

| Contract | Expected | Result |
|---|---|---|
| ADANIPORTS26OCT1760CE | premium up | matched, about +₹2,708 |
| COALINDIA26OCT425CE | premium up | matched, about +₹608 |
| ITC26OCT262.5CE | premium up | matched, about +₹6,555 |
| HDFCBANK26OCT710CE | premium up | missed, about −₹1,365 |
| ICICIBANK26OCT1320PE | premium up | missed, about −₹3,535 |
| INFY26OCT1020PE | premium up | missed, about −₹1,460 |
| RELIANCE26OCT1180PE | premium up | missed, about −₹1,975 |
| TCS26OCT2100PE | premium up | missed, about −₹1,317 |

Net on those eight closes is about +₹219 before treating it as an edge. Attribution names the underlier move and the premium path, and leaves IV, greeks, and timing unknown. A single session is a sample. It can be cited later. It is not a new rule.

Equity learner wrote 233 experience rows (173 direction matches, 48 misses, 12 blocked buys) and 22 learning events. Intraday wrote 3 experiences, including blocked buys. Those rows record what the existing gates did. They do not relax a gate.

Kernel, same day: debt, ROE, and FCF for the trusted HBLPOWER filing reached SUCCESS and can be read as trusted facts on a later investigation. PE stays BLOCKED on a real conflict (calculator versus seed). MoS stays a capability gap. Web snippets are still not stored as numbers. The kernel still cannot order.

RAG coverage measured after the 15:28 start: 1,669 chunks, 1,669 embeddings, 0 missing documents, model `nomic-embed-text`. That count is a coverage fact. It is not a trading signal.

## Other work landed in the tree today

- F&O control now reaches the existing put branch when the cash book is flat and the average is falling, and the call-close branch when a call is already held. HOLD still does not open. Four paper puts filled (RELIANCE, TCS, INFY, ICICIBANK) after the 12:41 process loaded that wiring. Later names stayed flat because paper cash was about ₹1,740 and the next premiums were about ₹10,000–₹21,000.
- A failed Zerodha option-master download no longer pins an empty option list for the rest of the day.
- Agent kernel retries a trusted metric without treating the old miss as a new gap (debt SUCCESS; ROE and FCF followed). A FEL candidate can enqueue one investigation and cannot promote to live control. RAG coverage is read from the existing knowledge service. A paper closed-loop test covers a trusted PE versus a rejected web snippet, with no order and PLC.A still required.

## What the learning layer did with those eight closes

The eight closes above are now visible to the learning layer as eight complete chains: attribution required and addressed on all eight, each one an L3 provisional learning, and `validated` still 0. The earlier `chain_complete=0` was not a stale snapshot. Two causes in code: the experience builder left `evidence_backed` out of its satisfied-status set, and the close-attribution rule did not recognize the Lab v1 experiment-close tag. Both are fixed, and the fix derives the answer when the day is read rather than rewriting what was already written.

A cognitive cycle then ran over the same eight episodes without being told what to look for. It found four candidate patterns, and flagged three of them as the same claim wearing different names: CE is only ever bought on a positive control margin, so option type, margin sign, and holding bucket partition these eight episodes identically. No sample from today can separate them.

It tested the one claim that could be tested. The option-premium form came back `NOT_EVALUABLE` because there is no option intraday history, and no daily-bar stand-in was substituted for it. Restated at the underlier level, where durable daily bars do exist, the gap fell to 0.25 against a required 0.5 — CE 0.75, PE 0.50, against a 0.625 baseline over the same eight. The verdict is INCONCLUSIVE.

So the day's honest count is four questions asked, one tested, none learned. Atlas declined to confirm the pattern it had just noticed in its own trades.

Two scoring rules were tightened the same night, without moving those counts. An explicit unknown is a filled attribution slot and not a satisfied cause, so writing "we don't know" cannot complete a chain. And the one question a cycle is allowed to ask is the split the sample can separate: `underlier_direction` ranks ahead of the larger, confounded CE-versus-PE gap. Today's eight closes stay `chain_complete=8` because their attribution is `evidence_backed`. The next cycle is the one that asks the separable question.


## 2026-10-06 — the F&O data plane failed silently (and what changed)

Oct 6 produced no F&O action at all. 29/29 packs were `NOT_READY` with `expiry_missing` from the open to the close. The cause was in the provider layer, not the strategy. A futures-master call made before the 06:39 Zerodha login cached an empty list for the whole day. Options recovered through a second fetch path; futures never did. Nothing alerted the operator. Equity held 9 candidates on gates that behaved as designed, but one of them, `fundamentals_incomplete`, has blocked most actionable buys for five sessions in a row.

That evening, Loop 0 (Operational Health) was added in [`2026-10-06_OPERATIONAL_HEALTH_LOOP0.md`](2026-10-06_OPERATIONAL_HEALTH_LOOP0.md):

- A failed fetch can no longer become a valid empty cache.
- A login triggers a refresh of the masters.
- Each session window is classified into one of five idle categories.
- Recovery is attempted three times; if it fails, the operator gets one email laid out as what failed / why / impact / what Atlas tried / current state / what you can do.
- The persistent fundamentals block is flagged for investigation. The gate itself is not loosened.

A long-running silent failure was fixed too: worker checkpoints holding a Python `set` had been failing ticks permanently since at least Sep 23.
