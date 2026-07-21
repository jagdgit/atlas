# Media Reader Family — spoken-word & video learning (implementation plan)

> **Open items / leftovers:** tracked centrally in **[`docs/OPEN_ITEMS.md`](OPEN_ITEMS.md)** as `OI-M*`.
>
> **Status:** 🟢 **FROZEN FOR IMPLEMENTATION (2026-07-21).** Post–Phase D improvement plan.
> Triggered by a live run that failed with *No transcript available / robots.txt disallows this URL /
> Text read 0 B / 0 documents* — an **acquisition failure, not a reasoning failure**. Atlas correctly
> refused to hallucinate (P15). This plan strengthens the **Media Reader family** (and a reusable
> **Reader strategy-chain** pattern) so spoken-word and video sources reach the existing Knowledge
> pipeline **without** inventing a YouTube/Video Intelligence or redesigning the OS.
>
> **Operator review (2026-07-21) — approved with three refinements, now folded in:**
> (1) **generalize the strategy-chain** beyond YouTube into a reusable Reader/acquisition execution
> pattern; (2) add a **Metadata Reader** before transcription; (3) keep media **non-special** —
> always `Asset → Reader Registry → Artifact → Knowledge`, with provider-specific code confined to
> acquisition strategies that *produce* assets.
>
> **Builds on:** Phase 0 Asset Store + resilient net (`robots.txt`, outcomes-not-exceptions);
> Stage 2 S18a `youtube.transcript` / `YouTubeTranscriptProvider`; Phase B **Asset → Reader →
> Artifact → Extraction → Knowledge** (P8/P11) + Reader Registry; Phase C Consolidator + candidacy;
> Phase D P15 `capability_gap` honesty.
>
> **Goal:** Atlas learns from YouTube, Zoom/Teams exports, conference talks, podcasts, and local
> `mp4`/`mp3`/`wav`/`vtt` **when a resilient Reader path succeeds** — and still reports an honest,
> named gap when every strategy fails. Media must feel like **just another asset**.
>
> **Not in this plan:** fabricated transcripts; bypassing `robots.txt` / ToS; new top-level
> intelligences; Decision Engine changes; real-time CCTV; paywalled auto-download; **frame / slide
> OCR** (deferred — architecture already allows it; see §7).

---

## 0. What the failed run proved

```
YouTube URL
    ↓
Acquire  ×  blocked / no transcript
    ✗  Reader never started
    ✗  Extract never started
    ✗  Learn never started
```

The LLM did not fail. Knowledge OS did not fail. The **Reader never even started**.

Today’s path is a **single strategy**:

```
YouTube URL → YouTubeTranscriptProvider (watch page + captionTracks)
            → text (or outcome: skipped / blocked / error)
```

When captions are absent **or** the net layer honours `robots.txt` and blocks the fetch, the job
reports `0 B` / `0 documents`. That is **correct** under P15. It is also product-incomplete: the
architecture already supports better Readers; only the Media Reader family + strategy resilience
are thin.

---

## 1. Guiding constraints (constitution)

- **P8 / P11 — Asset → Reader → Artifact; Readers never own knowledge.** Bytes land in the Asset
  Store; Readers are stateless transforms into Artifacts; Extraction → Candidates → Consolidator
  own knowledge. Re-reading an improved Reader re-parses the **same** asset (or a derived sibling),
  never a private media knowledge silo.
- **Media is non-special (MD8).** No `if youtube` / `if mp4` branches in Knowledge, Consolidator, or
  missions. Provider logic lives only in **acquisition strategies that register Assets**. After that,
  everything is `Asset → Reader Registry → Capability Registry → Artifact → Knowledge`.
- **P15 — capability-gap honesty.** Prefer `blocked` / `skipped` / `capability_gap: speech_to_text`
  over a fabricated transcript. Missing Whisper ⇒ named gap, not a hard dependency.
- **R2/R3 — outcomes, never exceptions.** Every strategy returns a typed outcome; the chain
  continues or stops with a journaled reason.
- **Resilient net stays law.** Do not “fix” acquisition by ignoring `robots.txt`. Prefer
  official APIs / operator-provided assets / local files when scrape paths are disallowed.
- **No new Intelligence.** This is a **Media Reader family** feeding Research / Knowledge OS — same
  pattern as Document / Conversation / MarketData. Atlas stays a **universal asset learning system**.

---

## 2. Locked decisions (MD*)

| # | Decision | Rationale |
|---|----------|-----------|
| **MD1** | **Media Reader family** (not a “Media Acquisition subsystem” or “Video Intelligence”). Terminology: Readers + optional source strategies that *produce* assets. | Fits Atlas; acquisition is one step, not the family name. |
| **MD2** | **Asset-first media** — URLs/providers produce `video` / `audio` / `transcript` assets; local files are first-class and do **not** require YouTube. Knowledge never sees the provider. | Unlocks Zoom, conferences, phone notes, podcasts with zero provider-specific knowledge path. |
| **MD3** | **Reusable `ReaderStrategyChain` (aka StrategyExecutor)** — ordered strategies, first `ok` wins, full `strategies_tried[]` audit. First consumer = media/transcript; designed for reuse (documents, git, OCR, CAD, …). | Operator insight: the pattern is architectural, not YouTube-specific. |
| **MD4** | **Metadata Reader before transcript** — duration, language, title, description, tags, channel, upload date, resolution/fps/codec where available → **metadata artifact** (structured facts about the asset, not Knowledge claims). | Useful later; cheap; keeps technical/descriptive props out of the transcript path. |
| **MD5** | **Whisper / local STT is an optional Capability Registry entry** (`speech_to_text`) — missing ⇒ `capability_gap`, never a mandatory install. | P15; Atlas stays installable. |
| **MD6** | **Respect robots + ToS** — scrape/caption paths remain polite; when blocked, fall through to operator upload / local asset / (future) official API; never silent bypass. | Honesty > convenience. |
| **MD7** | **Evidence level stays graded** — caption/official transcript ≈ L1–L2 spoken; Whisper of operator-owned media same band; never inflate to peer-reviewed. | Verification + reports stay coherent. |
| **MD8** | **Provider-agnostic source fetch** — “get bytes into an Asset” is a small strategy set (YouTube, Vimeo, podcast enclosure, local path, …), not a YouTube-only download bridge. | Tomorrow’s sources shouldn’t require a Knowledge redesign. |
| **MD9** | **No redesign of Asset→Reader→Artifact→Candidate→Knowledge** — only thicken Readers + introduce the reusable strategy-chain helper. | Review discipline: extend an existing layer. |

---

## 3. Target architecture

Media must disappear into the universal pipeline:

```
Code / Documents / Media / …
        ↓
      Asset
        ↓
  Reader Registry  (+ ReaderStrategyChain where a Reader has fallbacks)
        ↓
     Artifact(s)     ← metadata, then transcript (and later: frames — deferred)
        ↓
  Knowledge Candidates → Consolidator → Knowledge
```

Spoken content specifically:

```
Source URL or local path
        ↓
  [optional] SourceFetch strategies → Media Asset   (MD8; provider-specific HERE only)
        ↓
  MetadataReader → metadata artifact                 (MD4)
        ↓
  ReaderStrategyChain for transcript:
     ├─ caption / subtitle strategies (remote or sidecar files)
     ├─ TranscriptFileReader (.vtt / .srt / .txt asset)
     ├─ AudioDemuxReader (video → audio artifact/asset)
     ├─ SpeechReader via speech_to_text capability (Whisper, …)
     └─ Existing Knowledge dedupe (already-learned content hash / source id)
        ↓ first ok
  Transcript Artifact → Extract → Candidates → Knowledge
```

**YouTube disappears after the Asset exists.** The Knowledge pipeline must not know or care whether
the transcript came from YouTube or a phone recording.

```
Capability
    ↓
Strategy 1 → Strategy 2 → Strategy 3 → …
    ↓
Outcome (+ strategies_tried[])
```

That chain is the reusable pattern (`ReaderStrategyChain`); media is the first production user.

---

## 4. Implementation slices

### M.1 — Diagnose & instrument  ·  ✅ DONE
- Emit structured outcomes into job/learning reports: which strategy ran, `outcome`, `reason`
  (`robots_disallowed`, `no_captions`, `private`, `rate_limited`, …), bytes read.
- Operator-facing copy: *acquisition/read failed before extract* — not “Atlas couldn’t think”.
- Hermetic tests for outcome taxonomy.
- **Acceptance:** a blocked YouTube URL yields one explainable record and **0 fabricated docs**.

### M.2 — `ReaderStrategyChain` (+ YouTube captions as first consumer)  ·  ✅ DONE
- Introduce a small reusable helper (name TBD in code: `ReaderStrategyChain` / `StrategyExecutor`) in
  a neutral package (e.g. under `atlas/readers/` or `atlas/acquisition/` — prefer readers-adjacent,
  not a new plane): ordered callables → first `ok` → `strategies_tried[]`.
- Refactor `YouTubeTranscriptProvider` to run caption strategies through the chain (watch-page +
  `captionTracks`, language fallbacks). Keep `youtube.transcript` tool API stable; enrich
  `as_dict()` with the audit trail.
- Document the pattern for later reuse (documents/git/OCR) without implementing those yet.
- **Acceptance:** unit tests for captions ok / no captions / robots blocked, each with
  `strategies_tried[]`.

### M.3 — Media assets + Metadata Reader  ·  ✅ DONE
- Asset kinds: `video`, `audio`, `transcript` (align with Asset Store conventions).
- **MediaMetadataReader** — from asset bytes and/or provider sidecar info → metadata artifact:
  duration, language, title, description, tags, channel/uploader, upload/created date,
  resolution, fps, codec (best-effort; absent fields omitted, never invented).
- Metadata is **structured artifact data**, not Knowledge claims (P11). Downstream may later promote
  selected fields via extractors if useful.
- **Acceptance:** registering a local `mp4`/`mp3` yields a metadata artifact without requiring
  transcription to succeed.

### M.4 — Transcript / Audio / Speech Readers (Asset-first continuum)
- **TranscriptFileReader** — `.vtt` / `.srt` / `.txt` → transcript artifact.
- **AudioDemuxReader** (ffmpeg-backed helper, optional capability) — `video` → `audio` derived
  asset/artifact.
- Register all media Readers in the **Reader Registry** (advances OI-C1/OI-C2 where overlapping).
- Ingestion: `atlas ingest ./talk.mp4` (and/or API) → Asset → metadata → transcript chain →
  candidates (reuse OI-C5 wiring where useful).
- **Acceptance:** a local `.mp4` or `.vtt` reaches Knowledge **with no YouTube URL and no
  provider-specific branches past the Asset boundary**.

### M.5 — Optional `speech_to_text` capability (Whisper or equivalent)
- Capability Registry entry; Speech Reader is a strategy in the transcript chain.
- Model/version stamped on the artifact (P9); evidence L1.
- Missing binary/model → `capability_gap: speech_to_text` (P15); default **off** until configured
  (`plugins.speech` / Whisper path).
- **Acceptance:** Whisper on → caption-less local audio becomes knowledge; Whisper off → explicit gap.

### M.6 — Provider-agnostic source fetch → Asset (when policy allows)
- Small **source-fetch strategy set** that only’s job is *bytes → Asset* (YouTube, later Vimeo /
  podcast enclosure / lecture archive, …). Not a “YouTube download” feature.
- Runs only when prior transcript strategies failed **and** net/ToS policy permits; otherwise
  `blocked` + operator hint: *upload a local file or a transcript asset*.
- Manual/local ingest (M.3/M.4) remains the always-on escape hatch.
- **Acceptance:** blocked scrape never silently bypasses robots; an allowed fetch yields an Asset
  that then rides the same M.3→M.5 Reader path as a phone recording.

### M.7 — Job / Research wiring + e2e gate
- Research jobs (and any media-capable path) use Metadata Reader + transcript strategy chain.
- Dedupe by content hash / stable source id (e.g. `youtube:<id>`) — P13.
- Events: e.g. `MediaReadFailed`, `MediaMetadataAcquired`, `TranscriptAcquired`, `SpeechToTextGap`
  (names finalised in impl).
- Gate: (1) captions URL → knowledge; (2) local mp4 + Whisper → knowledge; (3) robots-blocked URL →
  honest failure + optional gap, **0 fabricated docs**; (4) assert no Knowledge-layer
  `if youtube` / `if mp4` branches in the new code paths.
- **Acceptance:** gate green; this plan marked complete; `OI-M0` closed.

---

## 5. Proposed data / config additions

| Area | Adds | Slice |
|------|------|-------|
| Code | `ReaderStrategyChain` helper (reusable) | M.2 |
| Assets | `video` / `audio` / `transcript` kinds + source metadata refs | M.3 |
| Artifacts | media **metadata** schema; transcript schema (`text`, `segments[]`, `strategy`, `model_versions`) | M.3–M.5 |
| Config | `plugins.speech` / Whisper enable + model path + languages | M.5 |
| Capability Registry | `speech_to_text` (+ gap self-report); optional `audio_demux` | M.4–M.5 |
| Events | metadata / transcript / gap / read-failed | M.7 |

No Decision Engine or `decision.*` migrations required.

---

## 6. Sequencing & method

Land each slice as its own commit: code → hermetic tests → live smoke where network/models apply →
checkbox in this plan.

Order: **M.1 → M.2** (honesty + reusable chain) → **M.3 → M.4 → M.5** (Asset-first Readers +
optional STT; highest leverage, no provider required) → **M.6** (provider fetch, policy-gated) →
**M.7** (gate).

Depends on / synergizes with: **OI-C1/OI-C2** (neutral Reader Registry), **OI-C5** (ingest
entrypoint), **OI-F5** (P15). Does **not** block on OI-F1–F4.

---

## 7. Open items / deferrals (`OI-M*`)

- **OI-M1** Official YouTube Data API captions (API key) as an extra polite caption strategy.
- **OI-M2** Speaker diarization on transcripts.
- **OI-M3** Streaming / live caption ingest.
- **OI-M4** CCTV / continuous video missions (out of scope until requested).
- **OI-M5** Cloud STT providers (only if local Whisper is insufficient; keep optional).
- **OI-M6** **Video frames → Image / OCR Readers** (slides, diagrams, timeline alignment with
  speech). Architecture already allows it (`Video → Speech | OCR | Images`); **not now**.
- **OI-M7** Apply `ReaderStrategyChain` to non-media Readers (documents, git, OCR, CAD) once the
  media consumer proves the pattern.

---

## 8. Success criteria (operator-facing)

| Today | After this plan |
|-------|-----------------|
| YouTube works only when caption scrape succeeds | Captions **or** (policy-allowed) fetch+STT **or** operator upload — same Knowledge path |
| Blocked URL looks like “Atlas failed to think” | Clear *read never started* / acquisition failure + optional `speech_to_text` gap |
| Local lecture `.mp4` is outside the path | Local video/audio/transcript files learn like any other asset |
| Single brittle strategy | Reusable strategy chain; first `ok` wins; full audit trail |
| Provider logic risks leaking into Knowledge | Provider code stops at Asset registration |

**Can Atlas learn from YouTube?** Yes — today partially (captions only); after M.1–M.7, for the
vast majority of operator-reachable spoken content, without sacrificing P15 or making media special.

---

## 9. Implementation checklist

- [x] **M.1** Diagnose & instrument
- [x] **M.2** `ReaderStrategyChain` + YouTube caption strategies
- [x] **M.3** Media assets + Metadata Reader
- [x] **M.4** Transcript / Audio / Speech Readers (Asset-first)
- [x] **M.5** Optional `speech_to_text` (Whisper)
- [x] **M.6** Provider-agnostic source fetch → Asset
- [ ] **M.7** Wiring + e2e gate → plan complete

---

> **M.1 ✅ DONE** (`atlas/transcripts/acquisition.py` + YouTube `AcquisitionRecord` on every
> `TranscriptResult`; Librarian video path uses `transcript_fetcher` and stamps acquisition into
> skipped/blocked; pipeline traces prefer `operator_summary`; assistant surfaces acquire-vs-reason
> copy; hermetic tests).
>
> **M.2 ✅ DONE** (`atlas/readers/strategy_chain.py` — reusable first-ok chain; YouTube per-language
> caption strategies + `:any` fallback; `strategies_tried[]` audit; `suggested_next_capability=
> speech_to_text` on caption failure).
>
> **M.3 ✅ DONE** (`atlas/readers/media_kinds.py` — `video`/`audio`/`transcript` kinds;
> `MediaMetadataReader` — sidecar + optional ffprobe → metadata artifact, never invents fields;
> mp4/mp3 metadata without transcription).
>
> **M.4 ✅ DONE** (`TranscriptFileReader` / `AudioDemuxReader`; media entries in Reader Registry;
> `MediaIngestor` + `atlas ingest` for local `.vtt`/`.mp4` → Asset → metadata → transcript/demux →
> Knowledge with no YouTube-specific Knowledge branches; speech_to_text deferred to M.5).
>
> **M.5 ✅ DONE** (`SpeechClient`/`WhisperEngine` + `SpeechToTextReader`; `CAP_SPEECH_TO_TEXT` in
> Capability Registry; `plugins.speech` default **off**; model stamped + evidence L1; MediaIngestor
> lands speech transcript when on, explicit `capability_gap` when off/missing).
>
> **M.6 ✅ DONE** (`SourceFetcher` — `local_file` / `http_direct` / `youtube_media` via
> `ReaderStrategyChain`; robots never bypassed; blocked → operator hint; allowed HTTP media →
> Asset → same M.3–M.5 Reader path; `atlas ingest <url>`). **Next: M.7 — Job/Research wiring +
> e2e gate.**
>
> Companion: [`OPEN_ITEMS.md`](OPEN_ITEMS.md) (`OI-M*`), roadmap P8/P11/P15,
> `atlas/transcripts/youtube.py` + `YouTubePlugin`.
>
> **Frozen decisions MD1–MD9 must not be reopened without a new decision-log / plan amendment.**
