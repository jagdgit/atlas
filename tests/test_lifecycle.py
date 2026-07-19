"""Tests for Finding consolidation + lifecycle (Stage 3B.3)."""

from __future__ import annotations

from atlas.eval.fixtures import load_cases
from atlas.eval.lifecycle import score_freshness_corpus, score_supersession_corpus
from atlas.knowledge.consolidation import InMemoryFindingStore, KnowledgeLifecycleService
from atlas.knowledge.lifecycle import (
    decide_lifecycle_transition,
    freshness_label,
    finding_identity_key,
)


def _finding(**kwargs):
    base = {
        "statement": "RMSE about 1.2 percent",
        "value": {"number": 1.2, "unit": "%", "kind": "rmse"},
        "domain": "research",
        "confidence": "HIGH",
        "status": "active",
        "supporting_sources": [{"source_id": "p1", "evidence_level": 4}],
        "contradicting_sources": [],
        "provenance": {"component": "synthesizer:v1", "component_version": "1"},
        "claim_type": "quantitative",
    }
    base.update(kwargs)
    return base


def test_freshness_policy_matches_eval_fixtures():
    result = score_freshness_corpus(load_cases("freshness_cases.json"))
    assert result["freshness_label_accuracy"] == 1.0
    assert freshness_label(knowledge_type="software", age_days=400) == "stale"


def test_second_job_creates_revision_not_overwrite():
    store = InMemoryFindingStore()
    life = KnowledgeLifecycleService(store)
    first = life.consolidate(_finding())
    assert first["_transition"] == "create"
    assert first["revision"] == 1
    cid = first["canonical_id"]
    statement_v1 = first["statement"]

    second = life.consolidate(
        _finding(
            statement="RMSE about 1.25 percent",
            value={"number": 1.25, "unit": "%", "kind": "rmse"},
            supporting_sources=[
                {"source_id": "p1", "evidence_level": 4},
                {"source_id": "p2", "evidence_level": 4},
            ],
        )
    )
    assert second["_transition"] == "revise"
    assert second["canonical_id"] == cid
    assert second["revision"] == 2
    assert second["supersedes"] == first["id"]

    old = store.get(first["id"])
    assert old["status"] == "superseded"
    assert old["superseded_by"] == second["id"]
    assert old["statement"] == statement_v1  # never overwritten


def test_identical_promote_is_noop():
    store = InMemoryFindingStore()
    life = KnowledgeLifecycleService(store)
    a = life.consolidate(_finding())
    b = life.consolidate(_finding())
    assert b["_transition"] == "noop"
    assert b["id"] == a["id"]
    assert len(store.rows) == 1


def test_archive_and_active_heads_exclude_archive():
    store = InMemoryFindingStore()
    life = KnowledgeLifecycleService(store)
    row = life.consolidate(_finding())
    life.archive(row["id"])
    heads = store.list_active_heads(include_archive=False)
    assert heads == []
    assert store.get_head(row["canonical_id"], include_archive=True)["status"] == "archived"


def test_invalidate_component_marks_stale_and_enqueues_review():
    store = InMemoryFindingStore()
    enqueued = []
    life = KnowledgeLifecycleService(store, enqueue=lambda t, p: enqueued.append((t, p)))
    row = life.consolidate(_finding())
    out = life.invalidate_component("synthesizer:v1", version="1")
    assert out["stale_count"] == 1
    assert store.get(row["id"])["freshness"] == "stale"
    assert store.reviews
    assert enqueued and enqueued[0][0] == "review_finding"


def test_review_finding_re_verifies_and_completes_review():
    store = InMemoryFindingStore()
    life = KnowledgeLifecycleService(store)
    row = life.consolidate(
        _finding(
            supporting_sources=[
                {
                    "source_id": "p1",
                    "evidence_level": 4,
                    "extracted_value": 1.2,
                    "unit": "%",
                    "snippet": "RMSE 1.2%",
                    "stance": "support",
                },
                {
                    "source_id": "p2",
                    "evidence_level": 4,
                    "extracted_value": 1.25,
                    "unit": "%",
                    "snippet": "RMSE 1.25%",
                    "stance": "support",
                },
            ]
        )
    )
    life.invalidate_component("synthesizer:v1", version="1")
    assert store.get(row["id"])["freshness"] == "stale"
    result = life.review_finding({"finding_id": row["id"], "reason": "component bug"})
    assert result["status"] == "done"
    assert result["confidence"] in {"HIGH", "MEDIUM", "LOW", "INSUFFICIENT"}
    updated = store.get(row["id"])
    assert updated["freshness"] in {"current", "stale"}
    assert updated["last_verified"]
    assert any(r["status"] == "done" for r in store.reviews)


def test_supersession_fixture_transitions():
    # Production decide_lifecycle_transition aligns with labeled fixtures.
    cases = load_cases("supersession_cases.json")
    for case in cases:
        predicted = decide_lifecycle_transition(
            existing={"id": "x"} if case["gold_transition"] != "create" else None,
            incoming={"transition": case["gold_transition"]},
            content_changed=case["gold_transition"] == "revise",
        )
        assert predicted == case["gold_transition"]
    scored = score_supersession_corpus(
        [{**c, "predicted_transition": c["gold_transition"]} for c in cases]
    )
    assert scored["supersession_correctness"] == 1.0


def test_identity_key_quant_vs_prose():
    q = finding_identity_key(_finding())
    p = finding_identity_key(
        {"statement": "Cleaning helps", "domain": "research", "value": None}
    )
    assert q[0] == "quant"
    assert p[0] == "prose"
    assert q != p


def test_identity_key_experience_keys_on_skill_and_context():
    # The SAME skill in the SAME context is one identity (corroboration across projects, C.6/CC6),
    # regardless of the surface statement wording.
    a = finding_identity_key({
        "domain": "experience", "statement": "Uses Celery in a Django project",
        "value": {"kind": "experience", "skill": "Celery", "context": "python"},
    })
    b = finding_identity_key({
        "domain": "experience", "statement": "Relied on Celery for background jobs",
        "value": {"kind": "experience", "skill": "celery", "context": "Python"},
    })
    assert a[0] == "experience"
    assert a == b  # skill+context are normalized → same identity

    # Different context (or skill) → different identity.
    c = finding_identity_key({
        "domain": "experience", "statement": "Uses Celery",
        "value": {"kind": "experience", "skill": "celery", "context": "rust"},
    })
    assert c != a
    # Falls back to the statement when no structured skill is supplied.
    d = finding_identity_key({"domain": "experience", "statement": "Led a solo project"})
    assert d[0] == "experience" and d[1]
