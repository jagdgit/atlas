"""Canonical F&O closed-loop dataset — join today's RTs into one replayable artifact."""

from __future__ import annotations

import json
from pathlib import Path

from atlas.investment.fno_closed_loop_dataset import (
    VERSION,
    assemble_closed_loop_rows,
    build_and_persist_day,
    load_closed_loop_day,
)


def _seed_day(tmp: Path, day: str = "2026-10-05") -> None:
    lab = "india_fno_learner"
    learn = tmp / "investment" / "learning" / lab
    learn.mkdir(parents=True, exist_ok=True)
    pred_root = tmp / "investment" / "fno" / "lab_v1_predictions"
    pred_root.mkdir(parents=True, exist_ok=True)

    contracts = [
        ("ADANIPORTS26OCT1760CE", "ADANIPORTS", "CE", 41.65, 47.35, 2707.5, "matched", "up"),
        ("TCS26OCT2100PE", "TCS", "PE", 20.0, 15.0, -1317.0, "missed", "down"),
    ]
    lines: list[str] = []
    for i, (sym, und, right, entry, exit_px, pnl, match, obs_dir) in enumerate(contracts):
        eid = f"exp-{i}"
        pred_path = pred_root / f"{sym.replace('.', '_')}.json"
        pred_path.write_text(
            json.dumps(
                {
                    "version": "fno.lab.v1.1",
                    "prediction_status": "stated",
                    "contract": sym,
                    "underlying": und,
                    "option_type": right,
                    "expected_return": 0.08,
                    "expected_direction": "up",
                    "predicted_probability": 0.7,
                    "prediction_horizon": "session_flat",
                    "er_model": "fno_lab_v1_control_signal.v1",
                    "entry_premium": entry,
                    "entry_time": f"{day}T05:00:00+00:00",
                    "decision_id": f"dec-{i}",
                    "experiment_id": f"FNO-ATM-{und[:3]}-001",
                }
            ),
            encoding="utf-8",
        )
        realized_pct = 100.0 * (exit_px - entry) / entry
        exp = {
            "kind": "EXPERIENCE",
            "laboratory_id": lab,
            "as_of_ist": day,
            "symbol": sym,
            "experience_id": eid,
            "action": "sell",
            "entry": {"price": entry, "at": None, "trade_id": f"buy-{i}"},
            "exit": {"price": exit_px, "at": f"{day}T10:00:00+00:00", "trade_id": f"sell-{i}"},
            "pnl": pnl,
            "predicted": {
                "expected_return": 0.08,
                "expected_direction": "up",
                "confidence": 0.7,
                "prediction_status": "stated",
                "prediction_horizon": "session_flat",
                "er_model": "fno_lab_v1_control_signal.v1",
                "decision_id": f"dec-{i}",
            },
            "prediction_error": {
                "predicted_er": 0.08,
                "realized_return_pct": realized_pct,
                "error_pct": realized_pct - 8.0,
                "predicted_direction": "up",
                "observed_direction": obs_dir,
                "direction_match": match,
                "status": "computed",
            },
            "attribution": {
                "status": "evidence_backed",
                "required": False,
                "satisfied": False,
                "causal_factors": {
                    "status": "evidence_backed",
                    "helped": ["underlying_move", "option_premium_path"]
                    if match == "matched"
                    else ["option_premium_path"],
                    "hurt": [] if match == "matched" else ["underlying_move"],
                    "unknown": ["iv_change"],
                    "missing_evidence": ["iv_change"],
                    "narrative": "test",
                    "fno_rt_evidence": {
                        "observables": {
                            "underlying": und,
                            "option_right": right,
                            "underlying_session": {
                                "date": day,
                                "open": 100.0,
                                "close": 101.0 if match == "matched" else 99.0,
                                "return_pct": 1.0 if match == "matched" else -1.0,
                                "source": "market/bars durable daily",
                            },
                        }
                    },
                },
            },
            "belief_update": "unchanged",
            "lessons": [],
        }
        story = {
            "kind": "LEARNING_STORY",
            "laboratory_id": lab,
            "as_of_ist": day,
            "symbol": sym,
            "experience_id": eid,
            "story_id": f"story-{i}",
            "belief_update": "unchanged",
            "error": exp["prediction_error"],
        }
        lines.append(json.dumps(exp))
        lines.append(json.dumps(story))
    (learn / f"{day}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_assemble_closed_loop_pipeline_complete(tmp_path: Path):
    day = "2026-10-05"
    _seed_day(tmp_path, day)
    doc = assemble_closed_loop_rows(tmp_path, as_of_ist=day)
    assert doc["ok"] is True
    assert doc["n_rows"] == 2
    assert doc["n_complete"] == 2
    assert doc["pipeline_complete"] is True
    row = doc["rows"][0]
    assert row["prediction"]["prediction_status"] == "stated"
    assert row["prediction_error"]["status"] == "computed"
    assert row["underlier_movement"]["session"]["date"] == day
    assert row["option_movement"]["entry_premium"] is not None
    assert row["attribution"]["status"] == "evidence_backed"
    assert row["chain_complete"] is True


def test_persist_resolves_predictions(tmp_path: Path):
    day = "2026-10-05"
    _seed_day(tmp_path, day)
    out = build_and_persist_day(tmp_path, as_of_ist=day, resolve_predictions=True)
    assert out["persist"]["ok"] is True
    assert out["persist"]["pipeline_complete"] is True
    assert out["persist"]["predictions_resolved"] == 2
    loaded = load_closed_loop_day(tmp_path, as_of_ist=day)
    assert loaded is not None
    assert loaded["n_rows"] == 2
    pred = json.loads(
        (
            tmp_path
            / "investment"
            / "fno"
            / "lab_v1_predictions"
            / "ADANIPORTS26OCT1760CE.json"
        ).read_text(encoding="utf-8")
    )
    assert pred["prediction_status"] == "consumed"
    assert pred["closed_loop_experience_id"] == "exp-0"
    assert VERSION in (out.get("version") or "")
