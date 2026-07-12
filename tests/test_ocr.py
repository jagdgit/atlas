"""Tests for the OCR capability (S20c).

The client + sandbox + outcome mapping are hermetic via an injectable fake engine.
The default `TesseractEngine` is exercised only when the system dependencies are
actually present (otherwise skipped), and it must report `unavailable` — never raise —
when they are not.
"""

from __future__ import annotations

import pytest

from atlas.ocr.engine import (
    OCR_EMPTY,
    OCR_ERROR,
    OCR_OK,
    OCR_UNAVAILABLE,
    OCR_UNSUPPORTED,
    OCRClient,
    OCREngineError,
    OCRUnavailable,
    OCRUnsupported,
    TesseractEngine,
)
from atlas.plugins.ocr_plugin import OCRPlugin


class FakeEngine:
    name = "fake"

    def __init__(self, *, text="", exc=None, available=True):
        self._text = text
        self._exc = exc
        self._available = available

    def available(self):
        return self._available

    def image_to_text(self, path, *, lang):
        if self._exc is not None:
            raise self._exc
        return self._text


def _img(tmp_path, name="scan.png"):
    p = tmp_path / name
    p.write_bytes(b"\x89PNG\r\n\x1a\n fake image bytes")
    return p


# --- outcome mapping -----------------------------------------------------
def test_image_ok(tmp_path):
    _img(tmp_path)
    client = OCRClient(FakeEngine(text="  Hello world \n"), tmp_path)
    res = client.image("scan.png")
    assert res["outcome"] == OCR_OK
    assert res["text"] == "Hello world"
    assert res["chars"] == 11
    assert res["engine"] == "fake"


def test_image_empty_when_no_text(tmp_path):
    _img(tmp_path)
    res = OCRClient(FakeEngine(text="   \n  "), tmp_path).image("scan.png")
    assert res["outcome"] == OCR_EMPTY
    assert res["text"] == ""


def test_missing_file_is_unavailable(tmp_path):
    res = OCRClient(FakeEngine(text="x"), tmp_path).image("nope.png")
    assert res["outcome"] == OCR_UNAVAILABLE


def test_escape_is_unavailable(tmp_path):
    res = OCRClient(FakeEngine(text="x"), tmp_path).image("../secret.png")
    assert res["outcome"] == OCR_UNAVAILABLE


def test_non_image_suffix_is_unsupported(tmp_path):
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    res = OCRClient(FakeEngine(text="x"), tmp_path).image("notes.txt")
    assert res["outcome"] == OCR_UNSUPPORTED


def test_too_large_is_unsupported(tmp_path):
    _img(tmp_path)
    res = OCRClient(FakeEngine(text="x"), tmp_path, max_bytes=4).image("scan.png")
    assert res["outcome"] == OCR_UNSUPPORTED


def test_engine_unavailable_is_reported(tmp_path):
    _img(tmp_path)
    res = OCRClient(FakeEngine(exc=OCRUnavailable("no tesseract")), tmp_path).image("scan.png")
    assert res["outcome"] == OCR_UNAVAILABLE
    assert "tesseract" in res["reason"]


def test_engine_unsupported_is_reported(tmp_path):
    _img(tmp_path)
    res = OCRClient(FakeEngine(exc=OCRUnsupported("bad image")), tmp_path).image("scan.png")
    assert res["outcome"] == OCR_UNSUPPORTED


def test_engine_error_is_reported(tmp_path):
    _img(tmp_path)
    res = OCRClient(FakeEngine(exc=OCREngineError("boom")), tmp_path).image("scan.png")
    assert res["outcome"] == OCR_ERROR


def test_engine_crash_never_raises(tmp_path):
    _img(tmp_path)
    res = OCRClient(FakeEngine(exc=RuntimeError("kaboom")), tmp_path).image("scan.png")
    assert res["outcome"] == OCR_ERROR
    assert "kaboom" in res["reason"]


def test_custom_lang_passed_through(tmp_path):
    _img(tmp_path)
    res = OCRClient(FakeEngine(text="bonjour"), tmp_path, default_lang="eng").image(
        "scan.png", lang="fra"
    )
    assert res["lang"] == "fra"
    assert res["outcome"] == OCR_OK


# --- plugin wiring -------------------------------------------------------
def test_plugin_delegates_and_health(tmp_path):
    _img(tmp_path)
    plugin = OCRPlugin(OCRClient(FakeEngine(text="hi", available=False), tmp_path))
    res = plugin.image("scan.png")
    assert res["outcome"] == OCR_OK
    # A missing OCR backend is a *degraded* (not failed) health state.
    health = plugin.health_check()
    assert health.healthy is True
    assert health.data["available"] is False


class _Kernel:
    def __init__(self) -> None:
        caps: dict = {}
        tools: dict = {}
        self.caps = caps
        self.tool_map = tools

        class _Caps:
            def register(self, name, provider, *, contract=None, kind=None):
                caps[name] = provider

        class _Tools:
            def register(self, name, fn, *, description="", params=None, plugin=None):
                tools[name] = fn

        self.capabilities = _Caps()
        self.tools = _Tools()


def test_plugin_registers_capability_and_tool(tmp_path):
    plugin = OCRPlugin(OCRClient(FakeEngine(), tmp_path))
    kernel = _Kernel()
    plugin.register(kernel)
    assert "ocr" in kernel.caps
    assert "ocr.image" in kernel.tool_map


# --- default engine: honest, never raises --------------------------------
def test_tesseract_engine_degrades_or_reads(tmp_path):
    engine = TesseractEngine()
    if not engine.available():
        # Deps/binary missing → client must return `unavailable`, not raise.
        _img(tmp_path)
        res = OCRClient(engine, tmp_path).image("scan.png")
        assert res["outcome"] == OCR_UNAVAILABLE
        return
    # Deps present: render a real image with text and read it back.
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (220, 60), "white")
    ImageDraw.Draw(img).text((10, 20), "HELLO", fill="black")
    img.save(tmp_path / "hello.png")
    res = OCRClient(engine, tmp_path).image("hello.png")
    assert res["outcome"] in (OCR_OK, OCR_EMPTY)
    if res["outcome"] == OCR_OK:
        assert "HELLO" in res["text"].upper()
