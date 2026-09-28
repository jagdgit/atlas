"""OI-INTRADAY-FLAT — daily proof that the intraday lab is flat overnight.

Contract (NOW roadmap #3 / LINT0):
  5m → decide → enter → monitor → exit → 15:20–15:25 forced flatten
  → overnight_positions = 0 every day.

This module records that proof durably so evening mail / UI can show pass/fail
without reading worker state.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "now.intraday_integrity.v1"
STORE_REL = Path("investment") / "intraday_integrity"
DEFAULT_LAB = "equity_intraday_learner"
_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.intraday_integrity")


def ist_today() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def day_path(
    data_dir: str | Path | None,
    laboratory_id: str | None = None,
    as_of_ist: str | None = None,
) -> Path | None:
    if not data_dir:
        return None
    lab = (laboratory_id or DEFAULT_LAB).strip() or DEFAULT_LAB
    day = as_of_ist or ist_today()
    return Path(data_dir) / STORE_REL / lab / f"{day}.json"


def count_open_positions(positions: list[Any] | None) -> int:
    n = 0
    for p in positions or []:
        if not isinstance(p, dict):
            continue
        try:
            qty = float(p.get("quantity") or p.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        if abs(qty) > 1e-12:
            n += 1
    return n


def open_symbols(positions: list[Any] | None) -> list[str]:
    out: list[str] = []
    for p in positions or []:
        if not isinstance(p, dict):
            continue
        try:
            qty = float(p.get("quantity") or p.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        if abs(qty) <= 1e-12:
            continue
        sym = str(p.get("symbol") or "").strip()
        if sym:
            out.append(sym)
    return out


def build_integrity_doc(
    *,
    laboratory_id: str,
    as_of_ist: str | None = None,
    positions: list[Any] | None = None,
    must_be_flat: bool = False,
    flatten_outcomes: list[Any] | None = None,
    flatten_session: str | None = None,
    source: str = "paper_trading",
) -> dict[str, Any]:
    day = as_of_ist or ist_today()
    overnight_n = count_open_positions(positions)
    syms = open_symbols(positions)
    outcomes = [o for o in (flatten_outcomes or []) if isinstance(o, dict)]
    # Pass when we must be flat and are, OR when still in RTH with any book state.
    if must_be_flat:
        ok = overnight_n == 0
        status = "flat_ok" if ok else "overnight_carry"
    else:
        ok = True  # RTH — overnight contract not yet binding
        status = "session_open"
    return {
        "version": VERSION,
        "kind": "INTRADAY_INTEGRITY",
        "laboratory_id": laboratory_id,
        "as_of_ist": day,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "must_be_flat": bool(must_be_flat),
        "overnight_positions": overnight_n,
        "open_symbols": syms,
        "overnight_positions_ok": bool(ok) if must_be_flat else None,
        "status": status,
        "flatten_session": flatten_session,
        "flatten_outcomes_n": len(outcomes),
        "flatten_outcomes": outcomes[-12:],
        "honesty": (
            "overnight_positions must be 0 from 15:20 IST through next 09:15. "
            "Carrying qty overnight contaminates P&L, duration, and attribution."
        ),
    }


def save_integrity(
    data_dir: str | Path | None,
    doc: dict[str, Any],
) -> dict[str, Any]:
    path = day_path(
        data_dir,
        str(doc.get("laboratory_id") or DEFAULT_LAB),
        str(doc.get("as_of_ist") or ist_today()),
    )
    if path is None:
        return {"ok": False, "reason": "no_data_dir"}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")
        return {"ok": True, "path": str(path)}
    except OSError as exc:
        _log.debug("intraday integrity save failed: %s", exc)
        return {"ok": False, "reason": type(exc).__name__}


def load_integrity(
    data_dir: str | Path | None,
    *,
    laboratory_id: str | None = None,
    as_of_ist: str | None = None,
) -> dict[str, Any] | None:
    path = day_path(data_dir, laboratory_id, as_of_ist)
    if path is None or not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def record_intraday_integrity(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    positions: list[Any] | None,
    must_be_flat: bool,
    flatten_outcomes: list[Any] | None = None,
    flatten_session: str | None = None,
    as_of_ist: str | None = None,
    source: str = "paper_trading",
) -> dict[str, Any]:
    doc = build_integrity_doc(
        laboratory_id=laboratory_id,
        as_of_ist=as_of_ist,
        positions=positions,
        must_be_flat=must_be_flat,
        flatten_outcomes=flatten_outcomes,
        flatten_session=flatten_session,
        source=source,
    )
    save_integrity(data_dir, doc)
    return doc


def format_intraday_integrity_evening_lines(
    data_dir: str | Path | None,
    *,
    laboratory_id: str = DEFAULT_LAB,
    as_of_ist: str | None = None,
) -> list[str]:
    doc = load_integrity(data_dir, laboratory_id=laboratory_id, as_of_ist=as_of_ist)
    lines = ["", "── Intraday overnight integrity (NOW #3) ──"]
    if not doc:
        lines.append(
            f"  · {laboratory_id}: (no integrity file yet — wait for 15:20 flatten tick)"
        )
        return lines
    ok = doc.get("overnight_positions_ok")
    n = doc.get("overnight_positions")
    status = doc.get("status")
    if ok is True:
        lines.append(
            f"  · {laboratory_id}: overnight_positions=0 ✅ ({status})"
        )
    elif ok is False:
        syms = ", ".join(doc.get("open_symbols") or []) or "?"
        lines.append(
            f"  · {laboratory_id}: overnight_positions={n} ❌ CARRY [{syms}] — "
            "contaminates experiment"
        )
    else:
        lines.append(
            f"  · {laboratory_id}: status={status} · open={n} "
            f"(RTH — flatten gate not binding yet)"
        )
    lines.append(
        f"  flatten_outcomes={doc.get('flatten_outcomes_n', 0)} · "
        f"session={doc.get('flatten_session') or '—'}"
    )
    lines.append(str(doc.get("honesty") or ""))
    return lines
