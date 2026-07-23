# Media Learning Report — LR1–LR8

> **Status:** LR1–LR8 DONE · **Date:** 2026-07-22  
> **Trigger:** media.learn runtime succeeds (AL1–AL5) but Job report still uses
> Research verification template → INSUFFICIENT / “no verifiable claims”.  
> **Parent:** [`MEDIA_ASSET_LIFECYCLE_PLAN.md`](MEDIA_ASSET_LIFECYCLE_PLAN.md)

---

## Frozen decisions

| # | Decision |
|---|----------|
| **LR1** | Separate **Learning Report** from **Research Report**; select by `media.learn` extras / `stages`, not empty claims |
| **LR2** | Metadata-only Knowledge is a valid completed learning job |
| **LR3** | Learning Status (e.g. PARTIAL) + stage table — not Verification Confidence / INSUFFICIENT |
| **LR4** | Executive Summary describes Asset + metadata Knowledge + pending speech/transcript |
| **LR5** | Observations = metadata facts (URL, title, asset_id, …) — not “verified claims” |
| **LR6** | Methodology = acquire → readers → Knowledge; omit Verification / Evidence Budget / Convergence |
| **LR7** | Next Action = pending capabilities (Whisper / upload transcript) — not “no further research” |
| **LR8** | Acquire-wait honesty (RH*) unchanged for blocked/waiting acquire |
| **LS1** | Learning Status opens with capability summary table (Metadata / Transcript / Speech / Knowledge) — not PARTIAL alone |
| **OC1** | Official captions journal uses precise reason codes: `not_configured`, `authentication_failed`, `quota_exceeded`, `api_error` (+ existing oauth / no_captions) |

### Explicit non-goals

- Acquisition / Media Reader pipeline changes  
- Research Report redesign  
- AL6 Reader Eligibility  

---

## Selection

```
Job finalize
  ├─ blocked media.learn + interactive → acquire termination (RH*)  [keep]
  ├─ DONE media.learn with stages/acquisition → learning termination (LR*)
  └─ else → Research Report
```

---

## Checklist

- [x] Plan freeze  
- [x] ReportGenerator `mode=learning`  
- [x] JobService learning payload from done steps  
- [x] Hermetic tests (`tests/test_learning_report.py`)  
- [x] OPEN_ITEMS  
- [x] LS1 Learning Status capability summary  
- [x] OC1 Official captions reason codes  
