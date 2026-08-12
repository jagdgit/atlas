"""DAV densify — sizing learning journal (proposals / evidence only).

Records confidence → size → outcome tuples on material exits so Atlas can later
learn which confidence bands deserve larger allocation. Does **not** auto-change
``trade_fraction`` or promote strategy (proposals-only).
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "dav.sizing.journal.v1"
_LOCK = threading.RLock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def journal_path(data_dir: str | Path | None, *, laboratory_id: str) -> Path | None:
    if not data_dir:
        return None
    root = Path(data_dir) / "investment" / "sizing_learning" / str(laboratory_id)
    return root / "journal.jsonl"


def record_sizing_outcome(
    data_dir: str | Path | None,
    *,
    laboratory_id: str = "india_equity_learner",
    symbol: str,
    decision_id: str | None = None,
    confidence: float | None = None,
    size_fraction: float | None = None,
    notional: float | None = None,
    filled_qty: float | None = None,
    pnl: float | None = None,
    price_change_pct: float | None = None,
    thesis_correct: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one sizing→outcome row. Fail-closed if data_dir missing."""
    path = journal_path(data_dir, laboratory_id=laboratory_id)
    row = {
        "id": str(uuid.uuid4()),
        "version": VERSION,
        "ts": _utc_now(),
        "laboratory_id": laboratory_id,
        "symbol": str(symbol or "").upper(),
        "decision_id": decision_id,
        "confidence": float(confidence) if confidence is not None else None,
        "size_fraction": float(size_fraction) if size_fraction is not None else None,
        "notional": float(notional) if notional is not None else None,
        "filled_qty": float(filled_qty) if filled_qty is not None else None,
        "pnl": float(pnl) if pnl is not None else None,
        "price_change_pct": float(price_change_pct)
        if price_change_pct is not None
        else None,
        "thesis_correct": thesis_correct,
        "extra": dict(extra or {}),
        "honesty": (
            "Journal only — does not mutate trade_fraction or strategy. "
            "Sizing learning activates after enough closed rows."
        ),
    }
    if path is None:
        return {"ok": False, "reason": "no_data_dir", "row": row}
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"ok": True, "path": str(path), "row": row}


def load_sizing_journal(
    data_dir: str | Path | None,
    *,
    laboratory_id: str = "india_equity_learner",
    limit: int = 200,
) -> dict[str, Any]:
    path = journal_path(data_dir, laboratory_id=laboratory_id)
    rows: list[dict[str, Any]] = []
    if path and path.is_file():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            for line in lines[-max(1, int(limit)) :]:
                line = line.strip()
                if not line:
                    continue
                try:
                    doc = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(doc, dict):
                    rows.append(doc)
        except OSError:
            rows = []
    return {
        "version": VERSION,
        "laboratory_id": laboratory_id,
        "count": len(rows),
        "rows": rows,
        "path": str(path) if path else None,
        "proposals_only": True,
    }


def format_sizing_learning_evening_lines(doc: dict[str, Any] | None) -> list[str]:
    lines = ["", "Sizing learning (journal · proposals only):"]
    if not isinstance(doc, dict) or not doc.get("count"):
        lines.append(
            "  (empty — rows stamp on material exits; no auto size mutation)"
        )
        return lines
    n = int(doc.get("count") or 0)
    rows = [r for r in (doc.get("rows") or []) if isinstance(r, dict)]
    with_conf = sum(1 for r in rows if r.get("confidence") is not None)
    lines.append(
        f"  Sample={n} · with confidence={with_conf} · "
        "strategy size still control SMA/RSI (proposals only)"
    )
    for r in rows[-3:]:
        lines.append(
            f"  · {r.get('symbol')} conf={r.get('confidence')} "
            f"frac={r.get('size_fraction')} pnl={r.get('pnl')} "
            f"Δ%={r.get('price_change_pct')}"
        )
    return lines
