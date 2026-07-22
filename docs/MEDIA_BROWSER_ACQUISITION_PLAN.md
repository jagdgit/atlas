# Browser as Media Acquisition — Discussion Plan

> **Status:** IN SCOPE of Media Orchestration plan · **Required** · **Date:** 2026-07-22  
> **Implement after RH.5 + MO.5** (same roadmap — not a side quest).  
> **Does not** reopen Media Reader MD1–MD9. Browser produces **Assets**; Readers produce Knowledge.
>
> Parent checklist: [`MEDIA_ORCHESTRATION_PLAN.md`](MEDIA_ORCHESTRATION_PLAN.md) (§4 ship order).

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
| **BA5** | Part of **this** media.learn roadmap (required). Sequence: after RH.5 → MO.5, before MO.3 | Not optional / not a separate product |
| **BA6** | **Browser v1 (required):** open page → extract metadata → **DOM captions** → Asset. **No** downloads, clicks, or login | — |
| **BA7** | **Browser v2 (later, same plan family):** policy-gated media obtain → Asset | After v1 proves Browser → Asset |
### Strategy order inside `media.learn` (target)

1. Official / polite captions  
2. Browser-assisted (v1: metadata + DOM captions → Asset)  
3. Local media + Whisper (when Asset exists)  
4. Interactive recovery → **waiting** (operator upload)

---

## 3. Implementation slices (after RH.5 / MO.5)

| Slice | Scope |
|-------|--------|
| **BA.1** | Spec + hermetic fakes: browser caption extract → Asset (no live YouTube in CI) |
| **BA.2** | Wire as automatic strategy in `media.learn` |
| **BA.3** | Gate: captions via browser DOM when watch-page scrape blocked but DOM allows (policy permitting) |
| **BA.4+** | Browser v2 media obtain (separate decision) |

---

## 4. Checklist

- [x] Freeze BA1–BA7  
- [x] Wait for RH.5 + MO.5  
- [x] **BA.1** Browser DOM captions strategy + `media.learn` wiring (`tests/test_browser_captions_ba1.py`)  
- [ ] **BA.4+** Browser v2 media obtain (separate)  

---

> Companions: [`MEDIA_REPORT_HONESTY_AMENDMENT.md`](MEDIA_REPORT_HONESTY_AMENDMENT.md),
> [`MEDIA_ORCHESTRATION_PLAN.md`](MEDIA_ORCHESTRATION_PLAN.md).
