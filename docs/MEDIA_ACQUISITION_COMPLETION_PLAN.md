# Media Acquisition Completion — Version 4 Follow-on

> **Status:** OPEN for discussion · **Date:** 2026-07-22 · **No code until AC\* locked**  
> **Trigger:** Live Version-4 run — planner / orchestrator / journal / report honesty are
> correct; pipeline still ends at `interactive_recovery_required` because **no Media Asset
> was produced** from the YouTube URL under current strategies + config.  
> **Verdict:** Architecture ~90–95% complete. Remaining work is **acquisition capability
> completion + configuration**, not another Media Reader redesign.

---

## 1. What Version 4 proved (keep)

| Layer | Status |
|-------|--------|
| Planner (“Learn from media”) | ✅ Complete |
| Strategy orchestration + automatic vs interactive | ✅ Complete |
| Strategy journal (what ran) | ✅ Complete (outcome *why* still thin — AC4) |
| Report honesty (waiting / Next Action) | ✅ Complete — **stop spending here** |
| Media Reader Family (Asset → Readers → Knowledge) | ✅ Complete |
| Knowledge pipeline | ✅ Complete |

Log shape (correct stop):

```
youtube_caption_tracks     tried
browser_dom_captions       tried
youtube_media              tried
media_asset                none
→ interactive_recovery_required
```

Atlas is telling the truth: *every executable automatic strategy was exhausted; none produced a Media Asset.*

---

## 2. Four missing capabilities (focus only here)

### AC1 — Browser v1 must produce Assets (gap in BA.1 delivery)

**Plan said:** open → metadata → DOM captions → **Asset**.  
**Runtime often does:** open → search DOM → no captions → return (no Asset).

| When | Expected Asset |
|------|----------------|
| Caption / transcript text found | **Transcript Asset** → Media Readers → Knowledge |
| Page opens, no captions | At least **Metadata Asset** (title, URL, channel hints) — Browser → Asset responsibility |
| Browser blocked / unavailable | Journal explicit outcome; no fake Asset |

**Do not** write Knowledge from the browser. Asset only.

### AC2 — Official captions API is suggestion-only

Journal / Next Action lists `configure_official_captions_api` — that is **not** an executed strategy.

| Today | Needed for auto YouTube learn |
|-------|-------------------------------|
| Capability listed, not configured | Optional but **operational** polite strategy when API key present (`OI-M1`) |
| Else journal `skipped / not_configured` with clear reason | Already mostly true — keep distinct from “tried and failed” |

### AC3 — Browser v2 (policy-gated media obtain) not implemented

Without v2 there is **no** automatic path:

```
YouTube URL → Video/Audio Asset → Speech Reader → Knowledge
```

when captions are absent. That is expected (BA7 deferred) and is the **largest** remaining feature for caption-less URLs.

### AC4 — `speech_to_text` status: missing

Even if an audio/video Asset appeared tomorrow, Whisper (or equivalent) must be **installed and configured**. Aligns with MD5 (optional, default off) — but for the operator goal “learn from YouTube without captions,” it is a hard dependency once Assets exist.

---

## 3. New: Capability Readiness Matrix (AC5)

Before (or as the first phase of) `media.learn`, evaluate whether **any viable automatic path** exists:

| Capability | Example status | Can continue automatically? |
|------------|----------------|------------------------------|
| Browser | ready / unavailable | … |
| DOM captions path | ready | … |
| Official captions API | not_configured | … |
| Media obtain (Browser v2) | not_implemented | … |
| speech_to_text | ready / disabled / missing | … |

If **no** viable automatic path for the source kind:

```
Preflight: no viable automatic acquisition path
→ Waiting / Next Action (configure API, enable STT, upload, or implement media obtain)
```

That is more informative than discovering the same fact only after exhausting the chain — though the chain remains the source of truth for *what was attempted*.

**Draft decision:** Readiness is **advisory + early exit when zero viable paths**; it must not skip strategies that *are* ready.

---

## 4. Journal outcome clarity (AC6)

Today: strategy **name** appeared.  
Needed: **outcome why** on every automatic row.

| Strategy | Example outcome line |
|----------|----------------------|
| `browser_dom_captions` | `no_caption_nodes` **or** `asset_produced:transcript` **or** `asset_produced:metadata` |
| `youtube_media` | `policy_requires_operator_asset` |
| `configure_official_captions_api` | `not_configured` (skipped — not “tried”) |
| `speech_to_text` | only if Asset existed; else omit (MO.5) |

Reuse `AcquisitionAttempt.reason` / `reason_code`; surface in activity + report extras.

---

## 5. What remains for “paste YouTube URL → Atlas learns”

| # | Work | Unblocks |
|---|------|----------|
| 1 | **AC1** Browser v1 always attempts Asset (transcript and/or metadata) | Readers can run on something real |
| 2 | **AC2 / OI-M1** Configure + execute official captions when key present | High-reliability path when API allows |
| 3 | **AC3** Browser v2 policy-gated media → Video/Audio Asset | Caption-less URL → Whisper path |
| 4 | **AC4** Install/configure `speech_to_text` (operator/env) | Transcription once Asset exists |
| 5 | **AC5** Capability Readiness Matrix | Honest preflight |
| 6 | **AC6** Rich strategy outcomes in journal | Debuggability |

Then existing Media Reader Family does: metadata → transcript/speech → extract → Knowledge.

---

## 6. Draft locked decisions (AC*)

| # | Draft | Notes |
|---|-------|-------|
| **AC1** | Browser v1 **incomplete until** successful opens produce Transcript and/or Metadata **Assets** | Fix BA.1 gap |
| **AC2** | Official captions: execute when configured; else journal `not_configured` (never pretend tried) | Raise OI-M1 priority when auto-YouTube is a goal |
| **AC3** | Browser v2 is the **primary** remaining feature for caption-less auto-learn | Policy still gates; not a robots bypass |
| **AC4** | STT install/config is an **operator readiness** item; Atlas reports missing honestly | Not a Reader redesign |
| **AC5** | Add Capability Readiness Matrix to `media.learn` preflight | Early “no viable path” when appropriate |
| **AC6** | Every strategy journal row includes precise outcome reason_code | Extend AcquisitionAttempt usage |

### Explicit non-goals

- Redesigning Media Readers / planner / report honesty  
- Silent robots bypass  
- Enabling Whisper by default without operator choice  
- Treating readiness matrix as a replacement for the strategy journal  

---

## 7. Proposed ship order

```
AC6  Journal outcome clarity          (small, high leverage)
  ↓
AC1  Browser v1 → always Asset        (close BA.1 contract)
  ↓
AC5  Capability Readiness Matrix      (preflight)
  ↓
AC2  Official captions when configured (OI-M1)
  ↓
AC4  Operator: install STT            (docs + status; may parallel)
  ↓
AC3  Browser v2 media obtain          (largest)
```

---

## 8. Discussion prompts

1. Confirm ship order above (or reorder AC2 before AC1 if API key is already available)?  
2. Metadata-only Asset: promote to Knowledge as stub, or Asset-only until transcript/speech exists? (**Recommend Asset-only**, Readers no-op / gap until spoken content.)  
3. Readiness matrix: fail-fast when zero paths, or always run chain and only *display* readiness? (**Recommend:** display always; fail-fast only when zero viable automatic paths.)  
4. Browser v2 policy: operator allowlist domains / explicit config flag before any media obtain?

---

## 9. Checklist

- [ ] Freeze AC1–AC6 (or revise)  
- [ ] **AC6** Journal outcomes  
- [ ] **AC1** Browser → Asset (transcript + metadata)  
- [ ] **AC5** Readiness matrix  
- [ ] **AC2** Official captions execute-when-configured  
- [ ] **AC4** STT operator readiness (docs / install path)  
- [ ] **AC3** Browser v2  

---

> Companions: [`MEDIA_BROWSER_ACQUISITION_PLAN.md`](MEDIA_BROWSER_ACQUISITION_PLAN.md),
> [`MEDIA_ORCHESTRATION_PLAN.md`](MEDIA_ORCHESTRATION_PLAN.md),
> [`MEDIA_ACQUISITION_PLAN.md`](MEDIA_ACQUISITION_PLAN.md),
> [`OPEN_ITEMS.md`](OPEN_ITEMS.md).
