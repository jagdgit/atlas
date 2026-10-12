"""Switch proof fail-closed when bars thin; justify only from durable session returns."""

from __future__ import annotations

import json
from pathlib import Path

from atlas.investment.switch_proof import (
    STATUS_JUSTIFIED,
    STATUS_NOT_EVALUABLE,
    STATUS_NOT_JUSTIFIED,
    build_switch_proof,
)


def _bars(tmp: Path, symbol: str, day: str, o: float, c: float) -> None:
    p = tmp / "market" / "bars" / f"{symbol}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "bars": [
                    {
                        "date": day,
                        "open": o,
                        "high": max(o, c),
                        "low": min(o, c),
                        "close": c,
                        "volume": 1,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_not_evaluable_without_challenger_bars(tmp_path: Path):
    day = "2026-10-05"
    _bars(tmp_path, "INC.NS", day, 100.0, 101.0)
    proof = build_switch_proof(
        tmp_path,
        laboratory_id="india_equity_learner",
        incumbent="INC",
        challenger="MISSING",
        as_of_ist=day,
    )
    assert proof["status"] == STATUS_NOT_EVALUABLE
    assert proof["reason"] == "bars_not_replayable"


def test_justified_when_challenger_better(tmp_path: Path):
    day = "2026-10-05"
    _bars(tmp_path, "INC.NS", day, 100.0, 100.0)
    _bars(tmp_path, "CHAL.NS", day, 100.0, 105.0)
    proof = build_switch_proof(
        tmp_path,
        laboratory_id="india_equity_learner",
        incumbent="INC",
        challenger="CHAL",
        as_of_ist=day,
        switch_cost_pct=0.5,
    )
    assert proof["status"] == STATUS_JUSTIFIED
    assert proof["edge_after_cost_pct"] > 0


def test_not_justified_when_flat_after_cost(tmp_path: Path):
    day = "2026-10-05"
    _bars(tmp_path, "INC.NS", day, 100.0, 102.0)
    _bars(tmp_path, "CHAL.NS", day, 100.0, 102.1)
    proof = build_switch_proof(
        tmp_path,
        laboratory_id="india_equity_learner",
        incumbent="INC",
        challenger="CHAL",
        as_of_ist=day,
        switch_cost_pct=1.0,
    )
    assert proof["status"] == STATUS_NOT_JUSTIFIED
