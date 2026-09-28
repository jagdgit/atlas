"""COG-1..4 — Cognitive Core contract densify (envelope, expected_effect, L2 provenance, Eng)."""

from __future__ import annotations

from atlas.engineering.mentor import synthesize_engineering_lesson
from atlas.investment.lesson_influence import (
    E001_LESSON_ID,
    INFLUENCE_SOURCE_COGNITIVE_UNREVIEWED,
    INFLUENCE_SOURCE_DETERMINISTIC,
    apply_to_options,
    canonical_e001_lesson,
    match_lessons,
    stamp_belief_context,
)
from atlas.reasoning.cognitive_contract import (
    CONTRACT_VERSION,
    CognitiveSurface,
    EFFECT_DIR_NEGATIVE,
    EFFECT_DIR_UNKNOWN,
    expected_effect,
    influence_event,
    lesson_expected_effect,
    make_cognitive_result,
    polarity_inverted_vs_expected_effect,
)
from atlas.reasoning.cognitive_core import (
    REVIEWED,
    UNREVIEWED,
    evidence_packet_from_engineering,
    reason_as_scientist,
    reason_decide_rationale,
)


def test_cog1_dual_surface_envelope():
    sci = make_cognitive_result(
        surface=CognitiveSurface.SCIENTIST,
        review_status=REVIEWED,
        decision_id="d-sci-1",
        payload={"interpretation": "hold", "recommendation": "densify"},
        claims=[{"text": "a", "evidence_ids": ["e1"]}],
        confidence=0.4,
    )
    assert sci["contract_version"] == CONTRACT_VERSION
    assert sci["surface"] == "scientist"
    assert sci["payload"]["interpretation"] == "hold"
    assert sci["interpretation"] == "hold"  # flattened
    assert sci["decision_id"] == "d-sci-1"
    assert "e1" in sci["provenance"]

    dec = make_cognitive_result(
        surface=CognitiveSurface.DECIDE_RATIONALE,
        review_status=REVIEWED,
        decision_id="d-dec-1",
        payload={"rationale_text": "caution", "falsifiers": ["f1"]},
    )
    assert dec["surface"] == "decide_rationale"
    assert dec["rationale_text"] == "caution"
    assert dec["payload"]["falsifiers"] == ["f1"]


def test_cog1_scientist_and_decide_stamp_surface():
    adv = reason_as_scientist(
        packet={"question": "x", "evidence": ["a"], "decision_id": "d1"},
        llm=None,
    )
    assert adv["surface"] == "scientist"
    assert adv["review_status"] == UNREVIEWED
    assert adv["decision_id"] == "d1"
    assert "payload" in adv

    dec = reason_decide_rationale(
        packet={"question": "y", "evidence": ["b"], "decision_id": "d2"},
        llm=None,
    )
    assert dec["surface"] == "decide_rationale"
    assert dec["decision_id"] == "d2"
    assert dec["review_status"] == UNREVIEWED


def test_cog2_e001_carries_expected_effect_not_id_logic():
    lesson = canonical_e001_lesson()
    ee = lesson_expected_effect(lesson)
    assert ee["target"] == "buy_score"
    assert ee["direction"] == EFFECT_DIR_NEGATIVE
    assert lesson["expected_effect"]["direction"] == EFFECT_DIR_NEGATIVE

    unknown = lesson_expected_effect({"id": "L-X", "statement": "thin"})
    assert unknown["direction"] == EFFECT_DIR_UNKNOWN

    # Supportive flip of negative buy_score → inverted
    assert polarity_inverted_vs_expected_effect(
        "Volume acceleration supports the buy",
        lessons=[lesson],
        lesson_refs=[E001_LESSON_ID],
    )
    # Caution reading → ok
    assert not polarity_inverted_vs_expected_effect(
        "Do not treat vol-accel as a reason to buy; caution only.",
        lessons=[lesson],
        lesson_refs=[E001_LESSON_ID],
    )
    # No expected_effect → no assertion
    assert not polarity_inverted_vs_expected_effect(
        "supports the buy",
        lessons=[{"id": "L-NONE", "expected_effect": expected_effect()}],
        lesson_refs=["L-NONE"],
    )


def test_cog2_decide_rejects_polarity_via_expected_effect():
    class _Flip:
        def for_role(self, role):
            return self

        def lane_busy(self):
            return False

        def chat(self, messages, **kwargs):
            class R:
                text = (
                    '{"rationale_text":"Volume acceleration supports the buy.",'
                    '"falsifiers":["momentum fades"],'
                    '"expected_outcome":"up",'
                    '"claims":[{"text":"vol-accel supports buying",'
                    '"evidence_ids":["obs-1"]}],'
                    '"confidence":0.6}'
                )

            return R()

    from atlas.reasoning.cognitive_core import build_evidence_packet

    pkt = build_evidence_packet(
        question="Buy?",
        symbol="HBLPOWER.NS",
        action="buy",
        decision_id="cog2-polarity",
        evidence=["obs-1"],
        experiences=[canonical_e001_lesson()],
        extra={"no_match": False, "lesson_refs": [E001_LESSON_ID]},
    )
    adv = reason_decide_rationale(
        packet=pkt, llm=_Flip(), allowed_evidence_ids=["obs-1"]
    )
    assert adv["review_status"] == UNREVIEWED
    assert adv["skip_reason"] == "failed_polarity_inversion"
    assert adv["surface"] == "decide_rationale"


def test_cog3_influence_provenance_deterministic():
    lessons = match_lessons(
        candidate={
            "decision_type": "buy_name",
            "action": "buy",
            "features": ["volume_acceleration_20d"],
            "query": "volume acceleration buy_name",
        },
        retrieved=[canonical_e001_lesson()],
        query="volume acceleration buy_name",
    )
    ctx = stamp_belief_context({}, lessons)
    events = ctx.get("influence_events") or []
    assert events
    assert events[0]["influence_source"] == INFLUENCE_SOURCE_DETERMINISTIC
    assert events[0]["lesson_id"] == E001_LESSON_ID
    assert events[0]["bounded_delta"]["option"] < 0

    class _Opt:
        key = "buy:HBLPOWER.NS"
        score = 0.8
        rationale = "base"
        experience_refs: list[str] = []

    opt = _Opt()
    apply_to_options([opt], lessons)
    assert opt.score < 0.8
    assert getattr(opt, "influence_events", None)


def test_cog3_cognitive_unreviewed_zeros_delta():
    ev = influence_event(
        lesson_id="L-X",
        bounded_delta={"option": -0.25, "ranking": -0.1},
        influence_source=INFLUENCE_SOURCE_COGNITIVE_UNREVIEWED,
        cognitive_review_status=UNREVIEWED,
    )
    assert ev["bounded_delta"]["option"] == 0.0
    assert ev["influence_source"] == INFLUENCE_SOURCE_COGNITIVE_UNREVIEWED


def test_cog4_engineering_packet_through_core():
    mentor = synthesize_engineering_lesson([], force_topic="cognitive-contract")
    assert mentor is not None
    pkt = evidence_packet_from_engineering(mentor, decision_id="eng-cog4-1")
    assert pkt["kind"] == "EVIDENCE_PACKET"
    assert pkt["laboratory_id"] == "engineering_mentor"
    assert pkt["decision_id"] == "eng-cog4-1"
    assert pkt.get("symbol") is None
    assert any("domain:engineering" in str(k) for k in (pkt.get("known") or []))
    assert (pkt.get("extra") or {}).get("domain") == "engineering"

    # No LLM → honest UNREVIEWED with lineage preserved
    adv = reason_as_scientist(packet=pkt, llm=None)
    assert adv["surface"] == "scientist"
    assert adv["review_status"] == UNREVIEWED
    assert adv["decision_id"] == "eng-cog4-1"
    assert adv["laboratory_id"] == "engineering_mentor"
    assert adv["never_orders"] is True

    class _EngLLM:
        def for_role(self, role):
            return self

        def lane_busy(self):
            return False

        def chat(self, messages, **kwargs):
            class R:
                text = (
                    '{"summary":"Prefer smaller diffs when debt signals repeat.",'
                    '"recommendation":"Keep mentor advice soft-bias only.",'
                    '"unknowns":["whether_pattern_still_applies"],'
                    '"falsifiers":["debt signals gone after refactor"],'
                    '"confidence":0.5}'
                )

            return R()

    reviewed = reason_as_scientist(packet=pkt, llm=_EngLLM())
    assert reviewed["review_status"] == REVIEWED
    assert reviewed["surface"] == "scientist"
    assert reviewed["decision_id"] == "eng-cog4-1"
    assert reviewed["payload"]["recommendation"]
    assert "engineering" in (reviewed.get("laboratory_id") or "")
