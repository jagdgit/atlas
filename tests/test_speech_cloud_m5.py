"""OI-M5 cloud STT engine seam (no live API calls)."""

from __future__ import annotations

import os
from pathlib import Path

from atlas.speech.cloud import CloudSttEngine, build_speech_engine
from atlas.speech.engine import (
    CAPABILITY_GAP,
    STT_OK,
    STT_UNAVAILABLE,
    SpeechClient,
    WhisperEngine,
)


class FakeCloudEngine:
    name = "cloud_stt"

    def __init__(self, *, text="hello from cloud", available=True):
        self._text = text
        self._available = available
        self.api_key_env = "ATLAS_SPEECH_API_KEY"

    def available(self):
        return self._available

    def transcribe(self, path, *, model, language):
        return {
            "text": self._text,
            "segments": [{"start": 0, "end": 1, "text": self._text}],
            "model": f"fake-cloud:{model}",
            "language": language or "en",
        }


def test_build_speech_engine_selects_cloud_stub():
    class Cfg:
        engine = "cloud"
        provider = "openai_whisper_api"
        api_key_env = "ATLAS_SPEECH_API_KEY"
        binary = "whisper"
        timeout = 0.0

    eng = build_speech_engine(Cfg())
    assert isinstance(eng, CloudSttEngine)
    assert eng.provider == "openai_whisper_api"


def test_build_speech_engine_default_whisper():
    class Cfg:
        engine = "whisper"
        binary = "whisper"
        timeout = 0.0

    eng = build_speech_engine(Cfg())
    assert isinstance(eng, WhisperEngine)


def test_cloud_engine_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("ATLAS_SPEECH_API_KEY", raising=False)
    eng = CloudSttEngine(provider="openai_whisper_api")
    assert eng.available() is False
    client = SpeechClient(eng, enabled=True, model="base")
    out = client.transcribe("/tmp/does-not-need-to-exist-for-avail-check.wav")
    # available() fails before file check
    assert out["outcome"] == STT_UNAVAILABLE
    assert out["capability_gap"] == CAPABILITY_GAP
    assert "cloud" in out["reason"].lower() or "ATLAS_SPEECH_API_KEY" in out["reason"]


def test_cloud_engine_stub_with_key_still_no_network(monkeypatch, tmp_path):
    monkeypatch.setenv("ATLAS_SPEECH_API_KEY", "test-key-not-real")
    eng = CloudSttEngine(provider="openai_whisper_api")
    assert eng.available() is True
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF....")
    client = SpeechClient(eng, enabled=True, model="whisper-1")
    out = client.transcribe(audio)
    assert out["outcome"] == STT_UNAVAILABLE
    assert "not implemented" in (out.get("reason") or "").lower()
    assert out["capability_gap"] == CAPABILITY_GAP


def test_fake_cloud_engine_ok(tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    client = SpeechClient(FakeCloudEngine(), enabled=True, model="x")
    out = client.transcribe(audio)
    assert out["outcome"] == STT_OK
    assert "cloud" in out["text"]
    assert out["engine"] == "cloud_stt"
