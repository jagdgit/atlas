"""Opportunity-switch proof records — justify switches; never invent edge.

P3: capability to *prove* when switching is justified.
Success is not a higher switch rate. Thin history → ``NOT_EVALUABLE``.
Requires P2 durable daily bars health for incumbent and challenger.
Does not mutate allocation authority or SMA/RSI.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "switch.proof.v1"
STORE_REL = Path("investment") / "switch_proof"
STATUS_JUSTIFIED = "JUSTIFIED"
STATUS_NOT_JUSTIFIED = "NOT_JUSTIFIED"
STATUS_NOT_EVALUABLE = "NOT_EVALUABLE"

_log = logging.getLogger("atlas.investment.switch_proof")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session_return_pct(path: Path, as_of_ist: str) -> float | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    bars = doc.get("bars") if isinstance(doc, dict) else None
    if not isinstance(bars, list):
        return None
    for b in bars:
        if not isinstance(b, dict):
            continue
        d = str(b.get("date") or "")[:10]
        if d != as_of_ist:
            continue
        try:
            o = float(b["open"])
            c = float(b["close"])
        except (KeyError, TypeError, ValueError):
            return None
        if o == 0:
            return None
        return 100.0 * (c - o) / o
    return None


def build_switch_proof(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    incumbent: str,
    challenger: str,
    as_of_ist: str,
    horizon: str = "session_1d",
    switch_cost_pct: float = 0.0,
) -> dict[str, Any]:
    """Compare session returns from durable bars only.

    JUSTIFIED if challenger session return exceeds incumbent by more than
    ``switch_cost_pct``. Missing/invalid bars → NOT_EVALUABLE (never invent).
    """
    from atlas.investment.market_bars_health import assess_symbols, bar_path

    inc = str(incumbent or "").strip().upper()
    ch = str(challenger or "").strip().upper()
    health = assess_symbols(data_dir, [inc, ch], as_of_ist=as_of_ist)
    by_sym = {
        str(r.get("symbol") or "").upper(): r
        for r in (health.get("symbols") or [])
        if isinstance(r, dict)
    }
    inc_h = by_sym.get(inc) or {}
    ch_h = by_sym.get(ch) or {}
    base = {
        "version": VERSION,
        "kind": "SWITCH_PROOF",
        "laboratory_id": laboratory_id,
        "as_of_ist": as_of_ist,
        "horizon": horizon,
        "incumbent": inc,
        "challenger": ch,
        "switch_cost_pct": float(switch_cost_pct),
        "bars_health": {
            "incumbent_replayable": bool(inc_h.get("replayable")),
            "challenger_replayable": bool(ch_h.get("replayable")),
            "incumbent_issues": list(inc_h.get("issues") or []),
            "challenger_issues": list(ch_h.get("issues") or []),
        },
        "built_at": _now(),
        "mutates_allocation": False,
        "honesty": (
            "Proof uses durable daily open→close only. Not intraday path. "
            "Not a license to raise switch rate. NOT_EVALUABLE when history thin."
        ),
    }
    if not data_dir or not inc or not ch:
        return {
            **base,
            "status": STATUS_NOT_EVALUABLE,
            "reason": "missing_args",
        }
    if not inc_h.get("replayable") or not ch_h.get("replayable"):
        return {
            **base,
            "status": STATUS_NOT_EVALUABLE,
            "reason": "bars_not_replayable",
        }
    inc_path = bar_path(data_dir, inc)
    ch_path = bar_path(data_dir, ch)
    if inc_path is None or ch_path is None:
        return {
            **base,
            "status": STATUS_NOT_EVALUABLE,
            "reason": "bars_path_missing",
        }
    inc_ret = _session_return_pct(inc_path, as_of_ist)
    ch_ret = _session_return_pct(ch_path, as_of_ist)
    base["incumbent_session_return_pct"] = inc_ret
    base["challenger_session_return_pct"] = ch_ret
    if inc_ret is None or ch_ret is None:
        return {
            **base,
            "status": STATUS_NOT_EVALUABLE,
            "reason": "session_bar_missing_for_day",
        }
    edge = ch_ret - inc_ret - float(switch_cost_pct)
    base["edge_after_cost_pct"] = edge
    if edge > 1e-9:
        return {
            **base,
            "status": STATUS_JUSTIFIED,
            "reason": "challenger_session_return_exceeds_incumbent_after_cost",
        }
    return {
        **base,
        "status": STATUS_NOT_JUSTIFIED,
        "reason": "challenger_not_better_after_cost",
    }


def persist_switch_proof(
    data_dir: str | Path | None, proof: dict[str, Any]
) -> dict[str, Any]:
    if not data_dir or not isinstance(proof, dict):
        return {"ok": False, "reason": "missing_args"}
    lab = str(proof.get("laboratory_id") or "unknown")
    day = str(proof.get("as_of_ist") or "")
    inc = str(proof.get("incumbent") or "inc")
    ch = str(proof.get("challenger") or "ch")
    root = Path(data_dir) / STORE_REL / lab
    name = f"{day}_{inc}_vs_{ch}.json".replace("/", "_")
    path = root / name
    try:
        root.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(proof, indent=2, default=str) + "\n", encoding="utf-8")
        return {"ok": True, "path": str(path)}
    except OSError as exc:
        _log.debug("switch proof persist failed", exc_info=True)
        return {"ok": False, "reason": type(exc).__name__}
