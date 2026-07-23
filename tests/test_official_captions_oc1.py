"""OC1 — precise official captions API reason codes."""

from __future__ import annotations

from atlas.transcripts.official_captions import (
    OfficialYouTubeCaptions,
    classify_youtube_api_failure,
)


def test_classify_auth_quota_api():
    assert (
        classify_youtube_api_failure(status_code=403, message="forbidden")
        == "authentication_failed"
    )
    assert (
        classify_youtube_api_failure(
            status_code=403,
            message="quotaExceeded",
            body={"error": {"errors": [{"reason": "quotaExceeded"}], "message": "quota"}},
        )
        == "quota_exceeded"
    )
    assert (
        classify_youtube_api_failure(message="API key not valid. Please pass a valid API key.")
        == "authentication_failed"
    )
    assert classify_youtube_api_failure(status_code=500, message="boom") == "api_error"


def test_official_api_error_body_classified():
    def fetch_json(url: str):
        return {
            "error": {
                "code": 403,
                "message": "The request cannot be completed because you have exceeded your quota.",
                "errors": [{"reason": "quotaExceeded"}],
            }
        }

    client = OfficialYouTubeCaptions("fake-key", fetch_json=fetch_json)
    out = client.fetch("https://youtu.be/abcdefghijk")
    assert out["outcome"] == "error"
    assert out["reason_code"] == "quota_exceeded"


def test_official_not_configured():
    out = OfficialYouTubeCaptions("").fetch("https://youtu.be/abcdefghijk")
    assert out["reason_code"] == "not_configured"
