# Media / Research Report Honesty — Operator Actionability Plan

> **Status:** frozen for implementation · **Date:** 2026-07-22  
> **Trigger:** Live YouTube research run that correctly **blocked at Acquire** (`robots_disallowed`),
> produced **0 documents**, and suggested `speech_to_text` — architecture scored excellent (P15),
> but report copy still spoke as if Verification / Evidence Budget had run, and “Next Research”
> said *No further research required*.  
> **Method:** Document first (this plan), then land as small hermetic slices with tests.  
> **Does not reopen** Media Reader Family MD1–MD9 / M.1–M.7 (complete). This is report +
> acquisition-operator UX on top of that spine.

---

## 1. What the live run proved (keep)

| Observation | Verdict |
|-------------|---------|
| Pipeline stopped at Acquire; Reader/Extract/Candidate/Knowledge never ran | Correct |
| `Acquisition failed before read` + `robots_disallowed` + strategies tried | Correct (P15) |
| 0 fabricated documents / ~0 B text | Correct |
| Suggested `speech_to_text` | Directionally right (capability gap) |

**Do not change** acquire-stop semantics, robots honesty, or “no fabricate” behavior.

---

## 2. Problems to fix (operator report UX)

| # | Current (wrong for acquire-stop) | Target |
|---|----------------------------------|--------|
| **R1** | Next Research: *“No further research required”* | **Research blocked** + actionable continue-after list |
| **R2** | Confidence: **INSUFFICIENT** (sounds like thin evidence) | **Acquisition failed** / confidence **NOT_APPLICABLE**; reasoning not attempted |
| **R3** | Methodology still describes Verification Engine / Evidence Budget / Convergence | **Pipeline terminated during acquisition. Verification was not executed.** |
| **R4** | `suggested_next_capability: speech_to_text` only | **`suggested_next_strategies`** — operator actions (upload transcript / upload media / enable STT / official API) |
| **R5** | Gap treats “missing” and “disabled” the same | Surface **`speech_to_text` status:** `ready` \| `disabled` \| `missing` |

---

## 3. Locked decisions (RH*)

| # | Decision |
|---|----------|
| **RH1** | Acquisition failure is a **first-class report termination mode**, distinct from evidence insufficiency. |
| **RH2** | When `read == 0` and every media/video path stopped at acquire (blocked/skipped with acquisition records, or equivalent empty-doc acquire-stop), treat the run as **acquire-terminated**. |
| **RH3** | Operator-facing “next” language prefers **strategies (actions)** over raw capability ids; capability id remains in structured payload for machines. |
| **RH4** | Capability Registry / SpeechClient already know enabled vs available — report must expose that distinction when suggesting STT. |
| **RH5** | No Knowledge fabrication; no change to FetchClient robots policy; no YouTube Knowledge branches. |

---

## 4. Target report shape (acquire-terminated)

```
Result                 Acquisition Failed
Reason                 robots_disallowed   (or other reason_code)
Knowledge Produced     0
Reasoning              Not attempted
Verification           Not executed
Confidence             NOT_APPLICABLE

Methodology
  Pipeline terminated during acquisition.
  Verification was not executed.
  No Evidence Budget or convergence assessment was performed
  because no documents were read.

Next Research
  Research blocked.

  Continue after one of:
  • transcript available (upload .vtt / .srt / .txt)
  • local media uploaded (.mp4 / .mp3 / …)
  • speech_to_text enabled and ready (Whisper)
  • official captions API configured (when available)

  speech_to_text status: disabled | missing | ready
```

Structured fields (API / JSON report) should mirror this so UI and markdown stay aligned.

---

## 5. Implementation slices

### RH.1 — AcquisitionRecord: operator strategies + capability status hint
- Add `suggested_next_strategies: tuple[str, …]` (stable strings).
- Keep `suggested_next_capability` for back-compat; `operator_summary` prefers strategies list.
- Helper `default_media_recovery_strategies(*, speech_status)` → ordered actions.
- Helper `speech_to_text_status(enabled, available) → ready|disabled|missing`.
- YouTube / chain failure paths populate strategies (not only capability id).
- **Acceptance:** robots-blocked acquisition dict includes strategies; summary no longer only says “Suggested next capability: speech_to_text”.

### RH.2 — ReportGenerator: acquire-termination mode
- `generate(..., termination: dict | None = None)`.
- When `termination.stage == "acquire"` (and no verified body):
  - `overall_confidence = NOT_APPLICABLE` (new constant alongside INSUFFICIENT).
  - `sections.confidence` includes `result`, `reason_code`, `knowledge_produced`, `reasoning`, `verification`.
  - `methodology` = acquire-stop copy (not Verification Engine boilerplate).
  - `next_research` = Research blocked + continue-after list (+ optional capability status line).
  - `answer` / executive summary acknowledge acquire-stop, not “no verifiable claims” alone.
- Markdown Confidence + Methodology + Next Research sections render the richer shape.
- **Acceptance:** hermetic test with empty claims + acquire termination ⇒ NOT_APPLICABLE, no “No further research required”, methodology mentions verification not executed.

### RH.3 — ResearchService: detect acquire-stop and pass `termination`
- After pipeline assembly, if no documents read (`pipeline["read"] == 0`, `chars_read == 0`) and blocked/skipped carry acquisition failures (or all video sources failed at acquire):
  - Build `termination` from the dominant acquisition record(s).
  - Attach speech status from config / speech client if available.
  - Pass into ReportGenerator.
- Job result `stopped.reasons` should mention acquisition failure when applicable (not “budget satisfied”).
- **Acceptance:** research-shaped fixture with one robots-blocked YouTube source ⇒ report sections match RH.2.

### RH.4 — Tests + docs checkbox
- Unit tests: AcquisitionRecord strategies; ReportGenerator termination; ResearchService wiring (hermetic fakes).
- Update `OPEN_ITEMS.md` with `OI-RH0` (this plan) → closed when RH.1–RH.3 land; optional deferrals stay separate.
- Mark this plan complete in footer.

---

## 6. Out of scope (explicit)

- Implementing official YouTube Data API captions (**OI-M1**) — only mention as a *strategy string* when relevant.
- Enabling Whisper by default (**MD5** stays: default off).
- Changing robots bypass or adding silent YouTube media scrape.
- Full UI redesign (JSON + markdown honesty is enough; Missions UI can consume fields later).

---

## 7. Checklist

- [x] **RH.1** AcquisitionRecord strategies + speech status helper
- [x] **RH.2** ReportGenerator acquire-termination mode
- [x] **RH.3** ResearchService termination wiring
- [x] **RH.4** Tests + OPEN_ITEMS / plan complete

---

> **RH.1–RH.4 ✅ DONE** (2026-07-22). Acquire-stop reports now use `NOT_APPLICABLE`
> confidence, honest methodology (verification not executed), **Research blocked** +
> operator strategies, and `speech_to_text` status `ready|disabled|missing`. Hermetic
> tests: `tests/test_media_report_honesty.py`.
>
> **Amendment (2026-07-22):** Job/`media.learn` path still renders empty Verification
> reports — see [`MEDIA_REPORT_HONESTY_AMENDMENT.md`](MEDIA_REPORT_HONESTY_AMENDMENT.md)
> (RH.5+). Research path honesty does not automatically cover Job finalize.
>
> **Frozen decisions RH1–RH5 must not be reopened without a plan amendment.**
