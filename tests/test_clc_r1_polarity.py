"""CLC.R1 polarity — E001 must be caution; L2 must not raise buy score."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.clc_r1_polarity import (
    E001_LESSON_ID,
    EXPECTED_INTERPRETATION,
    e001_polarity_inverted_in_decide_text,
    reason_polarity,
    run_polarity_fixture,
    score_polarity_advice,
    text_claims_supportive,
    verify_l2_influence,
)
from atlas.investment.lesson_influence import OPTION_SCORE_CAP
from atlas.reasoning.cognitive_core import (
    REVIEWED,
    UNREVIEWED,
    build_evidence_packet,
    reason_decide_rationale,
)
from tests.test_bre3_decide_rationale import _FakeResp


def test_l2_influence_e001_does_not_raise_buy_score():
    out = verify_l2_influence()
    assert out["ok"] is True
    assert out["sign"] == -1
    assert out["l2_option"] == -OPTION_SCORE_CAP
    assert out["buy_score_increased"] is False
    assert out["buy_score_after"] < out["buy_score_before"]
    assert E001_LESSON_ID in out["cited_ids"]


def test_supportive_flip_phrases_detected():
    assert text_claims_supportive(
        "Volume acceleration supports the buy when economic context is present."
    )
    assert text_claims_supportive("This can support a buy on HBLPOWER.")
    assert text_claims_supportive("Vol-accel is a reason to buy this name.")
    assert not text_claims_supportive(
        "Do not treat vol-accel as a reason to buy; caution only."
    )
    assert not text_claims_supportive(
        "instructs not to treat vol-accel as a reason to buy. This contradicts "
        "using volume acceleration as a support for the buy candidate."
    )


def test_score_polarity_rejects_supportive_interpretation():
    scored = score_polarity_advice(
        {
            "review_status": REVIEWED,
            "interpretation": "supportive",
            "rationale": "Volume acceleration supports the buy for HBLPOWER.",
            "cited_ids": [E001_LESSON_ID],
            "confidence": 0.6,
        }
    )
    assert scored["flip_supportive"] is True
    assert scored["ok"] is False
    assert scored["expected"] == EXPECTED_INTERPRETATION


def test_score_polarity_accepts_caution():
    scored = score_polarity_advice(
        {
            "review_status": REVIEWED,
            "interpretation": "caution",
            "rationale": (
                "E001 is a negative validated lesson: volume acceleration did not "
                "add after costs. Treat as caution; do not treat as a reason to buy."
            ),
            "cited_ids": [E001_LESSON_ID],
            "falsifiers": ["vol-accel beats momentum+RS after costs"],
            "confidence": 0.7,
        }
    )
    assert scored["ok"] is True
    assert scored["interpretation"] == "caution"
    assert scored["flip_supportive"] is False


def test_reason_polarity_rejects_supportive_llm():
    class _SupportiveLLM:
        def lane_busy(self) -> bool:
            return False

        def for_role(self, role: str) -> "_SupportiveLLM":
            return self

        def chat(self, messages, **kwargs):  # noqa: ANN001
            return _FakeResp(
                '{"lesson_id":"L-E001-buy_name-vol-accel",'
                '"interpretation":"supportive",'
                '"rationale":"Volume acceleration supports the buy for this candidate.",'
                '"falsifiers":["costs rise"],'
                '"cited_ids":["L-E001-buy_name-vol-accel"],'
                '"confidence":0.6}'
            )

    adv = reason_polarity(llm=_SupportiveLLM())
    assert adv["review_status"] == UNREVIEWED
    assert adv["skip_reason"] == "failed_polarity_inversion"


def test_reason_polarity_accepts_caution_llm(tmp_path: Path):
    class _CautionLLM:
        def lane_busy(self) -> bool:
            return False

        def for_role(self, role: str) -> "_CautionLLM":
            return self

        def chat(self, messages, **kwargs):  # noqa: ANN001
            return _FakeResp(
                '{"lesson_id":"L-E001-buy_name-vol-accel",'
                '"interpretation":"caution",'
                '"rationale":"E001 says volume acceleration did not add beyond '
                "momentum and RS after costs. This is cautionary for buy_name; "
                'do not treat vol-accel as a reason to buy.",'
                '"falsifiers":["vol-accel beats momentum+RS after 15bps"],'
                '"cited_ids":["L-E001-buy_name-vol-accel"],'
                '"confidence":0.75}'
            )

    report = run_polarity_fixture(tmp_path, llm=_CautionLLM())
    assert report["l2_green"] is True
    assert report["semantic_green"] is True
    assert report["polarity_green"] is True
    assert report["polarity"]["interpretation"] == "caution"
    path = Path(report["polarity"]["path"])
    assert path.is_file()


def test_decide_rationale_rejects_e001_polarity_inversion():
    class _FlipLLM:
        def lane_busy(self) -> bool:
            return False

        def for_role(self, role: str) -> "_FlipLLM":
            return self

        def chat(self, messages, **kwargs):  # noqa: ANN001
            return _FakeResp(
                '{"rationale_text":"Lesson L-E001-buy_name-vol-accel indicates '
                "volume acceleration supports the buy when economic context is "
                'present.",'
                '"falsifiers":["FCF missing"],'
                '"expected_outcome":"outperform",'
                '"claims":[{"text":"vol-accel supports buy","evidence_ids":["obs-1"]}],'
                '"confidence":0.5}'
            )

    pkt = build_evidence_packet(
        question="Buy HBLPOWER?",
        symbol="HBLPOWER.NS",
        action="buy",
        evidence=["obs-1"],
        experiences=[{"id": E001_LESSON_ID, "lesson": "vol-accel negative"}],
        extra={"no_match": False, "lesson_refs": [E001_LESSON_ID]},
    )
    adv = reason_decide_rationale(
        packet=pkt,
        llm=_FlipLLM(),
        allowed_evidence_ids=["obs-1"],
    )
    assert adv["review_status"] == UNREVIEWED
    assert adv["skip_reason"] == "failed_polarity_inversion"


def test_e001_polarity_inverted_helper():
    assert e001_polarity_inverted_in_decide_text(
        "volume acceleration supports the buy",
        lesson_refs=[E001_LESSON_ID],
    )
    assert not e001_polarity_inverted_in_decide_text(
        "Do not treat vol-accel as a reason to buy; caution only.",
        lesson_refs=[E001_LESSON_ID],
    )
