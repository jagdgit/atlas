"""Program materials — single share path for Personal + Engineering."""

from __future__ import annotations

from pathlib import Path

from atlas.missions.materials import (
    ProgramMaterialsService,
    extract_paths,
    infer_kind,
    looks_like_share,
)


def test_infer_kind_file_document(tmp_path: Path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4")
    assert infer_kind(resume) == "document"


def test_infer_kind_code_repo(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "main.py").write_text("print('hi')\n")
    assert infer_kind(tmp_path) == "code"


def test_extract_paths_and_share_hint():
    msg = "please share /data/me/resume.pdf and learn from /home/me/projects/atlas"
    assert looks_like_share(msg)
    paths = extract_paths(msg)
    assert "/data/me/resume.pdf" in paths
    assert "/home/me/projects/atlas" in paths


def test_share_document_once_feeds_personal(tmp_path: Path):
    resume = tmp_path / "cv.md"
    resume.write_text("# Jag\nEducation: B.Tech\n")

    class _Ingest:
        def __init__(self):
            self.calls = []

        def ingest_file(self, path, **kwargs):
            self.calls.append((str(path), kwargs))

            class R:
                candidates = 2
                experiences = 0
                chunks = 3

            return R()

    class _Cfg:
        def __init__(self):
            self.doc = {"archive_roots": []}
            self.version = 1

        def get_active(self, _mid):
            class C:
                document = self.doc
                version = self.version

            return C()

        def update_config(self, _mid, document, **_kw):
            self.doc = dict(document)
            self.version += 1

            class C:
                document = self.doc
                version = self.version

            return C()

    class _Mission:
        def to_dict(self):
            return {
                "id": "m-owner",
                "status": "active",
                "title": "Personal Observer",
                "labels": ["program:personal_intelligence"],
                "metadata": {"template": "owner_knowledge", "program_id": "personal_intelligence"},
            }

    class _Missions:
        def list_missions(self, **_kw):
            return [_Mission()]

    ingest = _Ingest()
    cfg = _Cfg()
    svc = ProgramMaterialsService(
        missions=_Missions(),
        configuration=cfg,
        ingestion=ingest,
        intelligence=None,
        personal=None,
    )
    out = svc.share(str(resume), program_id="personal_intelligence", process_now=True)
    assert out["ok"] is True
    assert out["kind"] == "document"
    assert out["feeds"] == ["personal_intelligence"]
    assert len(ingest.calls) == 1
    assert cfg.doc["archive_roots"][0]["path"] == str(resume.resolve())

    # Second share from Engineering must not double-ingest archive registration.
    out2 = svc.share(str(resume), program_id="engineering_intelligence", process_now=False)
    assert out2["archive"]["already_present"] is True
    assert len(cfg.doc["archive_roots"]) == 1


def test_share_code_feeds_personal_and_engineering(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "app.py").write_text("x = 1\n")

    class _Intel:
        def __init__(self):
            self.n = 0

        def learn_repository(self, **kwargs):
            self.n += 1
            return {
                "outcome": "ok",
                "findings": 4,
                "experiences": 2,
                "repository": {"repo_uid": "r1"},
            }

    class _Cfg:
        def get_active(self, _mid):
            return None

        def update_config(self, *_a, **_k):
            raise AssertionError("should not update without active config when get_active is None")

    class _Missions:
        def list_missions(self, **_kw):
            return []

    intel = _Intel()
    svc = ProgramMaterialsService(
        missions=_Missions(),
        configuration=_Cfg(),
        intelligence=intel,
        templates=None,
    )
    out = svc.share(str(tmp_path), program_id="engineering_intelligence")
    assert out["feeds"] == ["personal_intelligence", "engineering_intelligence"]
    assert intel.n == 1
    assert out["processed"]["findings"] == 4


def test_chat_help_without_path():
    svc = ProgramMaterialsService()
    out = svc.chat("personal_intelligence", "how do I upload my resume?")
    assert "share" in out["answer"].lower()
    assert out["shares"] == []


def test_chat_shares_path(tmp_path: Path):
    resume = tmp_path / "resume.txt"
    resume.write_text("Jag — engineer\n")

    class _Ingest:
        def ingest_file(self, *_a, **_k):
            class R:
                candidates = 1
                experiences = 0
                chunks = 1

            return R()

    svc = ProgramMaterialsService(ingestion=_Ingest())
    out = svc.chat(
        "personal_intelligence",
        f"share my resume at {resume}",
    )
    assert len(out["shares"]) == 1
    assert out["shares"][0]["kind"] == "document"
