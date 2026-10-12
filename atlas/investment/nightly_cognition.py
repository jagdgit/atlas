"""Cognitive Loop C0 — nightly cognition receipt, decoupled from the mail path.

The evening digest is sent on the *timely* path, which deliberately skips WSO sync,
belief revision, global-mind distill, memory distill, reflection and CWS so SMTP can
leave on time. Without this module those stages would simply never run again.

So the stages run in their own window, after the day's evening mail is already out,
and persist a receipt. The digest then *reads* the receipt instead of computing it —
mail latency stays flat, and "no reflection ran" becomes a visible fact rather than a
silent omission.

Writes a receipt. Does not place orders, change strategy, or promote anything.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "cognitive.nightly.v1"
KIND = "NIGHTLY_COGNITION"
STORE_REL = Path("investment") / "nightly_cognition"
_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.nightly_cognition")

# Stages the timely mail path skips. Order matters: each feeds the next.
STAGES: tuple[str, ...] = (
    "wso_sync",
    "curiosity_drain",
    "decide_rationale",
    "belief_revision",
    "global_mind",
    "memory_distill",
    "reflection",
    "meta_cognition",
    "cognitive_work",
)


def ist_today() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def receipt_path(
    data_dir: str | Path, *, laboratory_id: str, as_of_ist: str
) -> Path:
    return Path(data_dir) / STORE_REL / str(laboratory_id) / f"{as_of_ist}.json"


def _count(value: Any) -> int | None:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        for key in ("count", "revisions", "revised", "done", "n"):
            if isinstance(value.get(key), int):
                return int(value[key])
        return len(value) or None
    return None


def build_receipt(
    port: dict[str, Any] | None,
    *,
    laboratory_id: str,
    as_of_ist: str | None = None,
    skipped_reason: str | None = None,
) -> dict[str, Any]:
    """Which stages produced something, and which stayed empty — stated either way."""
    p = port if isinstance(port, dict) else {}
    stages: dict[str, Any] = {}

    def record(name: str, value: Any) -> None:
        stages[name] = {
            "ran": value is not None,
            "count": _count(value),
        }

    record("wso_sync", p.get("world_states"))
    record("curiosity_drain", p.get("curiosity_queue"))
    record("decide_rationale", p.get("decide_rationale"))
    record("belief_revision", p.get("world_states") if p.get("world_states") else None)
    record("global_mind", p.get("global_wso"))
    record("memory_distill", p.get("memory_distill"))
    record("reflection", p.get("reflection"))
    record("meta_cognition", p.get("meta_cognition"))
    record("cognitive_work", p.get("cognitive_work"))

    ran = [name for name, st in stages.items() if st.get("ran")]
    return {
        "version": VERSION,
        "kind": KIND,
        "laboratory_id": str(laboratory_id or ""),
        "as_of_ist": as_of_ist or ist_today(),
        "ran": bool(ran) and not skipped_reason,
        "skipped_reason": skipped_reason,
        "stages": stages,
        "stages_ran": ran,
        "stages_empty": [name for name, st in stages.items() if not st.get("ran")],
        "jis_revisions": p.get("jis_revisions"),
        "reflection_section": p.get("reflection_section"),
        "recorded_at": datetime.now(_IST).isoformat(),
        "honesty": (
            "Receipt of nightly cognitive stages run off the mail path. "
            "An empty stage means it produced nothing, not that it was hidden. "
            "No orders, no strategy change, no promotion."
        ),
    }


def persist_receipt(data_dir: str | Path, receipt: dict[str, Any]) -> dict[str, Any]:
    if not data_dir or not isinstance(receipt, dict):
        return {"ok": False, "reason": "missing_args"}
    try:
        path = receipt_path(
            data_dir,
            laboratory_id=str(receipt.get("laboratory_id") or ""),
            as_of_ist=str(receipt.get("as_of_ist") or ist_today()),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "path": str(path)}
    except Exception as exc:  # noqa: BLE001
        _log.debug("nightly cognition receipt persist failed", exc_info=True)
        return {"ok": False, "reason": type(exc).__name__}


def load_receipt(
    data_dir: str | Path, *, laboratory_id: str, as_of_ist: str | None = None
) -> dict[str, Any] | None:
    if not data_dir:
        return None
    path = receipt_path(
        data_dir, laboratory_id=laboratory_id, as_of_ist=as_of_ist or ist_today()
    )
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return doc if isinstance(doc, dict) else None


def format_nightly_cognition_section(receipt: dict[str, Any] | None) -> list[str]:
    """Evening-digest lines read from the receipt — never computed inline."""
    lines = ["Nightly cognition:"]
    if not isinstance(receipt, dict):
        lines.append(
            "  not run yet today — reflection / belief revision pending (runs after the digest)"
        )
        return lines
    if not receipt.get("ran"):
        reason = receipt.get("skipped_reason") or "no stage produced output"
        lines.append(f"  skipped — {reason}")
        return lines
    ran = list(receipt.get("stages_ran") or [])
    empty = list(receipt.get("stages_empty") or [])
    lines.append(f"  ran at {receipt.get('recorded_at')}")
    lines.append(f"  produced: {', '.join(ran) if ran else 'nothing'}")
    if empty:
        lines.append(f"  empty: {', '.join(empty)}")
    return lines
