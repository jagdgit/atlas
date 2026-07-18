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


def test_bare_numbers_same_statement_dedup_across_sources():
    # Identical config statements from two representations of one study must NOT
    # appear twice — they merge into one claim with multi-source support (§3B dedup).
    claims = [
        _claim("a", "The train/test split was 80/20.", number=80.0, unit="", kind="", source="p1"),
        _claim("b", "The train/test split was 80/20.", number=80.0, unit="", kind="", source="p2"),
    ]
    grouped = group_claims(claims)
    assert len(grouped) == 1
    assert len(grouped[0].supporting) == 2


def test_bare_numbers_different_statements_stay_apart():
    # Same bare number but different statements are different claims (no false merge).
    claims = [
        _claim("a", "The quantile q was set to 0.9.", number=0.9, unit="", kind="", source="p1"),
        _claim("b", "The dropout rate was 0.9 during training.", number=0.9, unit="", kind="", source="p2"),
    ]
    grouped = group_claims(claims)
    assert len(grouped) == 2


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


def test_representative_prefers_specific_numeric_over_longer_vague():
    from atlas.research.grouping import _rep

    vague = _claim(
        "long_vague",
        "the model reduced error substantially in every evaluated scenario overall",
        source="p1",
    )
    numeric = _claim("short_numeric", "the model reduced error by 0.4%", source="p2")
    # Same evidence level; the quantified statement must win despite being shorter,
    # so merging near-duplicate prose never discards the number (§3B refinement).
    assert _rep([vague, numeric]).id == "short_numeric"


def test_grouping_is_monotonic_adding_claims_never_reduces_count():
    # Property: group_claims only ever merges — adding claims (a later round)
    # cannot reduce the distinct total. Guards the reported "15 → 14" confusion.
    subset = [
        _claim("a", "RMSE 1.2%", number=1.2, unit="%", kind="rmse", source="p1"),
        _claim("b", "efficiency improved on unseen sites", source="p2"),
    ]
    extra = [
        _claim("c", "soiling loss 0.3%/day", number=0.3, unit="%/day",
               kind="soiling_loss", source="p3"),
        _claim("d", "a different qualitative finding about latitude effects", source="p4"),
    ]
    n_subset = len(group_claims(subset))
    n_superset = len(group_claims(subset + extra))
    assert n_superset >= n_subset


def test_empty_input():
    assert group_claims([]) == []
