"""OI-SCI-DRAIN0 / OI-LEARN-AUDIT0 — Ops indicator for scientist LLM backlog.

Advice-only research queue health. Never implies fills or capital action.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "ops.scientist_drain.v1"
_IST = ZoneInfo("Asia/Kolkata")

_LABS = (
    "india_equity_learner",
    "india_fno_learner",
    "equity_intraday_learner",
)

_LAB_LABELS = {
    "india_equity_learner": "Swing",
    "india_fno_learner": "F&O",
    "equity_intraday_learner": "Intraday",
}


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in (s or ""))[:80]


def _ist_today() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def _lab_counts(data_dir: Path, laboratory_id: str) -> dict[str, Any]:
    root = (
        data_dir
        / "investment"
        / "scientist_notes"
        / _safe(laboratory_id)
        / "by_id"
    )
    out: dict[str, Any] = {
        "laboratory_id": laboratory_id,
        "label": _LAB_LABELS.get(laboratory_id, laboratory_id),
        "pending": 0,
        "REVIEWED": 0,
        "done": 0,
        "failed_AttributeError": 0,
        "failed_OllamaError": 0,
        "failed_non_json": 0,
        "failed_permanent": 0,
        "failed_other": 0,
        "deferred_lane_busy": 0,
        "total": 0,
    }
    if not root.is_dir():
        return out
    for p in root.glob("*.json"):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict):
            continue
        out["total"] += 1
        st = str(doc.get("llm_status") or "")
        notes = doc.get("notes") if isinstance(doc.get("notes"), dict) else {}
        if str(notes.get("review_status") or "") == "REVIEWED":
            out["REVIEWED"] += 1
        if st == "pending":
            out["pending"] += 1
        elif st == "done":
            out["done"] += 1
        elif st == "deferred_lane_busy":
            out["deferred_lane_busy"] += 1
        elif st.startswith("failed_permanent"):
            out["failed_permanent"] += 1
        elif "AttributeError" in st:
            out["failed_AttributeError"] += 1
        elif "OllamaError" in st or "Timeout" in st:
            out["failed_OllamaError"] += 1
        elif "non_json" in st:
            out["failed_non_json"] += 1
        elif st.startswith("failed"):
            out["failed_other"] += 1
        elif st in {"pending", ""} or st.startswith("deferred"):
            out["pending"] += 1
    # Retriable = still eligible for drain (permanent excluded)
    out["retriable"] = (
        int(out["pending"])
        + int(out["failed_AttributeError"])
        + int(out["failed_OllamaError"])
        + int(out["failed_non_json"])
        + int(out["deferred_lane_busy"])
    )
    return out


def _fitness_scientist_today(data_dir: Path, day: str) -> dict[str, Any]:
    path = data_dir / "investment" / "llm_fitness" / f"{day}.jsonl"
    out = {"n": 0, "ok": 0, "error": 0, "timeout": 0}
    if not path.is_file():
        return out
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            purpose = str(row.get("purpose") or "").lower()
            if not any(x in purpose for x in ("scientist", "icr5", "bre3")):
                continue
            out["n"] += 1
            oc = str(row.get("outcome") or "")
            if oc == "ok":
                out["ok"] += 1
            elif oc == "timeout":
                out["timeout"] += 1
            elif oc in {"error", "busy", "lane_busy"}:
                out["error"] += 1
    except OSError:
        pass
    return out


def scientist_drain_snapshot(
    data_dir: str | Path | None,
    *,
    as_of_ist: str | None = None,
    laboratory_ids: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    """Compact Ops card payload for scientist LLM backlog."""
    day = as_of_ist or _ist_today()
    if not data_dir:
        return {
            "version": VERSION,
            "as_of_ist": day,
            "status": "unknown",
            "honesty": "no_data_dir",
            "advice_only": True,
            "never_orders": True,
        }
    root = Path(data_dir)
    labs = list(laboratory_ids or _LABS)
    by_lab = [_lab_counts(root, lab) for lab in labs]
    pending = sum(int(x.get("pending") or 0) for x in by_lab)
    reviewed = sum(int(x.get("REVIEWED") or 0) for x in by_lab)
    retriable = sum(int(x.get("retriable") or 0) for x in by_lab)
    failed_attr = sum(int(x.get("failed_AttributeError") or 0) for x in by_lab)
    failed_ollama = sum(int(x.get("failed_OllamaError") or 0) for x in by_lab)
    failed_json = sum(int(x.get("failed_non_json") or 0) for x in by_lab)
    failed_perm = sum(int(x.get("failed_permanent") or 0) for x in by_lab)
    fitness = _fitness_scientist_today(root, day)

    if reviewed > 0 and retriable == 0:
        status = "caught_up"
    elif fitness.get("ok") and reviewed == 0:
        status = "draining_unvalidated"  # ok calls but no REVIEWED yet (e.g. non_json)
    elif retriable > 0 and (fitness.get("n") or 0) > 0:
        status = "draining"
    elif retriable > 0:
        status = "backlog_idle"
    else:
        status = "idle"

    primary = next(
        (x for x in by_lab if x.get("laboratory_id") == "india_equity_learner"),
        by_lab[0] if by_lab else {},
    )

    return {
        "version": VERSION,
        "as_of_ist": day,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "pending": pending,
        "REVIEWED": reviewed,
        "retriable": retriable,
        "failed_AttributeError": failed_attr,
        "failed_OllamaError": failed_ollama,
        "failed_non_json": failed_json,
        "failed_permanent": failed_perm,
        "fitness_today": fitness,
        "primary_lab": primary,
        "by_lab": by_lab,
        "operator_line": (
            f"Scientist notes: REVIEWED={reviewed} · pending/retriable≈{retriable} "
            f"· permanent={failed_perm} (bounded retries; advice-only)"
        ),
        "why_pending": (
            "Each paper tick used to mint a new acp_id UUID and duplicate pending rows "
            "for the same state_hash; scheduling is now idempotent per symbol+state_hash. "
            "Deterministic AttributeError/non-JSON failures promote to failed_permanent "
            "after max attempts so they cannot burn tick/LLM capacity forever."
        ),
        "advice_only": True,
        "never_orders": True,
        "honesty": (
            "REVIEWED is research advice surface — not learning and not fills. "
            "Learning still needs prediction→outcome→attribution. "
            "failed_permanent is not an investment failure."
        ),
    }
