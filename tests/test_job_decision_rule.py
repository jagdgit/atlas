"""Hermetic tests for JobDecisionRule (Phase D · §D.8).

Deterministic ranking of postings against skills/locations/salary/companies; hold is
policy-neutral so prefer/avoid can arbitrate; hard constraints withhold rather than recommend.
"""

from __future__ import annotations

from atlas.career.decision_rule import JobDecisionRule
from atlas.decision.context import IntelligenceContext
from atlas.decision.contracts import DecisionRequest
from atlas.decision.rules import apply_policy_influence

RULE = JobDecisionRule()
CTX = IntelligenceContext()


def _req(**context) -> DecisionRequest:
    return DecisionRequest(mission_id="m1", mission_type="job_hunting", context=context)


def _keys(options):
    return {o.key.split(":")[0] for o in options}


_POSTINGS = [
    {
        "id": "j1", "title": "Senior Python Engineer", "company": "Acme",
        "location": "Berlin, DE", "skills": ["python", "django"], "salary": 120000,
        "url": "https://example.com/j1",
    },
    {
        "id": "j2", "title": "Java Backend", "company": "BetaCorp",
        "location": "Remote", "skills": ["java", "spring"], "salary": 110000,
    },
    {
        "id": "j3", "title": "Python Data Engineer", "company": "Acme",
        "location": "Munich", "skills": ["python", "spark"], "salary": 90000,
    },
]


def test_skill_overlap_ranks_higher():
    opts = RULE.score(
        _req(postings=_POSTINGS, personal_skills=["python"], skills=[]),
        CTX,
    )
    asserts_match = [o for o in opts if o.key.startswith("recommend")]
    asserts_match.sort(key=lambda o: o.score, reverse=True)
    assert asserts_match[0].key in ("recommend:j1", "recommend:j3")
    assert asserts_match[0].payload["kind"] == "recommend_match"
    assert asserts_match[0].side_effecting is False
    assert "hold" in _keys(opts)


def test_location_and_salary_constraints_withhold():
    opts = RULE.score(
        _req(
            postings=_POSTINGS,
            personal_skills=["python"],
            locations=["berlin"],
            min_salary=100000,
        ),
        CTX,
    )
    keys = {o.key for o in opts if o.key.startswith("recommend")}
    assert keys == {"recommend:j1"}  # j3 salary too low; j2 location + skills


def test_company_allow_list():
    opts = RULE.score(
        _req(postings=_POSTINGS, companies=["betacorp"], personal_skills=["java"]),
        CTX,
    )
    keys = {o.key for o in opts if o.key.startswith("recommend")}
    assert keys == {"recommend:j2"}


def test_min_skill_overlap_withholds_weak_matches():
    opts = RULE.score(
        _req(
            postings=[
                {"id": "a", "title": "Engineer", "company": "X", "location": "Remote",
                 "skills": ["python"], "salary": 100000},
            ],
            personal_skills=["python"],
            min_skill_overlap=2,
        ),
        CTX,
    )
    assert _keys(opts) == {"hold"}  # only 1 overlapping skill, need 2



def test_empty_postings_holds():
    assert _keys(RULE.score(_req(postings=[]), CTX)) == {"hold"}


def test_policy_avoid_company_suppresses_match():
    opts = RULE.score(
        _req(postings=_POSTINGS[:1], personal_skills=["python", "django"]),  # Acme only
        CTX,
    )
    apply_policy_influence(opts, [{"id": "pol-avoid", "terms": ["acme"], "weight": -5.0}])
    ranked = sorted(opts, key=lambda o: o.final_score, reverse=True)
    assert ranked[0].key == "hold"
    acme = next(o for o in opts if o.key.startswith("recommend"))
    assert "pol-avoid" in acme.policy_ids
    assert acme.final_score < 0.3


def test_hold_has_no_venue_tags():
    opts = RULE.score(_req(postings=_POSTINGS[:1], personal_skills=["python"]), CTX)
    hold = next(o for o in opts if o.key == "hold")
    assert hold.tags == ("hold",)
