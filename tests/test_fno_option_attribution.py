"""F&O option attribution from durable underlier/premium evidence."""

from __future__ import annotations

import json
from pathlib import Path

from atlas.investment.fno_option_attribution import (
    STATUS_EVIDENCE_BACKED,
    STATUS_PARTIAL,
    STATUS_UNKNOWN,
    build_fno_rt_evidence,
    evaluate_fno_causal_factors,
)
from atlas.investment.learning_story import ensure_close_attribution


def _bars(tmp: Path, symbol: str, day: str, *, o: float, c: float) -> None:
    p = tmp / "market" / "bars" / f"{symbol}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "symbol": symbol,
                "bars": [
                    {
                        "date": day,
                        "open": o,
                        "close": c,
                        "high": max(o, c),
                        "low": min(o, c),
                        "volume": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_ce_winner_underlying_up_is_evidence_backed(tmp_path: Path):
    day = "2026-09-29"
    _bars(tmp_path, "ADANIPORTS.NS", day, o=1700.0, c=1769.0)
    ev = build_fno_rt_evidence(
        underlying="ADANIPORTS",
        option_symbol="ADANIPORTS26SEP1740CE",
        option_right="CE",
        entry_premium=5.9,
        exit_premium=50.35,
        realized_pnl=21113.75,
        data_dir=tmp_path,
        as_of_ist=day,
        mark_source="option_ltp",
    )
    causal = evaluate_fno_causal_factors(ev)
    assert causal["status"] == STATUS_EVIDENCE_BACKED
    assert "underlying_move" in causal["helped"]
    assert "iv_change" in causal["unknown"]
    assert "option_greeks" in causal["unknown"]


def test_ce_loser_underlying_down_hurts(tmp_path: Path):
    day = "2026-09-29"
    _bars(tmp_path, "ITC.NS", day, o=410.0, c=400.0)
    ev = build_fno_rt_evidence(
        underlying="ITC",
        option_symbol="ITC26SEP265CE",
        option_right="CE",
        entry_premium=0.5,
        exit_premium=0.05,
        realized_pnl=-776.25,
        data_dir=tmp_path,
        as_of_ist=day,
        mark_source="option_ltp",
    )
    causal = evaluate_fno_causal_factors(ev)
    assert causal["status"] == STATUS_EVIDENCE_BACKED
    assert "underlying_move" in causal["hurt"]


def test_missing_bars_stays_unknown_or_partial(tmp_path: Path):
    ev = build_fno_rt_evidence(
        underlying="NOSUCH",
        option_symbol="NOSUCH26SEP100CE",
        option_right="CE",
        entry_premium=1.0,
        exit_premium=2.0,
        realized_pnl=100.0,
        data_dir=tmp_path,
        as_of_ist="2026-09-29",
    )
    causal = evaluate_fno_causal_factors(ev)
    assert causal["status"] in {STATUS_PARTIAL, STATUS_UNKNOWN}
    assert "underlying_move" in causal["unknown"]
    # premium path alone can label helped — still not evidence_backed without underlier
    assert causal["status"] != STATUS_EVIDENCE_BACKED


def test_ensure_close_attribution_fno_path(tmp_path: Path):
    day = "2026-09-29"
    _bars(tmp_path, "TATASTEEL.NS", day, o=160.0, c=168.0)
    attr = ensure_close_attribution(
        packet={
            "strategy_tag": "fno_lab_v1_experiment_close",
            "as_of_ist": day,
            "fno_lab_v1": {
                "underlying": "TATASTEEL",
                "option_contract": "TATASTEEL26SEP185CE",
                "option_type": "CE",
                "entry_ltp": 0.45,
                "exit_ltp": 3.56,
                "realized_pnl": 8552.5,
                "mark_source": "option_ltp",
            },
            "expected": {"prediction_status": "stated", "expected_return": 0.05},
        },
        trade={"realized_pnl": 8552.5, "price": 3.56, "symbol": "TATASTEEL26SEP185CE"},
        laboratory_id="india_fno_learner",
        data_dir=tmp_path,
    )
    assert attr["status"] == STATUS_EVIDENCE_BACKED
    causal = attr["payload"]["causal_factors"]
    assert "underlying_move" in causal["helped"]
    assert attr["payload"]["fno_rt_evidence"]["version"].startswith("fno.option")


def test_core_evidence_lines_forbid_invention(tmp_path: Path):
    from atlas.investment.fno_option_attribution import evidence_lines_for_core

    ev = build_fno_rt_evidence(
        underlying="HDFCBANK",
        option_right="CE",
        entry_premium=4.0,
        exit_premium=2.0,
        data_dir=tmp_path,
        as_of_ist="2026-09-29",
    )
    lines = evidence_lines_for_core(ev)
    assert any("ATTRIBUTION_RULE" in x for x in lines)
    assert any("iv_change=unknown" in x for x in lines)
