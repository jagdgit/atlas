"""OI-STAB0 P0.0 — Daily Activity Journal (ownership, not debug logs)."""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from atlas.repositories.base import BaseRepository

VERSION = "stab0.activity_journal.v1"
_log = logging.getLogger("atlas.activity")
_IST = ZoneInfo("Asia/Kolkata")

ACTIVITY_DOMAINS = ("market", "engineering", "personal", "cross", "system")
ACTIVITY_RESULTS = ("completed", "skipped", "failed", "deferred", "partial")

_COLS = (
    "id, ts, domain, worker, action, target, result, summary, evidence, created_at"
)

# Process-wide optional binder (bootstrap sets this).
_journal: "ActivityJournal | None" = None
_journal_lock = threading.Lock()


def bind_journal(journal: "ActivityJournal | None") -> None:
    global _journal
    with _journal_lock:
        _journal = journal


def get_journal() -> "ActivityJournal | None":
    with _journal_lock:
        return _journal


def record_activity(
    *,
    domain: str,
    action: str,
    summary: str,
    worker: str = "",
    target: str | None = None,
    result: str = "completed",
    evidence: dict[str, Any] | None = None,
    ts: datetime | None = None,
) -> dict[str, Any] | None:
    """Fire-and-forget journal write. Never raises into callers."""
    j = get_journal()
    if j is None:
        return None
    try:
        return j.record(
            domain=domain,
            action=action,
            summary=summary,
            worker=worker,
            target=target,
            result=result,
            evidence=evidence,
            ts=ts,
        )
    except Exception:  # noqa: BLE001
        _log.debug("activity journal record failed", exc_info=True)
        return None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


class ActivityRepository(BaseRepository):
    def insert_event(
        self,
        *,
        domain: str,
        worker: str,
        action: str,
        summary: str,
        target: str | None = None,
        result: str = "completed",
        evidence: dict[str, Any] | None = None,
        ts: datetime | None = None,
    ) -> dict[str, Any]:
        domain = (domain or "system").strip().lower()
        if domain not in ACTIVITY_DOMAINS:
            domain = "system"
        result = (result or "completed").strip().lower()
        if result not in ACTIVITY_RESULTS:
            result = "completed"
        row = self.fetch_one(
            f"""
            INSERT INTO activity.activity_events
                (ts, domain, worker, action, target, result, summary, evidence)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {_COLS}
            """,
            (
                ts or _utcnow(),
                domain,
                (worker or "")[:120],
                (action or "unknown")[:120],
                (target[:240] if target else None),
                result,
                (summary or "").strip()[:2000] or action,
                Jsonb(_json_safe(evidence or {})),
            ),
        )
        assert row is not None
        return row

    def list_for_day_ist(
        self,
        day: date | str,
        *,
        domain: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        day_s = day.isoformat() if isinstance(day, date) else str(day)
        params: list[Any] = [day_s]
        where = (
            "(ts AT TIME ZONE 'Asia/Kolkata')::date = %s::date"
        )
        if domain:
            where += " AND domain = %s"
            params.append(domain.strip().lower())
        params.append(max(1, min(int(limit), 2000)))
        return self.fetch_all(
            f"""
            SELECT {_COLS} FROM activity.activity_events
            WHERE {where}
            ORDER BY ts ASC
            LIMIT %s
            """,
            tuple(params),
        )

    def count_for_day_ist(self, day: date | str) -> int:
        day_s = day.isoformat() if isinstance(day, date) else str(day)
        val = self.fetch_val(
            """
            SELECT COUNT(*) FROM activity.activity_events
            WHERE (ts AT TIME ZONE 'Asia/Kolkata')::date = %s::date
            """,
            (day_s,),
        )
        return int(val or 0)


class InMemoryActivityRepository:
    """Hermetic test double."""

    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def insert_event(self, **kwargs: Any) -> dict[str, Any]:
        domain = str(kwargs.get("domain") or "system").lower()
        if domain not in ACTIVITY_DOMAINS:
            domain = "system"
        result = str(kwargs.get("result") or "completed").lower()
        if result not in ACTIVITY_RESULTS:
            result = "completed"
        row = {
            "id": uuid.uuid4(),
            "ts": kwargs.get("ts") or _utcnow(),
            "domain": domain,
            "worker": str(kwargs.get("worker") or "")[:120],
            "action": str(kwargs.get("action") or "unknown")[:120],
            "target": kwargs.get("target"),
            "result": result,
            "summary": str(kwargs.get("summary") or kwargs.get("action") or "")[:2000],
            "evidence": dict(kwargs.get("evidence") or {}),
            "created_at": _utcnow(),
        }
        with self._lock:
            self._rows.append(row)
        return dict(row)

    def list_for_day_ist(
        self, day: date | str, *, domain: str | None = None, limit: int = 500
    ) -> list[dict[str, Any]]:
        day_s = day.isoformat() if isinstance(day, date) else str(day)
        out = []
        with self._lock:
            for r in self._rows:
                ts = r["ts"]
                if isinstance(ts, datetime):
                    local = ts.astimezone(_IST) if ts.tzinfo else ts.replace(tzinfo=timezone.utc).astimezone(_IST)
                    if local.date().isoformat() != day_s:
                        continue
                if domain and r["domain"] != domain.strip().lower():
                    continue
                out.append(dict(r))
        return out[: max(1, min(int(limit), 2000))]

    def count_for_day_ist(self, day: date | str) -> int:
        return len(self.list_for_day_ist(day, limit=2000))


class ActivityJournal:
    """Service façade over activity_events."""

    def __init__(self, repo: ActivityRepository | InMemoryActivityRepository) -> None:
        self._repo = repo

    @property
    def VERSION(self) -> str:  # noqa: N802
        return VERSION

    def record(
        self,
        *,
        domain: str,
        action: str,
        summary: str,
        worker: str = "",
        target: str | None = None,
        result: str = "completed",
        evidence: dict[str, Any] | None = None,
        ts: datetime | None = None,
    ) -> dict[str, Any]:
        return self._repo.insert_event(
            domain=domain,
            worker=worker,
            action=action,
            summary=summary,
            target=target,
            result=result,
            evidence=evidence,
            ts=ts,
        )

    def for_day(
        self, day: date | str | None = None, *, limit: int = 500
    ) -> list[dict[str, Any]]:
        if day is None:
            day = datetime.now(_IST).date()
        return self._repo.list_for_day_ist(day, limit=limit)

    def format_day_brief(self, day: date | str | None = None) -> dict[str, Any]:
        if day is None:
            day = datetime.now(_IST).date()
        day_s = day.isoformat() if isinstance(day, date) else str(day)
        rows = self.for_day(day_s, limit=500)
        if not rows:
            return {
                "ok": False,
                "version": VERSION,
                "day_ist": day_s,
                "count": 0,
                "answer": (
                    f"I have no activity_events for {day_s} (IST) yet. "
                    "Either the journal was not bound this process, or no emitters "
                    "have written work events today."
                ),
                "events": [],
            }
        lines = [
            f"Here is my work journal for {day_s} (IST) — "
            "ownership from activity_events, not introspection:",
            "",
        ]
        citations = []
        for r in rows:
            ts = r.get("ts")
            if isinstance(ts, datetime):
                local = (
                    ts.astimezone(_IST)
                    if ts.tzinfo
                    else ts.replace(tzinfo=timezone.utc).astimezone(_IST)
                )
                clock = local.strftime("%H:%M")
            else:
                clock = "??:??"
            result = r.get("result") or "completed"
            tag = "" if result == "completed" else f" [{result}]"
            lines.append(f"{clock}  {r.get('summary')}{tag}")
            citations.append(
                {
                    "type": "activity",
                    "document_id": f"activity:{r.get('id')}",
                    "chunk_id": str(r.get("id") or ""),
                    "snippet": str(r.get("summary") or "")[:200],
                    "similarity": 1.0,
                    "index": len(citations),
                }
            )
        lines.append("")
        lines.append(
            f"{len(rows)} work events. Ask “market intelligence status” for lab KPIs "
            "or “why do you believe …” for worldview."
        )
        return {
            "ok": True,
            "version": VERSION,
            "day_ist": day_s,
            "count": len(rows),
            "answer": "\n".join(lines),
            "events": rows,
            "citations": citations,
        }
