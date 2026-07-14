"""Tests for cross-source claim grouping (§5g / D3.7 / A2)."""

from __future__ import annotations

from atlas.evidence.models import (
    STANCE_CONTRADICT,
    STANCE_SUPPORT,
    Claim,
    ClaimValue,
    EvidenceItem,
    LEVEL_PEER_REVIEWED,
    LEVEL_TECHNICAL,
)
from atlas.research.grouping import group_claims


def _claim(cid, statement, *, number=None, unit="", kind="", source="s", level=LEVEL_TECHNICAL):
    value = ClaimValue(number=number, unit=unit, kind=kind) if number is not None else None
    ev = EvidenceItem(
        source_id=source, evidence_level=level,
        extracted_value=number, unit=unit, snippet=statement, stance=STANCE_SUPPORT,
    )
    return Claim(id=cid, statement=statement, value=value, evidence=[ev])


def test_agreeing_quant_claims_merge_into_one_multi_source_claim():
    claims = [
        _claim("a", "RMSE 1.2%", number=1.2, unit="%", kind="rmse", source="p1", level=4),
        _claim("b", "RMSE 1.25%", number=1.25, unit="%", kind="rmse", source="p2", level=4),
        _claim("c", "RMSE 1.18%", number=1.18, unit="%", kind="rmse", source="p3", level=3),
    ]
    grouped = group_claims(claims)
    assert len(grouped) == 1
    merged = grouped[0]
    assert len(merged.supporting) == 3  # three independent sources back one claim
    assert {e.source_id for e in merged.supporting} == {"p1", "p2", "p3"}


def test_disagreeing_quant_value_becomes_contradiction():
    claims = [
        _claim("a", "loss 0.3%/day", number=0.3, unit="%/day", kind="soiling_loss", source="p1"),
        _claim("b", "loss 0.32%/day", number=0.32, unit="%/day", kind="soiling_loss", source="p2"),
        _claim("c", "loss 5.0%/day", number=5.0, unit="%/day", kind="soiling_loss", source="p3"),
    ]
    grouped = group_claims(claims)
    assert len(grouped) == 1
    merged = grouped[0]
    assert len(merged.supporting) == 2       # the agreeing majority
    assert len(merged.contradicting) == 1    # the outlier disagrees
    assert merged.contradicting[0].source_id == "p3"
    assert merged.contradicting[0].stance == STANCE_CONTRADICT


def test_different_kinds_do_not_merge():
    claims = [
        _claim("a", "RMSE 2%", number=2.0, unit="%", kind="rmse", source="p1"),
        _claim("b", "efficiency 2%", number=2.0, unit="%", kind="efficiency", source="p2"),
    ]
    grouped = group_claims(claims)
    assert len(grouped) == 2  # same value+unit but different quantity → separate claims


def test_bare_numbers_without_kind_stay_standalone():
    claims = [
        _claim("a", "value 10", number=10.0, unit="", kind="", source="p1"),
        _claim("b", "value 10", number=10.0, unit="", kind="", source="p2"),
    ]
    grouped = group_claims(claims)
    assert len(grouped) == 2  # no kind → grouping would be a false match, so kept apart


def test_similar_prose_claims_merge():
    claims = [
        _claim("a", "Data-driven cleaning schedules reduce operational cost significantly.", source="p1"),
        _claim("b", "Data-driven cleaning schedules significantly reduce operational costs.", source="p2"),
        _claim("c", "Solar irradiance varies with latitude and season.", source="p3"),
    ]
    grouped = group_claims(claims)
    # the two near-identical prose claims merge; the unrelated one stays separate
    assert len(grouped) == 2
    biggest = max(grouped, key=lambda c: len(c.supporting))
    assert len(biggest.supporting) == 2


def test_representative_prefers_stronger_evidence():
    claims = [
        _claim("weak", "finding stated weakly", source="blog", level=LEVEL_TECHNICAL),
        _claim("strong", "finding stated strongly with more detail here", source="ieee",
               level=LEVEL_PEER_REVIEWED),
    ]
    # make them similar enough to group
    claims[0] = _claim("weak", "finding stated strongly with more detail here too",
                       source="blog", level=LEVEL_TECHNICAL)
    grouped = group_claims(claims)
    assert len(grouped) == 1
    assert grouped[0].id == "strong"  # highest evidence level wins the representative


def test_empty_input():
    assert group_claims([]) == []
