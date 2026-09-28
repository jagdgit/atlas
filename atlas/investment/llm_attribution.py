"""OI-MDPH0 Phase 7 — LLM contribution attribution (measurement only).

deterministic baseline ‖ Ollama advice → accepted? → changed anything? → outcome

Never grants allocation authority. Call counts are not contribution.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "learn.llm_attribution.v1"
STORE_REL = Path("investment") / "llm_attribution"
_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.llm_attribution")


def ist_today() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_consultation(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    purpose: str,
    advice_summary: str | None = None,
    accepted: bool | None = None,
    changed: list[str] | None = None,
    outcome_ref: str | None = None,
    deterministic_action: str | None = None,
    advised_action: str | None = None,
) -> dict[str, Any]:
    """Append one attribution row. ``changed`` examples: research, ranking, none."""
    row = {
        "version": VERSION,
        "as_of_ist": ist_today(),
        "recorded_at": _now_iso(),
        "laboratory_id": laboratory_id,
        "purpose": purpose,
        "advice_summary": (advice_summary or "")[:400] or None,
        "deterministic_action": deterministic_action,
        "advised_action": advised_action,
        "accepted": accepted,
        "changed": list(changed or []) or ["none"],
        "outcome_ref": outcome_ref,
        "influence": "advice_only",
        "never_orders": True,
        "honesty": (
            "Attribution row — not proof of value until outcome_ref is joined. "
            "Successful LLM HTTP ≠ economic contribution."
        ),
    }
    if not data_dir:
        return row
    root = Path(data_dir) / STORE_REL
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{ist_today()}.jsonl"
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
    except OSError:
        _log.debug("llm attribution write failed", exc_info=True)
    return row


def summarize_day(data_dir: str | Path, *, as_of_ist: str | None = None) -> dict[str, Any]:
    day = as_of_ist or ist_today()
    path = Path(data_dir) / STORE_REL / f"{day}.jsonl"
    rows: list[dict[str, Any]] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    accepted = sum(1 for r in rows if r.get("accepted") is True)
    ignored = sum(1 for r in rows if r.get("accepted") is False)
    changed_research = sum(1 for r in rows if "research" in (r.get("changed") or []))
    changed_ranking = sum(1 for r in rows if "ranking" in (r.get("changed") or []))
    changed_allocation = sum(1 for r in rows if "allocation" in (r.get("changed") or []))
    return {
        "version": VERSION,
        "as_of_ist": day,
        "n": len(rows),
        "accepted": accepted,
        "ignored": ignored,
        "changed_research": changed_research,
        "changed_ranking": changed_ranking,
        "changed_allocation": changed_allocation,
        "proven_allocation_improvements": 0,  # requires outcome join — honesty
        "honesty": (
            "proven_allocation_improvements stays 0 until outcome join proves "
            "advice caused a better Next-₹1 decision than deterministic-alone."
        ),
    }
