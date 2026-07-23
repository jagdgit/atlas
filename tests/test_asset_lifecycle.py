"""AL1–AL5 — Asset lifecycle honesty (acquire vs metadata vs speech vs knowledge)."""

from __future__ import annotations

from atlas.ingestion.acquire import AcquiredAsset
from atlas.ingestion.media_learn import MediaLearnOrchestrator, build_media_stages
from atlas.readers.media_kinds import ASSET_KIND_AUDIO, ASSET_KIND_METADATA
from atlas.reports.generator import ReportGenerator
from atlas.transcripts.acquisition import AcquisitionAttempt, AcquisitionRecord


class FakeAcquirer:
    def __init__(self) -> None:
        self._n = 0

    def acquire_bytes(self, data, *, kind="document", filename=None, source_uri=None,
                      content_type=None, metadata=None):
        self._n += 1
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


class FakeMedia:
    """Simulate SourceFetch Asset + metadata Knowledge without speech."""

    def __init__(self, *, with_ingest: bool = True) -> None:
        self.with_ingest = with_ingest

    def ingest_url(self, url, **kwargs):
        ingest = (
            {"outcome": "ok", "document_id": "d1", "chunks": 3, "source_id": "youtube:zHt5"}
            if self.with_ingest
            else None
        )
        note = "Media asset (audio): clip.m4a\ntitle: Demo Talk\nuploader: Atlas"
        return {
            "outcome": "ok" if ingest else "empty",
            "asset_id": "asset-54mb",
            "asset_version": 1,
            "kind": ASSET_KIND_AUDIO,
            "filename": "clip.m4a",
            "text": note if ingest else "",
            "fetch": {
                "outcome": "ok",
                "asset_id": "asset-54mb",
                "kind": ASSET_KIND_AUDIO,
                "bytes_read": 54_499_519,
                "reason_code": "ok",
                "strategies_tried": [
                    {
                        "name": "local_file",
                        "outcome": "skipped",
                        "reason_code": "not_applicable",
                        "bytes_read": 0,
                    },
                    {
                        "name": "http_direct",
                        "outcome": "skipped",
                        "reason_code": "not_applicable",
                        "bytes_read": 0,
                    },
                    {
                        "name": "youtube_media",
                        "outcome": "ok",
                        "reason_code": "ok",
                        "bytes_read": 54_499_519,
                    },
                ],
            },
            "metadata": {"outcome": "ok", "fields": {"title": "Demo Talk", "uploader": "Atlas"}},
            "speech": {
                "outcome": "unavailable",
                "capability_gap": "speech_to_text",
                "reason": "speech_to_text missing",
            },
            "ingest": ingest,
        }


def test_al1_acquisition_success_requires_asset_id():
    attempts = [
        AcquisitionAttempt(
            strategy="youtube_media",
            outcome="ok",
            reason="bytes only",
            reason_code="ok",
            bytes_read=54_499_519,
        )
    ]
    record = AcquisitionRecord.from_attempts(attempts, source_url="https://youtu.be/x")
    assert not record.ok
    assert "failed" in record.operator_summary.lower() or "no_asset" in record.reason_code

    attempts2 = [
        AcquisitionAttempt(
            strategy="youtube_media",
            outcome="ok",
            reason_code="asset_registered",
            bytes_read=100,
            asset_id="a1",
            asset_kind=ASSET_KIND_AUDIO,
        )
    ]
    record2 = AcquisitionRecord.from_attempts(attempts2, source_url="https://youtu.be/x")
    assert record2.ok
    assert "asset_id=a1" in record2.operator_summary
    assert "registered" in record2.operator_summary.lower()


def test_al3_metadata_knowledge_succeeds_without_whisper():
    orch = MediaLearnOrchestrator(
        caption_fetch=lambda v: {"outcome": "blocked", "text": "", "acquisition": {"strategies_tried": []}},
        official_captions_api=None,
        browser_render=None,
        media_ingestor=FakeMedia(with_ingest=True),
        speech_status=lambda: "missing",
        asset_acquirer=FakeAcquirer(),
    )
    result = orch.learn("https://youtu.be/zHt5Mdr0QFk")
    assert result["outcome"] == "ok"
    assert result["interactive_recovery"] is False
    assert result["waiting_for"] is None
    assert result["knowledge_produced"] == 3
    assert result["stages"]["acquire"] == "success"
    assert result["stages"]["metadata"] == "success"
    assert result["stages"]["speech"] == "waiting"
    assert result["stages"]["knowledge"] == "success"
    assert result["acquisition"]["asset_id"] == "asset-54mb"
    names = [s["strategy"] for s in result["strategies"]]
    assert "youtube_media" in names
    assert "media_metadata" in names
    assert "speech_to_text" in names
    assert "knowledge" in names
    assert any(s.get("reason_code") == "metadata_ingested" for s in result["strategies"])


def test_al2_asset_without_knowledge_waits_for_speech_not_asset():
    orch = MediaLearnOrchestrator(
        caption_fetch=lambda v: {"outcome": "blocked", "text": "", "acquisition": {"strategies_tried": []}},
        media_ingestor=FakeMedia(with_ingest=False),
        speech_status=lambda: "missing",
        asset_acquirer=FakeAcquirer(),
    )
    result = orch.learn("https://youtu.be/zHt5Mdr0QFk")
    assert result["outcome"] == "waiting"
    assert result["waiting_for"] == "speech_to_text"
    assert result["acquisition"]["asset_id"] == "asset-54mb"
    assert result["stages"]["acquire"] == "success"
    assert "Waiting for Media Asset" not in (result.get("operator_summary") or "")


def test_al5_report_uses_knowledge_produced_and_stages():
    stages = build_media_stages(
        acquire="success",
        metadata="success",
        transcript="waiting",
        speech="waiting",
        knowledge="empty",
    )
    report = ReportGenerator().generate(
        "learn video",
        claims=[],
        termination={
            "stage": "acquire",
            "status": "waiting",
            "reason": "speech_to_text_required",
            "audience": "job",
            "waiting_for": "speech_to_text",
            "knowledge_produced": 0,
            "stages": stages,
            "suggested_next_strategies": ["enable_speech_to_text"],
        },
    )
    conf = report["sections"]["confidence"]
    assert conf["waiting_for"] == "speech_to_text"
    assert conf["knowledge_produced"] == 0
    assert "Stages:" in report["markdown"]
    assert "speech_to_text" in report["markdown"].lower().replace(" ", "_") or "Speech To Text" in report["markdown"]
