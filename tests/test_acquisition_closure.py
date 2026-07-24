"""BA.1b / MO.6 / CR.1 / OI-M1 — acquisition closure hermetic tests."""

from __future__ import annotations

from atlas.ingestion.acquire import AcquiredAsset
from atlas.ingestion.media_learn import MediaLearnOrchestrator
from atlas.ingestion.media_readiness import build_media_readiness, format_readiness_block
from atlas.readers.media_kinds import ASSET_KIND_METADATA, ASSET_KIND_TRANSCRIPT
from atlas.reports.generator import ReportGenerator
from atlas.transcripts.acquisition import STRATEGY_YOUTUBE_OFFICIAL_CAPTIONS
from atlas.transcripts.official_captions import OfficialYouTubeCaptions


class FakeAcquirer:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._n = 0

    def acquire_bytes(self, data, *, kind="document", filename=None, source_uri=None,
                      content_type=None, metadata=None):
        self._n += 1
        self.calls.append({"kind": kind, "filename": filename, "bytes": len(data),
                           "metadata": metadata})
        return AcquiredAsset(
            asset_id=f"a{self._n}",
            asset_version=1,
            kind=kind,
            name="sha",
            checksum="sha",
            content_type=content_type,
            source_uri=source_uri,
            size_bytes=len(data),
            reused=False,
            source=filename or "bytes",
        )


def test_ba1b_metadata_asset_when_browser_opens_without_captions():
    acq = FakeAcquirer()
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
            "title": "Some Talk",
            "text": "Subscribe Share",
            "html": "<html></html>",
            "final_url": u,
        },
        asset_acquirer=acq,
        media_ingestor=None,
        readiness=lambda: build_media_readiness(
            browser="ready",
            official_captions="not_configured",
            speech_to_text="missing",
        ),
    )
    result = orch.learn("https://youtu.be/abcdefghijk", to_knowledge=False)
    assert result["outcome"] == "waiting"
    browser_rows = [
        s for s in result["strategies"] if s["strategy"] == "browser_dom_captions"
    ]
    assert browser_rows
    row = browser_rows[0]
    assert row["reason_code"] == "no_caption_nodes_found"
    assert row["asset_id"] == "a1"
    assert row["asset_kind"] == ASSET_KIND_METADATA
    assert acq.calls and acq.calls[0]["kind"] == ASSET_KIND_METADATA
    assert result.get("readiness")
    assert "capabilities" in result["readiness"]


def test_ba1b_transcript_asset_when_dom_captions_found():
    acq = FakeAcquirer()
    body = "\n".join(
        f"00:{i:02d} spoken content about solar panels and energy storage"
        for i in range(8)
    )
    orch = MediaLearnOrchestrator(
        caption_fetch=lambda v: {
            "outcome": "skipped",
            "text": "",
            "acquisition": {"strategies_tried": []},
        },
        browser_render=lambda u: {
            "outcome": "ok",
            "title": "Lecture",
            "text": body,
            "html": "",
        },
        asset_acquirer=acq,
        media_ingestor=None,
    )
    result = orch.learn("https://youtu.be/abcdefghijk", to_knowledge=False)
    assert result["outcome"] == "ok"
    row = next(s for s in result["strategies"] if s["strategy"] == "browser_dom_captions")
    assert row["reason_code"] == "asset_produced"
    assert row["asset_kind"] == ASSET_KIND_TRANSCRIPT
    assert row["asset_id"]


def test_cr2_official_api_not_configured_one_skip_row():
    orch = MediaLearnOrchestrator(
        caption_fetch=lambda v: {
            "outcome": "blocked",
            "text": "",
            "acquisition": {
                "strategies_tried": [
                    {
                        "strategy": "youtube_caption_tracks",
                        "outcome": "blocked",
                        "reason_code": "robots_disallowed",
                        "bytes_read": 0,
                    }
                ]
            },
        },
        official_captions_api=None,
        browser_render=None,
        media_ingestor=None,
    )
    result = orch.learn("https://youtu.be/abcdefghijk", to_knowledge=False)
    official = [
        s for s in result["strategies"]
        if s["strategy"] == STRATEGY_YOUTUBE_OFFICIAL_CAPTIONS
    ]
    assert len(official) == 1
    assert official[0]["outcome"] == "skipped"
    assert official[0]["reason_code"] == "not_configured"


def test_oi_m1_official_api_lists_captions_honest_oauth_gap():
    def fetch_json(url: str) -> dict:
        if "videos" in url:
            return {
                "items": [{"snippet": {"title": "API Talk"}, "id": "abcdefghijk"}]
            }
        if "captions" in url:
            return {"items": [{"id": "cap1", "snippet": {"language": "en"}}]}
        return {}

    client = OfficialYouTubeCaptions(
        "test-key",
        fetch_json=fetch_json,
        fetch_bytes=lambda u: b'{"error":{"message":"Login Required"}}',
    )
    out = client.fetch("https://youtu.be/abcdefghijk")
    assert out["strategy"] == STRATEGY_YOUTUBE_OFFICIAL_CAPTIONS
    assert out["title"] == "API Talk"
    assert out["reason_code"] == "api_download_requires_oauth"
    assert out["outcome"] == "skipped"


def test_oi_m1_wired_into_media_learn_when_configured():
    acq = FakeAcquirer()

    def official(video: str):
        return {
            "outcome": "ok",
            "text": "Official caption text about fusion.",
            "title": "From API",
            "bytes_read": 40,
            "reason_code": "ok",
        }

    orch = MediaLearnOrchestrator(
        caption_fetch=lambda v: {
            "outcome": "blocked",
            "text": "",
            "acquisition": {
                "strategies_tried": [
                    {
                        "strategy": "youtube_caption_tracks",
                        "outcome": "blocked",
                        "reason_code": "robots_disallowed",
                        "bytes_read": 0,
                    }
                ]
            },
        },
        official_captions_api=official,
        asset_acquirer=acq,
        browser_render=None,
        media_ingestor=None,
    )
    result = orch.learn("https://youtu.be/abcdefghijk")
    assert result["outcome"] == "ok"
    assert "fusion" in result["text"]
    row = next(
        s for s in result["strategies"]
        if s["strategy"] == STRATEGY_YOUTUBE_OFFICIAL_CAPTIONS
    )
    assert row["reason_code"] == "asset_produced"
    assert row["asset_kind"] == ASSET_KIND_TRANSCRIPT


def test_readiness_in_job_report_next_action():
    readiness = build_media_readiness(
        browser="ready",
        official_captions="not_configured",
        media_obtain="not_configured",
        speech_to_text="missing",
    )
    report = ReportGenerator().generate(
        "Learn from video",
        claims=[],
        termination={
            "stage": "acquire",
            "status": "waiting",
            "reason": "interactive_recovery_required",
            "audience": "job",
            "suggested_next_strategies": ["upload_transcript"],
            "speech_to_text_status": "missing",
            "readiness": readiness,
        },
    )
    next_a = report["sections"]["next_research"]
    assert "Capability readiness" in next_a
    assert "not_configured" in next_a
    assert "Assessment:" in next_a
    assert "## Next Action" in report["markdown"]


def test_format_readiness_block():
    text = format_readiness_block(
        build_media_readiness(browser="ready", speech_to_text="missing")
    )
    assert "browser" in text
    assert "missing" in text


# --- BA.v2 media obtain ----------------------------------------------------
from atlas.ingestion.youtube_media_obtain import YoutubeMediaObtain
from atlas.ingestion.source_fetch import SourceFetcher, OPERATOR_HINT
from atlas.readers.media_kinds import ASSET_KIND_AUDIO


class _Proc:
    def __init__(self, code=0, stderr=""):
        self.returncode = code
        self.stderr = stderr
        self.stdout = ""


def test_youtube_media_obtain_not_configured():
    obt = YoutubeMediaObtain(enabled=False, which=lambda _: "/usr/bin/yt-dlp")
    assert obt.readiness_status() == "not_configured"
    out = obt.fetch("https://youtu.be/abcdefghijk")
    assert out["reason_code"] == "not_configured"


def test_youtube_media_obtain_binary_missing():
    obt = YoutubeMediaObtain(enabled=True, which=lambda _: None)
    assert obt.readiness_status() == "missing"
    out = obt.fetch("https://youtu.be/abcdefghijk")
    assert out["reason_code"] == "binary_missing"


def test_youtube_media_obtain_ok_via_fake_run(tmp_path):
    def fake_which(name):
        return "/bin/yt-dlp"

    def fake_run(cmd, **kwargs):
        # Write a tiny media file where -o template points.
        out_arg = cmd[cmd.index("-o") + 1]
        # template is .../media.%(ext)s → write media.m4a in that dir
        from pathlib import Path

        dest = Path(out_arg.replace("%(ext)s", "m4a"))
        dest.write_bytes(b"fake-audio-bytes")
        return _Proc(0)

    obt = YoutubeMediaObtain(
        enabled=True,
        which=fake_which,
        run=fake_run,
        format_spec="bestaudio/best",
    )
    assert obt.readiness_status() == "ready"
    out = obt.fetch("https://www.youtube.com/watch?v=abcdefghijk")
    assert out["outcome"] == "ok"
    assert out["content"] == b"fake-audio-bytes"
    assert out["kind"] == ASSET_KIND_AUDIO
    assert out["filename"].endswith(".m4a")


def test_source_fetch_wires_obtain_asset():
    fetch = FakeFetchAllow()
    obt = YoutubeMediaObtain(
        enabled=True,
        which=lambda _: "/bin/yt-dlp",
        run=lambda cmd, **kw: _write_from_cmd(cmd),
    )
    acq = _Acq()
    result = SourceFetcher(acq, fetch, youtube_fetch=obt.fetch).fetch(
        "https://youtu.be/abcdefghijk"
    )
    assert result.ok
    assert result.kind in (ASSET_KIND_AUDIO, "video")
    assert acq.last_kind in (ASSET_KIND_AUDIO, "video")


class FakeFetchAllow:
    def allowed(self, url):
        return True

    def get(self, url, *, use_cache=True):
        raise AssertionError("http_direct should skip youtube")


class _Acq:
    def __init__(self):
        self.last_kind = None
        self.n = 0

    def acquire_bytes(self, data, *, kind="document", filename=None, source_uri=None, content_type=None, metadata=None):
        from atlas.ingestion.acquire import AcquiredAsset

        self.n += 1
        self.last_kind = kind
        return AcquiredAsset(
            asset_id=f"a{self.n}",
            asset_version=1,
            kind=kind,
            name="sha",
            checksum="sha",
            content_type=content_type,
            source_uri=source_uri,
            size_bytes=len(data),
            reused=False,
            source=filename or "bytes",
        )


def _write_from_cmd(cmd):
    from pathlib import Path

    out_arg = cmd[cmd.index("-o") + 1]
    dest = Path(out_arg.replace("%(ext)s", "m4a"))
    dest.write_bytes(b"\x00audio")
    return _Proc(0)


def test_readiness_media_obtain_not_configured_hint():
    readiness = build_media_readiness(
        browser="unavailable",
        official_captions="not_configured",
        media_obtain="not_configured",
        speech_to_text="missing",
    )
    assert readiness["automatic_path_viable"] is False
    assert "media_obtain_enabled" in readiness["assessment"]


def test_youtube_media_obtain_rejects_part_files(tmp_path):
    from pathlib import Path
    from atlas.ingestion.youtube_media_obtain import YoutubeMediaObtain

    class _Proc:
        returncode = 0
        stderr = ""
        stdout = ""

    def fake_run(cmd, **kwargs):
        # Simulate yt-dlp abort leaving only an incomplete .part
        dest = Path(cmd[cmd.index("-o") + 1].replace("%(ext)s", "webm.part"))
        # path is media.%(ext)s → media.webm.part when we write wrong; write as media.webm.part
        out_arg = cmd[cmd.index("-o") + 1]
        # Create incomplete file next to template dir
        folder = Path(out_arg).parent
        (folder / "media.webm.part").write_bytes(b"x" * 1000)
        return _Proc()

    obt = YoutubeMediaObtain(
        enabled=True,
        which=lambda _: "/bin/yt-dlp",
        run=fake_run,
    )
    out = obt.fetch("https://youtu.be/abcdefghijk")
    assert out["outcome"] == "error"
    assert out["reason_code"] == "incomplete_download"
