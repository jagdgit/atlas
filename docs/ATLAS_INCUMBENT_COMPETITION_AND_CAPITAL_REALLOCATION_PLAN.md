# Incumbent Competition & Capital Reallocation (ICR)

> **Status:** 🔒 **PLAN LOCKED for implementation** (operator diagnosis 2026-08-21)  
> **OI:** `OI-ICR0`  
> **Priority:** **P0** — learning-integrity / allocation architecture (before more swing adds)  
> **Date:** 2026-08-21  
> **Does not reopen:** DI / LI / LQ / PLC / UTS architectures as wholesale rewrites  
> **Builds on:** `OI-UTS0` (Next-₹1 / switching) · `OI-LOOP0` L1 E[R] prototype · `OI-LINT0` · `OI-CF0` · lab contracts  
> **Trigger case:** CIPLA.NS — technical BUY → incumbent → research AVOID / MoS− / very_low / QUARANTINED → no exit → challengers blocked → fresh cash can re-feed SMA ADD

---

## 0. Verdict

UTS0 taught Atlas to *review* holds vs challengers. CIPLA shows the review is **asymmetric**:

| Layer | What it does today | Gap |
|-------|--------------------|-----|
| SMA/RSI | Can BUY / ADD | Consumes new cash without Next-₹1 packet |
| Research / gate_buy | AVOID blocks *some* new thesis buys | Does **not** force incumbent review or block ADD hard enough |
| PLC.B | Stop / trail / time / thesis_broken | AVOID ≠ thesis_broken; MoS− ≠ exit |
| UTS switch | `hold_incumbent` / `switch_blocked_*` | Missing E[R] / PLC.A on challenger → incumbent wins by default |
| Allocator | Exposure / cash capacity | No mandatory “where should this rupee go?” before ADD |

**Diagnosis (lock):** Atlas can enter and protect a position; it cannot yet **continuously justify capital trapped in that position** against challengers and cash.

This is an **allocation-architecture** problem, not a “CIPLA is down −1.5% ⇒ sell” problem. P&L must not drive the rule. **Relative expected return + evidence quality + switch cost** must.

**North star:** Every material use of capital (new buy, ADD, KEEP, rotate, EXIT_REVIEW) is an experiment with **chosen + rejected alternatives + opportunity cost**, not a lone technical fill.

---

## 0.1 Non-negotiables

1. **No AVOID ⇒ instant liquidation.** Temporary research error must not force churn. Use `EXIT_REVIEW` → deterministic checks → EXIT when justified.
2. **No incumbent preferential veto.** `hold_incumbent` means “challenger not *sufficiently* better after costs,” never “never challenge the book.”
3. **NO ADD without allocation comparison** once a position exists (hard safety until ICR packets land).
4. **AVOID / QUARANTINED ⇒ NO BUY and NO ADD** until identity re-established and thesis cleared by explicit evidence (not SMA alone).
5. **Honest preliminary E[R]** always — number + `er_completeness` + `er_model` (LOOP0 L1). Missing knowledge must not become a *positive* signal for the incumbent.
6. Laboratory hermeticity; paper only; no live NN trading.
7. **Same state = same experiment** (EXP0 + ACP `state_hash`): repeated CIPLA ADDs with identical evidence/E[R]/challenger set/portfolio fingerprint ≠ three learning events. Visible acceptance test required.
8. LLM (scientist) improves ranking *reasoning*; deterministic allocator still executes.
9. **Capital-decision provenance** — every ADD/KEEP/SWITCH/EXIT_REVIEW must be traceable through ACP → candidates → E[R] versions → evidence/packet IDs → technical + research → optional scientist note → deterministic decision (reuse DI/LI; no new DB).
10. **Capital regret** is a first-class allocator KPI (chosen path vs best feasible rejected), distinct from book P&L.

---

## 0.2 Relationship to existing work

| Plan | Role vs ICR |
|------|-------------|
| **UTS0** | Challenger review + switch learning + missed-opp ledger — **keep**; ICR makes ADD / fresh-cash / AVOID paths use the same economic center |
| **LOOP0 L1** | E[R] prototype — **required substrate**; ICR forbids ADD when comparison packet lacks versioned E[R] for incumbent + best challenger + cash |
| **LINT0** | Thesis identity quarantine — **strengthen** to block ADD and force `EXIT_REVIEW`, not only buy hold |
| **PLC.A / PLC.B** | Entry / risk exits — **unchanged**; ICR adds *allocation* exits / reviews above them |
| **CF0** | Counterfactuals on buys — **extend** to rejected challengers (opportunity-cost ledger) |
| **CU0 / CHAT-INFER0** | Scientist packet on allocation comparisons (advice-only) |

**Identity (lock):** Atlas is a **capital allocator with memory**. Technical signals are *evidence*, not capital consumers.

---

## 1. Economic hierarchy (locked)

```
                 ATLAS INVESTMENT DECISION
                           │
                           ▼
              What is the best use of capital now?
                           │
             ┌─────────────┼─────────────┐
             ▼             ▼             ▼
         Incumbents    Challengers      Cash
             │             │             │
             └─────────────┼─────────────┘
                           ▼
              Relative E[R] + risk + uncertainty
              + evidence quality + switch cost
              + concentration + identity/thesis status
                           ▼
                    ALLOCATION DECISION
                           │
        ┌──────────┬───────┼───────┬──────────┐
        ▼          ▼       ▼       ▼          ▼
       ADD       KEEP    HOLD   SWITCH_REVIEW EXIT_REVIEW
                                      │            │
                                      ▼            ▼
                                   SWITCH        EXIT
```

**Incumbent’s only structural advantage:** transaction-cost / uncertainty hurdle the challenger must clear — not immunity from comparison.

---

## 2. CIPLA / red-flag audit (baseline)

Observed (swing `india_equity_learner`, as of 2026-08-21 audit):

- Position: **15 × CIPLA.NS** @ ~₹1,459.81 (buys 6 Aug, 10 Aug ×2, 19 Aug ADD).
- Research banner: **AVOID · conf very_low · cov 22.6% · MoS −55% · quality developing**.
- Identity: **QUARANTINED** (hospital-network language on pharma pack).
- Gate: `allowed=False` (`mos_negative`, `thesis_avoid`, `investment_confidence_very_low`).
- PLC.B: **no exit** (loss ≪ stop; stance AVOID ≠ `thesis_broken`).
- Session: `hold` / `mark_only` / `hold_incumbent` / prior `switch_blocked_*`.
- Open MTM ≈ **−1.5%** — irrelevant as sell rule; MoS is valuation, not trade P&L.

**Operator experiment:** adding cash must not silently become “SMA consumes spare cash into CIPLA.” That path is the **incumbent-lock loop**:

```
tech BUY → incumbent → AVOID (no sell) → challenger incomplete
  → hold_incumbent → fresh cash → tech BUY → ADD → larger incumbent → repeat
```

---

## 3. Immediate safety (Ship first — ICR.0)

**Scope:** swing lab only (`india_equity_learner`). FNO / intraday unchanged except shared helpers if cheap.

| Rule | Behavior |
|------|----------|
| **ICR.0a** `NO_ADD_AVOID_QUARANTINE` | If thesis stance ∈ {AVOID, INVALID} **or** identity QUARANTINED → reject **BUY** and **ADD** (qty that increases open size). Reason: `add_blocked_research` / `add_blocked_quarantine`. |
| **ICR.0b** `NO_ADD_WITHOUT_ALLOCATION_PACKET` | If `held > 0` and intent is ADD (or BUY that increases size) → require durable **Allocation Comparison Packet** (ACP) for this IST decision state; else `add_blocked_no_acp`. |
| **ICR.0c** Fresh-cash path | Deposit / cash increase does **not** auto-arm SMA ADD; next fill must pass 0a+0b. |
| **ICR.0d** Freeze scope | Observation, research, FNO, intraday, PLC.B sells, UTS *reviews* continue. Only **accumulation** freezes without ACP. |

**Done when:** Hermetic tests: CIPLA-like fixture (held + AVOID + QUARANTINED + SMA BUY) → no size increase; packet missing → no ADD; AVOID alone → no ADD.

**Same-state acceptance (visible):** two ticks with identical `state_hash` attempting ADD → second is `add_blocked_duplicate_state` (or equivalent), not a second learning fill.

**Ops:** Prefer bounce after merge so live swing cannot ADD CIPLA on next tick.

---

## 4. Allocation Comparison Packet (ACP) — ICR.1

Durable per lab / IST day / decision-state hash (reuse EXP0 state keys).

Minimum fields:

| Field | Notes |
|-------|-------|
| `available_capital` | Cash (and optional free capacity) |
| `incumbent` | symbol, qty, avg, mark, thesis, identity, MoS, E[R], completeness, confidence |
| `challengers[]` | top 1–2 + optional watch hit; each with E[R] + completeness + confidence + PLC.A status |
| `cash` | E[R]≈0, completeness=1, explicit alternative |
| `benchmark` | NIFTY / sector RS stub when available |
| `switch_cost` | fees + spread proxy + min advantage threshold |
| `concentration` | name weight vs cap |
| `decision` | `KEEP` \| `ADD` \| `SWITCH_REVIEW` \| `EXIT_REVIEW` \| `HOLD` |
| `why` | short deterministic reason code + human line |
| `rejected[]` | symbols not chosen + why |
| `er_model` / inputs | LOOP0 versioned E[R] |
| `state_hash` | evidence fingerprint for dedupe — **same hash ⇒ same experiment** |
| `provenance` | Chain ids: ACP id → candidate set → `er_model`+inputs → evidence/packet/decision ids → technical signal refs → thesis/identity snapshot → optional `scientist_notes` → final decision (DI/LI reuse) |

**UI / evening:** one line per open name — “why still own / best alternative / min advantage to switch.”

**Provenance acceptance:** given any ADD/KEEP/EXIT_REVIEW row, operator can walk the chain without reading today’s code.

---

## 5. Incumbent Review Engine — ICR.2

Periodic (plan tick / daily densify), **every open swing hold**:

1. Build ACP (incumbent vs best challenger vs cash vs benchmark).  
2. Map research → review state:

| Research / identity | Review state |
|---------------------|--------------|
| BUY / strong E[R] edge | `KEEP` or `ADD` (only with ACP) |
| WATCH / thin evidence | `HOLD` + curiosity densify |
| AVOID / MoS≪0 / very_low | `EXIT_REVIEW` (not auto EXIT) |
| QUARANTINED | `EXIT_REVIEW` + identity research task (CUR/CWS) |

3. `EXIT_REVIEW` deterministic ladder (examples — tune in code, not ad hoc sells):

   - Identity quarantine unresolved N days → propose EXIT  
   - AVOID + challenger clears switch cost → `SWITCH_REVIEW`  
   - AVOID + no viable challenger + cash preferred by E[R] honesty → EXIT to cash  
   - Else stay `EXIT_REVIEW` with explicit “waiting for: …” unknowns  

**Not** PLC.B replacement — PLC.B remains hard risk stops.

---

## 6. Opportunity-cost learning object — ICR.3

First-class learning event (JSONL under lab learning store; feed LI / CF):

```text
Chosen: CIPLA
Rejected: EICHERMOT, INFY, CASH
Why / E[R]s / confidence / evidence / unknowns
Later: realized paths for chosen + rejected (horizon 1/5/20d)
Opportunity cost: chosen − best_rejected (honest nulls allowed)
Attribution: thesis | technical | missing_er | quarantine | costs | …
Learning: allocation forecast quality — not “price went down”
```

Reuse CF0 scheduling where possible; do not invent PnL when bars missing.

### Capital regret KPI (operator-approved addition)

```text
capital_regret_20d = actual_chosen_return_20d − best_feasible_rejected_return_20d
```

Example: CIPLA +1%, EICHER +7%, cash 0% → `capital_regret_20d = −6%`.

- Null when rejected legs lack honest marks (do not invent).
- Roll up: mean / median capital regret by lab (allocator quality), **separate from** portfolio P&L.
- Aligns with UTS missed-opportunity / opportunity-capture measures.

---

## 7. E[R] & knowledge-induced lock-in — ICR.4

| Problem | Fix |
|---------|-----|
| `missing_er` ⇒ keep incumbent forever | Prototype E[R] **always** on ACP legs (LOOP0); block is only “advantage unclear,” logged as such |
| Challenger PLC.A fail ⇒ no comparison | Still emit ACP with `challenger_status=plc_a_blocked` and cash alternative |
| Repeated same state | EXP0: one ADD / one ACP decision per state hash per IST day |

---

## 8. LLM role (scientist only) — ICR.5

On ACP / `EXIT_REVIEW` densify (budgeted, CU0 lanes):

- Contradictions (tech BUY vs AVOID vs quarantine)  
- Which unknown flips the ranking  
- Whether incumbent edge is robust  

**Never** places orders. Output attaches to ACP as `scientist_notes` (advice-only).

---

## 9. Phased delivery

| Phase | ID | Deliverable | Exit criteria |
|-------|-----|-------------|---------------|
| **Safety freeze** | **ICR.0** | NO ADD on AVOID/QUARANTINE; NO ADD without ACP stub | Tests green; live CIPLA cannot grow on SMA |
| **ACP v1** | **ICR.1** | Packet schema + persist + evening/UI one-liner | Every swing ADD/KEEP attempt writes ACP |
| **Incumbent review** | **ICR.2** | Daily/tick review → KEEP/HOLD/EXIT_REVIEW/SWITCH_REVIEW | CIPLA-like → EXIT_REVIEW not silent hold |
| **Opp-cost ledger** | **ICR.3** | Learning object + horizon fill | Counterfactual rows for rejected alts |
| **E[R] symmetry** | **ICR.4** | No missing_er lock-in on ACP | Reviews never “incumbent wins because challenger null” without cash compare |
| **Scientist densify** | **ICR.5** | Optional LLM notes on EXIT_REVIEW | Budgeted; no execution |

**Do not** start ICR.5 before ICR.0–1. Do not “fix CIPLA” by teaching −1.5% ⇒ sell.

---

## 10. Explicit non-goals

- Rewriting SMA/RSI control strategy  
- AtlasNet / live NN trading  
- Auto-liquidation on every AVOID  
- Merging lab ledgers  
- AGENT-1 / Phase 5 belief soft-influence (still frozen on STAB gates)

---

## 11. Acceptance story (operator)

After ICR.0–2, Atlas must be able to say for CIPLA:

> I own CIPLA. Here is why I still own it (or why EXIT_REVIEW).  
> Here is what I give up vs best challenger and cash.  
> Here is the minimum advantage to switch.  
> Here is the evidence that would change my mind.  
> SMA alone cannot add while AVOID/QUARANTINED.

Until then: **treat further CIPLA accumulation as a P0 learning-integrity incident.**

---

## 12. Checklist

- [x] ICR.0a–d implemented + hermetic tests (**incl. same-state ≠ triple learning**)  
- [ ] CIPLA live: no ADD under AVOID/QUARANTINE (bounce to load ICR.0–5)  
- [x] ICR.1 ACP schema + persist path + **provenance chain**  
- [x] ICR.2 EXIT_REVIEW densify (WAIT / SWITCH_TO / EXIT_TO_CASH) + paper_trading execute  
- [x] ICR.3 opportunity-cost learning object + **`capital_regret_20d` KPI**  
- [x] ICR.4 E[R] on all ACP legs + `advantage_unclear` (no missing_er lock-in) + PLC.A visible  
- [x] ICR.5 scientist notes (deterministic draft + budgeted research-lane LLM; advice-only)  
- [x] OPEN_ITEMS `OI-ICR0` updated per phase (ICR.0–5)  
- [x] Evening / Market UI surface ACP one-liner (+ ICR.2 exit + ICR.5 scientist line)  

---

## 13. Revision log

| Date | Note |
|------|------|
| 2026-08-21 | Plan locked from operator CIPLA / fresh-cash diagnosis; UTS/Next-₹1 remains substrate |
| 2026-08-21 | Operator approve-for-impl: +provenance chain · +capital_regret_20d · +same-state acceptance test; ICR.0 implementation starts |
| 2026-08-21 | **ICR.0 shipped** — `atlas/investment/incumbent_capital.py` + paper_trading gates; `tests/test_icr0_incumbent_capital.py` |
| 2026-08-21 | **ICR.1 shipped** — ACP build/persist/provenance; evening + Market UI one-liner; never auto-ADD |
| 2026-08-21 | **ICR.2 shipped** — `incumbent_review.py` ladder; quarantine clock; EXIT_TO_CASH / SWITCH_TO execute in paper_trading; not AVOID=instant sell |
| 2026-08-21 | **ICR.3 shipped** — `allocation_regret.py` opportunity-cost objects; `capital_regret_20d`; schedule on ACP; drain in decision_evolution; evening KPI |
| 2026-08-21 | **ICR.4 shipped** — E[R] symmetry on ACP legs; `advantage_unclear`; PLC.A-blocked challengers visible; same-state day registry |
| 2026-08-21 | **ICR.5 shipped** — `incumbent_scientist.py` deterministic + optional LLM notes; advice-only; evening/UI; never orders |
