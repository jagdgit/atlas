"""YouTube transcript tests (S18a).

Hermetic: a fake FetchClient returns a canned watch page (with a captionTracks blob)
and a canned timedtext XML, so the two-step scrape + cue parsing is verified without
touching YouTube.
"""

from __future__ import annotations

from atlas.net import OUTCOME_BLOCKED, OUTCOME_OK, FetchResult
from atlas.plugins.youtube_plugin import YouTubePlugin
from atlas.transcripts import YouTubeTranscriptProvider

_WATCH_PAGE = (
    '<html><head><title>Test</title></head><body>'
    '<script>var x = {"title":"How Solar Panels Work",'
    '"captionTracks":[{"baseUrl":"https://youtube.com/api/timedtext?v=abc\\u0026lang=en",'
    '"languageCode":"en"}]};</script></body></html>'
)
_TIMEDTEXT = (
    '<?xml version="1.0"?><transcript>'
    '<text start="0.0" dur="1.5">Solar panels convert sunlight</text>'
    '<text start="1.5" dur="2.0">into electricity &amp; heat</text>'
    '</transcript>'
)


class FakeClient:
    def __init__(self, by_substr):
        self._by_substr = by_substr
        self.calls = []

    def get(self, url, **kw):
        self.calls.append(url)
        for sub, result in self._by_substr.items():
            if sub in url:
                return result
        return FetchResult(url, OUTCOME_OK, text="")


def _provider():
    client = FakeClient(
        {
            "watch": FetchResult("u", OUTCOME_OK, text=_WATCH_PAGE),
            "timedtext": FetchResult("u", OUTCOME_OK, text=_TIMEDTEXT),
        }
    )
    return YouTubeTranscriptProvider(client), client


def test_transcript_ok_full_flow():
    prov, client = _provider()
    result = prov.fetch("https://www.youtube.com/watch?v=abcdefghijk")
    assert result.ok
    assert result.title == "How Solar Panels Work"
    assert result.language == "en"
    assert "Solar panels convert sunlight" in result.text
    assert "electricity & heat" in result.text  # entity decoded
    assert len(result.segments) == 2
    assert result.as_source()["evidence_level"] == 1
    assert len(client.calls) == 2  # watch page + timedtext


def test_transcript_bad_id_is_error():
    prov, _ = _provider()
    result = prov.fetch("https://example.com/notyoutube")
    assert result.outcome == "error"
    assert "video id" in (result.reason or "")


def test_transcript_no_captions_is_skipped():
    client = FakeClient({"watch": FetchResult("u", OUTCOME_OK, text="<html>no tracks</html>")})
    result = YouTubeTranscriptProvider(client).fetch("abcdefghijk")
    assert result.outcome == "skipped"


def test_transcript_blocked_watch_page():
    client = FakeClient({"watch": FetchResult("u", OUTCOME_BLOCKED, reason="429")})
    result = YouTubeTranscriptProvider(client).fetch("abcdefghijk")
    assert result.outcome == OUTCOME_BLOCKED
    assert result.reason == "429"


def test_language_preference_picks_matching_track():
    page = (
        '<html><title>Multi</title><script>{"captionTracks":['
        '{"baseUrl":"https://x/timedtext?lang=fr","languageCode":"fr"},'
        '{"baseUrl":"https://x/timedtext?lang=en","languageCode":"en"}]}</script></html>'
    )
    client = FakeClient(
        {"watch": FetchResult("u", OUTCOME_OK, text=page),
         "timedtext": FetchResult("u", OUTCOME_OK, text=_TIMEDTEXT)}
    )
    prov = YouTubeTranscriptProvider(client, languages=["en"])
    result = prov.fetch("abcdefghijk")
    assert result.ok
    assert result.language == "en"


def test_youtube_plugin_tool_returns_dict():
    prov, _ = _provider()
    out = YouTubePlugin(prov).youtube_transcript("https://youtu.be/abcdefghijk")
    assert out["outcome"] == "ok"
    assert out["text"]
    assert YouTubePlugin(prov).health_check().healthy
