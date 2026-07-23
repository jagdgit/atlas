# Media Asset Lifecycle Honesty — AL1–AL5

> **Status:** AL1–AL5 DONE · AL6 deferred · **Date:** 2026-07-22  
> **Trigger:** Live run after BA.v2 — ~54 MB obtained, report said both
> “Acquisition succeeded” and “Waiting for Media Asset” / Knowledge 0.  
> **Parent:** [`MEDIA_ACQUISITION_CLOSURE_PLAN.md`](MEDIA_ACQUISITION_CLOSURE_PLAN.md)

---

## Frozen decisions

| # | Decision |
|---|----------|
| **AL1** | **Acquisition success = registered Asset (`asset_id`)**, not bytes downloaded / HTTP 200 / any strategy `ok`. |
| **AL2** | Downstream stages report **independently** (`acquire` / `metadata` / `transcript` / `speech` / `knowledge`). No generic `partial` flag. Asset without speech ⇒ Acquire=success, Metadata=success (when read), Transcript/Speech=waiting — **not** “Waiting for Media Asset”. |
| **AL3** | **Metadata → Knowledge without Whisper is valid.** Job must not block solely because `speech_to_text` is missing when metadata Knowledge was ingested. |
| **AL4** | Journal every stage with outcome, reason_code, and `asset_id` where applicable (`youtube_media` → `media_metadata` → `speech_to_text` → `knowledge`). |
| **AL5** | **Knowledge Produced** comes from actual ingest (MediaIngestor / `media.learn`), never hardcoded `0` on wait when ingest ran. |
| **AL6** | Reader Eligibility block — **later** (diagnostic). |
| **AL7** | Explicit **Asset vs Derived Artifact** distinction in stage payloads (Asset → metadata/transcript artifacts → Knowledge). |

### Explicit non-goals

- Redesign Media Reader Family / report-honesty spine  
- Make Whisper mandatory  
- Robots bypass  

---

## Target shapes

### Stages (AL2)

```json
{
  "acquire": "success",
  "metadata": "success",
  "transcript": "waiting",
  "speech": "waiting",
  "knowledge": "success"
}
```

### Operator summary (AL1)

```
Acquisition succeeded (asset_id=…, N B registered).
```

Not: “Acquisition succeeded (N B read)” from a non-asset strategy ok.

### waiting_for

| Situation | waiting_for |
|-----------|-------------|
| No Asset | `media_asset` |
| Asset + no spoken text + no metadata Knowledge | `speech_to_text` (or upload transcript) |
| Metadata Knowledge ingested | `null` (job not blocked for Whisper) |

---

## Checklist

- [x] AL1 AcquisitionRecord / operator_summary  
- [x] AL2 stages + waiting_for  
- [x] AL3 metadata Knowledge completes learn (no Whisper block)  
- [x] AL4 journal rows  
- [x] AL5 knowledge_produced wiring (Job + report)  
- [x] Hermetic tests (`tests/test_asset_lifecycle.py`)  
- [x] OPEN_ITEMS  
- [ ] AL6 Reader Eligibility (later)  

---

> Companion: live BA.v2 contradiction (bytes vs Asset vs Readers).
