"""Browser DOM captions strategy (BA.1)."""

from __future__ import annotations

from atlas.ingestion.browser_captions import (
    STRATEGY_BROWSER_DOM_CAPTIONS,
    browser_dom_captions,
    extract_caption_tracks_json,
    text_looks_like_transcript,
)
from atlas.ingestion.media_learn import MediaLearnOrchestrator


def test_extract_caption_tracks_from_html():
    html = 'var x={"captionTracks":[{"baseUrl":"https://example.com/tt","languageCode":"en"}]}'
    tracks = extract_caption_tracks_json(html)
    assert tracks and tracks[0]["languageCode"] == "en"


def test_text_looks_like_transcript():
    assert not text_looks_like_transcript("short")
    body = "\n".join(f"00:{i:02d} line of spoken words here" for i in range(5))
    assert text_looks_like_transcript(body)


def test_browser_dom_captions_ok_via_timedtext():
    html = (
        '"captionTracks":[{"baseUrl":"https://ex.test/tt?lang=en",'
        '"languageCode":"en"}]'
    )

    def render(url: str):
        return {
            "outcome": "ok",
            "title": "Talk",
            "text": "watch page chrome",
            "html": html,
            "final_url": url,
        }

    def timedtext(u: str) -> str:
        return "<text>Hello from captions.</text><text> More speech.</text>"

    out = browser_dom_captions(
        "https://youtu.be/abcdefghijk",
        render=render,
        fetch_timedtext=timedtext,
    )
    assert out["strategy"] == STRATEGY_BROWSER_DOM_CAPTIONS
    assert out["outcome"] == "ok"
    assert "Hello from captions" in out["text"]


def test_media_learn_uses_browser_when_captions_fail():
    orch = MediaLearnOrchestrator(
        caption_fetch=lambda v: {
            "outcome": "blocked",
            "reason_code": "robots_disallowed",
            "text": "",
            "acquisition": {
                "strategies_tried": [
                    {
                        "strategy": "youtube_watch_page",
                        "outcome": "blocked",
                        "reason_code": "robots_disallowed",
                        "bytes_read": 0,
                    }
                ]
            },
        },
        browser_render=lambda u: {
            "outcome": "ok",
            "title": "Lecture",
            "text": "\n".join(
                f"00:{i:02d} spoken content about solar panels and energy"
                for i in range(8)
            ),
            "html": "",
        },
        media_ingestor=None,
        knowledge=None,
    )
    result = orch.learn("https://youtu.be/abcdefghijk")
    assert result["outcome"] == "ok"
    assert "solar" in result["text"].lower()
    names = [s["strategy"] for s in result["strategies"]]
    assert STRATEGY_BROWSER_DOM_CAPTIONS in names
