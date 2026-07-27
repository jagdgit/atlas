"""Durable per-IST-day session notes for evening reports / outage honesty.

Paper trading writes aggregated hold / feed reasons; investor reports reads them
so the evening email can explain zero fills honestly.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

_log = logging.getLogger("atlas.investment.session_notes")

STORE_REL = Path("market") / "session_notes"


def notes_dir(data_dir: str | Path) -> Path:
    return Path(data_dir) / STORE_REL


def notes_path(data_dir: str | Path, *, portfolio_key: str, ist_date: str) -> Path:
    safe_key = (portfolio_key or "default").replace("/", "_").strip() or "default"
    return notes_dir(data_dir) / safe_key / f"{ist_date}.json"


def load_day_notes(
    data_dir: str | Path | None,
    *,
    portfolio_key: str,
    ist_date: str,
) -> dict[str, Any]:
    if not data_dir:
        return {}
    path = notes_path(data_dir, portfolio_key=portfolio_key, ist_date=ist_date)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:  # noqa: BLE001
        _log.debug("session notes read failed: %s", path, exc_info=True)
        return {}


def merge_day_notes(
    data_dir: str | Path | None,
    *,
    portfolio_key: str,
    ist_date: str,
    reason_counts: dict[str, int],
    samples: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge reason counters into today's note file (idempotent across ticks)."""
    if not data_dir:
        return {}
    path = notes_path(data_dir, portfolio_key=portfolio_key, ist_date=ist_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_day_notes(data_dir, portfolio_key=portfolio_key, ist_date=ist_date)
    counts = dict(existing.get("reason_counts") or {})
    for k, v in (reason_counts or {}).items():
        key = str(k)
        try:
            counts[key] = int(counts.get(key, 0)) + int(v)
        except (TypeError, ValueError):
            continue
    sample_list = list(existing.get("samples") or [])
    for s in samples or []:
        text = str(s).strip()
        if text and text not in sample_list:
            sample_list.append(text)
        if len(sample_list) >= 40:
            break
    doc: dict[str, Any] = {
        "ist_date": ist_date,
        "portfolio_key": portfolio_key or "default",
        "reason_counts": counts,
        "samples": sample_list[-40:],
    }
    if extra:
        for k, v in extra.items():
            if v is not None:
                doc[k] = v
    # Preserve prior extras not overwritten
    for k, v in existing.items():
        if k not in doc and k not in {"reason_counts", "samples"}:
            doc[k] = v
    try:
        path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        _log.debug("session notes write failed: %s", path, exc_info=True)
    return doc


def classify_action(action: str) -> str | None:
    """Map a journal action string to a coarse evening-report bucket."""
    a = (action or "").lower()
    if ": buy " in a or a.endswith(" buy") or ":buy" in a.replace(" ", ""):
        return None  # fills aren't "why no fill"
    if ": sell " in a or ":sell" in a.replace(" ", ""):
        return None
    if "session_closed" in a:
        return "session_closed"
    if "empty_live_feed" in a:
        return "empty_live_feed"
    if "empty_feed" in a:
        return "empty_feed"
    if "feed_error" in a:
        return "feed_error"
    if "research_hold" in a:
        return "research_hold"
    if "policy_block" in a:
        return "policy_block"
    if "pack_block" in a:
        return "pack_block"
    if "mark_only" in a:
        return "mark_only"
    if "gap (" in a or ": gap" in a:
        return "capability_gap"
    if ": hold @" in a:
        return "strategy_hold"
    if "feed_exhausted" in a:
        return "feed_exhausted"
    return "other_idle"


REASON_LABELS = {
    "session_closed": "Market session closed (outside NSE cash hours / weekend)",
    "empty_live_feed": "Live price feed empty (often internet / Yahoo outage)",
    "empty_feed": "Bar feed empty",
    "feed_error": "Live feed errors while fetching bars",
    "research_hold": "Research gate held buys (MVR / thesis / MoS incomplete)",
    "policy_block": "Policy engine blocked the order",
    "pack_block": "Instrument pack validation blocked the order",
    "mark_only": "Same bar already decided — mark-to-market only (no new decision)",
    "capability_gap": "Capability gap (missing feed / pack capability)",
    "strategy_hold": "Strategy decided hold (no buy/sell signal)",
    "feed_exhausted": "Replay feed exhausted",
    "other_idle": "Other idle / skip reasons",
}


def format_no_fill_reasons(notes: dict[str, Any] | None) -> list[str]:
    """Human lines explaining why the evening report shows zero fills."""
    notes = notes or {}
    counts = notes.get("reason_counts") or {}
    if not counts:
        return [
            "No simulated fills in this snapshot — and no session reason counters "
            "were recorded yet (worker may have been down or outside market hours)."
        ]
    # Prefer explanatory buckets over mark_only noise
    ordered = sorted(
        ((k, int(v)) for k, v in counts.items() if int(v) > 0),
        key=lambda kv: (-kv[1], kv[0]),
    )
    lines: list[str] = []
    for key, n in ordered[:8]:
        label = REASON_LABELS.get(key, key)
        lines.append(f"{label} ×{n}")
    gap = notes.get("feed_gap_days")
    if gap is not None:
        try:
            gd = float(gap)
            if gd >= 1:
                lines.append(
                    f"Price feed resumed after ~{gd:.0f} calendar day(s) gap — "
                    "existing holdings were kept; marks refresh on live bars."
                )
        except (TypeError, ValueError):
            pass
    return lines
