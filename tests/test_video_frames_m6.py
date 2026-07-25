"""OI-M6 video frame extract + optional OCR composition."""

from __future__ import annotations

from atlas.frames.engine import CAPABILITY_GAP, FRAME_OK, FRAME_UNAVAILABLE, VideoFrameClient
from atlas.readers.media_kinds import ASSET_KIND_VIDEO
from atlas.readers.video_frames import VideoFramesReader


def test_disabled_gap():
    client = VideoFrameClient(enabled=False)
    out = client.extract_frame("/tmp/x.mp4")
    assert out["outcome"] == FRAME_UNAVAILABLE
    assert out["capability_gap"] == CAPABILITY_GAP


def test_fake_extract_with_ocr(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake-video")

    def fake_extract(src, dst):
        # Minimal valid-ish PNG header + bytes
        dst.write_bytes(
            b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
        )

    class FakeOCR:
        def image_to_text(self, path, *, lang="eng"):
            return "Slide title: Markets"

    client = VideoFrameClient(enabled=True, extract=fake_extract, ocr=FakeOCR())
    out = client.extract_frame(video)
    assert out["outcome"] == FRAME_OK
    assert out["ocr_text"] == "Slide title: Markets"
    assert out["image_bytes"]


def test_video_frames_reader(tmp_path):
    class FakeAssets:
        def get(self, asset_id):
            return {"id": asset_id, "kind": ASSET_KIND_VIDEO}

        def get_bytes(self, asset_id, version=None):
            return b"vid"

    class FakeArts:
        def __init__(self):
            self.store = {}

        def get(self, *a):
            return None

        def put(self, asset_id, version, reader, reader_version, artifact):
            self.store[(asset_id, version, reader)] = artifact

    def fake_extract(src, dst):
        dst.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)

    reader = VideoFramesReader(
        FakeAssets(),
        FakeArts(),
        VideoFrameClient(enabled=True, extract=fake_extract),
    )
    art = reader.read("a1", 1, filename="demo.mp4")
    assert art["outcome"] == FRAME_OK
    assert art["has_image"] is True
