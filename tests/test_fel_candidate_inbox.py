"""STEP 005 — a FEL candidate may enqueue one investigation and must not change the strategy."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from atlas.agent_kernel.kernel import AgentKernel
from atlas.investment.data_quality import Q_PENDING, Q_TRUSTED, Q_UNKNOWN, commit_record, current_capability, envelope
from atlas.investment.fel.promotion import assert_not_live, enqueue_candidate_investigation, promotion_for
from atlas.trading.strategy import StrategyDecisionRule

NOW = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
PERIOD = "2026-03-31"
CANDIDATE = "FEL-E001"


def _trusted_fcf(tmp_path: Path) -> None:
    commit_record(
        tmp_path,
        envelope(
            symbol="HBLPOWER.NS",
            metric="fcf",
            value=100.0,
            period=PERIOD,
            period_end=PERIOD,
            provider="nse_xbrl",
            evidence_id="ev-fcf",
            components={"operating_cash_flow": 150.0, "capex": 50.0},
            now=NOW,
        ),
        now=NOW,
    )


def _ordering_advice(packet: dict) -> dict:
    return {
        "review_status": "REVIEWED",
        "conclusion": "Cited the candidate pointer only.",
        "uncertainty": "one fact",
        "falsifiers": ["filing restated"],
        "action": "BUY",
        "orders": [{"side": "BUY", "quantity": 1}],
    }


def test_candidate_inbox_cites_the_candidate_and_leaves_strategy(tmp_path: Path):
    _trusted_fcf(tmp_path)
    assert current_capability(tmp_path, "HBLPOWER.NS", "fcf")["quality_status"] == Q_TRUSTED
    written = enqueue_candidate_investigation(
        tmp_path,
        promotion="candidate",
        candidate_id=CANDIDATE,
        symbol="HBLPOWER.NS",
        metric="fcf",
    )
    assert written["written"] is True
    raw = Path(written["path"]).read_text(encoding="utf-8")
    doc = json.loads(raw)
    assert CANDIDATE in doc["objective"]
    assert "100" not in raw
    assert "value" not in doc["fact"]
    again = enqueue_candidate_investigation(
        tmp_path,
        promotion="candidate",
        candidate_id=CANDIDATE,
        symbol="HBLPOWER.NS",
        metric="fcf",
    )
    assert again["written"] is False

    kernel = AgentKernel(tmp_path, cognitive_fn=_ordering_advice)
    report = kernel.cycle(mode="tick", allow_external=False, max_investigations=1)
    assert report["created"]
    task = kernel.task(report["created"][0])
    assert task is not None
    assert CANDIDATE in task["objective"]
    assert CANDIDATE in str(kernel.state.get("current_goal") or "")
    assert task["constraints"]["strategy_mutation"] is False
    if task.get("cognitive"):
        assert task["cognitive"]["never_orders"] is True
        assert task["cognitive"]["action"] is None
        assert task["cognitive"]["orders"] is None

    strategy_src = Path("atlas/trading/strategy.py").read_text(encoding="utf-8")
    assert 'VERSION = "1.0.0"' in strategy_src
    assert StrategyDecisionRule.VERSION == "1.0.0"
    with pytest.raises(ValueError, match="live_control"):
        assert_not_live("live_control")
    assert promotion_for(result="improve", operator_level10=True) == "candidate"


def test_unknown_fact_is_a_pointer_and_other_states_are_refused(tmp_path: Path):
    commit_record(
        tmp_path,
        envelope(
            symbol="HBLPOWER.NS",
            metric="fcf",
            value=None,
            provider="nse_xbrl",
            evidence_id="ev-missing",
            now=NOW,
        ),
        now=NOW,
    )
    row = current_capability(tmp_path, "HBLPOWER.NS", "fcf")
    assert row["quality_status"] == Q_UNKNOWN
    assert row["reason"]
    written = enqueue_candidate_investigation(
        tmp_path,
        promotion="candidate",
        candidate_id="FEL-UNK",
        symbol="HBLPOWER.NS",
        metric="fcf",
    )
    assert written["written"] is True
    doc = json.loads(Path(written["path"]).read_text(encoding="utf-8"))
    assert doc["fact"]["quality"] == "UNKNOWN"
    assert "FEL-UNK" in doc["objective"]

    refused = enqueue_candidate_investigation(
        tmp_path,
        promotion="never",
        candidate_id="FEL-NO",
        symbol="HBLPOWER.NS",
        metric="fcf",
    )
    assert refused["written"] is False
    assert not (tmp_path / "agent_kernel" / "inbox" / "fel-FEL-NO.json").exists()

    commit_record(
        tmp_path,
        envelope(
            symbol="TATA.NS",
            metric="fcf",
            value=10.0,
            provider="universe_seed",
            now=NOW,
        ),
        now=NOW,
    )
    pending = current_capability(tmp_path, "TATA.NS", "fcf")
    assert pending["quality_status"] == Q_PENDING
    blocked = enqueue_candidate_investigation(
        tmp_path,
        promotion="candidate",
        candidate_id="FEL-PEND",
        symbol="TATA.NS",
        metric="fcf",
    )
    assert blocked["reason"] == "fact_not_trusted_or_unknown"
    with pytest.raises(ValueError, match="live_control"):
        enqueue_candidate_investigation(
            tmp_path,
            promotion="live_control",
            candidate_id="FEL-LIVE",
            symbol="HBLPOWER.NS",
            metric="fcf",
        )
