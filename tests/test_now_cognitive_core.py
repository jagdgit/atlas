"""NOW #5 — ReasoningService Cognitive Core (scientist evidence packets)."""

from __future__ import annotations

from atlas.reasoning.cognitive_core import (
    REVIEWED,
    UNREVIEWED,
    build_evidence_packet,
    evidence_packet_from_icr_notes,
    merge_advice_into_icr_notes,
    reason_as_scientist,
)
from atlas.reasoning.service import ReasoningService
from atlas.repositories.belief_repo import InMemoryBeliefRepository


def test_packet_bounds_and_honesty():
    pkt = build_evidence_packet(
        question="Should CIPLA stay allocated?",
        laboratory_id="india_equity_learner",
        symbol="CIPLA.NS",
        evidence=["acp=EXIT_REVIEW", "stance=AVOID"],
        unknowns=["identity_repair"],
        contradictions=["AVOID while held"],
    )
    assert pkt["kind"] == "EVIDENCE_PACKET"
    assert pkt["advice_only"] if "advice_only" in pkt else True
    assert "never invent" in (pkt.get("temporal_note") or "").lower() or "unknown" in (
        pkt.get("honesty") or ""
    ).lower()
    assert pkt["symbol"] == "CIPLA.NS"


def test_no_llm_is_unreviewed_not_silent_success():
    pkt = build_evidence_packet(question="x", evidence=["a"])
    adv = reason_as_scientist(packet=pkt, llm=None)
    assert adv["review_status"] == UNREVIEWED
    assert adv["advice_only"] is True
    assert adv["never_orders"] is True
    assert adv["llm"] is False
    assert adv.get("skip_reason") == "no_llm"


class _FakeLLM:
    def for_role(self, role):
        assert role in {"scientist", "researcher"}
        return self

    def lane_busy(self):
        return False

    def chat(self, messages, **kwargs):
        class R:
            text = (
                '{"explanations":["thesis AVOID vs book"],'
                '"contradictions":["allocated under AVOID"],'
                '"unknowns":["identity_repair"],'
                '"falsifiers":["clear quarantine with MoS>0"],'
                '"confidence":0.55,'
                '"recommendation":"Keep EXIT_REVIEW; densify identity before ADD",'
                '"summary":"CIPLA: EXIT_REVIEW — repair identity before trusting edge."}'
            )

        return R()


def test_llm_success_is_reviewed():
    from atlas.llm.provider import ChatMessage

    pkt = build_evidence_packet(
        question="CIPLA?",
        symbol="CIPLA.NS",
        evidence=["EXIT_REVIEW"],
    )
    seen = {}

    class _MsgLLM(_FakeLLM):
        def chat(self, messages, **kwargs):
            seen["messages"] = messages
            return super().chat(messages, **kwargs)

    adv = reason_as_scientist(packet=pkt, llm=_MsgLLM())
    assert adv["review_status"] == REVIEWED
    assert adv["llm"] is True
    assert adv["never_orders"] is True
    assert "EXIT" in (adv.get("summary") or "")
    assert adv.get("confidence") == 0.55
    assert seen["messages"]
    assert all(isinstance(m, ChatMessage) for m in seen["messages"])
    assert hasattr(seen["messages"][0], "as_dict")


def test_coerce_chat_messages_accepts_dicts():
    from atlas.llm.provider import ChatMessage, coerce_chat_messages

    out = coerce_chat_messages(
        [
            {"role": "system", "content": "sys"},
            ChatMessage(role="user", content="hi"),
        ]
    )
    assert len(out) == 2
    assert all(isinstance(m, ChatMessage) for m in out)
    assert out[0].as_dict() == {"role": "system", "content": "sys"}


def test_merge_unreviewed_keeps_deterministic_draft():
    notes = {
        "source": "deterministic",
        "summary": "draft",
        "contradictions": ["c1"],
        "llm": False,
    }
    adv = reason_as_scientist(packet=build_evidence_packet(question="q"), llm=None)
    merged = merge_advice_into_icr_notes(notes, adv)
    assert merged["review_status"] == UNREVIEWED
    assert merged["summary"] == "draft"
    assert merged["llm"] is False
    assert merged["cognitive_core"]["skip_reason"] == "no_llm"


def test_icr_packet_bridge():
    pkt = evidence_packet_from_icr_notes(
        {
            "symbol": "CIPLA.NS",
            "acp_decision": "EXIT_REVIEW",
            "contradictions": ["AVOID while held"],
            "unknowns_that_flip_ranking": ["identity_repair"],
            "incumbent_edge_robust": "fragile",
            "flip_hints": ["clear quarantine"],
        },
        acp_snapshot={"decision": "EXIT_REVIEW", "thesis_stance": "avoid"},
        laboratory_id="india_equity_learner",
    )
    assert pkt["symbol"] == "CIPLA.NS"
    assert any("EXIT_REVIEW" in e for e in pkt["evidence"])


def test_reasoning_service_reason_scientist():
    repo = InMemoryBeliefRepository()
    rs = ReasoningService(repo, llm=_FakeLLM())
    adv = rs.reason_scientist(
        question="CIPLA EXIT_REVIEW?",
        laboratory_id="india_equity_learner",
        symbol="CIPLA.NS",
        evidence=["ACP EXIT_REVIEW", "stance AVOID"],
        unknowns=["identity_repair"],
        consult_beliefs=True,
    )
    assert adv["review_status"] == REVIEWED
    assert adv["advice_only"] is True


class _FakeDecideLLM:
    def for_role(self, role):
        assert role in {"market", "scientist", "researcher"}
        return self

    def lane_busy(self):
        return False

    def chat(self, messages, **kwargs):
        class R:
            text = (
                '{"rationale_text":"Buy on cited obs only.",'
                '"falsifiers":["FCF stays missing"],'
                '"expected_outcome":"outperform 30d",'
                '"claims":[{"text":"ok","evidence_ids":["obs-1"]}]}'
            )

        return R()


def test_reason_decide_rationale_reviewed():
    from atlas.reasoning.cognitive_core import reason_decide_rationale

    pkt = build_evidence_packet(
        question="Buy APOLLO?",
        symbol="APOLLOHOSP.NS",
        action="buy",
        evidence=["obs-1"],
    )
    adv = reason_decide_rationale(
        packet=pkt,
        llm=_FakeDecideLLM(),
        allowed_evidence_ids=["obs-1"],
    )
    assert adv["review_status"] == REVIEWED
    assert adv["rationale_text"]
    assert adv["falsifiers"]
    assert adv["never_orders"] is True


class _TruncatedDecideLLM:
    def for_role(self, role):
        return self

    def lane_busy(self):
        return False

    def chat(self, messages, **kwargs):
        class R:
            text = (
                '{"rationale_text":"Lesson E001 still applies; do not size up.",'
                '"falsifiers":["FCF stays missing"],'
                '"expected_outcome":"flat to down 5d",'
                '"claims":[{"text":"cited","evidence_ids":["obs-1"]}],'
                '"confidence":0.4'
            )

        return R()


def test_reason_decide_rationale_repairs_truncated_json():
    from atlas.reasoning.cognitive_core import reason_decide_rationale

    pkt = build_evidence_packet(
        question="Buy HBLPOWER?",
        symbol="HBLPOWER.NS",
        action="buy",
        evidence=["obs-1"],
        experiences=[{"id": "E001-buy_name-vol-accel", "lesson": "vol accel failed"}],
    )
    adv = reason_decide_rationale(
        packet=pkt,
        llm=_TruncatedDecideLLM(),
        allowed_evidence_ids=["obs-1"],
    )
    assert adv["review_status"] == REVIEWED
    assert "E001" in (adv.get("rationale_text") or "") or "Lesson" in (
        adv.get("rationale_text") or ""
    )
    assert adv.get("llm") is True


def test_parse_json_blob_salvages_rationale_text():
    from atlas.reasoning.cognitive_core import _parse_json_blob

    blob = (
        "preamble\n"
        '{"rationale_text":"Keep HOLD; PLC.A incomplete.",'
        '"falsifiers":["valuation arrives"]'
        " garbage"
    )
    parsed = _parse_json_blob(blob)
    assert parsed is not None
    assert "PLC.A" in str(parsed.get("rationale_text") or "")


class _EchoDecideLLM:
    def for_role(self, role):
        return self

    def lane_busy(self):
        return False

    def chat(self, messages, **kwargs):
        class R:
            text = (
                '{"task":"bre3_decide_rationale","advice_only":true,'
                '"symbol":"COALINDIA.NS","action":"buy",'
                '"return_schema":{"rationale_text":"1-3 sentences"}}'
            )

        return R()


def test_reason_decide_rationale_rejects_prompt_echo():
    from atlas.reasoning.cognitive_core import UNREVIEWED, reason_decide_rationale

    pkt = build_evidence_packet(
        question="Buy COALINDIA?",
        symbol="COALINDIA.NS",
        action="buy",
        evidence=["obs-1"],
        extra={"no_match": True},
    )
    adv = reason_decide_rationale(
        packet=pkt,
        llm=_EchoDecideLLM(),
        allowed_evidence_ids=["obs-1"],
    )
    assert adv["review_status"] == UNREVIEWED
    assert adv["skip_reason"] == "failed_prompt_echo"
    assert adv.get("llm") is True
    assert adv.get("raw_llm_text")


class _SchemaEchoDecideLLM:
    def for_role(self, role):
        return self

    def lane_busy(self):
        return False

    def chat(self, messages, **kwargs):
        class R:
            text = (
                '{"rationale_text":"1-3 sentences","falsifiers":["str"],'
                '"expected_outcome":null,"claims":[{"text":"str","evidence_ids":[]}],'
                '"confidence":0.4}'
            )

        return R()


def test_reason_decide_rationale_rejects_schema_echo():
    from atlas.reasoning.cognitive_core import UNREVIEWED, reason_decide_rationale

    pkt = build_evidence_packet(
        question="Buy HBLPOWER?",
        symbol="HBLPOWER.NS",
        action="buy",
        evidence=["obs-1"],
        extra={"no_match": False, "lesson_refs": ["L-E001-buy_name-vol-accel"]},
    )
    adv = reason_decide_rationale(
        packet=pkt,
        llm=_SchemaEchoDecideLLM(),
        allowed_evidence_ids=["obs-1"],
    )
    assert adv["review_status"] == UNREVIEWED
    assert adv["skip_reason"] == "failed_schema_echo"
    assert adv.get("llm") is True


def test_scientist_lane_busy_is_unreviewed():
    class _Busy:
        def for_role(self, role):
            return self

        def lane_busy(self):
            return True

        def chat(self, *a, **k):
            raise AssertionError("chat must not run when lane_busy")

    adv = reason_as_scientist(
        packet=build_evidence_packet(question="x", evidence=["a"]),
        llm=_Busy(),
    )
    assert adv["review_status"] == UNREVIEWED
    assert adv["skip_reason"] == "lane_busy"
    assert adv["never_orders"] is True


def test_scientist_malformed_json_is_unreviewed():
    class _Bad:
        def for_role(self, role):
            return self

        def lane_busy(self):
            return False

        def chat(self, messages, **kwargs):
            class R:
                text = "not json at all — just prose"
                thinking = ""

            return R()

    adv = reason_as_scientist(
        packet=build_evidence_packet(question="x", evidence=["a"]),
        llm=_Bad(),
    )
    assert adv["review_status"] == UNREVIEWED
    assert adv["skip_reason"] == "failed_non_json"


def test_scientist_empty_packet_is_unreviewed():
    adv = reason_as_scientist(packet={}, llm=_FakeLLM())
    assert adv["review_status"] == UNREVIEWED
    assert adv["skip_reason"] == "empty_packet"
