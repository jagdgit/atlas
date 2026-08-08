"""LI.3b — Forgotten opportunity tracker (LI.0a.3).

Lab-scoped records of ignored / missed / rejected / deferred opportunities.
Outcomes from later material moves are **not** trade win-rate — they teach
whether Atlas under-observed the book (separate from strategy edge gates).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from atlas.investment.laboratory import (
    LaboratoryContaminationError,
    assert_single_laboratory,
    normalize_laboratory_id,
    stamp_laboratory_identity,
)

_log = logging.getLogger("atlas.investment.opportunity_tracker")

VERSION = "li.3b.opportunity_tracker"
STORE_REL = Path("investment") / "opportunities"

OPPORTUNITY_KINDS = frozenset({"ignored", "missed", "rejected", "deferred"})
OUTCOME_STATUSES = frozenset(
    {"open", "materialized_adverse", "materialized_favorable", "expired", "closed"}
)


def mirror_root(data_dir: str | Path, laboratory_id: str) -> Path:
    lab = normalize_laboratory_id(laboratory_id=laboratory_id)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in lab)
    return Path(data_dir) / STORE_REL / safe


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")


def _write_by_id(data_dir: str | Path, laboratory_id: str, row: dict[str, Any]) -> str | None:
    try:
        root = mirror_root(data_dir, laboratory_id)
        path = root / "by_id" / f"{row['id']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(row, indent=2, default=str) + "\n", encoding="utf-8")
        _append_jsonl(root / "events.jsonl", row)
        return str(path)
    except Exception:  # noqa: BLE001
        _log.debug("opportunity mirror failed", exc_info=True)
        return None


def record_opportunity(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    symbol: str,
    kind: str,
    reason: str = "",
    source: str = "operator",
    mark: float | None = None,
    horizon: str | None = None,
    related_decision_id: str | None = None,
    related_discovery_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one forgotten-opportunity row (lab-scoped)."""
    k = str(kind or "").strip().lower()
    if k not in OPPORTUNITY_KINDS:
        raise ValueError(
            f"invalid opportunity kind {kind!r}; expected one of {sorted(OPPORTUNITY_KINDS)}"
        )
    lab = normalize_laboratory_id(laboratory_id=laboratory_id)
    sym = str(symbol or "").strip().upper()
    if not sym:
        raise ValueError("symbol is required")
    row: dict[str, Any] = {
        "id": str(uuid4()),
        "created_at": _now(),
        "symbol": sym,
        "kind": k,
        "status": "open",
        "reason": (reason or "")[:400],
        "source": str(source or "operator")[:80],
        "mark_at_record": mark,
        "horizon": horizon,
        "related_decision_id": related_decision_id,
        "related_discovery_id": related_discovery_id,
        "outcome": None,
        "extra": dict(extra or {}),
        "version": VERSION,
    }
    stamp_laboratory_identity(row, lab)
    mirror = None
    if data_dir:
        mirror = _write_by_id(data_dir, lab, row)
    return {"opportunity": row, "mirror_path": mirror, "version": VERSION}


def list_opportunities(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    status: str | None = None,
    kind: str | None = None,
    symbol: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    if not data_dir:
        return []
    lab = normalize_laboratory_id(laboratory_id=laboratory_id)
    root = mirror_root(data_dir, lab) / "by_id"
    if not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(doc, dict):
            continue
        if status and str(doc.get("status") or "") != status:
            continue
        if kind and str(doc.get("kind") or "") != kind:
            continue
        if symbol and str(doc.get("symbol") or "").upper() != str(symbol).upper():
            continue
        rows.append(doc)
        if len(rows) >= limit:
            break
    # Hermeticity: refuse if somehow mixed
    assert_single_laboratory(rows, expected=lab, context="list_opportunities")
    return rows


def resolve_material_move(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    opportunity_id: str,
    mark_now: float,
    adverse: bool | None = None,
    note: str = "",
) -> dict[str, Any] | None:
    """Close an open opportunity with a material-move outcome (not trade PnL)."""
    if not data_dir:
        return None
    lab = normalize_laboratory_id(laboratory_id=laboratory_id)
    path = mirror_root(data_dir, lab) / "by_id" / f"{opportunity_id}.json"
    if not path.is_file():
        # Hermeticity: refuse if the id lives under another laboratory
        root = Path(data_dir) / STORE_REL
        if root.is_dir():
            for lab_dir in root.iterdir():
                other = lab_dir / "by_id" / f"{opportunity_id}.json"
                if other.is_file():
                    raise LaboratoryContaminationError(
                        f"opportunity {opportunity_id} belongs to laboratory "
                        f"{lab_dir.name!r}, not {lab!r}"
                    )
        return None
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(row, dict):
        return None
    extract_lab = row.get("laboratory_id") or row.get("portfolio_key")
    if extract_lab and str(extract_lab) != lab:
        raise LaboratoryContaminationError(
            f"opportunity {opportunity_id} belongs to {extract_lab}, not {lab}"
        )
    mark0 = row.get("mark_at_record")
    chg = None
    try:
        if mark0 is not None and float(mark0) != 0:
            chg = round(100.0 * (float(mark_now) - float(mark0)) / abs(float(mark0)), 3)
    except (TypeError, ValueError):
        chg = None
    if adverse is None and chg is not None:
        # Default: large absolute move = material; direction vs deferred/ignored is informational
        adverse = abs(chg) >= 5.0 and chg < 0
    status = "materialized_adverse" if adverse else "materialized_favorable"
    if chg is not None and abs(chg) < 2.0:
        status = "expired"
    row["status"] = status
    row["outcome"] = {
        "resolved_at": _now(),
        "mark_now": mark_now,
        "price_change_pct": chg,
        "note": (note or "")[:300],
        "is_trade_pnl": False,
        "honesty": "Opportunity outcome ≠ strategy edge / win-rate.",
    }
    stamp_laboratory_identity(row, lab)
    _write_by_id(data_dir, lab, row)
    return row


def record_plan_avoid(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    symbol: str,
    reason: str = "",
    mark: float | None = None,
    kind: str = "deferred",
) -> dict[str, Any]:
    """Convenience: morning-plan avoid / weaker rank → deferred|rejected opportunity."""
    k = kind if kind in OPPORTUNITY_KINDS else "deferred"
    return record_opportunity(
        data_dir,
        laboratory_id=laboratory_id,
        symbol=symbol,
        kind=k,
        reason=reason or "plan_avoid",
        source="morning_plan",
        mark=mark,
        horizon="swing",
    )


def opportunity_counts(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
) -> dict[str, Any]:
    rows = list_opportunities(data_dir, laboratory_id=laboratory_id, limit=500)
    by_kind: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for r in rows:
        k = str(r.get("kind") or "unknown")
        s = str(r.get("status") or "open")
        by_kind[k] = by_kind.get(k, 0) + 1
        by_status[s] = by_status.get(s, 0) + 1
    return {
        "laboratory_id": normalize_laboratory_id(laboratory_id=laboratory_id),
        "n": len(rows),
        "by_kind": by_kind,
        "by_status": by_status,
        "version": VERSION,
        "note": "Opportunity stats never pool across laboratories or into trade win-rate.",
    }


def format_opportunities_section(rows: list[dict[str, Any]] | None) -> list[str]:
    rows = list(rows or [])
    lines = ["", f"Forgotten opportunities (LI.3b) ({len(rows)}):"]
    if not rows:
        lines.append("  (none — watch/hold/reject/defer seams not yet labeled)")
        return lines
    for r in rows[:12]:
        out = r.get("outcome") or {}
        chg = out.get("price_change_pct")
        chg_s = f" move={chg:+.1f}%" if isinstance(chg, (int, float)) else ""
        lines.append(
            f"  · {r.get('kind')} {r.get('symbol')} [{r.get('status')}] "
            f"— {(r.get('reason') or '')[:80]}{chg_s}"
        )
    return lines
