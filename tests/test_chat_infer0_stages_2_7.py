"""OI-CHAT-INFER0 Stages 2–7 first-slice — CPU policy, ROI, scientist packet."""

from __future__ import annotations

from atlas.investment.scientist_packet import VERSION as PACKET_VERSION
from atlas.investment.scientist_packet import build_scientist_packet
from atlas.llm.cognitive_roi import score_day
from atlas.llm.cpu_policy import (
    hardware_limit_advice,
    truncate_text,
)
from atlas.investment.cognitive_experiment import format_cognitive_loop_evening_lines


def test_scientist_packet_bounds_evidence():
    pkt = build_scientist_packet(
        laboratory_id="india_equity_learner",
        decision_id="d1",
        packet_summary={"symbol": "CIPLA.NS", "action": "hold"},
        evidence_ids=[f"e{i}" for i in range(50)],
        unknowns=["fcf_missing"],
    )
    assert pkt["version"] == PACKET_VERSION
    assert len(pkt["evidence_ids"]) == 40
    assert "fcf_missing" in pkt["unknowns"]
    assert "never invent" in pkt["temporal_note"].lower() or "unknown" in pkt["temporal_note"].lower()


def test_cognitive_roi_scientist_vs_timeout():
    rows = [
        {
            "purpose": "bre3_decide_rationale",
            "outcome": "ok",
            "generate_ms": 10000,
            "call_kind": "chat",
        },
        {
            "purpose": "assistant_compose",
            "outcome": "timeout",
            "generate_ms": 90000,
            "call_kind": "chat",
        },
        {
            "purpose": "memory_recall_embed",
            "outcome": "ok",
            "generate_ms": 50,
            "call_kind": "embed",
        },
    ]
    score = score_day(rows)
    assert score["scientist_ok_n"] == 1
    assert score["compose_timeout_n"] == 1
    assert score["roi_ratio_scientist_vs_compose_timeout"] == round(10000 / 100000, 3)
    assert score["embed_n"] == 1


def test_hardware_advice_cpu_no_auto_apply():
    advice = hardware_limit_advice(
        {
            "inferences": 10,
            "outcomes": {"ok": 5, "timeout": 3},
            "by_lane": {"chat": {"generate_p95_ms": 110000, "queue_wait_p95_ms": 0}},
        },
        interactive_timeout=120.0,
        accelerator="cpu",
        max_concurrency=1,
    )
    assert advice["accelerator"] == "cpu"
    assert advice["auto_applied"] is False
    assert advice["recommend_gpu"] is True
    assert advice["recommend_concurrency_bump"] is False


def test_truncate_for_cpu():
    text = "x" * 5000
    out = truncate_text(text, max_chars=100)
    assert len(out) < 150
    assert "truncated" in out.lower()


def test_cognitive_loop_evening_no_crash(tmp_path):
    lines = format_cognitive_loop_evening_lines(tmp_path, as_of_ist="2026-08-20")
    text = "\n".join(lines)
    assert "Cognitive loop" in text
    assert "hypothesis" in text.lower()
