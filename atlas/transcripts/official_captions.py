"""YouTube Data API v3 captions strategy (OI-M1) — executable when ``api_key`` set.

Lists caption tracks via the official API. Downloading track bodies typically
requires OAuth; when download is unavailable we return an honest outcome with
video metadata so the strategy is still a real attempt (not suggestion-only).

OC1: API failures use precise ``reason_code`` values
(``not_configured``, ``authentication_failed``, ``quota_exceeded``, ``api_error``, …)
instead of a single generic ``official_api_error``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable
from urllib.parse import urlencode

from atlas.ingestion.source_fetch import is_youtube_url, youtube_video_id
from atlas.transcripts.acquisition import STRATEGY_YOUTUBE_OFFICIAL_CAPTIONS

FetchJson = Callable[[str], dict[str, Any]]


class OfficialCaptionsFetchError(Exception):
    """Transport/API failure with a classified ``reason_code`` (OC1)."""

    def __init__(
        self,
        reason_code: str,
        message: str,
        *,
        status_code: int | None = None,
        payload: Any = None,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.status_code = status_code
        self.payload = payload


def classify_youtube_api_failure(
    *,
    status_code: int | None = None,
    message: str = "",
    body: str | dict[str, Any] | None = None,
    outcome: str | None = None,
) -> str:
    """Map HTTP / API error signals → stable reason_code (OC1)."""
    msg = (message or "").lower()
    text = body if isinstance(body, str) else ""
    err_obj: dict[str, Any] = {}
    if isinstance(body, dict):
        err_obj = body.get("error") if isinstance(body.get("error"), dict) else body
        text = json.dumps(body)
    elif text.strip().startswith("{"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                err_obj = parsed.get("error") if isinstance(parsed.get("error"), dict) else parsed
        except json.JSONDecodeError:
            pass

    blob = " ".join(
        [
            msg,
            text.lower(),
            str(err_obj.get("message") or "").lower(),
            str(err_obj.get("status") or "").lower(),
            " ".join(str(e.get("reason") or "") for e in (err_obj.get("errors") or []) if isinstance(e, dict)),
        ]
    )

    if outcome == "blocked" or status_code in (401, 403):
        if "quota" in blob or "dailylimitexceeded" in blob or "usageratelimitexceeded" in blob:
            return "quota_exceeded"
        return "authentication_failed"
    if status_code == 429 or "quota" in blob or "ratelimit" in blob.replace(" ", ""):
        return "quota_exceeded"
    if "api key not valid" in blob or "invalid api key" in blob or "keyinvalid" in blob:
        return "authentication_failed"
    if "not configured" in blob or outcome == "unavailable":
        return "not_configured"
    if status_code and status_code >= 400:
        return "api_error"
    if blob.strip():
        return "api_error"
    return "api_error"


class OfficialYouTubeCaptions:
    """``youtube_official_captions`` automatic strategy (requires API key)."""

    def __init__(
        self,
        api_key: str,
        *,
        fetch_json: FetchJson | None = None,
        fetch_bytes: Callable[[str], bytes] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._key = (api_key or "").strip()
        self._fetch_json = fetch_json
        self._fetch_bytes = fetch_bytes
        self._logger = logger or logging.getLogger("atlas.transcripts.official_captions")

    @property
    def configured(self) -> bool:
        return bool(self._key)

    def fetch(self, video: str) -> dict[str, Any]:
        if not self._key:
            return {
                "outcome": "skipped",
                "reason_code": "not_configured",
                "reason": "YouTube Data API key not configured",
                "text": "",
                "strategy": STRATEGY_YOUTUBE_OFFICIAL_CAPTIONS,
            }
        if not is_youtube_url(video) and len((video or "").strip()) != 11:
            return {
                "outcome": "skipped",
                "reason_code": "not_applicable",
                "reason": "not a YouTube URL/id",
                "text": "",
                "strategy": STRATEGY_YOUTUBE_OFFICIAL_CAPTIONS,
            }
        vid = youtube_video_id(video) or (video.strip() if len(video.strip()) == 11 else "")
        if not vid:
            return {
                "outcome": "error",
                "reason_code": "bad_video_id",
                "reason": "could not parse video id",
                "text": "",
                "strategy": STRATEGY_YOUTUBE_OFFICIAL_CAPTIONS,
            }

        try:
            meta = self._videos_list(vid)
        except OfficialCaptionsFetchError as exc:
            return self._err(exc.reason_code, str(exc))
        except Exception as exc:  # noqa: BLE001
            self._logger.exception("official videos.list failed")
            code = classify_youtube_api_failure(message=str(exc))
            return self._err(code, str(exc))

        items = (meta or {}).get("items") or []
        if not items:
            return {
                "outcome": "skipped",
                "reason_code": "private_or_unavailable",
                "reason": "videos.list returned no items",
                "text": "",
                "title": None,
                "strategy": STRATEGY_YOUTUBE_OFFICIAL_CAPTIONS,
                "metadata": meta,
            }
        snippet = items[0].get("snippet") or {}
        title = snippet.get("title") or ""

        try:
            caps = self._captions_list(vid)
        except OfficialCaptionsFetchError as exc:
            return self._err(exc.reason_code, f"captions.list failed: {exc}", title=title)
        except Exception as exc:  # noqa: BLE001
            code = classify_youtube_api_failure(message=str(exc))
            return self._err(code, f"captions.list failed: {exc}", title=title)

        tracks = (caps or {}).get("items") or []
        if not tracks:
            return {
                "outcome": "skipped",
                "reason_code": "no_captions",
                "reason": "official API lists no caption tracks",
                "text": "",
                "title": title,
                "strategy": STRATEGY_YOUTUBE_OFFICIAL_CAPTIONS,
                "metadata": {"video": items[0], "captions": caps},
            }

        # Attempt download for the first track (often requires OAuth — be honest).
        track_id = tracks[0].get("id")
        if track_id and self._fetch_bytes is not None:
            try:
                raw = self._fetch_bytes(self._caption_download_url(str(track_id)))
                text = raw.decode("utf-8", errors="replace").strip() if raw else ""
                if text and not text.lstrip().startswith("{"):
                    return {
                        "outcome": "ok",
                        "reason_code": "ok",
                        "reason": None,
                        "text": text,
                        "title": title,
                        "bytes_read": len(raw),
                        "strategy": STRATEGY_YOUTUBE_OFFICIAL_CAPTIONS,
                        "metadata": {"caption_id": track_id},
                    }
                if text.lstrip().startswith("{"):
                    err = json.loads(text)
                    msg = (
                        ((err.get("error") or {}).get("message"))
                        or "caption download rejected"
                    )
                    code = classify_youtube_api_failure(message=str(msg), body=err)
                    if code == "api_error":
                        code = "api_download_requires_oauth"
                    return {
                        "outcome": "skipped",
                        "reason_code": code,
                        "reason": str(msg),
                        "text": "",
                        "title": title,
                        "strategy": STRATEGY_YOUTUBE_OFFICIAL_CAPTIONS,
                        "metadata": {
                            "captions_listed": len(tracks),
                            "download_error": err,
                        },
                    }
            except OfficialCaptionsFetchError as exc:
                return self._err(exc.reason_code, str(exc), title=title)
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("caption download failed: %s", exc)

        return {
            "outcome": "skipped",
            "reason_code": "api_download_requires_oauth",
            "reason": (
                f"official API listed {len(tracks)} caption track(s) but download "
                "requires OAuth or is unavailable with API key alone"
            ),
            "text": "",
            "title": title,
            "strategy": STRATEGY_YOUTUBE_OFFICIAL_CAPTIONS,
            "metadata": {"captions_listed": len(tracks)},
        }

    def _err(self, reason_code: str, reason: str, *, title: str | None = None) -> dict[str, Any]:
        return {
            "outcome": "error",
            "reason_code": reason_code,
            "reason": reason,
            "text": "",
            "title": title,
            "strategy": STRATEGY_YOUTUBE_OFFICIAL_CAPTIONS,
        }

    def _api(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        q = dict(params)
        q["key"] = self._key
        url = f"https://www.googleapis.com/youtube/v3/{path}?{urlencode(q)}"
        if self._fetch_json is None:
            raise OfficialCaptionsFetchError(
                "not_configured",
                "fetch_json not configured",
            )
        data = self._fetch_json(url)
        if isinstance(data, dict) and data.get("error"):
            err = data.get("error") or {}
            msg = str(err.get("message") or "YouTube API error")
            code = classify_youtube_api_failure(message=msg, body=data)
            raise OfficialCaptionsFetchError(code, msg, payload=data)
        return data if isinstance(data, dict) else {}

    def _videos_list(self, video_id: str) -> dict[str, Any]:
        return self._api("videos", {"part": "snippet,contentDetails", "id": video_id})

    def _captions_list(self, video_id: str) -> dict[str, Any]:
        return self._api("captions", {"part": "snippet", "videoId": video_id})

    def _caption_download_url(self, caption_id: str) -> str:
        return (
            f"https://www.googleapis.com/youtube/v3/captions/{caption_id}"
            f"?{urlencode({'key': self._key, 'tfmt': 'srt'})}"
        )
