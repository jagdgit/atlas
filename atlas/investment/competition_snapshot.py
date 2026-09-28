"""OI-MDPH0 Phase 5 — Intraday opportunity competition snapshot.

candidate_set → scores → winner → decision

Advice/instrument layer: records what the competitive set looked like.
Does not mutate strategy parameters or invent cooldown rules.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "learn.competition.v1"
STORE_REL = Path("investment") / "competition"
_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.competition")
CASH = "CASH"


def ist_today() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in (s or ""))[:80]


def _f(v: Any) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def build_competition_snapshot(
    *,
    laboratory_id: str,
    candidates: list[dict[str, Any]],
    decision: str | None = None,
    incumbent: str | None = None,
    as_of_ist: str | None = None,
) -> dict[str, Any]:
    """Normalize a scored candidate set into an auditable competition record.

    Each candidate dict should include at least ``symbol`` and a score field
    (``expected_return`` / ``opportunity_score`` / ``score``).
    """
    day = as_of_ist or ist_today()
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for c in candidates or []:
        if not isinstance(c, dict):
            continue
        sym = str(c.get("symbol") or "").strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        er = _f(c.get("expected_return") if c.get("expected_return") is not None else c.get("er"))
        opp = _f(c.get("opportunity_score") if c.get("opportunity_score") is not None else c.get("score"))
        score = opp if opp is not None else er
        rows.append(
            {
                "symbol": sym,
                "expected_return": er,
                "opportunity_score": opp,
                "score": score,
                "eligible": c.get("eligible", True),
                "notes": c.get("notes") or c.get("reason"),
            }
        )
    # Ensure CASH present for relative framing (once)
    if CASH not in seen:
        rows.append(
            {
                "symbol": CASH,
                "expected_return": 0.0,
                "opportunity_score": 0.0,
                "score": 0.0,
                "eligible": True,
                "notes": "cash_benchmark",
            }
        )
        seen.add(CASH)
    eligible = [r for r in rows if r.get("eligible") is not False and r.get("score") is not None]
    eligible.sort(key=lambda r: float(r.get("score") or 0.0), reverse=True)
    winner = eligible[0]["symbol"] if eligible else None
    return {
        "version": VERSION,
        "kind": "OPPORTUNITY_COMPETITION",
        "laboratory_id": laboratory_id,
        "as_of_ist": day,
        "recorded_at": _now_iso(),
        "incumbent": str(incumbent or "").upper() or None,
        "candidate_set": [r["symbol"] for r in rows],
        "scores": rows,
        "ranked": eligible,
        "winner": winner,
        "decision": decision,
        "earned": bool(winner and winner != CASH),
        "honesty": (
            "Snapshot of relative scores only — not a trade instruction. "
            "No symbol cooldown; incumbents must re-earn vs challengers+CASH."
        ),
        "anti_pattern": "no_primary_cooldown",
    }


def persist_competition(
    data_dir: str | Path,
    snap: dict[str, Any],
) -> Path | None:
    lab = _safe(str(snap.get("laboratory_id") or "default"))
    day = str(snap.get("as_of_ist") or ist_today())
    root = Path(data_dir) / STORE_REL / lab
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{day}.jsonl"
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(snap, default=str) + "\n")
        (root / "_latest.json").write_text(
            json.dumps(snap, indent=2, default=str) + "\n", encoding="utf-8"
        )
        return path
    except OSError:
        _log.debug("competition persist failed", exc_info=True)
        return None


def format_competition_line(snap: dict[str, Any]) -> str:
    ranked = snap.get("ranked") or []
    parts = []
    for r in ranked[:6]:
        sc = r.get("score")
        try:
            pct = f"{float(sc) * 100:.2f}%" if abs(float(sc or 0)) < 2 else f"{float(sc):.4f}"
        except (TypeError, ValueError):
            pct = str(sc)
        parts.append(f"{r.get('symbol')} {pct}")
    winner = snap.get("winner") or "?"
    return (
        " · ".join(parts)
        + f" → {winner} wins"
        + (f" (decision={snap.get('decision')})" if snap.get("decision") else "")
    )
