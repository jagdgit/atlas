# Media Acquisition Closure — Version 4 → Version 5

> **Status:** BA.1b + MO.6 + CR.1 + OI-M1 + BA.v2 DONE · Whisper ops remaining ·
> **Date:** 2026-07-22  
> **Trigger:** Version-4 live run — planner / orchestrator / journal / report honesty validated.
> Bottleneck is **URL → Media Asset**.  
> **Parent:** [`MEDIA_ORCHESTRATION_PLAN.md`](MEDIA_ORCHESTRATION_PLAN.md) ·
> [`MEDIA_BROWSER_ACQUISITION_PLAN.md`](MEDIA_BROWSER_ACQUISITION_PLAN.md)

---

## 1. Verdict

| Layer | Status |
|-------|--------|
| Planner / orchestrator / journal / report honesty | ✅ Complete — **stop investing** |
| Media Reader Family / Knowledge | ✅ Complete |
| **Automatic path: URL → Media Asset** | ❌ Incomplete — **this plan** |

---

## 2. Frozen decisions (AC* / CR*)

| # | Decision |
|---|----------|
| **AC1** | No Media Reader / report-honesty redesign — acquisition Assets only |
| **AC2** | **BA.1b first:** On successful browser open, **always** create an Asset — transcript if captions found, else **metadata Asset** at minimum |
| **AC3** | Official captions API is an **executable automatic strategy when configured**; elevate OI-M1 ahead of Browser v2 |
| **AC4** | Browser v2 (policy-gated media obtain) **after** BA.1b + official API path |
| **AC5** | **Capability Readiness Matrix** on `media.learn`; surface in **journal and Job report** |
| **AC6** | Journal records precise end reasons + whether an Asset was created (`asset_id` / kind) |
| **CR1** | Evaluate readiness before/at start of `media.learn` (Browser, DOM captions, Official API, Media obtain, speech_to_text, operator upload) |
| **CR2** | **Run** strategies marked `ready` (diagnostics). **Skip** `not_configured` / `not_implemented` with **one journal row each** (not a fake full attempt). Do not skip the whole chain silently. |

### Decision log (2026-07-22)

| Prompt | Choice |
|--------|--------|
| Metadata Asset when browser opens but no captions? | **Yes** |
| Run ready strategies; skip not_configured with one row? | **Yes** |
| Official captions API vs Browser v2 first? | **Official captions API first** |
| Readiness in Job report as well as journal? | **Yes** |

---

## 3. Four missing capabilities (still the backlog)

1. **BA.1b** — Browser → Asset (metadata minimum)  
2. **OI-M1** — Official captions API executable when configured  
3. **Browser v2** — policy-gated media obtain (after 1–2)  
4. **Ops** — `speech_to_text` installed/ready for caption-less path  

Plus **CR.1** readiness matrix + **MO.6** journal outcome clarity.

---

## 4. Ship order (locked)

```
BA.1b     Browser always produces Asset (transcript | metadata)
   ↓
MO.6      Journal outcome clarity (+ asset_id)
   ↓
CR.1      Capability Readiness Matrix (journal + Job report)
   ↓
OI-M1     Official captions API (executable when configured)
   ↓
BA.v2     Policy-gated media obtain
   ↓
Ops       speech_to_text ready (operator)
```

---

## 5. Target shapes

### Readiness (journal + report)

```
Capability readiness
  Browser              ready | unavailable
  DOM captions         ready
  Official captions    ready | not_configured
  Media obtain         ready | not_implemented | policy_blocked
  speech_to_text       ready | disabled | missing
  Operator upload      ready

Assessment: … viable automatic path / no viable automatic path …
```

### Strategy journal row

```
strategy: browser_dom_captions
outcome: skipped | ok | blocked | …
reason_code: no_caption_nodes_found | asset_produced | not_configured | …
asset_id: … | null
asset_kind: transcript | metadata | video | audio | null
```

### BA.1b browser open success

```
Open page (ok)
  ├─ captions found → Transcript Asset → Readers / Knowledge path
  └─ no captions    → Metadata Asset (title, url, …) + journal no_caption_nodes_found
```

---

## 6. Explicit non-goals

- Redesigning planner / orchestrator / report honesty  
- Robots bypass  
- Browser → Knowledge  
- Enabling Whisper by default in code  

---

## 7. Checklist

- [x] Freeze AC1–AC6, CR1–CR2  
- [x] **BA.1b** Browser → Asset (metadata minimum)  
- [x] **MO.6** Journal outcome clarity (`asset_id` / reason_codes)  
- [x] **CR.1** Readiness matrix (journal + Job report)  
- [x] **OI-M1** Official captions API executable when `plugins.youtube.api_key` set  
- [x] **BA.v2** Media obtain (opt-in `plugins.youtube.media_obtain_enabled` + `yt-dlp`)  
- [ ] Ops note: Whisper install  

---

## 8. Operator config (YouTube)

### Official captions API (`plugins.youtube.api_key`)

Create or edit **`config/local.yaml`** (gitignored):

```yaml
plugins:
  youtube:
    api_key: "YOUR_YOUTUBE_DATA_API_V3_KEY"
```

Or set the env var (takes precedence over YAML via Atlas env overrides):

```bash
export ATLAS_PLUGINS_YOUTUBE_API_KEY="YOUR_YOUTUBE_DATA_API_V3_KEY"
```

Then restart Atlas. Readiness should show `official_captions: ready`.  
Caption **list** works with an API key; **download** of caption bodies often still needs OAuth — Atlas journals `api_download_requires_oauth` honestly when that happens.

### Media obtain BA.v2 (`yt-dlp`)

Default **off** (policy opt-in). In `config/local.yaml`:

```yaml
plugins:
  youtube:
    media_obtain_enabled: true
    # media_obtain_binary: yt-dlp
    # media_obtain_format: bestaudio/best
```

Install `yt-dlp` on PATH. Robots still gate obtain. For caption-less → Knowledge you also need Whisper:

```yaml
plugins:
  speech:
    enabled: true
```

---

> Companions: [`MEDIA_BROWSER_ACQUISITION_PLAN.md`](MEDIA_BROWSER_ACQUISITION_PLAN.md) (BA8),
> [`OPEN_ITEMS.md`](OPEN_ITEMS.md) (OI-AC0, OI-M1, OI-BA0).
