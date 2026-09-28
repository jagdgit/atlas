"""OI-LEARN-AUDIT0 LA.0–LA.2 — Learning Auditor instrument."""

from __future__ import annotations

import json
from pathlib import Path

from atlas.investment.learning_audit import (
    NOT_LEARNING,
    build_and_persist_learning_audit,
    build_and_persist_weekly_learning_report,
    build_learning_audit,
    empty_audit,
    format_learning_audit_evening_lines,
    format_weekly_learning_report_lines,
    load_learning_audit,
    load_weekly_learning_report,
)


def test_empty_audit_is_honest_instrument():
    doc = empty_audit(laboratory_id="india_equity_learner", reason="test")
    assert doc["instrument_not_destination"] is True
    assert doc["never_orders"] is True
    assert doc["no_capital_increase"] is True
    assert doc["learning_record_n"] == 0
    assert "llm_call_count" in NOT_LEARNING
    assert "stored_neq" in doc["hard_principle"]


def test_throughput_not_counted_as_learning(tmp_path: Path):
    lab = "india_equity_learner"
    # Only KPI / fitness style noise — no EXPERIENCE chain
    day = "2026-08-23"
    kpi_dir = tmp_path / "market" / "trading_kpis" / lab
    kpi_dir.mkdir(parents=True)
    (kpi_dir / f"{day}.json").write_text(
        json.dumps(
            {
                "kpis": {
                    "fills_today": 99,
                    "buys_today": 50,
                    "top_no_fill_reasons": [
                        {"reason": "session_closed", "count": 100},
                    ],
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    fit = tmp_path / "investment" / "llm_fitness"
    fit.mkdir(parents=True)
    (fit / f"{day}.jsonl").write_text(
        json.dumps(
            {
                "kind": "LLM_FITNESS",
                "outcome": "ok",
                "purpose": "chat",
                "as_of_ist": day,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    doc = build_learning_audit(tmp_path, laboratory_id=lab, as_of_ist=day)
    assert doc["skipped"] is False
    assert doc["instrument_not_destination"] is True
    assert doc["learning_record_n"] == 0
    assert doc["genuine_learning_milestone"]["met"] is False
    assert doc["throughput_not_learning"]["kpi_fills_today"] == 99
    # fills are exposed as throughput warning, not as learning_records
    assert all(r.get("source") != "fills" for r in doc["learning_records"])


def test_provisional_from_opp_cost_and_persist(tmp_path: Path):
    lab = "india_equity_learner"
    day = "2026-08-23"
    learn = tmp_path / "investment" / "learning" / lab
    learn.mkdir(parents=True)
    (learn / f"{day}.jsonl").write_text(
        json.dumps(
            {
                "kind": "LEARNING_EVENT",
                "event_kind": "opportunity_cost_resolved",
                "symbol": "CIPLA.NS",
                "id": "oc-1",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    doc = build_and_persist_learning_audit(
        tmp_path, laboratory_id=lab, as_of_ist=day
    )
    assert doc["learning_record_n"] >= 1
    assert doc["genuine_learning_milestone"]["met"] is False
    assert doc["genuine_learning_milestone"]["have"] == 0  # not chain_complete
    loaded = load_learning_audit(tmp_path, laboratory_id=lab, as_of_ist=day)
    assert loaded is not None
    assert loaded.get("laboratory_id") == lab
    assert loaded.get("learning_record_n") >= 1
    assert (tmp_path / "investment" / "learning_audit" / lab / f"{day}.json").is_file()
    lines = format_learning_audit_evening_lines(doc)
    assert any("Learning Audit" in ln for ln in lines)
    assert any("instrument_not_destination" in ln for ln in lines)


def test_experience_with_computed_error_is_provisional(tmp_path: Path):
    lab = "india_equity_learner"
    day = "2026-08-23"
    learn = tmp_path / "investment" / "learning" / lab
    learn.mkdir(parents=True)
    (learn / f"{day}.jsonl").write_text(
        json.dumps(
            {
                "kind": "EXPERIENCE",
                "experience_id": "exp-abc",
                "symbol": "PRAJIND.NS",
                "prediction_error": {"status": "computed", "direction_match": "missed"},
                "attribution": {"required": True, "satisfied": True},
                "lesson": "Do not ADD without relative advantage",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    doc = build_learning_audit(tmp_path, laboratory_id=lab, as_of_ist=day)
    assert doc["learning_record_n"] == 1
    assert doc["learning_records"][0]["status"] == "PROVISIONAL"
    assert doc["learning_records"][0]["chain_complete"] is True
    assert doc["learning_records"][0]["level"] == "L3"
    mile = doc["genuine_learning_milestone"]
    assert mile["chain_complete_n"] == 1
    assert mile["have"] == 0  # L5 requires subsequent validation
    assert mile["met"] is False
    assert mile["unit"] == "independent_investment_L5"


def test_weekly_learning_report_honest_empty(tmp_path: Path):
    lab = "india_equity_learner"
    day = "2026-08-23"
    # KPI-only day — weekly must not invent learnings from fills
    kpi_dir = tmp_path / "market" / "trading_kpis" / lab
    kpi_dir.mkdir(parents=True)
    (kpi_dir / f"{day}.json").write_text(
        json.dumps({"kpis": {"fills_today": 12, "buys_today": 4}}) + "\n",
        encoding="utf-8",
    )
    daily = build_and_persist_learning_audit(
        tmp_path, laboratory_id=lab, as_of_ist=day
    )
    assert daily["learning_record_n"] == 0
    wk = build_and_persist_weekly_learning_report(
        tmp_path, laboratory_id=lab, as_of_ist=day, ensure_dailies=False
    )
    assert wk["kind"] == "WEEKLY_LEARNING_REPORT"
    assert wk["instrument_not_destination"] is True
    assert wk["not_eod_fills_report"] is True
    assert wk["learning_record_n"] == 0
    assert wk["what_we_learned"] == []
    assert wk["throughput_not_learning"]["kpi_fills_sum"] == 12
    assert (tmp_path / "investment" / "learning_audit" / lab / "weekly").is_dir()
    loaded = load_weekly_learning_report(tmp_path, laboratory_id=lab, as_of_ist=day)
    assert loaded is not None
    assert loaded.get("week") == wk.get("week")
    lines = format_weekly_learning_report_lines(wk)
    assert any("Weekly Learning Report" in ln for ln in lines)
    assert any("none yet" in ln for ln in lines)
    assert any("NOT learning" in ln or "not learning" in ln.lower() for ln in lines)


def test_weekly_rolls_provisional_learnings(tmp_path: Path):
    lab = "india_equity_learner"
    day = "2026-08-23"
    learn = tmp_path / "investment" / "learning" / lab
    learn.mkdir(parents=True)
    (learn / f"{day}.jsonl").write_text(
        json.dumps(
            {
                "kind": "EXPERIENCE",
                "experience_id": "exp-week",
                "symbol": "CIPLA.NS",
                "prediction_error": {"status": "computed"},
                "attribution": {"satisfied": True},
                "lesson": "Relative ranking before ADD",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    build_and_persist_learning_audit(tmp_path, laboratory_id=lab, as_of_ist=day)
    wk = build_and_persist_weekly_learning_report(
        tmp_path, laboratory_id=lab, as_of_ist=day, ensure_dailies=False
    )
    assert wk["learning_record_n"] >= 1
    assert wk["genuine_learning_milestone"]["have"] >= 1
    assert wk["genuine_learning_milestone"]["met"] is False
    assert any(
        "Relative ranking" in str(r.get("update") or "") for r in wk["what_we_learned"]
    )


def test_la3_contribution_throughput_without_advice(tmp_path: Path):
    lab = "india_equity_learner"
    day = "2026-08-23"
    fit = tmp_path / "investment" / "llm_fitness"
    fit.mkdir(parents=True)
    rows = [
        {
            "kind": "LLM_FITNESS",
            "outcome": "error",
            "purpose": "icr5_scientist_notes",
            "as_of_ist": day,
            "error": "OllamaError: timed out",
        },
        {
            "kind": "LLM_FITNESS",
            "outcome": "ok",
            "purpose": "assistant_compose",
            "as_of_ist": day,
        },
    ]
    (fit / f"{day}.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    doc = build_learning_audit(tmp_path, laboratory_id=lab, as_of_ist=day)
    llm = doc["llm_contribution"]
    assert llm["version"].startswith("learn_audit.la3")
    assert llm["relevant_calls"] == 1
    assert llm["relevant_error"] == 1
    assert llm["noise_calls"] == 1
    assert llm["useful_hypotheses"] == 0
    assert llm["validated_hypotheses"] == 0
    assert llm["contribution_rate"] is None
    assert llm["status"] == "joined_throughput_no_advice"
    assert "Call counts are not contribution" in llm["honesty"]
    lines = format_learning_audit_evening_lines(doc)
    assert any("LA.3 join" in ln for ln in lines)


def test_la3_contribution_partial_when_reviewed_joins_learning(tmp_path: Path):
    lab = "india_equity_learner"
    day = "2026-08-23"
    # REVIEWED scientist note
    by = tmp_path / "investment" / "scientist_notes" / lab / "by_id"
    by.mkdir(parents=True)
    (by / "note-1.json").write_text(
        json.dumps(
            {
                "symbol": "CIPLA.NS",
                "llm_status": "done",
                "notes": {
                    "review_status": "REVIEWED",
                    "symbol": "CIPLA.NS",
                    "recommendation": "Hold pending relative E[R]",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    fit = tmp_path / "investment" / "llm_fitness"
    fit.mkdir(parents=True)
    (fit / f"{day}.jsonl").write_text(
        json.dumps(
            {
                "outcome": "ok",
                "purpose": "icr5_scientist_notes",
                "as_of_ist": day,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    learn = tmp_path / "investment" / "learning" / lab
    learn.mkdir(parents=True)
    (learn / f"{day}.jsonl").write_text(
        json.dumps(
            {
                "kind": "EXPERIENCE",
                "experience_id": "exp-la3",
                "symbol": "CIPLA.NS",
                "prediction_error": {
                    "status": "computed",
                    "direction_match": "hit",
                },
                "attribution": {"satisfied": True},
                "lesson": "LLM falsifier matched later move",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    doc = build_learning_audit(tmp_path, laboratory_id=lab, as_of_ist=day)
    llm = doc["llm_contribution"]
    assert llm["useful_hypotheses"] >= 1
    assert llm["validated_hypotheses"] >= 1
    assert llm["status"] == "partial_economic"
    assert llm["contribution_rate"] is not None
    assert llm["llm_induced_correct_changes"] >= 1


def test_la4_insufficient_sample_refuses_improving(tmp_path: Path):
    lab = "india_equity_learner"
    day = "2026-08-23"
    learn = tmp_path / "investment" / "learning" / lab
    learn.mkdir(parents=True)
    # Only 2 directional experiences — below SAMPLE_GATE_N=5
    rows = []
    for i, dm in enumerate(["matched", "missed"]):
        rows.append(
            json.dumps(
                {
                    "kind": "EXPERIENCE",
                    "experience_id": f"e{i}",
                    "symbol": "CIPLA.NS",
                    "prediction_error": {
                        "status": "direction_only",
                        "direction_match": dm,
                    },
                }
            )
        )
    (learn / f"{day}.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
    doc = build_learning_audit(tmp_path, laboratory_id=lab, as_of_ist=day)
    imp = doc["improvement"]
    assert imp["version"].startswith("learn_audit.la4")
    assert imp["status"] == "INSUFFICIENT_SAMPLE"
    assert imp["current"]["direction_n"] == 2
    assert imp["sample_gate"] == 5
    dqi = doc["data_quality"]["decision_time_integrity"]
    assert dqi["status"] in {"UNKNOWN_NO_SAMPLE", "CLEAN_SAMPLED"}
    lines = format_learning_audit_evening_lines(doc)
    assert any("LA.4 rolling" in ln for ln in lines)
    assert any("LOOKAHEAD" in ln for ln in lines)


def test_la4_lookahead_flags_future_evidence(tmp_path: Path):
    lab = "india_equity_learner"
    day = "2026-08-20"
    pkt_dir = tmp_path / "investment" / "decisions" / "by_day" / lab
    pkt_dir.mkdir(parents=True)
    (pkt_dir / f"{day}.jsonl").write_text(
        json.dumps(
            {
                "decision_id": "d1",
                "ts_ist": day,
                "symbol": "CIPLA.NS",
                "action": "buy",
                "fundamentals_as_of": "2026-08-22",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    doc = build_learning_audit(tmp_path, laboratory_id=lab, as_of_ist=day)
    dqi = doc["data_quality"]["decision_time_integrity"]
    assert dqi["status"] == "LOOKAHEAD_FLAGS"
    assert dqi["lookahead_flags"] >= 1
    assert dqi["flags"][0]["evidence_as_of"] == "2026-08-22"


def test_lessons_dict_track_completes_chain(tmp_path: Path):
    """Experiences store lessons.* tracks — auditor must read them (OI-MDPH Phase 3)."""
    lab = "equity_intraday_learner"
    day = "2026-09-02"
    learn = tmp_path / "investment" / "learning" / lab
    learn.mkdir(parents=True)
    (learn / f"{day}.jsonl").write_text(
        json.dumps(
            {
                "kind": "EXPERIENCE",
                "experience_id": "f6f46cd8-f2e4",
                "symbol": "CYIENT.NS",
                "prediction_error": {
                    "status": "computed",
                    "error_pct": -4.38,
                    "predicted_er": 0.01,
                    "realized_return_pct": -3.29,
                },
                "attribution": {"required": True, "satisfied": True, "status": "unknown_explicit"},
                "lessons": {
                    "strategy": None,
                    "relative_opportunity": "Next-rupee vs WELCORP.NS: action=KEEP",
                },
                "belief_update": "unchanged",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    doc = build_learning_audit(tmp_path, laboratory_id=lab, as_of_ist=day)
    rec = doc["learning_records"][0]
    assert rec["chain_complete"] is True
    assert "relative_opportunity" in (rec.get("update") or "")
    assert rec["level"] == "L3"
    assert doc["genuine_learning_milestone"]["chain_complete_n"] == 1
    assert doc["genuine_learning_milestone"]["have"] == 0  # not L5 yet


def test_l5_requires_subsequent_validation(tmp_path: Path):
    from atlas.investment.learning_audit import classify_learning_level

    base = {
        "prediction": {"status": "computed"},
        "outcome": {"realized_pnl": 1},
        "attribution": {"satisfied": True},
        "update": "lesson text",
        "belief_update": "candidate",
    }
    assert classify_learning_level(base) == "L4"
    assert classify_learning_level({**base, "subsequent_test": {"ok": True}}) == "L5"
