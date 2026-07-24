# Speech-to-Text ops (Phase 1 · OI-STT0)

> Finish spoken-content learning after media Asset + metadata.  
> Code path already exists (`SpeechToTextReader` → global `KnowledgeService`).

## Install (CPU recommended)

Avoid the default CUDA torch wheel (multi‑GB). From the repo:

```bash
cd /data/atlas
uv pip install torch --index-url https://download.pytorch.org/whl/cpu
uv pip install openai-whisper
# optional: also record the extra
# uv sync --extra speech   # after CPU torch is present
```

Verify:

```bash
.venv/bin/python -c "from atlas.speech.engine import WhisperEngine; print(WhisperEngine().available())"
# → True
```

`ffmpeg` must be on PATH (already present on this host).

## Enable

`config/local.yaml`:

```yaml
plugins:
  youtube:
    media_obtain_enabled: true
    media_obtain_timeout: 0          # 0 = wait for yt-dlp
    media_obtain_max_bytes: 209715200
  speech:
    enabled: true
    model: tiny
    timeout: 0                       # 0 = wait for Whisper (long videos on CPU)
```

Restart Atlas. Readiness should show `speech_to_text: ready`.

**Note:** Incomplete yt-dlp leftovers (`*.part`) are refused — they must never become Assets.

Failed Whisper attempts are **not** cached, so fixing `plugins.speech.timeout` and re-running the same Asset retries STT instead of replaying an old timeout error.

## First run note

The first transcription downloads model weights to `~/.cache/whisper/` (~140 MB for `base`).

## Honesty

Until STT succeeds, Learning Reports say **metadata learned**, not “learned investing from the video,” and show Knowledge categories (`metadata` vs `transcript` / concepts…).
