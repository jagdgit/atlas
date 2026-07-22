# Media Orchestration — `media.learn`

> **Status:** MO.0–MO.5 + RH.5–RH.8 + BA.1 + MO.3 DONE · **Date:** 2026-07-22  
> Browser v2 (policy-gated media download) remains later.  
> **Open item:** OI-MO0 · Job report honesty detail:
> [`MEDIA_REPORT_HONESTY_AMENDMENT.md`](MEDIA_REPORT_HONESTY_AMENDMENT.md) · Browser v1 detail:
> [`MEDIA_BROWSER_ACQUISITION_PLAN.md`](MEDIA_BROWSER_ACQUISITION_PLAN.md)  
>
> **Browser is in scope for this plan** — required for a complete `media.learn` acquisition
> spine (Browser → Asset → Readers). It is sequenced after report honesty, not optional and
> not a separate product track.

---

## 1. Locked product decisions (unchanged)

| ID | Decision |
|----|----------|
| **MO1** | Capability / intent: **`media.learn`** |
| **MO2** | **Job/Assistant first**; Research consumes later |
| **MO3** | **One** outer job step + rich strategy journal (highest UX priority) |
| **MO4** | **Automatic** strategies execute; **interactive** (upload / local path) = suggestion-only |
| **MO5** | Planner **preserves** user goal (“Learn from media”); never sole rewrite to “Fetch transcript” |
| **MO6** | Journal **every** automatic strategy under that one step |

### Dependency (locked)

```
Assistant / Job  →  media.learn  →  Media Reader Family  →  Knowledge
                                                              ├── Research
                                                              ├── Owner Knowledge
                                                              └── …missions
```

Research must not own a parallel media story.

### Automatic vs interactive (locked)

| Kind | Examples | Runtime |
|------|----------|---------|
| **Automatic** | Caption/subtitle strategies, official captions API (when configured), SourceFetch when policy allows, metadata, demux, speech_to_text **iff Asset exists**, explicit `capability_gap` / `policy_skip` journal entries | Execute until exhausted |
| **Interactive** | Upload transcript, upload media, provide local asset | Suggest only until operator provides input |

---

## 2. Code reality (baseline)

| Fact | Location |
|------|----------|
| Assistant chat and Job steps share **one** planner + `AssistantService.run_step` | `atlas/planner/planner.py`, `atlas/services/assistant_service.py` |
| YouTube URL / transcript keywords → `Intent.YOUTUBE_TRANSCRIPT` → tool `youtube.transcript` only | Planner `_RULES`; `_do_youtube` |
| Step description today: *“Fetch a YouTube video transcript.”* | Planner |
| `MediaIngestor` exists (file/URL → metadata → demux/speech → optional Knowledge) | `atlas/ingestion/media.py` |
| Captions are **outside** MediaIngestor today (YouTube plugin / Librarian first) | `youtube_plugin`, `Librarian._acquire_video` |
| Librarian early-returns on `robots_disallowed` — never calls MediaIngestor | `atlas/research/acquire.py` |
| Job steps are **flat** (no nested child steps); strategies nest only in records/events | Job model + `AcquisitionRecord` |
| UI shows **tool chips**, not a strategy tree | `app.js` `renderStepCard` |
| Failed youtube acquire marks step **DONE** with prose, not `blocked` | `_do_youtube` |
| No `media.learn` intent/capability/mission yet; do **not** confuse with `CAP_LEARNING` (Experience ledger) | capabilities / missions |

---

## 3. Target architecture

### 3.1 Orchestrator (new shared unit)

Introduce a single **`MediaLearnOrchestrator`** (name may be `media_learn.run` / module under `atlas/ingestion/` or `atlas/media/`) that:

1. Runs **automatic** strategies in order (caption → … → speech / gaps).  
2. Returns one result: outcome, text (if any), **strategy journal**, interactive suggestions, knowledge ingest meta.  
3. Is called from Job/Assistant (`media.learn` step) first; later from Research (MO.3).

`youtube.transcript` remains a **low-level strategy/tool**, not the user-facing intent for “learn from video.”

```
media.learn (one job step)
    │
    ├─ [auto] captions / subtitle strategies     (existing M.2 / youtube.transcript)
    ├─ [auto] official captions API              (if configured; else journal skip)
    ├─ [auto] SourceFetch                        (policy-gated; journal policy_skip if blocked)
    ├─ [auto] MediaMetadataReader                (if Asset)
    ├─ [auto] AudioDemux / TranscriptFile        (if applicable)
    ├─ [auto] SpeechToText                       (if Asset + audio/video; else gap if expected)
    ├─ [auto] → Knowledge                        (when text acquired — see §5 default D1)
    └─ [interactive] upload / local path         (suggestions only if still no text)
```

### 3.2 External presentation (MO3)

```
Step 1 — Learn from media
  Strategies:  ✓/✗ captions · ✓/✗ fetch · ✓/✗ metadata · ✓/✗ speech · …
  → Knowledge updated  |  Interactive recovery required
```

Internally full chain; UI must not become 17 job steps.

### 3.3 Planner (MO5)

| Input | Intent |
|-------|--------|
| Learn / summarize / ingest / understand + media URL or video id | **`media.learn`** |
| Bare YouTube URL (no explicit “transcript only”) | **`media.learn`** — see default **D2** |
| Explicit caption-only (“fetch transcript”, “get captions”, “subtitles only”) | Keep **`youtube_transcript`** |

Step description for `media.learn`: **“Learn from media.”** (not “Fetch a YouTube video transcript.”)

---

## 4. Implementation slices (ordered, acceptance-ready)

| Slice | Deliverable | Acceptance |
|-------|-------------|------------|
| **MO.0** | Hermetic test proving Job/Assistant youtube path does **not** call MediaIngestor / orchestrator today | Failing or xfail baseline that flips green after MO.2; documents the gap |
| **MO.1** | `Intent.MEDIA_LEARN` + `CAP_MEDIA_LEARN` + planner rules (MO5) + JobPlanner allowlist; description “Learn from media.” | “Learn from this youtube URL” → `media.learn`, not `youtube_transcript`; caption-only phrasing still → `youtube_transcript` |
| **MO.2** | Orchestrator + Assistant `_do_media_learn` + tool `media.learn`; one step; strategy journal in step `extras` / tool_calls; automatic vs interactive; wire captions + MediaIngestor/SourceFetch/Speech | Live-equivalent hermetic: robots captions → journal continues automatic attempts → interactive suggestions; **no** silent single-tool stop |
| **MO.3** | Research `Librarian._acquire_video` calls shared orchestrator (remove parallel story / align robots fall-through with MO4) | Research video acquire uses same journal semantics |
| **MO.4** | Gate test: end-to-end Job “learn from video” with robots captions | Assert strategy journal length > 1 family; interactive suggestions present; no fabricated docs |
| **MO.5** | Journal honesty: no `speech_to_text` attempt without Asset; SourceFetch outcomes explicit (`policy_requires_operator_asset` / robots vs vague “no asset”); provider ids stay in journal only | Hermetic asserts on strategy list + reason_codes |
| **RH.5–RH.8** | Job report honesty: termination `{stage,status,reason}`, waiting vs blocked, **Next Action**, blocked answers in job result | See amendment; gate: no “no verifiable claims” / fake Verification on wait |
| **BA.1–BA.3** | **Required** Browser v1 inside `media.learn`: open → metadata → DOM captions → Asset (no download/click/login). Detail: browser plan | Hermetic fakes; journal strategy; Asset → Readers when captions found |
| **MO.3** | Research consumes shared `media.learn` orchestrator | Same journal / waiting semantics |

**Ship order (remaining — all required for this plan):**

```
RH.5–RH.8  (Job report honesty)
    ↓
MO.5       (journal clarity)
    ↓
BA.1–BA.3  (Browser → Asset v1 — required, not optional)
    ↓
MO.3       (Research consumes media.learn)
```

Browser v2 (policy-gated media download) stays **later** under the browser plan; v1 is enough to close the “URL → Asset without fragile scrape” gap for captions.

---

## 5. Implementation defaults (resolved for coding)

These are **finalized defaults** so implementation can start without another design round. Override only via plan amendment.

| ID | Topic | Default |
|----|--------|---------|
| **D1** | Knowledge write on success | When spoken/transcript text is acquired: **`to_knowledge=True`** (MediaIngestor default). Answer may also summarize. On acquire failure: **no** fabricated Knowledge (P15). |
| **D2** | Bare YouTube URL | Maps to **`media.learn`**, not `youtube_transcript`. Caption-only language keeps `youtube_transcript`. |
| **D3** | After caption `robots_disallowed` with **no** Asset | Still run/journal remaining **automatic** steps that do not need inventing bytes: e.g. official API (if configured), SourceFetch → **journal `policy_skip` / operator asset required** (do not scrape past robots). Do **not** claim Speech ran without an Asset. Then surface **interactive** suggestions. |
| **D4** | Job step status when interactive recovery required | Return **`blocked=True`** with reason like `interactive_recovery_required` (same family as “needs file”), plus operator summary + suggestions in answer/`extras`. Not a quiet DONE with only prose. |
| **D5** | Strategy journal MVP (MO.2) | Persist structured `strategies` (or extend `AcquisitionRecord`) on step **`extras`** + activity one-liner. Full strategy-tree UI in `app.js` is **nice-to-have in MO.2**, not a blocker if extras + activity are correct. |
| **D6** | Extract / consolidate | **Inside** the single `media.learn` step (ingest + short answer). No separate job steps for Extract/Consolidate in v1. |
| **D7** | Capability / tool ids | Capability: `CAP_MEDIA_LEARN` / id `media_learn`. Tool: `media.learn`. Intent: `media_learn`. Avoid colliding with `CAP_LEARNING`. |
| **D8** | Whisper | Unchanged: default off; missing/disabled → journal **`capability_gap`**, do not enable by default. |

---

## 6. Acceptance checklist (runtime)

| Check | Pass when |
|-------|-----------|
| Planner goal | Step description is “Learn from media” for learn/URL cases |
| Outer steps | Exactly **one** `media.learn` step for that objective |
| After robots captions | Automatic journal continues (policy skips / gaps allowed); not silent stop |
| Interactive | Uploads suggested, never auto-executed |
| Speech | Attempted only with Asset; else gap or skipped with journal reason |
| Tools / journal | More than a single caption-only attempt recorded when orchestrator runs |
| Knowledge | Written only on real acquire success |
| Research | Unchanged until MO.3; then shares orchestrator |

---

## 7. Non-goals

- Rebuilding Readers  
- Robots bypass / mandatory YouTube media download  
- Whisper on by default  
- Multi-step job UI for each Reader  
- New mission template in v1 (optional later)  
- Fancy strategy-tree UI as a hard dependency of MO.2 (see D5)

---

## 8. Open ambiguities (need a quick call — or accept defaults)

Only these remain soft. **If no reply, implement §5 defaults.**

| # | Ambiguity | Options | Default if silent |
|---|-----------|---------|-------------------|
| **A1** | Bare YouTube URL → `media.learn` or keep `youtube_transcript`? | (a) media.learn (b) transcript | **D2 = (a)** |
| **A2** | Interactive recovery → job `blocked` vs DONE + prose? | (a) blocked (b) DONE | **D4 = (a)** |
| **A3** | Always write Knowledge on success, or only when user said learn/ingest/remember? | (a) always on success (b) verb-gated | **D1 = (a)** |
| **A4** | Strategy-tree UI in MO.2 or extras/activity only? | (a) extras MVP (b) UI same slice | **D5 = (a)** |
| **A5** | Keep MO.0 as permanent regression (orchestrator must be invoked) after MO.2? | (a) keep inverted assertion (b) delete MO.0 | **(a)** keep as “orchestrator invoked” gate |

No other product ambiguities block coding. Naming (`MediaLearnOrchestrator` vs wrapping MediaIngestor) is an implementation detail inside MO.2.

---

## 9. Checklist

- [x] Product decisions MO1–MO6  
- [x] Implementation defaults D1–D8  
- [x] Slice order + acceptance  
- [x] Confirm or override A1–A5 (optional) — defaults accepted 2026-07-22  
- [x] **MO.0** Instrumentation / proof (`tests/test_media_orchestration.py`)  
- [x] **MO.1** Planner intent `media.learn` + preserve user goal  
- [x] **MO.2** Job/Assistant one-step orchestrator + strategy journal  
- [x] **MO.4** Job gate (hermetic)  
- [x] **RH.5–RH.8** Job report honesty (required; see amendment)  
- [x] **MO.5** Speech/fetch journal clarity  
- [x] **BA.1–BA.3** Browser → Asset v1 (required in this plan)  
- [x] **MO.3** Research consumes shared orchestrator  

---

## 10. Decision log

| Date | Item |
|------|------|
| 2026-07-22 | Priority / job shape / robots / naming locked (MO1–MO6) |
| 2026-07-22 | Plan finalized for implementation; defaults D1–D8; ambiguities A1–A5 listed |
| 2026-07-22 | **Implemented MO.0–MO.2 + MO.4** (Job/Assistant). MO.3 Research deferred. |
| 2026-07-22 | Version-3 review: runtime validated; Job report honesty + MO.5 + browser-acquire plans opened. |

---

> Companions: [`MEDIA_ACQUISITION_PLAN.md`](MEDIA_ACQUISITION_PLAN.md), [`MEDIA_REPORT_HONESTY_PLAN.md`](MEDIA_REPORT_HONESTY_PLAN.md), [`OPEN_ITEMS.md`](OPEN_ITEMS.md) (OI-MO0).
