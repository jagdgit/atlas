"""OI-SELF-EXP Phase 2 — Experience learning loop → Belief Core."""

from __future__ import annotations

from atlas.experience.os import ExperienceJournal, ExperienceOS
from atlas.reasoning import (
    InMemoryBeliefRepository,
    ReasoningService,
    close_loop,
    compute_delta,
    validate_belief_link,
)


class _FakeLearning:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def remember_experience(self, **fields):
        row = {"id": f"exp-{len(self.rows)+1}", **fields}
        self.rows.append(row)
        return {"applied": True, "event": {"ref_id": row["id"]}, "experience": row}

    def list_experiences(self, limit=50):
        return list(self.rows)[:limit]

    def recall(self, query, limit=None):
        return [r for r in self.rows if query.lower() in str(r).lower()][: limit or 20]

    def advice_for(self, query, limit=None):
        return {"query": query, "count": 0, "advice": "", "mutating": False}


def test_belief_link_required_for_learning_fields():
    eos = ExperienceOS(_FakeLearning())
    bad = eos.journal(
        title="t",
        observation="o",
        decision="d",
        outcome="out",
        reflection="r",
        lesson="l",
        prediction={"ret": 0.06},
        outcome_structured={"ret": -0.02},
        require_belief_link=True,
    )
    assert bad["ok"] is False
    assert bad["error"] == "belief_link_required"

    ok = eos.journal(
        title="t",
        observation="o",
        decision="d",
        outcome="out",
        reflection="r",
        lesson="Hidden state caused the flake",
        domain="engineering",
        prediction={"flake_rate": 0.2},
        outcome_structured={"flake_rate": 0.05},
        no_belief_link_reason="first observation; candidacy next",
        require_belief_link=True,
    )
    assert ok["ok"] is True
    assert ok["learning_loop"]["no_belief_link_reason"]


def test_closed_loop_strengthens_belief():
    learning = _FakeLearning()
    eos = ExperienceOS(learning)
    repo = InMemoryBeliefRepository()
    rs = ReasoningService(repo)
    rs.ensure_seeded()
    found = rs.consult(query="hidden state", limit=1)
    belief = found["beliefs"][0]
    before = float(belief["confidence"])

    out = close_loop(
        experience_os=eos,
        reasoning=rs,
        journal_kwargs={
            "title": "Eng flake loop",
            "observation": "Flaky test from cache",
            "decision": "Remove hidden cache",
            "outcome": "Flakes down",
            "reflection": "Hidden state hurt predictability",
            "lesson": "Hidden state reduces predictability across systems.",
            "domain": "engineering",
            "prediction": {"flake_rate": 0.3},
            "outcome_structured": {"flake_rate": 0.3},
            "affected_beliefs": [belief["id"]],
            "require_belief_link": True,
            "tags": ["engineering", "learning_loop"],
        },
        ingest_beliefs=True,
    )
    assert out["ok"] is True
    assert out["belief_ingest"]["ok"] is True
    after = rs.get_belief(belief["id"])
    # matched numeric delta → confidence up
    assert float(after["confidence"]) >= before
    mind = rs.what_changed_your_mind(belief["id"])
    assert mind["mind_changes"]


def test_closed_loop_creates_candidate_when_unlinked_ingest():
    """When affected_beliefs empty but we still ingest with only lesson → candidate path
    is via ingest_experience_lesson directly (mentor path)."""
    repo = InMemoryBeliefRepository()
    rs = ReasoningService(repo)
    rs.ensure_seeded()
    before_cand = len(rs.list_beliefs(status="candidate", limit=200))
    out = rs.ingest_experience_lesson(
        lesson="Prefer explicit module boundaries over shared mutable caches.",
        domain="engineering",
        experience_id="exp-test",
        delta_label="mentor",
    )
    assert out["ok"] is True
    assert out["candidate"]["status"] == "candidate"
    assert len(rs.list_beliefs(status="candidate", limit=200)) == before_cand + 1


def test_compute_delta_labels():
    d = compute_delta({"ret": 0.1}, {"ret": 0.1})
    assert d["label"] == "matched"
    d2 = compute_delta({"ret": 0.1}, {"ret": -0.05})
    assert d2["label"] == "missed"
    assert validate_belief_link(affected_beliefs=[], no_belief_link_reason=None)["ok"] is False


def test_legacy_journal_still_works_without_belief_link():
    eos = ExperienceOS(_FakeLearning())
    out = eos.journal(
        title="legacy",
        observation="o",
        decision="d",
        outcome="out",
        reflection="r",
        lesson="old path",
        domain="general",
    )
    assert out["ok"] is True


def test_experience_journal_dataclass_learning_fields():
    entry = ExperienceJournal(
        title="t",
        observation="o",
        decision="d",
        outcome="x",
        reflection="r",
        lesson="l",
        prediction={"a": 1},
        outcome_structured={"a": 2},
        affected_beliefs=["b1"],
    )
    payload = entry.to_store_payload()
    assert payload["learning_loop"]["belief_link_ok"] is True
    assert payload["delta"]["label"] == "missed"
