# Atlas — TRADE-LOOP0: NSE vertical slice + weekend proof

> **Status:** 🔒 **LOCKED** — N1 HBLPOWER candidate replay **PASS + golden fixture 2026-09-19**. Remaining P0 = other names + NSE edge cases. Do not re-engineer HBLPOWER unless the golden test regresses.  
> **Date:** 2026-09-18 (Friday night, revised ×3; operator: start)  
> **Parent:** [`ATLAS_OPERATIONAL_TRADING_LOOP_AND_FNO_UNIVERSE_DISCUSSION.md`](ATLAS_OPERATIONAL_TRADING_LOOP_AND_FNO_UNIVERSE_DISCUSSION.md)  
> **FI:** [`ATLAS_FUNDAMENTAL_INTELLIGENCE_PLAN.md`](ATLAS_FUNDAMENTAL_INTELLIGENCE_PLAN.md)  
> **FEA:** [`ATLAS_FUNDAMENTAL_EVIDENCE_ACQUISITION_PLAN.md`](ATLAS_FUNDAMENTAL_EVIDENCE_ACQUISITION_PLAN.md)  
> **Does not reopen:** PLC.A / WATCH / MoS · live orders · LLM→trade · RL · Screener HTML · universe-scale XBRL · a second FEA product

**Locked.** Implementation starts from the **existing** HBLPOWER UQ/FEA entry point — connect, do not rebuild. Do **not** ship an isolated NSE parser.

**Coverage mandate:** Atlas must attempt **every** PLC.A-required and swing-completeness fundamental/identity field for the test candidate (PE, ROE, D/E, FCF, sector, identity). A pass on PE/ROE/D/E/FCF with sector/identity still missing is **not** N1. Mos remains IRA-computed (not NSE). Thesis remains research (not NSE).

**Correction (operator 2026-09-18 evening):** postponing NSE/XBRL until after A–F live stamp was **too conservative**.

**Correction (operator 2026-09-18 later):** “NSE connected / XML parsed” is **not** the north star. The risk is saying NSE works while **financial correctness and as-of correctness** fail. Sector/identity, TTM EPS, average equity, D/E mapping, filing selection, `available_at`, bad-evidence rejection, and 18-Sep **candidate replay** are P0 acceptance — not polish.

---

## 0. Weekend objective

Not: *Did we implement Slices A–F?*  
Not: *Can Atlas parse an NSE XML?*

**Yes:**

> Can Atlas acquire the **right** financial evidence, at the **right point in time**, interpret it correctly, calculate the metrics deterministically, preserve exactly where they came from, complete **every PLC.A-required field** for the test candidate (including sector/identity via their own evidence paths), and feed the result back into the existing PLC.A decision path?

Hourly mail must show that difference **tomorrow**.

```text
REAL / REPLAYED TECHNICAL BUY
             ↓
      PLC.A incomplete
             ↓
        UQ material
             ↓
      FEA creates task
             ↓
     NSE filing selection          ← deterministic policy (§4)
             ↓
       raw XBRL stored
       hash + provenance
             ↓
      XBRL context parsing
             ↓
       canonical facts
             ↓
   period/scope/unit validation
             ↓
 ┌───────────┼────────────┐
 ↓           ↓            ↓
EPS         ROE          D/E
(TTM/FY)    avg equity   definition_id
 ↓           ↓            ↓
PE (Zerodha LTP / EPS)
             ↓
       FCF = CFO − CapEx
       (CapEx normalized once)
             ↓
     sector / identity            ← own sources, not forced into XBRL
             ↓
     cross-check / reference
             ↓
 VALID / CONFLICT / UNKNOWN
             ↓
     fundamentals store
             ↓
     IRA / completeness
             ↓
       PLC.A reread
             ↓
 ┌───────────┼──────────────┐
 ↓           ↓              ↓
COMPLETE   CONFLICT      STILL INCOMPLETE
 ↓           ↓              ↓
PLC.A      explicit       explicit
decision   diagnosis      UQ / wait
```

A provider failure is allowed **if explicit**. Silent UQ disappearance is not. HOLD after complete evidence is success. UNKNOWN ≠ 0. Negative FCF stays negative. Parse failure → RETRY / UNKNOWN, **never 0**.

Future filings must not leak into earlier decisions (`available_at` / `evidence_as_of`).

---

## 1. Where we are

| Area | Now | Tonight / weekend |
|------|-----|-------------------|
| SMA / PLC.A / Step 11 RAG | 🟢 Recall+provenance LIVE (PID 288870). Step 5: RAG cannot yet explain PLC.A (honest don't-know). | Keep; do not loosen PLC.A. Do not retune RAG ranking. Do not dump XBRL into vectors. |
| A–F plumbing | 🟡 In tree | Keep; not the north star |
| Yahoo-only FEA | 🔴 0 live acquires; 429 storm | Yahoo becomes **secondary** |
| NSE/XBRL | 🔵 Was “later” | **P0 vertical slice + correctness** |
| Canonical calc engine | 🔵 Design | **Minimum** + TTM/FY, avg equity, D/E map, CapEx normalize, `available_at` |
| Hourly mail | Weak “worker ticked” | **Must show FI + per-symbol missing/reason** |
| F&O 4-index | 🟡 Code in tree; live store still NIFTY-only | **P1** — do not steal fundamentals |
| FI universe / taxonomies at scale | 🔵 Later | N1 then N2/N3; N4–N6 stretch |
| RL / LLM trade | 🔒 | Unchanged |

---

## 2. Vertical slice — not the giant NSE system

**Do not** build full FI Stages 2–7 (Postgres fact warehouse, all taxonomies, auto-refresh of the universe) tonight.

**Do** prove **one real gap name** with **financial + as-of correctness**, then the named weekend targets.

### 2.1 Company bar (measurable — no more 1–3 vs 3–5 mix)

| ID | Name | Bar |
|----|------|-----|
| **N1** | **HBLPOWER** | **Friday/Saturday minimum. Must work.** Industrial; 18-Sep PLC.A hole: PE, ROE, D/E, **sector**. |
| **N2** | COALINDIA | Weekend target. Same path. Partial store already. |
| **N3** | TATACHEM | Weekend target. Persistent UQ (pe/roe/fcf/mos/identity). |
| **N4** | One BANKNIFTY constituent | Stretch — bank taxonomy. Not required for P0. |
| **N5** | One NBFC | Stretch — NBFC taxonomy. |
| **N6** | One insurer | Stretch — insurance taxonomy. |

N4–N6 exist to catch “parser tuned to one XML.” They are **not** required to call the fundamental P0 weekend a pass. **N1 is the gate. N2+N3 are the target. N4–N6 are stretch.**

### 2.2 HBLPOWER path (must include *every* PLC.A-required field)

18-Sep packet: `pe, roe, debt_to_equity, sector`. Completeness also requires **identity**.

```text
HBLPOWER
  → filing_selection_policy (§4)
  → store raw XBRL/XML (hash + path)
  → parse facts (revenue, PAT, equity begin+end, debt components, CFO, CapEx, shares)
  → calculate ROE, D/E, FCF, EPS, PE (Zerodha LTP, TTM EPS)
  → resolve sector + identity via their own evidence paths (§3.1)
  → compare to one independent reference (Yahoo and/or Screener export)
  → PLC.A reread
```

**Acceptance fail if** PE/ROE/D/E/FCF are VALID and PLC.A is still `INCOMPLETE` because `sector_missing` / `identity_unknown` was never tasked. That would make the weekend ambiguous.

NSE currently exposes: XBRL Filing Information (ordinary, bank, NBFC, life/general insurance, REIT/InvIT taxonomies); financial-results with XBRL / CSV / XBRL-to-Excel; **Integrated Filing – Financials** (results for quarter ending March 2025 onward) with symbol, company, quarter-end, submission type, audited/unaudited, consolidated/standalone, XBRL, broadcast time, revision. Use those as **structured evidence + provenance**. Confirm the exact machine-readable URL/file in implementation — do not assume every “download” button is an unrestricted API. **No HTML scrape of Screener. No invented facts.**

### 2.3 Slice C changes

Old C: `debt_missing` → UQ → FEA → fake Yahoo → store → PLC.A.

**New C:** `debt_missing` → UQ → FEA → **NSE/XBRL provider** → raw → parse → canonical debt **components** → **calculate D/E** (`definition_id`) → store + provenance → PLC.A.

Hermetic tests use a **checked-in NSE XBRL fixture** (not a live NSE call in CI). Live NSE is the weekend stamp. Negative fixtures (§8) are P0 tests, not optional.

### 2.4 TRADE-LOOP0 candidate replay (P0)

The north star says **real technical BUY**. The weekend may run when HBLPOWER is not emitting a new SMA BUY (market closed, no signal).

**Do not** invent a fake trade or a synthetic strategy result.

```text
18-Sep HBLPOWER BUY packet
        ↓
replay candidate   (TRADE-LOOP0 candidate replay)
        ↓
PLC.A incomplete
        ↓
UQ
        ↓
NSE acquisition
        ↓
calculations + sector/identity
        ↓
PLC.A reread
```

Replay is a **candidate**, not a paper fill. Persist before/after PLC.A status on disk so the hourly mail can show `PLC.A re-evaluated`.

**2026-09-19: N1 PASS.** HBLPOWER is the **golden end-to-end replay fixture**. Do not re-engineer this symbol unless `tests/test_hblpower_golden_replay.py` regresses. Do not turn the replay into a paper fill, reward, or learning experience.

---

## 3. Provider roles and PLC.A field ownership

| Source | Role |
|--------|------|
| **NSE XBRL / Integrated Filing** | Primary **raw** financial evidence (statements) |
| **Yahoo** | Secondary / cross-check; Slice A gate still required |
| **Screener export** | Bootstrap / reference (Slice G still operator import) |
| **Zerodha** | Price, volume, **instrument identity token** — **never** PE/FCF/sector-as-a-ratio |
| **Company profile / awareness / research pack** | **Sector** and **legal identity** — not XBRL P&L facts |
| **Atlas** | Canonical facts + **calculations** + conflict records + as-of |

Disagreement → `fundamental_conflict` with `conflict_type` (§6). **Do not silent-overwrite.**

FEA becomes provider-agnostic:

```text
FEA
 ├── NSE_XBRLProvider          (preferred for statements)
 ├── YahooProvider             (fallback / cross-check)
 ├── ScreenerImportProvider    (operator)
 └── Identity/SectorProvider   (profile / awareness — not XBRL)
```

### 3.1 Sector / identity (do not force into XBRL)

These are PLC.A completeness fields. They are **not** financial-statement facts.

| Field | Allowed sources (examples) | Never |
|-------|----------------------------|--------|
| **sector** | Company profile, awareness/research pack, operator Screener row `sector`, NSE company metadata if machine-readable | Invent from ticker; treat as an XBRL PAT concept |
| **identity** | Existing identity pack / company profile (name, legal name, ISIN, token) | Yahoo PE fetch; LLM guess |

UQ must emit `sector_missing` / `identity_unknown` for the replay candidate the same way it emits `pe_missing`. Close identity when AVAILABLE (already L5). **Acquire sector** via the identity/profile path, with provenance (`source`, `retrieved_at`). If sector cannot be obtained, PLC.A stays incomplete **with that reason visible** — not a silent pass on PE/ROE/D/E/FCF alone.

HBLPOWER must end the weekend with an explicit status on **PE, ROE, D/E, FCF, sector, identity**.

---

## 4. Filing selection / revision policy (deterministic)

“Latest relevant NSE result” is not a policy. Two runs must choose the same canonical filing.

```text
filing_selection_policy
1. Identify company by symbol + identity (ISIN when present)
2. Select required scope          (default: CONSOLIDATED; else STANDALONE if that is all that exists — labeled)
3. Select required period         (period_end matching the metric clock; TTM uses four quarters)
4. Prefer latest valid revision   (revision metadata / broadcast time)
5. Prefer final/audited where policy requires the annual number
6. Reject superseded filing       (keep it in raw/; do not use it as canonical)
7. Preserve all source filings    (raw store is append-only)
8. Mark which filing is canonical (canonical_filing_id on the fact set)
```

Unaudited quarterly results are allowed for TTM **when labeled**. Mixing standalone equity with consolidated PAT is a **SCOPE** conflict, not a number.

Integrated Filing – Financials (qe Mar 2025+) vs older XBRL Filing Information: prefer the series that actually contains the required period; record `filing_interface` on the raw blob.

---

## 5. Canonical fact + as-of (leak protection)

Minimum on-disk structures (files first, not a new DB product):

Every fact:

```text
symbol
canonical_field
value
unit
scale
period_start
period_end
period_type          FY | Q | TTM
scope                CONSOLIDATED | STANDALONE
source
source_document
filed_at
available_at         ← ADD  (when the market could have known this)
retrieved_at
raw_evidence_id
mapping_id
```

PLC.A / replay decision:

```text
decision_at
evidence_as_of       (no fact with available_at > evidence_as_of)
price_as_of          (Zerodha LTP clock)
fundamental_as_of    (same as evidence_as_of for books)
source_available_at  (per input fact)
```

**Hard rule:** a result for period 31-Mar-2026 filed/available 15-May-2026 **must not** influence a 10-Apr-2026 decision or a 18-Sep replay whose `evidence_as_of` is before that `available_at`. If `available_at` is unknown, do not invent it — mark `available_at_unknown` and **do not** use the fact for a decision whose `evidence_as_of` cannot be proven ≥ availability. Prefer `broadcast_time` / exchange timestamp as `available_at` when present.

Also store: `raw/` original filing; `calculation` (formula, inputs, `value_type=derived|reported`); `canonical_filing_id`.

---

## 6. Calculations (hard tests, not design notes)

UNKNOWN stays UNKNOWN. No NULL→0. No LLM fill.

### 6.1 EPS / PE — TTM preferred; never silent quarterly-as-annual

| Metric | Policy |
|--------|--------|
| EPS | **TTM preferred** = Q1+Q2+Q3+Q4 PAT (same scope; restatements: use latest revision per quarter; discontinued/extraordinary: follow filing labels, do not silently drop). Diluted shares when present, else basic **labeled**. |
| EPS FY fallback | **Only** when TTM cannot be formed **and** policy flag `eps_fy_fallback=true` is explicit on the calculation row. |
| PE | `Zerodha LTP / chosen EPS`. Record `eps_basis=TTM\|FY\|UNKNOWN`. Price clock ≠ filing clock. |

**P0 fail:** PE computed from a **single quarterly PAT** treated as annual EPS without `eps_basis` and without failing validation.

### 6.2 ROE — average equity requires two snapshots

Stated formula: `net income / average equity`. One “latest filing” is **not** enough for the denominator.

```text
average_equity = (beginning_equity + ending_equity) / 2
```

Same **scope**, same **period basis** as the numerator.

Acceptance row must record: numerator period, beginning equity (period + source), ending equity, formula, scope. If beginning equity is missing → ROE = UNKNOWN, not ending-equity-only disguised as average.

### 6.3 D/E — mapping policy, not “whatever looks like debt”

```text
definition_id = atlas.debt.total_borrowings.v1
TOTAL_DEBT = short-term borrowings + long-term borrowings
             + current maturities of long-term debt
```

**Excluded unless a later definition_id says otherwise:** lease liabilities, trade payables, other financial liabilities, total liabilities, bank deposits (bank taxonomy — N4, not HBLPOWER).

**P0 test:** `TOTAL_LIABILITIES ≠ TOTAL_DEBT` unless the company’s taxonomy actually defines them equal. Accidental use of total liabilities as debt is a **fail**, even if PLC.A would get a number.

Store: `definition_id`, component mapping, excluded liabilities.

### 6.4 FCF — CapEx normalized once, then one formula

Lock this (Yahoo `CFO + CapEx` when CapEx is reported negative is **equivalent**, not a second formula):

```text
reported CapEx sign
        ↓
normalize_capex()
        ↓
CAPEX = positive economic outflow
        ↓
FCF = CFO − CAPEX
```

Provenance keeps the **original reported value** and `normalization=NEGATIVE_OUTFLOW_TO_POSITIVE` (or `ALREADY_POSITIVE` / `UNKNOWN` → do not invent).

Example: reported CapEx = −3713.9 → canonical CAPEX = +3713.9; FCF = 3204.28 − 3713.9 = **−509.62**. Negative stays negative.

Missing CFO or missing CapEx → FCF UNKNOWN, not 0.

### 6.5 Debug card (disk; hourly summarizes)

```text
HBLPOWER FUNDAMENTAL EVIDENCE
PE   value …  price=Zerodha  EPS=NSE  eps_basis=TTM|FY  calc=price/EPS  VALID|UNKNOWN|CONFLICT
ROE  PAT / avg(begin,end equity)  source=NSE  VALID|…
D/E  definition_id=…  debt≠liabilities  source=NSE  VALID|…
FCF  CFO−CAPEX  capex_norm=…  derived  VALID|…  (negatives kept)
sector    source=profile|screener|…  VALID|MISSING
identity  source=…  VALID|MISSING
filing    canonical_id=…  period=…  scope=…  available_at=…
PLC.A: previously INCOMPLETE  now COMPLETE|INCOMPLETE|HOLD|AVOID
```

---

## 7. Cross-check acceptance (not “looks close”)

Disagreement → `fundamental_conflict`, never silent overwrite.

`conflict_type` (required on the record):

| Type | Example |
|------|---------|
| `PERIOD` | FY vs TTM vs one quarter |
| `SCOPE` | consolidated vs standalone |
| `UNIT` | crore vs absolute; scale |
| `DEBT_DEFINITION` | gross borrowings vs net debt vs total liabilities |
| `EPS_BASIS` | quarterly-as-annual vs TTM |
| `SOURCE_STALENESS` | Screener 3 Sep vs NSE May filing |
| `CALCULATION` | average vs ending equity |
| `UNKNOWN` | last resort; still a conflict, not a pick |

Tolerance (implementation may refine, must be explicit): ratios within **0.5 pp** or **2% relative**, whichever policy documents, **and** same period/scope/definition → `VALIDATED`. Atlas D/E 0.41 vs Yahoo 0.58 → **CONFLICT** with a typed hypothesis, not a blended 0.50.

HBLPOWER live stamp must produce either VALIDATED vs a reference **or** a typed conflict — not a silent ignore.

---

## 8. Negative tests (P0 — “NSE returned data, Atlas must reject it”)

Success-oriented tests are not enough. Fixtures (hermetic) must include:

| Bad evidence | Expected |
|--------------|----------|
| Wrong unit / scale | NOT VALIDATED → RETRY / UNKNOWN |
| Wrong period / future `available_at` vs `evidence_as_of` | excluded from that decision |
| Standalone vs consolidated mismatch | SCOPE conflict |
| Missing context / malformed XBRL | RETRY, not 0 |
| Duplicate fact | reject or explicit prefer-revision |
| Negative shares / zero equity | UNKNOWN (ROE/D/E not 0) |
| CFO missing / CapEx missing / PAT missing | FCF or EPS UNKNOWN |
| Total liabilities mapped as TOTAL_DEBT | fail mapping test |

**Never:** parse failure → 0. PLC.A remains appropriately blocked.

---

## 9. Priority (after lock)

| Pri | Item |
|-----|------|
| 🔴 P0 | NSE/XBRL HBLPOWER (N1) + candidate replay |
| 🔴 P0 | FEA → NSE provider + UQ PE/ROE/D/E/FCF |
| 🔴 P0 | Sector/identity completion (own path) |
| 🔴 P0 | TTM/FY EPS policy on PE |
| 🔴 P0 | ROE average-equity inputs |
| 🔴 P0 | D/E component definition + liabilities≠debt |
| 🔴 P0 | Filing selection / revision policy |
| 🔴 P0 | `available_at` / as-of protection |
| 🔴 P0 | Bad-XBRL / wrong-period negative tests |
| 🔴 P0 | PLC.A before/after replay |
| 🔴 P0 | Hourly FI block + **per-symbol missing/reason** |
| 🟡 P1 | Yahoo exclusive gate |
| 🟡 P1 | F&O four-index **live stamp** (code already in tree) |
| 🟢 Later | N4–N6 taxonomies, universe crawl |
| 🔒 | RL / LLM trading / PLC.A loosen |

---

## 10. Plumbing tests still required (A–F / T1–T11)

Keep recovery-not-only-deny, UQ idempotency, UNKNOWN≠0, pipeline reconcile, F&O family+isolation, restart of JSON. They are **necessary but not sufficient**.

**T4 revised:** gold chain uses **checked-in NSE XBRL fixture** for HBLPOWER through calc → store → PLC.A, plus **negative fixtures** (§8). Fake Yahoo is fallback, not the only gold.

**T11 revised:** live or replay HBLPOWER: NSE acquire **or** explicit `nse_unavailable` / parse error — never UQ=none. PLC.A field list includes sector/identity.

---

## 11. Hourly / evening mail — must show tomorrow’s delta

Do **not** invent a new mailer. Extend the existing hourly + evening digests.

**Exact extension points (after lock):**

| Digest | Function / file | Where the FI block goes |
|--------|-----------------|-------------------------|
| Hourly (08–20 IST) | `format_hourly_activity_report` in `atlas/investment/reports.py` | Immediately after the three-lab books section, **before** “Activity this hour” |
| Evening | `format_evening_report` in `reports.py` + `evening_learning_header.py` | Same FI block above the fold (with pipeline partition) |
| Sender | `InvestorReportsWorker.send_hourly` / evening send | Unchanged schedule; body grows |

Today’s hourly mail has **no** FUNDAMENTAL INTELLIGENCE section. That absence is the Friday baseline. Saturday’s first hourly must contain the block below even if all NSE counts are 0 — zeros with names are honest; missing section is a fail.

```text
━━━━━━━━ FUNDAMENTAL INTELLIGENCE ━━━━━━━━
Technical BUYs:          N
PLC.A incomplete:        N
UQ pending (pe/roe/d/e/fcf/sector/identity): N
FEA acquired this window: N
NSE XBRL success:        N
NSE parse failures:      N
Calculation failures:    N
Evidence conflicts:      N
PLC.A re-evaluated:      N
Still blocked:           N

Coverage (material names only)
  PE ROE D/E FCF sector identity   n/m each

Yahoo fundamentals: cooldown Y/N  consecutive_429  last_success
F&O resolved: NIFTY/BANK/FIN/MID  (ok/fail)

HBLPOWER
  PE  ✓/✗   ROE ✓/✗   D/E ✓/✗   FCF ✓/✗   sector ✓/✗   identity ✓/✗
  provider=nse_xbrl|yahoo|none   PLC.A=…
  missing: …
  UQ: pending|done|none
  FEA: …
  reason: …

YESBANK
  missing: sector, D/E
  UQ: pending
  FEA: waiting
  provider: NSE
  reason: …
(up to 8 material incompletes — actionable, not “Still blocked: 3”)
```

**Tomorrow you should be able to see** (vs 18 Sep “FEA worker ticked, 0 acquire, TATACHEM-only UQ”):

- SMA incompletes **listed with missing fields + reason**, not missing  
- `NSE XBRL success` > 0 **or** explicit parse/unavailable counts  
- `PLC.A re-evaluated` increment when a row lands  
- Coverage fractions for material names, not a fake 100%  
- Yahoo 429 **not** climbing like 1524 if cooldown is honest  

Evening mail repeats the same block plus the pipeline partition (SMA / incomplete / complete / research / AVOID / fills).

---

## 12. LIVE STAMP

| Item | Unit | Live | Evidence |
|------|------|------|----------|
| A Yahoo gate | in tree | ☐ | |
| B UQ materiality | in tree | ☐ | |
| C D/E **via NSE calc** (not fake-only) | ☐ | ☐ | |
| D lifecycle | in tree | ☐ | |
| E pipeline + **hourly FI block** | ☐ | ☐ | Saturday hourly body |
| F 4-index F&O | in tree | ☐ | live store still NIFTY-only as of 18 Sep |
| **N1** HBLPOWER replay → NSE → calc → **all PLC.A fields** → reread | ✅ | ✅ | golden fixture + `/data/atlas_data/investment/trade_loop0/replay/HBLPOWER_2026-09-18_result.json` |
| **N2** COALINDIA same path | ☐ | ☐ | weekend target |
| **N3** TATACHEM same path | ☐ | ☐ | weekend target |
| **N3b** Hourly delta vs 18 Sep | ☐ | ☐ | first Saturday mail |

Weekend **success bar:** **N1 PASS 2026-09-19** (golden fixture). Remaining: hourly block with per-symbol reasons · N2/N3 · filing-selection/scope/period/revision edge cases. N4–N6 stretch.

---

## 13. What not to do

- Scrape Screener HTML or NSE result **HTML** as the engine  
- Universe-wide XBRL crawl Friday night  
- Treat Yahoo ratios as unquestioned truth  
- Loosen PLC.A  
- LLM-guessed PAT/debt/sector  
- New paid API  
- More RAG/RL  
- Skip hourly block “until NSE is perfect”  
- Call N1 a pass if PE/ROE/D/E/FCF are filled but **sector/identity** still incomplete  
- Use one quarter of PAT as annual EPS  
- Use ending equity as “average” without beginning equity  
- Map total liabilities as total debt  
- Let `available_at` > `evidence_as_of` leak into PLC.A  
- Fake a paper fill to satisfy “technical BUY”  
- Turn the HBLPOWER candidate replay into a learning experience / reward / paper fill  
- Re-engineer HBLPOWER unless `tests/test_hblpower_golden_replay.py` regresses  

---

## 14. Files (after lock — not this turn)

| Area | Likely |
|------|--------|
| NSE adapter + raw store | `atlas/investment/fundamentals/` evidence/providers (new, small) |
| Filing selection + as-of | same; `available_at` on facts |
| Calc | EPS TTM, PE, ROE avg equity, D/E map, FCF normalize |
| Sector/identity | profile / awareness path + UQ codes; not XBRL |
| FEA policy | NSE preferred for statements; Yahoo fallback |
| Replay | 18-Sep HBLPOWER packet → candidate, not fill |
| Hourly/evening | `format_hourly_activity_report` + `format_evening_report` |
| Tests | fixture XBRL + **negative** fixtures; UNKNOWN≠0; as-of leak; PLC.A reread; no cash in F&O |
| Bounce | one `bounce_atlas_stab0.sh` after tests |

---

## 15. Operator lock

| ID | Decision | Lock |
|----|----------|------|
| **L12** | Weekend = implement + bounce + unattended proof via hourly mail | **LOCKED 2026-09-18** |
| **L19** | **NSE/XBRL vertical slice is P0 now** (HBLPOWER first). Not postponed behind A–F stamp | **LOCKED** |
| **L20** | Giant FI (universe, all taxonomies, auto-refresh) **not** tonight — N1 then N2/N3 | **LOCKED** |
| **L21** | FEA provider-agnostic: NSE primary raw, Yahoo secondary, Screener import, Zerodha = price | **LOCKED** |
| **L22** | Slice C = real D/E from NSE facts + Atlas calc | **LOCKED** |
| **L23** | Hourly/evening **FUNDAMENTAL INTELLIGENCE** block + **per-symbol missing/reason** | **LOCKED** |
| **L24** | F&O Slice F remains P1; does not preempt P0 NSE | **LOCKED** |
| **L25** | No Screener scrape; no PLC.A loosen; no LLM fill; UNKNOWN ≠ 0 | **LOCKED** |
| **L26** | NSE slice must resolve **every PLC.A-required field** for the candidate, including **sector/identity** via their own evidence paths (not forced into XBRL) | **LOCKED** |
| **L27** | PE `eps_basis`: **TTM preferred**; FY fallback only when explicit; never silent quarterly-as-annual | **LOCKED** |
| **L28** | ROE requires beginning + ending equity, same scope, average formula recorded | **LOCKED** |
| **L29** | D/E `definition_id` + component map; total liabilities ≠ total debt unless taxonomy says so | **LOCKED** |
| **L30** | CapEx `normalize_capex()` then **FCF = CFO − CAPEX**; original sign preserved; one formula | **LOCKED** |
| **L31** | Every fact has `available_at` (or explicit unknown). PLC.A `decision_at` / `evidence_as_of`. No future-filing leak | **LOCKED** |
| **L32** | `filing_selection_policy` (§4) is deterministic; superseded filings kept but not canonical | **LOCKED** |
| **L33** | Cross-check uses typed `conflict_type`; HBLPOWER stamp is VALIDATED or typed CONFLICT | **LOCKED** |
| **L34** | Negative XBRL / wrong-period / missing CFO-CapEx tests are P0 | **LOCKED** |
| **L35** | **TRADE-LOOP0 candidate replay** of 18-Sep HBLPOWER BUY — not a fake fill | **LOCKED** |
| **L36** | Connect, don't rebuild: implement from existing UQ/FEA → NSE provider → existing store → existing PLC.A. No isolated NSE parser product. | **LOCKED** |
| **L37** | **All-fundamentals coverage:** attempt PE, ROE, D/E, FCF, sector, identity for the candidate in one chain. Do not stop after the first filled ratio. | **LOCKED** |
| **L38** | **HBLPOWER N1 is the golden end-to-end replay fixture.** Isolated BEFORE INCOMPLETE → AFTER COMPLETE, locked calculations/provenance/`not_a_fill`. Not a paper fill. Not a learning experience. Do not re-engineer this symbol unless the golden test regresses. Remaining NSE P0 = other names + edge cases. | **LOCKED 2026-09-19** |

Previous **L16** (NSE inspect-only) and **L17** (FI only after A–F stamp) remain **superseded**.

Comment: 2026-09-18 — implement P0 NSE slice with L26–L37 correctness + hourly block, then bounce.

---

## 16. Decision log

| Date | Decision | Notes |
|------|----------|-------|
| 2026-09-18 | File opened | A–F tests + weekend stamp; NSE inspect-only |
| 2026-09-18 | **NSE P0 vertical slice** | Do not spend the weekend on Yahoo-only plumbing. Hourly mail must show FI/NSE/PLC.A. |
| 2026-09-18 | **Correctness + as-of before §15 lock** | Sector/identity, TTM EPS, avg equity, D/E map, filing selection, `available_at`, negative tests, candidate replay. |
| 2026-09-18 | **§15 LOCKED — start** | Operator: P0 NSE vertical slice + L26–L37 + hourly block, then bounce. Connect UQ/FEA → NSE → store → PLC.A. Cover **all** PLC.A/completeness fundamentals for the candidate. |
| 2026-09-19 | **N1 HBLPOWER PASS + L38 LOCKED** | Isolated candidate replay INCOMPLETE→COMPLETE. Golden fixture in `tests/test_hblpower_golden_replay.py`. Remaining: N2/N3 + filing-selection/scope/period/revision/units/missing/conflicts/`available_at`. |

---

## 17. North star

> A real or **replayed** technical BUY missing PE/ROE/D/E/FCF/**sector**/**identity** becomes a UQ task; Atlas obtains the **right** exchange evidence **as of** the decision, calculates metrics with explicit formulas and provenance, rejects bad evidence instead of inventing zeros, and PLC.A re-evaluates. Tomorrow’s hourly email is how we see whether that happened — by **symbol and missing field**, not a single “still blocked” count.
