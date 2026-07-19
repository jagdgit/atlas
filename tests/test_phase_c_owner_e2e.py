"""Phase-C · C.8 Owner Knowledge Mission end-to-end acceptance (live DB).

Instantiates the permanent **Owner Knowledge Mission** over a mixed **User Archive** — a code repo,
a document, and a chat/Cursor export — and drives its worker exactly as the WorkerManager does, then
asserts the C.8 gate:

  * one tick reads all three archive kinds through the ONE unified pipeline → engineering findings +
    consolidated owner experiences (code) + prose candidate-findings (doc) + a chat read, all
    provenance-stamped (P12), and rebuilds the personal profile (inferred skills, CC7);
  * a "process restart" (a fresh WorkerManager) resumes from the checkpoint and treats an unchanged
    archive as a cheap no-op (every root skipped) — reboot-safe;
  * a config edit bumps the version and is picked up on the next tick (config-versioned, journaled).

Requires a live DB; skipped entirely if PostgreSQL is unreachable (matching the other e2e modules).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from atlas.assets import AssetRepository, AssetStore
from atlas.code.parser import CodeParser
from atlas.code.service import CodeService
from atlas.config import IntelligenceConfig, LearningConfig
from atlas.configuration import ConfigRepository, ConfigurationService
from atlas.database.connection import DatabaseManager
from atlas.engineering.architecture import ArchitectureGraphStore
from atlas.engineering.artifacts import DerivedArtifactStore
from atlas.engineering.design_review import DesignReviewer
from atlas.engineering.findings import EngineeringFindingWriter
from atlas.engineering.ingest import RepoAcquirer
from atlas.engineering.readers import ReaderRegistry
from atlas.ingestion.acquire import AssetAcquirer
from atlas.ingestion.service import IngestionService
from atlas.intelligence.service import CodeStoreSink, IntelligenceService
from atlas.knowledge.candidate_consumer import CandidateConsumer
from atlas.knowledge.consolidation import KnowledgeLifecycleService
from atlas.knowledge.coverage import CoverageService
from atlas.knowledge.prose_extraction import ProseKnowledgeExtractor
from atlas.knowledge.service import KnowledgeService
from atlas.learning.experience_extraction import ExperienceWriter
from atlas.missions import MissionRepository, MissionService
from atlas.missions.templates import TemplateService
from atlas.models.learning import STORE_CODE
from atlas.personal import PersonalService
from atlas.readers import ConversationReader, DocumentReader
from atlas.recovery import CheckpointStore
from atlas.repositories.candidate_repo import CandidateRepository
from atlas.repositories.chunk_repo import ChunkRepository
from atlas.repositories.coverage_repo import CoverageRepository
from atlas.repositories.document_repo import DocumentRepository
from atlas.repositories.embedding_repo import EmbeddingRepository
from atlas.repositories.experience_store import ExperienceStore
from atlas.repositories.finding_repo import FindingRepository
from atlas.repositories.intelligence_repo import IntelligenceRepository
from atlas.repositories.learning_repo import LearningRepository
from atlas.repositories.personal_repo import PersonalRepository
from atlas.repositories.recovery_repo import CheckpointRepository
from atlas.repositories.schedule_repo import ScheduleRepository
from atlas.repositories.task_repo import TaskRepository
from atlas.repositories.template_repo import TemplateRepository
from atlas.repositories.worker_repo import WorkerRepository
from atlas.scheduler.schedules import ScheduleService
from atlas.services.learning_service import LearningService
from atlas.storage.repository import StorageRepository
from atlas.storage.service import StorageManager
from atlas.workers import OwnerKnowledgeWorker, WorkerManager


class _PathGit:
    def __init__(self, salt: str) -> None:
        self._salt = salt

    def root_commit(self, repo):  # noqa: ANN001
        return f"{self._salt}:{Path(repo).name}"

    def remote_url(self, repo):  # noqa: ANN001
        return None

    def clone_shallow(self, url, dest, *, branch=None):  # noqa: ANN001
        raise NotImplementedError("local-path acquisition only in this e2e")


class _StubLLM:
    embedding_model = "stub"
    model = "stub:1"

    def for_role(self, role):  # noqa: ANN001
        raise AssertionError("LLM should not be called on the embed=False / no-review path")

    def embed(self, texts, **kw):  # pragma: no cover
        raise AssertionError("embed should not be called with embed=False")


def _write(root: Path, files: dict[str, str]) -> str:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return str(root)


@pytest.fixture(scope="module")
def db():
    manager = DatabaseManager()
    try:
        if not manager.health_check():
            pytest.skip("database health check failed")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {exc}")
    yield manager
    manager.close()


class _OwnerStack:
    """The Owner-Knowledge service graph (engineering + ingestion + personal + mission/worker)."""

    def __init__(self, db: DatabaseManager, tmp_path: Path) -> None:
        self.db = db
        salt = uuid.uuid4().hex[:12]
        storage = StorageManager(tmp_path / "storage", StorageRepository(db))
        storage.start()
        assets = AssetStore(storage, AssetRepository(db))
        self.assets = assets
        artifacts = DerivedArtifactStore(storage)

        self.finding_repo = FindingRepository(db)
        self.intel_repo = IntelligenceRepository(db)
        writer = EngineeringFindingWriter(self.finding_repo)
        self.experience_store = ExperienceStore(db)
        exp_writer = ExperienceWriter(self.experience_store)
        self.learning = LearningService(LearningRepository(db), LearningConfig(auto_apply=False))
        self.learning.register_sink(
            STORE_CODE, CodeStoreSink(self.intel_repo, findings=writer, experiences=exp_writer)
        )
        code = CodeService(CodeParser(), readers=ReaderRegistry())
        coverage_repo = CoverageRepository(db)
        self.coverage = CoverageService(coverage_repo, self.finding_repo)
        self.intel = IntelligenceService(
            code, self.intel_repo, self.learning, IntelligenceConfig(),
            acquirer=RepoAcquirer(assets, storage, git=_PathGit(salt)),
            artifacts=artifacts,
            graph_store=ArchitectureGraphStore(assets),
            design_reviewer=DesignReviewer(_StubLLM()),
            findings=writer, finding_repo=self.finding_repo, coverage=self.coverage,
        )

        # Unified ingestion bridge (docs/chats) + the shared consolidator.
        self.knowledge = KnowledgeService(
            DocumentRepository(db), ChunkRepository(db), EmbeddingRepository(db), _StubLLM(),
            embedding_model="stub", chunk_max_words=40, chunk_overlap=5,
        )
        lifecycle = KnowledgeLifecycleService(self.finding_repo)
        self.knowledge._lifecycle = lifecycle  # noqa: SLF001
        self.candidates = CandidateConsumer(CandidateRepository(db), lifecycle)
        self.conversation_reader = ConversationReader(assets, artifacts)
        self.ingestion = IngestionService(
            AssetAcquirer(assets), DocumentReader(assets, artifacts), self.knowledge,
            extractor=ProseKnowledgeExtractor(), candidates=self.candidates, coverage=self.coverage,
        )
        self.personal = PersonalService(
            PersonalRepository(db), experiences=self.experience_store, intelligence=self.intel,
        )

        # Mission / worker stack.
        self.checkpoints = CheckpointStore(CheckpointRepository(db))
        self.mission_repo = MissionRepository(db)
        self.schedule_repo = ScheduleRepository(db)
        self.worker_repo = WorkerRepository(db)
        self.config_repo = ConfigRepository(db)
        self.task_repo = TaskRepository(db)
        self.missions = MissionService(
            self.mission_repo, schedule_repo=self.schedule_repo, worker_repo=self.worker_repo
        )
        self.configuration = ConfigurationService(self.config_repo, self.mission_repo)
        self.schedules = ScheduleService(
            self.schedule_repo, self.task_repo, mission_repo=self.mission_repo
        )
        self.workers = self.new_worker_manager()
        self.templates = TemplateService(
            TemplateRepository(db), self.missions, self.configuration, self.workers
        )
        self.templates.seed_builtins()

    def new_worker_manager(self) -> WorkerManager:
        mgr = WorkerManager(
            self.worker_repo, self.checkpoints, schedule_service=self.schedules,
            config_repo=self.config_repo, mission_repo=self.mission_repo,
        )
        mgr.register_worker_type(OwnerKnowledgeWorker(
            ingestion=self.ingestion, intelligence=self.intel, personal=self.personal,
            conversation_reader=self.conversation_reader, candidates=self.candidates,
        ))
        return mgr


@pytest.fixture(scope="module")
def stack(db, tmp_path_factory):
    return _OwnerStack(db, tmp_path_factory.mktemp("phase_c_owner_e2e"))


def _actions(stack: _OwnerStack, mission_id: str) -> list[str]:
    return [e.action for e in stack.missions.journal_entries(mission_id, limit=200)]


def test_owner_knowledge_mission_learns_archive_and_survives_reboot(stack: _OwnerStack, tmp_path):
    token = uuid.uuid4().hex[:8]
    code = _write(tmp_path / "archive" / "proj", {
        "app/__init__.py": "",
        "app/main.py": "class Api:\n    def run(self):\n        return 1\n",
        "requirements.txt": "fastapi\ncelery\n",
    })
    docs = _write(tmp_path / "archive" / "docs", {
        "notes.md": (
            f"# Owner notes {token}\n\n"
            "The owner has extensive experience building distributed task pipelines with Celery "
            "and has shipped several FastAPI services to production over many years.\n"
        ),
    })
    chats = _write(tmp_path / "archive" / "chats", {
        # Token keeps the content-addressed asset sha unique per run so a stale row from a prior
        # run in the shared dev DB (OI-T1) can't be reused with now-deleted backing bytes.
        "session.jsonl": (
            f'{{"role":"user","content":"I spent years optimizing PostgreSQL for analytics workloads. {token}"}}\n'
            '{"role":"assistant","content":"That is deep database expertise across many projects."}\n'
        ),
    })

    result = stack.templates.instantiate(
        "owner_knowledge",
        title=f"C.8 owner {token}",
        config_overrides={"archive_roots": [
            {"path": code, "kind": "code", "domain": "engineering"},
            {"path": docs, "kind": "document", "domain": "personal"},
            {"path": chats, "kind": "conversation", "domain": "personal"},
        ]},
    )
    mission_id = result["mission"].id
    wid = result["workers"][0].id
    try:
        assert result["workers"][0].type == "owner_knowledge"
        cfg = stack.configuration.get_active(mission_id)
        assert cfg.version == 1 and cfg.schema_type == "owner_knowledge"

        # 1. First tick: read all three kinds + build the profile.
        r1 = stack.workers.worker_tick({"worker_id": wid})
        assert r1["ticked"] is True
        cp = stack.checkpoints.load("worker", wid)
        totals = cp["last_totals"]
        assert totals["code_repos"] == 1
        assert totals["findings"] >= 1          # engineering findings from the code repo
        assert totals["experiences"] >= 1       # dual-extracted owner experiences (C.6)
        assert totals["documents"] == 1
        assert totals["conversations"] == 1
        assert totals["candidate_findings"] >= 1  # prose candidates drained into findings (C.3g)
        assert cp["ticks"] == 1

        # The personal profile now carries inferred skills distilled from consolidated experiences.
        skills = stack.personal.list_facts(category="skill")
        assert skills, "expected inferred skills on the owner profile"
        assert any(s["state"] == "inferred" for s in skills)

        # Coverage recorded the personal-domain reads (doc + chat).
        domains = {d["domain"] for d in stack.coverage.summary()["domains"]}
        assert "personal" in domains

        # 2. "Process restart": a fresh manager resumes from the checkpoint; unchanged archive → no-op.
        restarted = stack.new_worker_manager()
        restarted.worker_tick({"worker_id": wid})
        cp2 = stack.checkpoints.load("worker", wid)
        assert cp2["last_totals"]["skipped"] == 3   # every root unchanged → skipped
        assert cp2["last_totals"]["code_repos"] == 0
        assert cp2["ticks"] == 2

        # 3. Config-versioned: an edit bumps the version, picked up on the next tick (journaled).
        v2 = stack.configuration.update_config(
            mission_id, {**cfg.document, "build_profile": False},
            change_note="stop rebuilding profile", activate=True,
        )
        assert v2.version == 2
        stack.workers.worker_tick({"worker_id": wid})
        assert "config_picked_up" in _actions(stack, mission_id)
        assert stack.checkpoints.load("worker", wid)["config_version"] == 2
    finally:
        stack.missions.archive(mission_id, "C.8 cleanup")
        # P12: knowledge/experience/profile survive the mission being archived.
        assert stack.personal.list_facts(category="skill")
