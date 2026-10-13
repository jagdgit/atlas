"""Cognitive loop R1–R3: exact-test gate, LLM trade reviews, LLM-proposed questions.

The LLM proposes, the evidence decides: these tests pin that a proposal the data
can't support is rejected by code, that an accepted one goes through the same
admission as a detector pattern, and that nothing runs in market hours.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from atlas.investment.cognitive import llm_research as lr
from atlas.investment.cognitive.stats import benjamini_hochberg, fisher_exact
from atlas.llm.provider import LLMResponse

_LAB = "india_fno_learner"
# 2026-10-13 is a Tuesday; 14:00 UTC = 19:30 IST (off-hours), 05:00 UTC = 10:30 IST.
_EVENING = datetime(2026, 10, 13, 14, 0, tzinfo=timezone.utc)
_SESSION = datetime(2026, 10, 13, 5, 0, tzinfo=timezone.utc)


class _FakeLLM:
    def __init__(self, replies: list[dict]) -> None:
        self.replies = list(replies)
        self.calls: list[dict] = []

    def chat(self, messages, **kwargs):  # noqa: ANN001
        self.calls.append(kwargs)
        return LLMResponse(text=json.dumps(self.replies.pop(0)), model="fake")


def _episode(eid: str, *, right: str, matched: bool, day: str = "2026-10-12", hour: str = "05") -> dict:
    return {
        "experience_id": eid,
        "as_of_ist": day,
        "symbol": f"TCS26OCT2200{right}",
        "underlying": "TCS",
        "option_type": right,
        "features": {"option_type": right, "underlying_type": "stock", "sma_margin": 0.02},
        "prediction": {"expected_direction": "up"},
        "prediction_error": {"direction_match": "matched" if matched else "missed"},
        "outcome": {"realized_pnl": 100.0 if matched else -100.0},
        "fill": {"entry_at": f"{day}T{hour}:00:00+00:00", "exit_at": f"{day}T09:00:00+00:00",
                 "entry_premium": 50.0},
    }


def _episodes() -> list[dict]:
    return [_episode(f"ce-{i}", right="CE", matched=i < 3) for i in range(4)] + [
        _episode(f"pe-{i}", right="PE", matched=False) for i in range(4)
    ]


def _store(tmp_path: Path, rows: list[dict], day: str = "2026-10-12") -> None:
    from atlas.investment.fno_closed_loop_dataset import STORE_REL

    path = tmp_path / STORE_REL / _LAB / f"{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _review() -> dict:
    return {
        "what_happened": "premium fell",
        "main_driver": "underlier_move",
        "signal_or_luck": "unclear",
        "lesson_candidate": "puts bought on a rising stock lost",
        "data_missing": ["iv at entry"],
        "testable_idea": {"dimension": "option_type", "high_group": "CE", "low_group": "PE",
                          "mechanism": "trend favoured calls"},
    }


# --- stats -------------------------------------------------------------------


def test_fisher_exact_matches_known_values():
    # Lady-tasting-tea: 3/4 vs 1/4, two-sided p = 0.4857
    assert abs(fisher_exact(3, 4, 1, 4) - 0.4857) < 1e-3
    assert abs(fisher_exact(4, 4, 0, 4) - 0.0286) < 1e-3
    assert abs(fisher_exact(5, 5, 0, 5, alternative="greater") - 1 / 252) < 1e-6
    assert fisher_exact(0, 0, 1, 2) == 1.0


def test_benjamini_hochberg_gets_stricter_with_more_tests():
    assert benjamini_hochberg([0.04], 0.05) == [True]
    assert benjamini_hochberg([0.04] + [0.9] * 9, 0.05) == [False] + [False] * 9
    assert benjamini_hochberg([0.001, 0.02, 0.5], 0.05) == [True, True, False]


# --- R2 validation ---------------------------------------------------------------


def test_validator_rejects_what_the_data_cannot_support():
    from atlas.investment.cognitive.pattern_detector import dimension_table

    table = dimension_table(_episodes())
    ok = {"dimension": "option_type", "high_group": "CE", "low_group": "PE", "mechanism": "m", "falsifier": "f"}
    assert lr.validate_proposal(ok, table=table, asked=[]) == (True, "ok")
    assert lr.validate_proposal({**ok, "high_group": "FUT"}, table=table, asked=[])[1] == "group_not_in_data"
    assert lr.validate_proposal({**ok, "dimension": "underlier_direction"}, table=table, asked=[])[1] == (
        "not_a_decide_time_feature"
    )
    assert lr.validate_proposal(ok, table=table, asked=["option_type"])[1] == "already_asked"
    assert lr.validate_proposal({**ok, "mechanism": " "}, table=table, asked=[])[1] == "no_mechanism"
    assert lr.validate_proposal({**ok, "low_group": "CE"}, table=table, asked=[])[1] == "same_group"


def test_proposal_counts_come_from_the_data_not_the_llm():
    prop = {"dimension": "option_type", "high_group": "CE", "low_group": "PE", "mechanism": "m", "falsifier": "f",
            "claimed_hit_rate": 0.99}
    pattern = lr.proposal_to_pattern(prop, _episodes(), laboratory_id=_LAB, as_of_ist="2026-10-12")
    assert pattern["groups"]["CE"] == {"n": 4, "hits": 3, "hit_rate": 0.75}
    assert pattern["source"] == "llm_proposed"
    assert pattern["thin_groups"] == []
    assert len(pattern["source_experience_ids"]) == 8


# --- R1 reviews + the step ----------------------------------------------------------


def test_no_llm_work_in_market_hours(tmp_path: Path):
    _store(tmp_path, _episodes())
    llm = _FakeLLM([_review()])
    out = lr.run_research_step(tmp_path, laboratory_id=_LAB, llm=llm, now=_SESSION)
    assert out["skipped"] == "market_hours"
    assert llm.calls == []


def test_reviews_newest_trade_first_with_schema_and_persists(tmp_path: Path):
    _store(tmp_path, _episodes())
    llm = _FakeLLM([_review(), _review()])
    out = lr.run_research_step(tmp_path, laboratory_id=_LAB, llm=llm, now=_EVENING, max_calls=2)
    assert [a["action"] for a in out["actions"]] == ["trade_review", "trade_review"]
    assert out["actions"][0]["experience_id"] == "pe-3"
    assert llm.calls[0]["format"]["properties"]["main_driver"]["enum"]
    reviews = lr.load_trade_reviews(tmp_path, _LAB)
    assert [r["experience_id"] for r in reviews] == ["pe-3", "pe-2"]
    assert reviews[0]["influence"] == "advice_only"


def test_review_failures_stop_after_two_attempts(tmp_path: Path):
    _store(tmp_path, [_episode("only", right="CE", matched=True)])

    class Broken:
        calls = 0

        def chat(self, messages, **kwargs):  # noqa: ANN001
            Broken.calls += 1
            return LLMResponse(text="not json", model="fake")

    lr.run_research_step(tmp_path, laboratory_id=_LAB, llm=Broken(), now=_EVENING, max_calls=3)
    assert Broken.calls == 3  # two failed reviews, then one proposal attempt
    assert lr._unreviewed(tmp_path, _LAB, [_episode("only", right="CE", matched=True)]) == []


def test_daily_budget_caps_calls(tmp_path: Path):
    _store(tmp_path, [_episode(f"e{i}", right="CE", matched=True) for i in range(20)])
    llm = _FakeLLM([_review()] * 20)
    for _ in range(5):
        lr.run_research_step(tmp_path, laboratory_id=_LAB, llm=llm, now=_EVENING, max_calls=3)
    assert len(llm.calls) == lr.MAX_CALLS_PER_DAY


def test_proposal_runs_once_reviews_done_and_feeds_review_ideas(tmp_path: Path):
    rows = _episodes()
    _store(tmp_path, rows)
    replies = [_review()] * (lr.MAX_CALLS_PER_DAY - 1) + [{
        "proposals": [
            {"dimension": "option_type", "high_group": "CE", "low_group": "PE", "mechanism": "trend", "falsifier": "f"},
            {"dimension": "iv_bucket", "high_group": "under_15", "low_group": "over_25", "mechanism": "m",
             "falsifier": "f"},
        ]
    }]
    llm = _FakeLLM(replies)
    for _ in range(4):
        lr.run_research_step(tmp_path, laboratory_id=_LAB, llm=llm, now=_EVENING, max_calls=3)
    # Seven reviews, then the reserved last call goes to the proposal.
    assert len(llm.calls) == lr.MAX_CALLS_PER_DAY
    assert llm.calls[-1]["_atlas_purpose"] == "cognitive_hypothesis_proposal"
    assert len(lr.load_trade_reviews(tmp_path, _LAB)) == lr.MAX_CALLS_PER_DAY - 1
    rows_out = lr.accepted_proposals(tmp_path, laboratory_id=_LAB, as_of_ist="2026-10-13")
    assert [r["proposal"]["dimension"] for r in rows_out] == ["option_type"]
    raw = (tmp_path / lr.STORE_REL / _LAB / "proposals" / "2026-10-13.jsonl").read_text().splitlines()
    verdicts = {json.loads(x)["proposal"]["dimension"]: json.loads(x)["reason"] for x in raw}
    assert verdicts["iv_bucket"] == "group_not_in_data"


def test_cycle_admits_an_accepted_llm_proposal_through_normal_admission(tmp_path: Path):
    from atlas.investment.cognitive.loop import run_cycle

    bars = tmp_path / "market" / "bars"
    bars.mkdir(parents=True)
    series = [{"date": f"2026-09-{d:02d}", "open": 100, "high": 102, "low": 98, "close": 101, "volume": 1}
              for d in range(1, 29)]
    (bars / "TCS.NS.json").write_text(json.dumps({"bars": series}), encoding="utf-8")
    # A weak split the detector screen won't ask about on its own.
    rows = [_episode(f"ce-{i}", right="CE", matched=i < 2) for i in range(4)] + [
        _episode(f"pe-{i}", right="PE", matched=i < 1) for i in range(4)
    ]
    _store(tmp_path, rows)
    path = tmp_path / lr.STORE_REL / _LAB / "proposals" / "2026-10-12.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "verdict": "accepted",
        "proposal": {"dimension": "option_type", "high_group": "CE", "low_group": "PE",
                     "mechanism": "calls ride the trend", "falsifier": "puts do as well"},
    }) + "\n", encoding="utf-8")

    cycle = run_cycle(tmp_path, laboratory_id=_LAB, as_of_ist="2026-10-12")
    assert cycle["llm_hypotheses_created"] == 1
    assert len(cycle["hypotheses"]) == 1  # the detector did not ask it
    asked = cycle["hypotheses"][0]
    assert asked["source"] == "llm_proposed" and asked["mechanism"] == "calls ride the trend"
    assert cycle["awaiting"][0]["reason"] == "awaiting_fresh_sample"
    assert cycle["learning_candidates"] == 0
    assert cycle["mutates_strategy"] is False


def test_llm_question_statement_does_not_claim_the_proposed_order():
    from atlas.investment.cognitive.hypothesis_engine import build_hypothesis

    prop = {"dimension": "option_type", "high_group": "PE", "low_group": "CE", "mechanism": "m", "falsifier": "f"}
    pattern = lr.proposal_to_pattern(prop, _episodes(), laboratory_id=_LAB, as_of_ist="2026-10-12")
    hypo = build_hypothesis(pattern, laboratory_id=_LAB)
    assert hypo["statement"].startswith("Proposed question on option_type")
    assert "PE is 0/4" in hypo["statement"] and "CE is 3/4" in hypo["statement"]
    assert "LLM proposed" in hypo["honesty"]


def test_llm_proposal_carries_confounds():
    rows = _episodes()
    for row in rows:
        row["features"]["sma_margin"] = 0.02 if row["option_type"] == "CE" else -0.02
    prop = {"dimension": "sma_margin_sign", "high_group": "positive", "low_group": "negative",
            "mechanism": "m", "falsifier": "f"}
    pattern = lr.proposal_to_pattern(prop, rows, laboratory_id=_LAB, as_of_ist="2026-10-12")
    assert "option_type" in pattern["confounded_with"]


def test_review_packet_uses_market_local_time():
    packet = lr.review_packet(_episode("x", right="CE", matched=True))
    assert packet["fill"]["entry_ist"] == "2026-10-12 10:30 IST"
    assert "entry_at" not in packet["fill"]
