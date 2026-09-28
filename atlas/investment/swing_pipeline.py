"""TRADE-LOOP0 Slice E — swing candidate pipeline diagnostic (not a trader).

Universe → SMA BUY → PLC.A complete/incomplete → research/MoS/AVOID → fills.
HOLD after complete evidence is success. Does not loosen PLC.A.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "trade.loop0.swing_pipeline.v1"
STORE_REL = Path("investment") / "decisions" / "pipeline"
_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.swing_pipeline")


def ist_today() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def _sym(raw: Any) -> str:
    return str(raw or "").strip().upper()


def classify_packet(pkt: dict[str, Any]) -> str:
    kind = str(pkt.get("kind") or pkt.get("action") or "").lower()
    tag = str(pkt.get("strategy_tag") or "").lower()
    reasons = " ".join(
        str(x) for x in (pkt.get("reasons_against") or pkt.get("reasons") or [])
    ).lower()
    gate = pkt.get("plc_a") if isinstance(pkt.get("plc_a"), dict) else {}
    missing = gate.get("missing") or pkt.get("missing_fields") or []
    if "fundamentals_incomplete" in tag or "fundamentals_incomplete" in reasons:
        return "plc_a_incomplete"
    if missing:
        return "plc_a_incomplete"
    if "research" in tag or "thesis_watch" in reasons or kind == "research_hold":
        return "research_hold"
    if "avoid" in reasons or tag == "lab_policy":
        return "lab_policy_avoid"
    if "mos" in reasons and ("negative" in reasons or "unavailable" in reasons):
        return "mos_block"
    if kind == "buy":
        return "authorized_buy"
    if kind == "sell":
        return "sell"
    return "engine_hold"


def build_swing_pipeline(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    universe_n: int | None = None,
    sma_symbols: list[str] | None = None,
    packets: list[dict[str, Any]] | None = None,
    fills_n: int = 0,
    as_of_ist: str | None = None,
) -> dict[str, Any]:
    day = as_of_ist or ist_today()
    rows: list[dict[str, Any]] = []
    counts = {
        "plc_a_complete": 0,
        "plc_a_incomplete": 0,
        "research_hold": 0,
        "mos_unavailable": 0,
        "mos_negative": 0,
        "lab_policy_avoid": 0,
        "authorized_buy": 0,
        "engine_hold": 0,
        "sell": 0,
    }
    uq_by_sym: dict[str, list[str]] = {}
    if data_dir:
        try:
            from atlas.investment.uncertainty_queue import STATUS_PENDING, list_tasks

            for t in list_tasks(data_dir, laboratory_id, status=STATUS_PENDING) or []:
                s = _sym(t.get("symbol"))
                if s:
                    uq_by_sym.setdefault(s, []).append(str(t.get("unknown") or ""))
        except Exception:  # noqa: BLE001
            _log.debug("pipeline UQ scan skipped", exc_info=True)

    seen: set[str] = set()
    for pkt in packets or []:
        if not isinstance(pkt, dict):
            continue
        sym = _sym(pkt.get("symbol"))
        if not sym or sym in seen:
            continue
        seen.add(sym)
        bucket = classify_packet(pkt)
        if bucket == "mos_block":
            reasons = " ".join(str(x) for x in (pkt.get("reasons_against") or [])).lower()
            bucket = "mos_negative" if "negative" in reasons else "mos_unavailable"
        counts[bucket] = int(counts.get(bucket) or 0) + 1
        gate = pkt.get("plc_a") if isinstance(pkt.get("plc_a"), dict) else {}
        rows.append(
            {
                "symbol": sym,
                "sma_signal": str(pkt.get("kind") or pkt.get("action") or ""),
                "plc_a_status": bucket,
                "missing_fields": list(gate.get("missing") or []),
                "uq": uq_by_sym.get(sym) or [],
                "research_status": str(pkt.get("strategy_tag") or ""),
                "final": bucket,
            }
        )

    sma = [_sym(s) for s in (sma_symbols or []) if _sym(s)]
    doc = {
        "version": VERSION,
        "kind": "SWING_PIPELINE",
        "laboratory_id": laboratory_id,
        "as_of_ist": day,
        "universe_n": universe_n,
        "sma_candidates": len(sma) or len(rows),
        "paper_fills": int(fills_n),
        "counts": counts,
        "rows": rows,
        "honesty": (
            "Diagnostic — not a trading signal. HOLD after complete evidence is success. "
            "Zero fills with PLC.A incomplete is data starvation, not a strategy verdict."
        ),
    }
    return doc


def persist_swing_pipeline(
    data_dir: str | Path | None, doc: dict[str, Any] | None
) -> Path | None:
    if not data_dir or not isinstance(doc, dict):
        return None
    lab = str(doc.get("laboratory_id") or "lab").replace("/", "_")
    day = str(doc.get("as_of_ist") or ist_today())
    root = Path(data_dir) / STORE_REL / lab
    try:
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{day}.json"
        text = json.dumps(doc, indent=2, default=str) + "\n"
        path.write_text(text, encoding="utf-8")
        (root / "latest.json").write_text(text, encoding="utf-8")
        return path
    except OSError:
        _log.debug("swing pipeline persist failed", exc_info=True)
        return None
