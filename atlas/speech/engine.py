"""Speech-to-text client + Whisper engine (Media Reader Family · M.5).

``SpeechClient`` turns an audio/video file into transcript text through an injectable
``SpeechEngine`` (default ``WhisperEngine``). The engine seam keeps clients hermetic in
tests; the real engine **degrades gracefully**: missing binary/model/deps →
``unavailable`` + ``capability_gap: speech_to_text`` (P15), never a crash.

Default **off** until ``plugins.speech.enabled`` is set (MD5).
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Protocol

STT_OK = "ok"
STT_EMPTY = "empty"
STT_UNAVAILABLE = "unavailable"
STT_ERROR = "error"

CAPABILITY_GAP = "speech_to_text"


class SpeechUnavailable(Exception):
    """Engine/deps/config not usable → unavailable."""


class SpeechEngineError(Exception):
    """Engine failed on a valid input → error."""


class SpeechEngine(Protocol):
    name: str

    def available(self) -> bool:
        """True iff the engine can run (binary or package present)."""
        ...

    def transcribe(
        self, path: str, *, model: str, language: str | None
    ) -> dict[str, Any]:
        """Return ``{text, segments[], model, language}``. Raise on failure."""
        ...


class WhisperEngine:
    """Default engine: OpenAI Whisper via CLI (preferred) or optional Python package.

    All imports/subprocess are lazy so importing this module never requires Whisper.
    """

    name = "whisper"

    def __init__(
        self,
        *,
        binary: str = "whisper",
        timeout: float = 600.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self._binary = binary
        self._timeout = timeout
        self._logger = logger or logging.getLogger("atlas.speech.whisper")

    def available(self) -> bool:
        if shutil.which(self._binary):
            return True
        try:
            import whisper  # noqa: F401

            return True
        except Exception:  # noqa: BLE001
            return False

    def transcribe(
        self, path: str, *, model: str, language: str | None
    ) -> dict[str, Any]:
        if shutil.which(self._binary):
            return self._via_cli(path, model=model, language=language)
        return self._via_python(path, model=model, language=language)

    def _via_cli(
        self, path: str, *, model: str, language: str | None
    ) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="atlas-whisper-") as tmp:
            cmd = [
                self._binary,
                path,
                "--model", model,
                "--output_dir", tmp,
                "--output_format", "json",
                "--verbose", "False",
            ]
            if language:
                cmd.extend(["--language", language])
            try:
                proc = subprocess.run(
                    cmd,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                )
            except subprocess.TimeoutExpired as exc:
                raise SpeechEngineError(f"whisper timed out after {self._timeout}s") from exc
            except FileNotFoundError as exc:
                raise SpeechUnavailable(f"whisper binary not found: {exc}") from exc
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or "").strip()
                raise SpeechEngineError(err or f"whisper exit {proc.returncode}")
            stem = Path(path).stem
            json_path = Path(tmp) / f"{stem}.json"
            if not json_path.is_file():
                # Some whisper builds nest or rename; take the only json.
                candidates = list(Path(tmp).rglob("*.json"))
                if not candidates:
                    raise SpeechEngineError("whisper produced no json output")
                json_path = candidates[0]
            try:
                payload = json.loads(json_path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                raise SpeechEngineError(f"could not parse whisper json: {exc}") from exc
            return _normalize_whisper_payload(payload, model=model, language=language)

    def _via_python(
        self, path: str, *, model: str, language: str | None
    ) -> dict[str, Any]:
        try:
            import whisper
        except Exception as exc:  # noqa: BLE001
            raise SpeechUnavailable(
                "whisper CLI and Python package both unavailable"
            ) from exc
        try:
            loaded = whisper.load_model(model)
            kwargs: dict[str, Any] = {}
            if language:
                kwargs["language"] = language
            payload = loaded.transcribe(path, **kwargs)
        except SpeechUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SpeechEngineError(str(exc)) from exc
        return _normalize_whisper_payload(payload, model=model, language=language)


def _normalize_whisper_payload(
    payload: dict[str, Any], *, model: str, language: str | None
) -> dict[str, Any]:
    text = str(payload.get("text") or "").strip()
    raw_segments = payload.get("segments") if isinstance(payload.get("segments"), list) else []
    segments: list[dict[str, Any]] = []
    for seg in raw_segments:
        if not isinstance(seg, dict):
            continue
        body = str(seg.get("text") or "").strip()
        if not body:
            continue
        segments.append(
            {
                "start": seg.get("start", ""),
                "end": seg.get("end", ""),
                "text": body,
            }
        )
    lang = payload.get("language") or language
    return {
        "text": text,
        "segments": segments,
        "model": f"whisper:{model}",
        "language": lang,
    }


class SpeechClient:
    """Orchestrate enabled-check → engine → honest outcome dict (never raises)."""

    def __init__(
        self,
        engine: SpeechEngine,
        *,
        enabled: bool = False,
        model: str = "base",
        language: str | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._engine = engine
        self._enabled = bool(enabled)
        self._model = model
        self._language = language
        self._logger = logger or logging.getLogger("atlas.speech")

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def model(self) -> str:
        return self._model

    def available(self) -> bool:
        return self._enabled and self._engine.available()

    def transcribe(self, path: str | Path, *, language: str | None = None) -> dict[str, Any]:
        p = Path(path)
        lang = language if language is not None else self._language
        base: dict[str, Any] = {
            "path": str(p),
            "engine": getattr(self._engine, "name", "unknown"),
            "model": f"whisper:{self._model}",
            "capability_gap": CAPABILITY_GAP,
            "evidence_level": 1,
        }
        if not self._enabled:
            return {
                **base,
                "outcome": STT_UNAVAILABLE,
                "text": "",
                "segments": [],
                "reason": "speech_to_text disabled (set plugins.speech.enabled)",
            }
        if not self._engine.available():
            return {
                **base,
                "outcome": STT_UNAVAILABLE,
                "text": "",
                "segments": [],
                "reason": "speech_to_text unavailable (whisper not installed)",
            }
        if not p.is_file():
            return {
                **base,
                "outcome": STT_ERROR,
                "text": "",
                "segments": [],
                "reason": f"not a file: {p}",
            }
        try:
            result = self._engine.transcribe(
                str(p), model=self._model, language=lang
            )
        except SpeechUnavailable as exc:
            return {
                **base,
                "outcome": STT_UNAVAILABLE,
                "text": "",
                "segments": [],
                "reason": str(exc),
            }
        except SpeechEngineError as exc:
            self._logger.debug("speech transcribe failed: %s", exc)
            return {
                **base,
                "outcome": STT_ERROR,
                "text": "",
                "segments": [],
                "reason": str(exc),
            }
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("speech transcribe crashed: %s", exc)
            return {
                **base,
                "outcome": STT_ERROR,
                "text": "",
                "segments": [],
                "reason": str(exc),
            }

        text = str(result.get("text") or "").strip()
        segments = result.get("segments") if isinstance(result.get("segments"), list) else []
        out = {
            **base,
            "model": result.get("model") or base["model"],
            "language": result.get("language") or lang,
            "text": text,
            "segments": segments,
            "capability_gap": None,
        }
        if not text:
            return {**out, "outcome": STT_EMPTY, "reason": "no speech recognised"}
        return {
            **out,
            "outcome": STT_OK,
            "reason": None,
            "char_count": len(text),
        }
