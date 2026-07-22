# Media Report Honesty — Amendment (Job / `media.learn`)

> **Status:** RH.5–RH.8 DONE · **Date:** 2026-07-22  
> **Trigger:** Version-3 live run — runtime correctly does `media.learn` → strategy chain →
> interactive recovery, but the **final Job report** still shows empty Research boilerplate.  
> **Parent:** [`MEDIA_REPORT_HONESTY_PLAN.md`](MEDIA_REPORT_HONESTY_PLAN.md) (RH.1–RH.4 done for
> **Research** acquire-stop only).

---

## 1. Verdict

Runtime ≈ architecture. **Job report does not.** Root cause: `JobService._finalize`
calls ReportGenerator **without** `termination`; blocked-step answers are dropped;
UI prefers the fake report.

**Sequence (locked, all required for media.learn completeness):**

```
RH.5–RH.8  →  MO.5  →  BA.1 Browser v1  →  MO.3 Research
```

Browser is **required** in [`MEDIA_ORCHESTRATION_PLAN.md`](MEDIA_ORCHESTRATION_PLAN.md) — not reordered ahead of honesty, and not deferred as optional.

---

## 2. Frozen decisions (RH6–RH10)

| # | Decision |
|---|----------|
| **RH6** | Job finalize detects acquire / interactive recovery from step extras and passes **`termination`** into ReportGenerator. |
| **RH7** | Job `result.answer` includes blocked-step operator summaries (not only DONE). |
| **RH8** | **Result hierarchy** (not flat result enums): `stage` + `status` + `reason`. Example: `{ "stage": "acquire", "status": "blocked", "reason": "interactive_recovery_required" }`. Later reasons: `robots_disallowed`, `authentication_required`, `network_unavailable`, `operator_confirmation_required`, … |
| **RH9** | Job / domain-neutral reports use section title **Next Action** (not “Next Research”). Research-specific documents may still say “Next Research.” |
| **RH10** | Fourth acquire outcome family: **`waiting`** — distinct from hard **`blocked`**. Waiting = can continue when operator acts (e.g. upload). Blocked = strategy/policy must change (e.g. robots). Interactive upload recovery maps to **`status: waiting`**, `reason: interactive_recovery_required` (or `operator_upload_required`). |

### Termination payload shape (locked)

```json
{
  "stage": "acquire",
  "status": "waiting",
  "reason": "interactive_recovery_required",
  "knowledge_produced": 0,
  "reasoning": "not_started",
  "verification": "not_executed",
  "waiting_for": "media_asset",
  "suggested_next_strategies": ["upload_transcript", "upload_local_media", "..."],
  "speech_to_text_status": "missing"
}
```

Report confidence remains **`NOT_APPLICABLE`**. Methodology: acquire terminated; Verification not executed.

### Target operator copy

```
Result                 Waiting (acquire)
Reason                 interactive_recovery_required
Stage                  Acquire
Knowledge Produced     0
Reasoning              Not started
Verification           Not executed
Confidence             NOT_APPLICABLE
Waiting For            Media Asset / transcript upload

Methodology
  Pipeline terminated during acquisition (waiting for operator).
  Verification was not executed.

Next Action
  Waiting for operator.

  Continue after one of:
  • transcript upload …
  • media upload …
  …
```

### Explicit non-goals

- Redesigning Media Readers  
- Browser acquisition (separate plan)  
- Making every reason a top-level `overall_confidence` enum value  

---

## 3. Implementation slices

| Slice | Scope |
|-------|--------|
| **RH.5** | JobService: build termination from blocked/`media.learn` extras; pass to ReportGenerator; map interactive recovery → `status=waiting` |
| **RH.6** | Include blocked answers in job `answer`; report answer/exec ≠ “no verifiable claims” alone |
| **RH.7** | ReportGenerator: honor `termination.status` waiting vs blocked; Job markdown section **Next Action** |
| **RH.8** | Hermetic Job-shaped gate test |

---

## 4. Checklist

- [x] Freeze RH6–RH10  
- [x] **RH.5** Job termination wiring  
- [x] **RH.6** Blocked answers in job result  
- [x] **RH.7** Waiting vs blocked + Next Action  
- [x] **RH.8** Hermetic gate (`tests/test_job_report_honesty.py`)  

---

> Browser: [`MEDIA_BROWSER_ACQUISITION_PLAN.md`](MEDIA_BROWSER_ACQUISITION_PLAN.md).  
> Journal clarity: MO.5 in [`MEDIA_ORCHESTRATION_PLAN.md`](MEDIA_ORCHESTRATION_PLAN.md).
