"""Phase-C end-to-end acceptance — the Phase-C gate (PHASE_C_PLAN §C.9).

Exercises the **whole Phase-C story** against a live PostgreSQL through the *one unified pipeline*
(``Asset → Reader → Artifact → candidate → Consolidator → global knowledge``), wiring the real
Asset/Storage stores, the ingestion bridge (Document + Conversation readers), the shared
Consolidator with the **lineage** evidence graph, coverage, experience consolidation, the personal
domain, and the policy store — exactly as ``bootstrap`` does (deterministic stubs for the LLM):

  * **Global, deduplicated knowledge (P13):** the *same fact* stated in two different assets
    consolidates into **one finding with two evidence sources + higher confidence/maturity**, not two
    rows — and the merge is **explainable** (lineage `created_by` + `supported_by`, P9) and
    **provenance-stamped** (both source assets, P12).
  * **Consolidated experience/skills:** a code repo yields engineering findings **and** owner
    experiences, from which the personal profile infers skills (CC7).
  * **Coverage-driven re-extraction (A10):** re-reading an **unchanged** asset with a **bumped reader
    version** is *updates-not-duplicates* — the asset is reused (not re-stored), a new coverage row is
    minted for the new reader version, and the delta is attributable to the **reader** (not the source).
  * **Policy visibly biases retrieval, reversibly:** a live `prefer` rule lifts the matching hit in
    the re-ranker; reverting the rule removes the influence (P9, governed + reversible).

Requires a live DB; the whole module is skipped if PostgreSQL is unreachable (matching the other e2e
modules). The Owner Knowledge Mission running this on schedule / surviving reboot / config-versioned
is proven by ``tests/test_phase_c_owner_e2e.py`` (C.8e); this module is the knowledge-pipeline gate.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from atlas.assets import AssetRepository, AssetStore
from atlas.code.parser import CodeParser
from atlas.code.service import CodeService
from atlas.config import IntelligenceConfig, LearningConfig
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
from atlas.knowledge.access import RankedHit, heuristic_rerank
from atlas.knowledge.candidate_consumer import CandidateConsumer
from atlas.knowledge.consolidation import KnowledgeLifecycleService
from atlas.knowledge.coverage import CoverageService
from atlas.knowledge.lifecycle import finding_identity_key
from atlas.knowledge.prose_extraction import ProseKnowledgeExtractor
from atlas.knowledge.service import KnowledgeService
from atlas.learning.experience_extraction import ExperienceWriter
from atlas.models.learning import STORE_CODE
from atlas.personal import PersonalService
from atlas.policy import PolicyService
from atlas.readers import ConversationReader, DocumentReader
from atlas.readers.document import DOCUMENT_READER_ID
from atlas.repositories.candidate_repo import CandidateRepository
from atlas.repositories.chunk_repo import ChunkRepository
from atlas.repositories.coverage_repo import CoverageRepository
from atlas.repositories.document_repo import DocumentRepository
from atlas.repositories.embedding_repo import EmbeddingRepository
from atlas.repositories.experience_store import ExperienceStore
from atlas.repositories.finding_repo import FindingRepository
from atlas.repositories.intelligence_repo import IntelligenceRepository
from atlas.repositories.learning_repo import LearningRepository
from atlas.repositories.lineage_repo import LineageRepository
from atlas.repositories.personal_repo import PersonalRepository
from atlas.repositories.policy_repo import PolicyRepository
from atlas.services.learning_service import LearningService
from atlas.storage.repository import StorageRepository
from atlas.storage.service import StorageManager


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


class _DocumentReaderV2(DocumentReader):
    """Same reader, bumped version — the A10 'improved extractor/reader' knob."""

    VERSION = "2.0.0"


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


class _Stack:
    """The full Phase-C knowledge pipeline (engineering + ingestion + lineage + personal + policy)."""

    def __init__(self, db: DatabaseManager, tmp_path: Path) -> None:
        self.db = db
        salt = uuid.uuid4().hex[:12]
        storage = StorageManager(tmp_path / "storage", StorageRepository(db))
        storage.start()
        self.assets = AssetStore(storage, AssetRepository(db))
        self.artifacts = DerivedArtifactStore(storage)

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
        self.coverage = CoverageService(CoverageRepository(db), self.finding_repo)
        self.coverage_repo = CoverageRepository(db)
        self.intel = IntelligenceService(
            code, self.intel_repo, self.learning, IntelligenceConfig(),
            acquirer=RepoAcquirer(self.assets, storage, git=_PathGit(salt)),
            artifacts=self.artifacts,
            graph_store=ArchitectureGraphStore(self.assets),
            design_reviewer=DesignReviewer(_StubLLM()),
            findings=writer, finding_repo=self.finding_repo, coverage=self.coverage,
        )

        # Unified ingestion bridge + the shared Consolidator WITH the lineage evidence graph (P9).
        self.knowledge = KnowledgeService(
            DocumentRepository(db), ChunkRepository(db), EmbeddingRepository(db), _StubLLM(),
            embedding_model="stub", chunk_max_words=40, chunk_overlap=5,
        )
        self.lineage = LineageRepository(db)
        lifecycle = KnowledgeLifecycleService(self.finding_repo, lineage=self.lineage)
        self.knowledge._lifecycle = lifecycle  # noqa: SLF001
        self.candidates = CandidateConsumer(CandidateRepository(db), lifecycle)
        self.document_reader = DocumentReader(self.assets, self.artifacts)
        self.conversation_reader = ConversationReader(self.assets, self.artifacts)
        self.ingestion = IngestionService(
            AssetAcquirer(self.assets), self.document_reader, self.knowledge,
            extractor=ProseKnowledgeExtractor(), candidates=self.candidates, coverage=self.coverage,
        )
        self.personal = PersonalService(
            PersonalRepository(db), experiences=self.experience_store, intelligence=self.intel,
        )
        self.policy = PolicyService(PolicyRepository(db))


@pytest.fixture(scope="module")
def stack(db, tmp_path_factory):
    return _Stack(db, tmp_path_factory.mktemp("phase_c_e2e"))


def test_cross_source_global_dedup_is_explainable_and_provenanced(stack: _Stack, tmp_path):
    """P13 gate: the SAME fact stated in two distinct assets → ONE finding, TWO evidence sources,
    higher maturity — merged in place (not two rows), explainable via lineage (P9), and stamped with
    both source assets (P12)."""
    token = uuid.uuid4().hex[:8]
    # An identical, substantive claim in BOTH files; the token makes the *finding identity* unique
    # per run (knowledge is global + cumulative — a fixed claim would keep accumulating sources across
    # runs in the shared dev DB, OI-T1). Unique headers keep the two source assets distinct.
    claim = f"Atlas depends on Redis for its distributed {token} task queue across production services."
    doc_a = tmp_path / f"a_{token}.md"
    doc_b = tmp_path / f"b_{token}.md"
    doc_a.write_text(f"# note {token} A\n\n{claim}\n")
    doc_b.write_text(f"# note {token} B\n\n{claim}\n")

    ra = stack.ingestion.ingest_file(doc_a, domain="personal", embed=False, extract_findings=True)
    rb = stack.ingestion.ingest_file(doc_b, domain="personal", embed=False, extract_findings=True)
    assert ra.ok and rb.ok and ra.asset_id != rb.asset_id  # two distinct source assets
    assert ra.candidates >= 1 and rb.candidates >= 1

    # Drain the candidate inbox through the Consolidator (the single write path).
    stack.candidates.consume_pending(limit=500)

    identity = finding_identity_key({"statement": claim, "domain": "personal", "claim_type": "prose"})
    finding = stack.finding_repo.find_active_by_identity(identity)
    assert finding is not None, "the shared claim must exist as an active finding"

    # ONE finding, TWO evidence sources (both assets), rising maturity — cumulative, not duplicated.
    supporting = finding.get("supporting") or []
    source_ids = {s.get("source_id") for s in supporting}
    assert {ra.asset_id, rb.asset_id} <= source_ids, "both source assets corroborate the one finding"
    assert len(supporting) == 2
    assert finding["maturity"] in ("verified", "established")  # ≥2 independent sources
    assert finding["revision"] == 1  # evidence merged in place — NOT a new revision

    # Explainable (P9): the evidence graph records creation + corroboration.
    edges = {e["edge_type"] for e in stack.lineage.list_for_finding(str(finding["id"]))}
    assert "created_by" in edges and "supported_by" in edges

    # Provenance (P12): the finding carries its source lineage.
    assert (finding.get("provenance") or {}).get("source") == "document"


def test_code_repo_yields_experiences_and_personal_skills(stack: _Stack, tmp_path):
    """The same governed repo read produces engineering findings AND owner experiences (C.6), from
    which the personal domain infers skills (C.7) — retrieval, not action."""
    token = uuid.uuid4().hex[:8]
    repo = _write(tmp_path / f"proj_{token}", {
        "app/__init__.py": "",
        "app/main.py": f"class Api:  # {token}\n    def run(self):\n        return 1\n",
        "requirements.txt": "fastapi\ncelery\n",
    })
    out = stack.intel.learn_repository(path=repo)
    assert out["outcome"] == "ok"
    assert out["findings"] >= 1 and out["experiences"] >= 1
    repo_uid = out["repository"]["repo_uid"]

    # Engineering findings are global + provenance-stamped.
    findings = stack.finding_repo.list_active_by_repo_uid(repo_uid)
    assert findings

    # Personal profile infers skills from the consolidated experiences (held inferred, CC7).
    counts = stack.personal.infer()
    assert counts["skills"] >= 1
    skills = stack.personal.list_facts(category="skill")
    assert any(s["state"] == "inferred" for s in skills)


def test_reader_version_reextraction_updates_not_duplicates(stack: _Stack, tmp_path):
    """A10 gate: re-reading an UNCHANGED asset with a bumped reader version reuses the asset (no
    duplicate storage) and mints a NEW coverage row for the new reader version — the delta is
    attributable to the reader, not the source."""
    token = uuid.uuid4().hex[:8]
    doc = tmp_path / f"cov_{token}.md"
    doc.write_text(f"# coverage {token}\n\nThe Atlas coverage map tracks what each reader read per asset version.\n")

    r1 = stack.ingestion.ingest_file(doc, domain="external", embed=False)
    assert r1.ok and r1.asset_reused is False

    # Re-read the SAME bytes with a bumped reader version (v2.0.0).
    reader_v2 = _DocumentReaderV2(stack.assets, stack.artifacts)
    r2 = stack.ingestion.ingest_file(
        doc, domain="external", embed=False, reader=reader_v2, source="document"
    )
    assert r2.asset_reused is True                       # unchanged source → asset NOT re-stored
    assert r2.asset_id == r1.asset_id and r2.asset_version == r1.asset_version

    # Both reader versions have their own coverage row (the old read is preserved for the delta).
    cov_v1 = stack.coverage_repo.get(r1.asset_id, r1.asset_version, DOCUMENT_READER_ID, "1.0.0")
    cov_v2 = stack.coverage_repo.get(r1.asset_id, r1.asset_version, DOCUMENT_READER_ID, "2.0.0")
    assert cov_v1 is not None and cov_v1["status"] == "done"
    assert cov_v2 is not None and cov_v2["status"] == "done"

    # Targeted re-extraction (A10): from v2's vantage, the v1 row is stale and enumerable.
    stale = stack.coverage_repo.stale(DOCUMENT_READER_ID, reader_version="2.0.0")
    stale_keys = {(s["asset_id"], s["reader_version"]) for s in stale}
    assert (str(r1.asset_id), "1.0.0") in {(str(k[0]), k[1]) for k in stale_keys}


def test_policy_visibly_biases_retrieval_and_is_reversible(stack: _Stack):
    """CC8 gate: a live `prefer` rule lifts the matching hit in the re-ranker (influence, not
    arbitration); reverting the rule removes the influence (governed + reversible, P9)."""
    token = uuid.uuid4().hex[:8].lower()
    hits = [
        RankedHit(chunk_id="c_other", document_id="d1", ordinal=0,
                  content="a generic broad index note", rrf_score=0.02, score=0.02),
        RankedHit(chunk_id="c_topic", document_id="d2", ordinal=0,
                  content=f"a note about {token} strategy", rrf_score=0.02, score=0.02),
    ]

    rule = stack.policy.create_rule(token, "prefer", strength=1.0, created_by="test")

    influence = stack.policy.retrieval_influence()
    ranked = heuristic_rerank(list(hits), "", policy_rules=influence)
    assert ranked[0].chunk_id == "c_topic"          # the preferred topic is lifted
    assert ranked[0].policy_boost > 0
    assert str(rule["id"]) in {str(i) for i in ranked[0].policy_ids}

    # Reversible: revert the rule's creation → influence for this subject disappears.
    created = [e for e in stack.policy.list_events(rule_id=str(rule["id"]))
               if e["action"] == "created"][0]
    stack.policy.revert(str(created["id"]), actor="test")
    influence_after = stack.policy.retrieval_influence()
    assert token not in {i["subject"] for i in influence_after}
    ranked_after = heuristic_rerank(list(hits), "", policy_rules=influence_after)
    assert all(h.policy_boost == 0 for h in ranked_after)  # no policy influence remains
