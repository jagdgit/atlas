"""Phase-B end-to-end acceptance — the Phase-B gate (PHASE_B_PLAN §B.8).

Exercises the **full Engineering-Intelligence pipeline** against a live PostgreSQL, wiring the
real Asset Store / Storage Manager / Repo Acquirer / Code reader / Derived Artifact Store /
Architecture Graph Store / Engineering Finding writer / Learning ledger + Code sink /
Intelligence service exactly as ``bootstrap`` does (a deterministic fake stands in for the LLM
so the design review is reproducible, and a path-derived fake git avoids the ``git`` binary):

    ingest a real **Python** repo → architecture graph + engineering + design findings, all
    retrievable and versioned → ingest a **JS/TS** repo through the *same* pipeline → re-ingest
    after a change bumps the asset version, the graph diff reflects the change, and stale
    findings are superseded → every artifact is provenance-stamped + explainable + reversible;
    and a **RepoWatcher mission** drives that same governed ingest on its schedule, survives a
    process restart, and is config-versioned — with every action journaled (P9).

Requires a live DB; the whole module is skipped if PostgreSQL is unreachable (matching
``test_phase_a_e2e``), so the suite stays green without DB access.
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
from atlas.engineering.architecture import ASSET_KIND_GRAPH, ArchitectureGraphStore
from atlas.engineering.artifacts import DerivedArtifactStore
from atlas.engineering.design_review import CLAIM_DESIGN, CLAIM_RISK, DesignReviewer
from atlas.engineering.findings import CLAIM_STRUCTURE, EngineeringFindingWriter
from atlas.engineering.ingest import ASSET_KIND_REPO, RepoAcquirer
from atlas.engineering.readers import ReaderRegistry
from atlas.intelligence.service import CodeStoreSink, IntelligenceService
from atlas.learning.experience_extraction import ExperienceWriter
from atlas.missions import MissionRepository, MissionService
from atlas.missions.templates import TemplateService
from atlas.models.learning import SOURCE_REPO, STORE_CODE
from atlas.recovery import CheckpointStore
from atlas.repositories.experience_store import ExperienceStore
from atlas.repositories.finding_repo import FindingRepository
from atlas.repositories.intelligence_repo import IntelligenceRepository
from atlas.repositories.learning_repo import LearningRepository
from atlas.repositories.recovery_repo import CheckpointRepository
from atlas.repositories.schedule_repo import ScheduleRepository
from atlas.repositories.task_repo import TaskRepository
from atlas.repositories.template_repo import TemplateRepository
from atlas.repositories.worker_repo import WorkerRepository
from atlas.scheduler.schedules import ScheduleService
from atlas.services.learning_service import LearningService
from atlas.storage.repository import StorageRepository
from atlas.storage.service import StorageManager
from atlas.workers import RepoWatcher, WorkerManager


# --- a deterministic LLM for the design review ---------------------------
_REVIEW_JSON = (
    '[{"title":"API imports DB","type":"risk","confidence":"high",'
    '"statement":"The core layer reaches across a boundary.","evidence":["pkg/core.py"],'
    '"rationale":"Couples orchestration to a helper and blocks substitution.",'
    '"rejected_alternatives":["Introduce a port/adapter","Invert the dependency"]},'
    '{"title":"Layered package","type":"design","confidence":"medium",'
    '"statement":"Logic is organised into a cohesive package.","evidence":["pkg/"],'
    '"rationale":"Keeps units small and testable.","rejected_alternatives":["One big module"]}]'
)


class _Resp:
    def __init__(self, text: str) -> None:
        self.text = text


class _Client:
    model = "qwen-test:1"

    def chat(self, messages, **kw):  # noqa: ANN001, ANN003
        return _Resp(_REVIEW_JSON)


class _FakeLLM:
    def for_role(self, role):  # noqa: ANN001
        return _Client()


class _PathGit:
    """A git fake that derives a stable per-repo root-commit from the directory name.

    Distinct repos ⇒ distinct root-commits ⇒ distinct ``repo_uid`` (BB12); re-ingesting the
    same directory keeps its ``repo_uid`` so versions accrue against one identity. The ``salt``
    keeps ``repo_uid``s unique across test-module runs so live-DB version numbering is hermetic.
    """

    def __init__(self, salt: str) -> None:
        self._salt = salt

    def root_commit(self, repo):  # noqa: ANN001
        return f"{self._salt}:{Path(repo).name}"

    def remote_url(self, repo):  # noqa: ANN001
        return None

    def clone_shallow(self, url, dest, *, branch=None):  # noqa: ANN001
        raise NotImplementedError("local-path acquisition only in this e2e")


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
    except Exception as exc:  # noqa: BLE001 - any connection error means skip
        pytest.skip(f"database unreachable: {exc}")
    yield manager
    manager.close()


class _Stack:
    """The full Phase-B service graph (engineering + the mission/worker stack for RepoWatcher)."""

    def __init__(self, db: DatabaseManager, tmp_path: Path) -> None:
        self.db = db
        salt = uuid.uuid4().hex[:12]
        storage = StorageManager(tmp_path / "storage", StorageRepository(db))
        storage.start()
        assets = AssetStore(storage, AssetRepository(db))
        self.assets = assets

        self.finding_repo = FindingRepository(db)
        self.intel_repo = IntelligenceRepository(db)
        writer = EngineeringFindingWriter(self.finding_repo)
        self.experience_store = ExperienceStore(db)
        exp_writer = ExperienceWriter(self.experience_store)
        self.learning = LearningService(
            LearningRepository(db), LearningConfig(auto_apply=False)
        )
        self.learning.register_sink(
            STORE_CODE,
            CodeStoreSink(self.intel_repo, findings=writer, experiences=exp_writer),
        )
        code = CodeService(CodeParser(), readers=ReaderRegistry())
        self.graphs = ArchitectureGraphStore(assets)
        self.intel = IntelligenceService(
            code,
            self.intel_repo,
            self.learning,
            IntelligenceConfig(),
            acquirer=RepoAcquirer(assets, storage, git=_PathGit(salt)),
            artifacts=DerivedArtifactStore(storage),
            graph_store=self.graphs,
            design_reviewer=DesignReviewer(_FakeLLM()),
            findings=writer,
            finding_repo=self.finding_repo,
        )

        # Mission / worker stack (so a repository_learning mission drives the real ingest).
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
        mgr.register_worker_type(RepoWatcher(self.intel))
        return mgr


@pytest.fixture(scope="module")
def stack(db, tmp_path_factory):
    return _Stack(db, tmp_path_factory.mktemp("phase_b_e2e"))


def _actions(stack: _Stack, mission_id: str) -> list[str]:
    return [e.action for e in stack.missions.journal_entries(mission_id, limit=200)]


def _structure_finding(stack: _Stack, repo_uid: str) -> dict:
    rows = [r for r in stack.finding_repo.list_active_by_repo_uid(repo_uid)
            if r["claim_type"] == CLAIM_STRUCTURE]
    assert len(rows) == 1, "exactly one active structure finding per repo"
    return rows[0]


def test_engineering_full_lifecycle(stack: _Stack, tmp_path):
    # 1. Ingest a real Python repo → asset v1, architecture graph v1, findings + design review.
    py = _write(tmp_path / "pyrepo", {
        "pkg/__init__.py": "",
        "pkg/util.py": "def helper():\n    return 1\n",
        "pkg/core.py": "from pkg import util\n\n\nclass Engine:\n"
                       "    def run(self):\n        return util.helper()\n",
        "requirements.txt": "fastapi\n",
    })
    first = stack.intel.learn_repository(path=py)
    assert first["outcome"] == "ok" and first["applied"] is True
    assert first["asset"]["asset_version"] == 1 and first["asset"]["reused"] is False
    assert first["architecture_graph"]["version"] == 1
    assert first["design_review"]["ran"] is True          # first version ⇒ structural change
    assert first["design_findings"] == 2
    assert first["findings"] >= 3                          # structure + dependency + pattern
    repo_uid = first["repository"]["repo_uid"]
    repo_id = first["repository"]["id"]
    py_event = first["event"]["id"]
    assert first["repository"]["asset_version"] == 1

    # 2. Architecture graph is retrievable + versioned.
    graph = stack.intel.architecture_graph(repo_uid)
    assert graph is not None
    assert "pkg/core.py" in graph["modules"]
    assert [e for e in graph["import_edges"]]              # core → util edge captured
    assert len(stack.intel.architecture_graph_versions(repo_uid)) == 1

    # 3. Findings are retrievable with the P9 "why" + model/reader provenance.
    findings = stack.intel.list_findings(repo_uid=repo_uid)
    kinds = {f["claim_type"] for f in findings}
    assert {CLAIM_STRUCTURE, CLAIM_DESIGN, CLAIM_RISK} <= kinds
    assert all((f["provenance"] or {}).get("repo_uid") == repo_uid for f in findings)
    risk = next(f for f in findings if f["claim_type"] == CLAIM_RISK)
    assert risk["provenance"]["model"] == "qwen-test:1"    # P9: model version recorded
    assert risk["value"]["rejected_alternatives"]          # P9: alternatives rejected
    struct_v1 = _structure_finding(stack, repo_uid)
    assert struct_v1["revision"] == 1

    # 4. Ingest a JS/TS repo through the *same* pipeline (distinct identity, same governance).
    js = _write(tmp_path / "tsrepo", {
        "src/util.ts": "export function helper() { return 1; }\n",
        "src/index.ts": "import { helper } from './util';\n"
                        "export function main() { return helper(); }\n",
        "package.json": '{"name":"tsrepo","version":"1.0.0"}\n',
    })
    js_out = stack.intel.learn_repository(path=js)
    assert js_out["outcome"] == "ok" and js_out["applied"] is True
    js_uid = js_out["repository"]["repo_uid"]
    assert js_uid != repo_uid                              # separate repo_uid (BB12)
    assert "typescript" in (js_out["repository"]["languages"] or {})
    assert stack.intel.architecture_graph(js_uid) is not None
    assert js_out["findings"] >= 1                         # structural findings landed

    # 5. Re-ingest the Python repo after a change → asset v2, graph v2 + diff, findings superseded.
    _write(tmp_path / "pyrepo", {
        "pkg/extra.py": "def extra():\n    return 2\n",
        "pkg/core.py": "from pkg import util, extra\n\n\nclass Engine:\n"
                       "    def run(self):\n        return util.helper() + extra.extra()\n",
    })
    second = stack.intel.learn_repository(path=py)
    assert second["outcome"] == "ok"
    assert second["asset"]["asset_version"] == 2 and second["asset"]["reused"] is False
    assert second["architecture_graph"]["version"] == 2
    diff = stack.intel.architecture_graph_diff(repo_uid, 1, 2)
    assert diff is not None
    assert "pkg/extra.py" in diff["added_modules"]         # structural change reflected
    # The stale structure finding was superseded: one active row remains, but it's a *new*
    # canonical row whose statement reflects the change, and the prior row is marked superseded.
    struct_v2 = _structure_finding(stack, repo_uid)
    assert str(struct_v2["id"]) != str(struct_v1["id"])
    assert struct_v2["statement"] != struct_v1["statement"]
    assert stack.finding_repo.get(str(struct_v1["id"]))["status"] == "superseded"
    # Structural change re-ran the design review; design/risk still present (superseded, not lost).
    assert second["design_review"]["ran"] is True
    assert {CLAIM_DESIGN, CLAIM_RISK} <= {
        r["claim_type"] for r in stack.finding_repo.list_active_by_repo_uid(repo_uid)
    }

    # 6. Everything is provenance-stamped: the learned row + graph asset carry identity.
    rec = stack.intel.get_repository(repo_id)
    assert rec["repo_uid"] == repo_uid and rec["asset_id"] and rec["asset_version"] == 1
    repo_asset = stack.assets.get_by_name(ASSET_KIND_REPO, repo_uid)
    graph_asset = stack.assets.get_by_name(ASSET_KIND_GRAPH, repo_uid)
    assert stack.assets.verify(str(repo_asset["id"])) is True
    assert stack.assets.verify(str(graph_asset["id"])) is True

    # 7. Everything is explainable (P9): governed, ordered ledger events for each learn.
    events = stack.learning.list_events(store="code")
    assert len([e for e in events if e["status"] == "applied"]) >= 3   # py×2 + js
    explain = stack.learning.explain(py_event)
    assert explain and explain.get("summary")

    # 8. Everything is reversible: reverting the learn retires the row + archives its findings.
    stack.learning.revert(py_event)
    assert stack.intel.get_repository(repo_id)["status"] == "reverted"
    assert stack.finding_repo.list_active_by_repo_uid(repo_uid) == []  # archived (BB9)
    # The JS repo is untouched by the Python revert (findings are repo-scoped).
    assert stack.finding_repo.list_active_by_repo_uid(js_uid)


def test_c1_mission_scoped_ingest_stamps_global_provenance(stack: _Stack, tmp_path):
    """Phase-C · C.1/P12: a mission-scoped ingest records *who discovered* each finding, the
    findings are queryable by mission (a discovery lens, not ownership), and archiving the mission
    leaves the knowledge intact."""
    mission_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    repo = _write(tmp_path / "provrepo", {
        "pkg/__init__.py": "",
        "pkg/core.py": "from pkg import util\n\n\nclass Engine:\n    pass\n",
        "pkg/util.py": "def helper():\n    return 1\n",
        "requirements.txt": "fastapi\n",
    })
    out = stack.intel.learn_repository(path=repo, mission_id=mission_id, job_id=job_id)
    assert out["outcome"] == "ok"
    repo_uid = out["repository"]["repo_uid"]

    # Every finding carries the discovering mission/job on the DB columns *and* in provenance.
    rows = stack.finding_repo.list_active_by_repo_uid(repo_uid)
    assert rows
    for r in rows:
        assert str(r["mission_id"]) == mission_id
        assert str(r["job_id"]) == job_id
        assert (r["provenance"] or {}).get("mission_id") == mission_id
        assert (r["provenance"] or {}).get("source") == SOURCE_REPO

    # The discovery lens: list_findings(mission_id=…) returns exactly this repo's findings.
    by_mission = stack.intel.list_findings(mission_id=mission_id)
    assert {f["id"] for f in by_mission} == {str(r["id"]) for r in rows}
    assert all(f["mission_id"] == mission_id for f in by_mission)
    assert stack.finding_repo.list_by_job(job_id)

    # P12: archiving a mission does NOT delete its knowledge (soft ref, no cascade).
    real = stack.missions.create_mission("C.1 provenance mission")
    stack.missions.archive(real.id, "C.1 cleanup")
    assert stack.finding_repo.list_active_by_repo_uid(repo_uid)  # findings survive untouched


def _experiences_evidencing(stack: _Stack, *repo_uids: str) -> list[dict]:
    """Active experiences whose accumulated evidence references *every* given repo_uid."""
    from psycopg.rows import dict_row

    clause = " AND ".join(["evidence::text LIKE %s"] * len(repo_uids))
    params = tuple(f"%{u}%" for u in repo_uids)
    with stack.db.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"SELECT * FROM learning.experiences WHERE status = 'active' AND {clause}",
                params,
            )
            return cur.fetchall()


def test_c6_dual_extraction_consolidates_experiences_across_projects(stack: _Stack, tmp_path):
    """Phase-C · C.6/CC6/P13: the SAME governed repo reads that produce engineering findings also
    distill owner experiences (dual extraction). Two distinct Python projects share skills, so those
    experiences consolidate into ONE cumulative record — corroborated by both projects, rising
    maturity — and re-learning a project does not inflate the corroboration."""
    repo_a = _write(tmp_path / "xp_a", {
        "app/__init__.py": "",
        "app/main.py": "class Api:\n    pass\n",
        "requirements.txt": "fastapi\n",
    })
    repo_b = _write(tmp_path / "xp_b", {
        "svc/__init__.py": "",
        "svc/api.py": "def handler():\n    return 1\n",
        "requirements.txt": "fastapi\n",
    })

    out_a = stack.intel.learn_repository(path=repo_a)
    out_b = stack.intel.learn_repository(path=repo_b)
    assert out_a["outcome"] == "ok" and out_a["experiences"] > 0
    assert out_b["outcome"] == "ok" and out_b["experiences"] > 0
    uid_a = out_a["repository"]["repo_uid"]
    uid_b = out_b["repository"]["repo_uid"]
    assert uid_a != uid_b

    # Dual extraction wired: experiences from repo A landed, provenance-linked to it.
    assert _experiences_evidencing(stack, uid_a)

    # Shared skills (both are Python projects declaring FastAPI) consolidate into ONE experience
    # evidenced by BOTH projects — not two rows (P13). At least the Python-language skill overlaps.
    shared = _experiences_evidencing(stack, uid_a, uid_b)
    assert shared, "expected at least one experience corroborated by both projects"
    exp = shared[0]
    src_ids = {s.get("source_id") for s in (exp["evidence"] or [])}
    assert {uid_a, uid_b} <= src_ids  # both projects corroborate the same experience
    assert exp["corroboration_count"] >= 2
    assert exp["maturity"] in ("verified", "established")  # ≥2 independent sources
    payload = exp["payload"] or {}
    assert payload.get("domain") == "experience"
    assert (payload.get("provenance") or {}).get("source") == SOURCE_REPO

    # Re-learning project A is a no-op: an already-known source must neither inflate corroboration
    # nor spawn a revision (evidence-merge stays in place).
    before = {str(e["id"]): (e["corroboration_count"], e["revision"]) for e in shared}
    stack.intel.learn_repository(path=repo_a)
    after = _experiences_evidencing(stack, uid_a, uid_b)
    for e in after:
        if str(e["id"]) in before:
            assert (e["corroboration_count"], e["revision"]) == before[str(e["id"])]


def test_repo_watcher_mission_runs_real_ingest_and_survives_reboot(stack: _Stack, tmp_path):
    # A RepoWatcher mission drives the *real* governed ingest on its schedule.
    watch = _write(tmp_path / "watchrepo", {
        "app/__init__.py": "",
        "app/main.py": "def run():\n    return 1\n",
    })
    result = stack.templates.instantiate(
        "repository_learning",
        title="B.8 repo-watcher",
        config_overrides={"repo_path": watch},
    )
    mission_id = result["mission"].id
    wid = result["workers"][0].id
    try:
        assert result["workers"][0].type == "repo_watcher"
        cfg = stack.configuration.get_active(mission_id)
        assert cfg.version == 1 and cfg.schema_type == "repo_watcher"

        # 1. First tick performs a real ingest + checkpoints its progress.
        r1 = stack.workers.worker_tick({"worker_id": wid})
        assert r1["ticked"] is True
        cp = stack.checkpoints.load("worker", wid)
        assert cp["ingests"] == 1 and cp["last_tree_checksum"]
        watch_repo = stack.intel_repo.list_repositories(limit=50)
        assert any(r.root.endswith("watchrepo") for r in watch_repo)

        # 2. "Process restart": a fresh manager resumes; unchanged tree → cheap Detect no-op.
        restarted = stack.new_worker_manager()
        restarted.worker_tick({"worker_id": wid})
        assert stack.checkpoints.load("worker", wid)["ingests"] == 1       # no re-ingest
        assert stack.checkpoints.load("worker", wid)["last_result"] == "no_change"

        # 3. Change the repo → next tick re-ingests through the same governed pipeline.
        _write(tmp_path / "watchrepo", {"app/extra.py": "def extra():\n    return 2\n"})
        stack.workers.worker_tick({"worker_id": wid})
        assert stack.checkpoints.load("worker", wid)["ingests"] == 2

        # 4. Config-versioned: an edit bumps the version, picked up on the next tick (journaled).
        v2 = stack.configuration.update_config(
            mission_id, {**cfg.document, "embed_code": False, "policy": "personal"},
            change_note="tweak policy", activate=True,
        )
        assert v2.version == 2
        stack.workers.worker_tick({"worker_id": wid})
        assert "config_picked_up" in _actions(stack, mission_id)
        assert stack.checkpoints.load("worker", wid)["config_version"] == 2
    finally:
        stack.missions.archive(mission_id, "B.8 cleanup")
