# Browser as Media Acquisition — Discussion Plan

> **Status:** BA.1 + BA.1b + BA.v2 DONE · BA.v2+ deferred ·
> **Date:** 2026-07-22  
> **Does not** reopen Media Reader MD1–MD9. Browser produces **Assets**; Readers produce Knowledge.
>
> Parent: [`MEDIA_ORCHESTRATION_PLAN.md`](MEDIA_ORCHESTRATION_PLAN.md) ·
> Next phase: [`MEDIA_ACQUISITION_CLOSURE_PLAN.md`](MEDIA_ACQUISITION_CLOSURE_PLAN.md)

---

## 1. Architecture (locked)

```
Browser acquires / navigates  →  Assets
Media Reader Family           →  Artifacts / Knowledge
Job Runtime                   →  strategies + recovery
Report Generator              →  truthfully describes runtime
Research                      →  one Knowledge consumer (not media owner)
```

**Never:** Browser → Knowledge.

---

## 2. Frozen decisions (BA*)

| # | Decision |
|---|----------|
| **BA1** | Browser is an **acquisition** capability, not a Reader |
| **BA2** | Browser outputs **Assets** (and metadata), never Knowledge |
| **BA3** | Robots / policy / ToS still gate obtain — browser is not a bypass |
| **BA4** | Provider names stay in the strategy journal; user step remains **Learn from media** |
| **BA5** | Part of media.learn roadmap (required) | — |
| **BA6** | **Browser v1:** open → metadata → DOM captions → **Asset** (no download/click/login) |
| **BA7** | **Browser v2:** policy-gated media obtain → Video/Audio Asset | After BA.1b |
| **BA8** | **BA.1b (locked):** On successful browser open, **always** create an Asset — transcript if captions found, else **metadata Asset** at minimum. Strategy “ran” ≠ Asset produced. |

### Strategy order inside `media.learn`

1. Official / polite captions (when configured — executable, not suggestion-only)  
2. Browser-assisted (v1: metadata + DOM captions → **Asset**)  
3. Browser v2 / SourceFetch media obtain (when implemented + policy allows)  
4. Local media + Whisper (when Asset exists + STT ready)  
5. Interactive recovery → **waiting**

---

## 3. Version 4 finding (BA.1 incomplete)

| Shipped | Gap |
|---------|-----|
| `browser_dom_captions` strategy invoked from `media.learn` | Log shows strategy tried but **no Media Asset created** |
| Hermetic caption-text success path | Open → search DOM → empty → return **without** metadata Asset |

**BA.1b** closes BA2/BA6 properly.

---

## 4. Implementation slices

| Slice | Scope | Status |
|-------|--------|--------|
| **BA.1** | Strategy + wiring + hermetic caption text | ✅ Done |
| **BA.1b** | Register transcript **or** metadata Asset; journal `asset_produced` / `no_caption_nodes_found` + `asset_id` | ⬜ Next |
| **BA.2** | Gate: policy-allowing DOM captions when HTTP scrape blocked | partial / revisit with BA.1b |
| **BA.v2** | Policy-gated media obtain → bytes Asset | ✅ Opt-in yt-dlp |
| **BA.v2+** | Progress, resume, auth sessions | later |

---

## 5. Checklist

- [x] Freeze BA1–BA8  
- [x] **BA.1** Strategy wiring  
- [x] **BA.1b** Asset emission (metadata minimum) — locked yes  
- [x] **BA.v2** Media obtain (after official captions API)  

---

> Companions: [`MEDIA_ACQUISITION_CLOSURE_PLAN.md`](MEDIA_ACQUISITION_CLOSURE_PLAN.md),
> [`MEDIA_REPORT_HONESTY_AMENDMENT.md`](MEDIA_REPORT_HONESTY_AMENDMENT.md).
