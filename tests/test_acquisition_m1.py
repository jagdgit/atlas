"""Media acquisition record taxonomy + YouTube instrumentation (M.1)."""

from __future__ import annotations

from atlas.net import OUTCOME_BLOCKED, OUTCOME_OK, OUTCOME_SKIPPED, FetchResult
from atlas.transcripts.acquisition import (
    REASON_BAD_VIDEO_ID,
    REASON_NO_CAPTIONS,
    REASON_ROBOTS_DISALLOWED,
    STRATEGY_YOUTUBE_CAPTION_TRACKS,
    AcquisitionAttempt,
    AcquisitionRecord,
    normalize_reason_code,
)
from atlas.transcripts.youtube import YouTubeTranscriptProvider


def test_normalize_robots_disallowed():
    assert normalize_reason_code("skipped", "robots.txt disallows this URL") == REASON_ROBOTS_DISALLOWED


def test_normalize_no_captions():
    assert normalize_reason_code("skipped", "no captions available for this video") == REASON_NO_CAPTIONS


def test_normalize_bad_id():
    assert normalize_reason_code("error", "could not parse a YouTube video id") == REASON_BAD_VIDEO_ID


def test_operator_summary_marks_acquire_stop():
    attempt = AcquisitionAttempt(
        strategy=STRATEGY_YOUTUBE_CAPTION_TRACKS,
        outcome="skipped",
        reason="robots.txt disallows this URL",
        reason_code=REASON_ROBOTS_DISALLOWED,
        bytes_read=0,
    )
    rec = AcquisitionRecord.from_attempts([attempt], source_url="https://youtube.com/watch?v=abcdefghijk")
    assert not rec.ok
    assert rec.stage == "acquire"
    summary = rec.operator_summary
    assert "Acquisition failed before read" in summary
    assert "No document was fabricated" in summary
    assert STRATEGY_YOUTUBE_CAPTION_TRACKS in summary
    d = rec.as_dict()
    assert d["read_started"] is False
    assert d["reason_code"] == REASON_ROBOTS_DISALLOWED


def test_youtube_blocked_carries_acquisition_record():
    class Client:
        def get(self, url, **kw):
            return FetchResult(url, OUTCOME_BLOCKED, reason="robots.txt disallows this URL")

    result = YouTubeTranscriptProvider(Client()).fetch("abcdefghijk")
    assert result.outcome == OUTCOME_BLOCKED
    assert result.acquisition is not None
    assert result.acquisition.reason_code == REASON_ROBOTS_DISALLOWED
    payload = result.as_dict()
    assert payload["reason_code"] == REASON_ROBOTS_DISALLOWED
    assert payload["bytes_read"] == 0
    assert payload["strategies_tried"][0]["strategy"] == STRATEGY_YOUTUBE_CAPTION_TRACKS
    assert "Acquisition failed before read" in payload["operator_summary"]
    assert payload["acquisition"]["stage"] == "acquire"


def test_youtube_no_captions_acquisition_record():
    class Client:
        def get(self, url, **kw):
            return FetchResult(url, OUTCOME_OK, text="<html>no tracks</html>")

    result = YouTubeTranscriptProvider(Client()).fetch("abcdefghijk")
    assert result.outcome == OUTCOME_SKIPPED
    assert result.acquisition.reason_code == REASON_NO_CAPTIONS
    assert result.as_dict()["bytes_read"] > 0  # watch page was read


def test_youtube_ok_includes_strategy_audit():
    watch = (
        '<html><script>{"title":"T","captionTracks":['
        '{"baseUrl":"https://x/timedtext?lang=en","languageCode":"en"}]}</script></html>'
    )
    timed = (
        '<?xml version="1.0"?><transcript>'
        '<text start="0" dur="1">hello world</text></transcript>'
    )

    class Client:
        def get(self, url, **kw):
            if "timedtext" in url:
                return FetchResult(url, OUTCOME_OK, text=timed)
            return FetchResult(url, OUTCOME_OK, text=watch)

    result = YouTubeTranscriptProvider(Client()).fetch("abcdefghijk")
    assert result.ok
    assert result.acquisition.ok
    assert "Acquisition succeeded" in result.acquisition.operator_summary
    assert result.as_dict()["strategies_tried"]
