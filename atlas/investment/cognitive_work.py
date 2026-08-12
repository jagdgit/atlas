"""OI-CWS0 — Cognitive Work Scheduler (daily thinking quota).

Curiosity-driven work: belief reviews, research tasks, contradiction checks,
counterfactuals, and long-term synthesis — even when the market is closed.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

VERSION = "jdg.cws.v1"
STORE_REL = Path("investment") / "cognitive_work"
_log = logging.getLogger("atlas.investment.cognitive_work")

# Daily Cognitive Quota (LOCKED Judgment Pivot amendment B)
DEFAULT_QUOTA: dict[str, int] = {
    "belief_review": 5,
    "research_task": 3,
    "contradiction_check": 2,
    "counterfactual": 1,
    "synthesis": 1,
}


def _ist_today() -> str:
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime

        return datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        return time.strftime("%Y-%m-%d", time.gmtime())


def day_path(data_dir: str | Path, laboratory_id: str, ist_date: str | None = None) -> Path:
    day = ist_date or _ist_today()
    lab = "".join(c if c.isalnum() or c in "-_" else "_" for c in (laboratory_id or "lab"))
    d = Path(data_dir) / STORE_REL / lab
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{day}.json"


def load_day(
    data_dir: str | Path | None,
    laboratory_id: str,
    *,
    ist_date: str | None = None,
) -> dict[str, Any]:
    if not data_dir:
        return empty_day(laboratory_id, ist_date=ist_date)
    path = day_path(data_dir, laboratory_id, ist_date)
    if not path.is_file():
        return empty_day(laboratory_id, ist_date=ist_date)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else empty_day(laboratory_id, ist_date=ist_date)
    except (OSError, json.JSONDecodeError):
        return empty_day(laboratory_id, ist_date=ist_date)


def empty_day(laboratory_id: str, *, ist_date: str | None = None) -> dict[str, Any]:
    return {
        "version": VERSION,
        "laboratory_id": laboratory_id,
        "ist_date": ist_date or _ist_today(),
        "quota": dict(DEFAULT_QUOTA),
        "completed": {k: 0 for k in DEFAULT_QUOTA},
        "items": [],
        "honesty": (
            "CWS is a thinking quota — completing items ≠ trading edge. "
            "Empty market days still require cognitive work."
        ),
    }


def save_day(data_dir: str | Path | None, doc: dict[str, Any]) -> Path | None:
    if not data_dir or not isinstance(doc, dict):
        return None
    path = day_path(
        data_dir,
        str(doc.get("laboratory_id") or "lab"),
        str(doc.get("ist_date") or _ist_today()),
    )
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def remaining(doc: dict[str, Any] | None) -> dict[str, int]:
    d = doc if isinstance(doc, dict) else {}
    quota = d.get("quota") or DEFAULT_QUOTA
    done = d.get("completed") or {}
    return {
        k: max(0, int(quota.get(k) or 0) - int(done.get(k) or 0))
        for k in DEFAULT_QUOTA
    }


def record_item(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    kind: str,
    summary: str,
    detail: dict[str, Any] | None = None,
    ist_date: str | None = None,
) -> dict[str, Any]:
    """Record one completed cognitive work unit toward the daily quota."""
    doc = load_day(data_dir, laboratory_id, ist_date=ist_date)
    kind_k = str(kind or "").strip()
    if kind_k not in DEFAULT_QUOTA:
        kind_k = "research_task"
    completed = dict(doc.get("completed") or {})
    completed[kind_k] = int(completed.get(kind_k) or 0) + 1
    doc["completed"] = completed
    items = list(doc.get("items") or [])
    items.append(
        {
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "kind": kind_k,
            "summary": (summary or "")[:400],
            "detail": detail or {},
        }
    )
    doc["items"] = items[-80:]
    save_day(data_dir, doc)
    return doc


def ensure_queued_from_unknowns(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    wsos: list[dict[str, Any]] | None,
    max_new: int = 5,
) -> dict[str, Any]:
    """Deprecated stub path — prefer ``run_cws_pass`` / curiosity.drain_queue_work.

    Kept for hermetic callers; no longer counts unfinished TODOs as completed work.
    """
    doc = load_day(data_dir, laboratory_id)
    doc["queued_from_unknowns"] = 0
    doc["honesty_note"] = (
        "J4: research_task quota only increments after real work (IRA start), "
        "not when unknowns are merely listed."
    )
    return doc


def format_cws_section(doc: dict[str, Any] | None) -> list[str]:
    if not isinstance(doc, dict):
        return []
    lines = ["", "--- Cognitive Work (CWS) ---"]
    rem = remaining(doc)
    done = doc.get("completed") or {}
    bits = [
        f"{k}={done.get(k, 0)}/{(doc.get('quota') or DEFAULT_QUOTA).get(k, 0)}"
        for k in DEFAULT_QUOTA
    ]
    lines.append("quota today: " + " · ".join(bits))
    left = sum(rem.values())
    lines.append(f"remaining_units={left}")
    for it in list(doc.get("items") or [])[-5:]:
        if isinstance(it, dict):
            lines.append(f"  · [{it.get('kind')}] {it.get('summary')}")
    cq = doc.get("curiosity_queue") if isinstance(doc.get("curiosity_queue"), dict) else None
    if cq is not None:
        try:
            from atlas.investment.curiosity import format_curiosity_section

            lines.extend(format_curiosity_section(cq))
        except Exception:  # noqa: BLE001
            pass
    if left > 0:
        lines.append(
            "  Honesty: market idle ≠ cognitive idle — drain remaining quota before EOD."
        )
    return lines


def run_cws_pass(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    wsos: list[dict[str, Any]] | None = None,
    open_symbols: list[str] | None = None,
    research: Any | None = None,
) -> dict[str, Any]:
    """CWS tick: drain curiosity → real IRA work; advance Daily Cognitive Agenda.

    J4: ``research_task`` quota only increments when IRA actually starts.
    Amendment C: structural belief_review stubs do **not** clear agenda items.
    """
    rem0 = remaining(load_day(data_dir, laboratory_id))
    max_research = int(rem0.get("research_task") or 0)
    qdoc: dict[str, Any] = {}
    agenda: dict[str, Any] | None = None
    try:
        from atlas.investment.daily_cognitive_agenda import (
            load_agenda,
            mark_agenda_progress,
            save_agenda,
        )

        agenda = load_agenda(data_dir, laboratory_id)
    except Exception:  # noqa: BLE001
        agenda = None

    try:
        from atlas.investment.curiosity import drain_queue_work

        qdoc = drain_queue_work(
            data_dir,
            laboratory_id=laboratory_id,
            research=research,
            wsos=wsos,
            open_symbols=set(open_symbols or []) or None,
            max_starts=max_research,
            trigger="cws_j4",
        )
        for st in qdoc.get("work_started") or []:
            if not isinstance(st, dict):
                continue
            record_item(
                data_dir,
                laboratory_id=laboratory_id,
                kind="research_task",
                summary=(
                    f"IRA started for {st.get('symbol')} "
                    f"(unknown={st.get('unknown')})"
                ),
                detail={
                    "symbol": st.get("symbol"),
                    "unknown": st.get("unknown"),
                    "status": st.get("status") or "ira_started",
                    "source": "curiosity_drain",
                },
            )
            if agenda is not None:
                agenda = mark_agenda_progress(
                    agenda,
                    symbol=str(st.get("symbol") or "") or None,
                    unknown=str(st.get("unknown") or "") or None,
                    status="done",
                    work_ref="ira_started",
                )
    except Exception:  # noqa: BLE001
        _log.debug("J4 curiosity drain skipped", exc_info=True)

    rem = remaining(load_day(data_dir, laboratory_id))
    if rem.get("belief_review", 0) > 0:
        for sym in list(open_symbols or [])[: min(2, rem["belief_review"])]:
            record_item(
                data_dir,
                laboratory_id=laboratory_id,
                kind="belief_review",
                summary=f"Belief review pass: {sym} (structural — check WSO unknowns)",
                detail={"symbol": sym, "mode": "structural", "clears_agenda": False},
            )
            # Structural review → in_progress, not done (amendment C)
            if agenda is not None:
                agenda = mark_agenda_progress(
                    agenda,
                    symbol=sym,
                    status="in_progress",
                    work_ref="structural_belief_review",
                )

    day_now = load_day(data_dir, laboratory_id)
    rem = remaining(day_now)
    done_n = sum(int(v or 0) for v in (day_now.get("completed") or {}).values())
    if rem.get("synthesis", 0) > 0 and done_n >= 2:
        record_item(
            data_dir,
            laboratory_id=laboratory_id,
            kind="synthesis",
            summary="Interim synthesis: what agenda items remain blocked by missing evidence?",
            detail={"mode": "structural"},
        )

    if agenda is not None and data_dir:
        try:
            save_agenda(data_dir, agenda)
        except Exception:  # noqa: BLE001
            _log.debug("agenda save skipped", exc_info=True)

    out = load_day(data_dir, laboratory_id)
    if qdoc:
        out["curiosity_queue"] = qdoc
    if agenda is not None:
        out["cognitive_agenda"] = agenda
    save_day(data_dir, out)
    return out
