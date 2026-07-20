"""Hermetic tests for AdvisoryDecisionRule (Phase D · §D.9)."""

from __future__ import annotations

from atlas.decision.context import IntelligenceContext
from atlas.decision.contracts import DecisionRequest
from atlas.decision.rules import apply_policy_influence
from atlas.watch.decision_rule import (
    MISSION_TYPE_SECURITY,
    MISSION_TYPE_TECHNOLOGY,
    AdvisoryDecisionRule,
)

CTX = IntelligenceContext()
TECH = AdvisoryDecisionRule(MISSION_TYPE_TECHNOLOGY)
SEC = AdvisoryDecisionRule(MISSION_TYPE_SECURITY)

_ADVISORIES = [
    {
        "id": "CVE-2024-1", "title": "Critical RCE in openssl", "severity": "critical",
        "kind": "cve", "package": "openssl", "packages": ["openssl"], "cve": "CVE-2024-1",
        "url": "https://nvd.nist.gov/1",
    },
    {
        "id": "BRK-1", "title": "Breaking change in fastapi 0.110", "severity": "medium",
        "kind": "breaking_change", "package": "fastapi", "packages": ["fastapi"],
    },
    {
        "id": "LOW-1", "title": "Info note about lodash", "severity": "low",
        "kind": "dependency", "package": "lodash",
    },
]


def _req(rule, **context) -> DecisionRequest:
    return DecisionRequest(mission_id="m1", mission_type=rule.mission_type, context=context)


def _keys(options):
    return {o.key.split(":")[0] for o in options}


def test_severity_floor_filters_low():
    opts = TECH.score(
        _req(TECH, advisories=_ADVISORIES, severity_floor="medium", mode="technology"),
        CTX,
    )
    ids = {o.payload.get("advisory", {}).get("id") for o in opts if o.key.startswith("recommend")}
    assert "LOW-1" not in ids
    assert "BRK-1" in ids or "CVE-2024-1" in ids


def test_focus_requires_hit():
    opts = TECH.score(
        _req(TECH, advisories=_ADVISORIES, focus=["fastapi"], severity_floor="low", mode="technology"),
        CTX,
    )
    keys = {o.key for o in opts if o.key.startswith("recommend")}
    assert keys == {"recommend:BRK-1"}


def test_security_mode_prefers_cve():
    opts = SEC.score(
        _req(SEC, advisories=_ADVISORIES, focus=["openssl", "fastapi"],
             severity_floor="medium", mode="security"),
        CTX,
    )
    ranked = sorted([o for o in opts if o.key.startswith("recommend")],
                    key=lambda o: o.score, reverse=True)
    assert ranked[0].key == "recommend:CVE-2024-1"
    assert ranked[0].side_effecting is False


def test_technology_mode_prefers_breaking():
    # Equal focus; technology mode bonuses breaking_change over cve.
    mixed = [
        {**_ADVISORIES[0], "severity": "high"},  # cve high
        {**_ADVISORIES[1], "severity": "high"},  # breaking high
    ]
    opts = TECH.score(
        _req(TECH, advisories=mixed, focus=["openssl", "fastapi"],
             severity_floor="medium", mode="technology"),
        CTX,
    )
    ranked = sorted([o for o in opts if o.key.startswith("recommend")],
                    key=lambda o: o.score, reverse=True)
    assert ranked[0].key == "recommend:BRK-1"


def test_empty_holds():
    assert _keys(TECH.score(_req(TECH, advisories=[]), CTX)) == {"hold"}


def test_policy_avoid_package():
    opts = SEC.score(
        _req(SEC, advisories=[_ADVISORIES[0]], focus=["openssl"],
             severity_floor="high", mode="security"),
        CTX,
    )
    apply_policy_influence(opts, [{"id": "pol", "terms": ["openssl"], "weight": -5.0}])
    ranked = sorted(opts, key=lambda o: o.final_score, reverse=True)
    assert ranked[0].key == "hold"


def test_hold_untagged():
    opts = TECH.score(_req(TECH, advisories=_ADVISORIES[:1], severity_floor="low"), CTX)
    assert next(o for o in opts if o.key == "hold").tags == ("hold",)
