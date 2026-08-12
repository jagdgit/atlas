"""Belief Core repository — ``beliefs.*`` (OI-SELF0 Phase 1)."""

from __future__ import annotations

import threading
import time
import uuid
import re
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from atlas.repositories.base import BaseRepository

BELIEF_DOMAINS = ("market", "engineering", "personal", "cross")
BELIEF_LEVELS = ("concrete", "domain", "abstract")
BELIEF_STATUSES = (
    "candidate",
    "active",
    "weakened",
    "falsified",
    "superseded",
    "dormant",
)
BELIEF_ORIGINS = ("operator", "llm", "mentor", "experience", "research", "imported")
REVISION_ACTIONS = (
    "create",
    "revise",
    "promote",
    "weaken",
    "falsify",
    "supersede",
    "dormant",
    "reactivate",
)
EVIDENCE_KINDS = ("knowledge", "experience", "packet", "url", "note", "operator")
INFLUENCE_STRENGTHS = ("advice",)  # Phase 1 hard lock in DB + app

_BELIEF_COLS = (
    "id, belief_key, domain, level, themes, applies_to, statement, confidence, "
    "status, origin, open_questions, last_evidence_at, last_consulted_at, "
    "last_revised_at, metadata, created_at, updated_at"
)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return list(value)


def _search_tokens(query: str) -> list[str]:
    q = (query or "").strip().lower()
    if not q:
        return []
    tokens = [t for t in re.split(r"[^\w]+", q) if len(t) >= 3]
    return tokens[:6] or [q]


def _belief_relevance_score(row: dict[str, Any], query: str, tokens: list[str]) -> int:
    """Higher = better. Prefer phrase / theme / multi-token hits over single-token.

    Prevents “capital preservation” from ranking a belief that only mentions
    “capital decisions” above the capital-preservation seed.
    """
    phrase = (query or "").strip().lower()
    statement = str(row.get("statement") or "").lower()
    key = str(row.get("belief_key") or "").lower()
    themes = [str(t).lower() for t in (row.get("themes") or [])]
    themes_blob = " ".join(themes)
    blob = f"{statement} {key} {themes_blob}"
    if tokens and not any(t in blob for t in tokens):
        return -1

    score = 0
    phrase_us = phrase.replace(" ", "_")
    if phrase and phrase in statement:
        score += 120
    if phrase_us and (phrase_us in key or any(phrase_us == t or phrase_us in t for t in themes)):
        score += 100
    if phrase and tokens and all(t in statement for t in tokens):
        score += 60
    hits = sum(1 for t in tokens if t in blob)
    score += hits * 12
    if len(tokens) >= 2 and hits >= 2:
        score += 25
    status = str(row.get("status") or "")
    score += {"active": 8, "weakened": 4, "candidate": 1}.get(status, 0)
    score += int(float(row.get("confidence") or 0) * 5)
    return score


def _rank_belief_hits(
    rows: list[dict[str, Any]], query: str, *, limit: int
) -> list[dict[str, Any]]:
    tokens = _search_tokens(query)
    scored: list[tuple[int, dict[str, Any]]] = []
    for r in rows:
        s = _belief_relevance_score(r, query, tokens)
        if s >= 0:
            scored.append((s, r))
    scored.sort(
        key=lambda x: (
            -x[0],
            {"active": 0, "weakened": 1, "candidate": 2}.get(
                str(x[1].get("status")), 9
            ),
            -float(x[1].get("confidence") or 0),
        )
    )
    return [dict(r) for _, r in scored[: max(1, min(int(limit), 50))]]


class BeliefRepository(BaseRepository):
    # --- identity -------------------------------------------------------
    def latest_identity(self) -> dict[str, Any] | None:
        return self.fetch_one(
            """
            SELECT id, version, title, statement, non_negotiables, voice,
                   metadata, created_by, created_at
            FROM beliefs.identity_documents
            ORDER BY version DESC
            LIMIT 1
            """
        )

    def insert_identity(
        self,
        *,
        statement: str,
        title: str = "Atlas Identity",
        non_negotiables: list[Any] | None = None,
        voice: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        created_by: str = "operator",
    ) -> dict[str, Any]:
        cur = self.fetch_val(
            "SELECT COALESCE(MAX(version), 0) FROM beliefs.identity_documents"
        )
        version = int(cur or 0) + 1
        return self.fetch_one(
            """
            INSERT INTO beliefs.identity_documents (
                version, title, statement, non_negotiables, voice, metadata, created_by
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id, version, title, statement, non_negotiables, voice,
                      metadata, created_by, created_at
            """,
            (
                version,
                title,
                statement.strip(),
                Jsonb(non_negotiables or []),
                Jsonb(voice or {}),
                Jsonb(metadata or {}),
                created_by,
            ),
        )

    # --- beliefs --------------------------------------------------------
    def create_belief(
        self,
        *,
        statement: str,
        domain: str,
        level: str = "domain",
        status: str = "candidate",
        origin: str = "llm",
        confidence: float = 0.5,
        themes: list[Any] | None = None,
        applies_to: list[Any] | None = None,
        open_questions: list[Any] | None = None,
        belief_key: str | None = None,
        metadata: dict[str, Any] | None = None,
        last_evidence_at: datetime | None = None,
        actor: str = "system",
        create_revision: bool = True,
    ) -> dict[str, Any]:
        domain = (domain or "").strip().lower()
        level = (level or "domain").strip().lower()
        status = (status or "candidate").strip().lower()
        origin = (origin or "llm").strip().lower()
        if domain not in BELIEF_DOMAINS:
            raise ValueError(f"invalid belief domain: {domain}")
        if level not in BELIEF_LEVELS:
            raise ValueError(f"invalid belief level: {level}")
        if status not in BELIEF_STATUSES:
            raise ValueError(f"invalid belief status: {status}")
        if origin not in BELIEF_ORIGINS:
            raise ValueError(f"invalid belief origin: {origin}")
        conf = max(0.0, min(1.0, float(confidence)))
        evidence_at = last_evidence_at or _utcnow()
        row = self.fetch_one(
            f"""
            INSERT INTO beliefs.beliefs (
                belief_key, domain, level, themes, applies_to, statement,
                confidence, status, origin, open_questions, last_evidence_at,
                last_revised_at, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {_BELIEF_COLS}
            """,
            (
                belief_key,
                domain,
                level,
                Jsonb(themes or []),
                Jsonb(applies_to or []),
                statement.strip(),
                conf,
                status,
                origin,
                Jsonb(open_questions or []),
                evidence_at,
                evidence_at,
                Jsonb(metadata or {}),
            ),
        )
        if create_revision and row:
            self.add_revision(
                row["id"],
                action="create",
                before=None,
                after=row,
                reason="belief created",
                confidence_before=None,
                confidence_after=conf,
                actor=actor,
            )
        return row

    def get_belief(self, belief_id: UUID | str) -> dict[str, Any] | None:
        return self.fetch_one(
            f"SELECT {_BELIEF_COLS} FROM beliefs.beliefs WHERE id = %s",
            (str(belief_id),),
        )

    def get_by_key(self, belief_key: str) -> dict[str, Any] | None:
        return self.fetch_one(
            f"SELECT {_BELIEF_COLS} FROM beliefs.beliefs WHERE belief_key = %s",
            (belief_key,),
        )

    def list_beliefs(
        self,
        *,
        domain: str | None = None,
        status: str | None = None,
        statuses: list[str] | None = None,
        theme: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if domain:
            clauses.append("domain = %s")
            params.append(domain)
        if status:
            clauses.append("status = %s")
            params.append(status)
        if statuses:
            clauses.append("status = ANY(%s)")
            params.append(list(statuses))
        if theme:
            clauses.append("themes @> %s")
            params.append(Jsonb([theme]))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 200)))
        return self.fetch_all(
            f"""
            SELECT {_BELIEF_COLS} FROM beliefs.beliefs
            {where}
            ORDER BY updated_at DESC
            LIMIT %s
            """,
            tuple(params),
        )

    def search_beliefs(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return []
        tokens = _search_tokens(q)
        like_params = [f"%{t}%" for t in tokens]
        # Match if ANY token hits statement/key/themes — rank in Python for phrase fidelity
        token_clause = " OR ".join(
            [
                "(statement ILIKE %s OR coalesce(belief_key, '') ILIKE %s OR themes::text ILIKE %s)"
                for _ in tokens
            ]
        )
        params: list[Any] = []
        for lp in like_params:
            params.extend([lp, lp, lp])
        # Over-fetch then re-rank so multi-token queries don't lose to high-conf single-token hits
        fetch_n = max(20, min(int(limit) * 8, 80))
        params.append(fetch_n)
        rows = self.fetch_all(
            f"""
            SELECT {_BELIEF_COLS} FROM beliefs.beliefs
            WHERE status IN ('active', 'weakened', 'candidate')
              AND ({token_clause})
            LIMIT %s
            """,
            tuple(params),
        )
        return _rank_belief_hits(rows, q, limit=limit)

    def update_belief(
        self,
        belief_id: UUID | str,
        *,
        statement: str | None = None,
        confidence: float | None = None,
        status: str | None = None,
        open_questions: list[Any] | None = None,
        themes: list[Any] | None = None,
        applies_to: list[Any] | None = None,
        metadata: dict[str, Any] | None = None,
        last_evidence_at: datetime | None = None,
        touch_revised: bool = True,
    ) -> dict[str, Any] | None:
        row = self.get_belief(belief_id)
        if row is None:
            return None
        if status is not None:
            status = status.strip().lower()
            if status not in BELIEF_STATUSES:
                raise ValueError(f"invalid belief status: {status}")
        conf = row["confidence"]
        if confidence is not None:
            conf = max(0.0, min(1.0, float(confidence)))
        revised = _utcnow() if touch_revised else row.get("last_revised_at")
        return self.fetch_one(
            f"""
            UPDATE beliefs.beliefs SET
                statement = %s,
                confidence = %s,
                status = %s,
                open_questions = %s,
                themes = %s,
                applies_to = %s,
                metadata = %s,
                last_evidence_at = COALESCE(%s, last_evidence_at),
                last_revised_at = %s,
                updated_at = now()
            WHERE id = %s
            RETURNING {_BELIEF_COLS}
            """,
            (
                statement if statement is not None else row["statement"],
                conf,
                status if status is not None else row["status"],
                Jsonb(
                    open_questions
                    if open_questions is not None
                    else _as_list(row.get("open_questions"))
                ),
                Jsonb(themes if themes is not None else _as_list(row.get("themes"))),
                Jsonb(
                    applies_to
                    if applies_to is not None
                    else _as_list(row.get("applies_to"))
                ),
                Jsonb(metadata if metadata is not None else (row.get("metadata") or {})),
                last_evidence_at,
                revised,
                str(belief_id),
            ),
        )

    def touch_consulted(self, belief_id: UUID | str) -> None:
        self.execute(
            """
            UPDATE beliefs.beliefs
            SET last_consulted_at = now(), updated_at = updated_at
            WHERE id = %s
            """,
            (str(belief_id),),
        )

    # --- revisions / evidence / contradictions / influence -------------
    def next_revision_no(self, belief_id: UUID | str) -> int:
        n = self.fetch_val(
            "SELECT COALESCE(MAX(revision_no), 0) FROM beliefs.revisions WHERE belief_id = %s",
            (str(belief_id),),
        )
        return int(n or 0) + 1

    def add_revision(
        self,
        belief_id: UUID | str,
        *,
        action: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        reason: str = "",
        evidence_summary: str = "",
        confidence_before: float | None = None,
        confidence_after: float | None = None,
        actor: str = "system",
    ) -> dict[str, Any]:
        action = (action or "").strip().lower()
        if action not in REVISION_ACTIONS:
            raise ValueError(f"invalid revision action: {action}")
        rev_no = self.next_revision_no(belief_id)
        return self.fetch_one(
            """
            INSERT INTO beliefs.revisions (
                belief_id, revision_no, action, before_snapshot, after_snapshot,
                reason, evidence_summary, confidence_before, confidence_after, actor
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, belief_id, revision_no, action, before_snapshot,
                      after_snapshot, reason, evidence_summary,
                      confidence_before, confidence_after, actor, created_at
            """,
            (
                str(belief_id),
                rev_no,
                action,
                Jsonb(_json_safe(before)) if before is not None else None,
                Jsonb(_json_safe(after)) if after is not None else None,
                reason or "",
                evidence_summary or "",
                confidence_before,
                confidence_after,
                actor,
            ),
        )

    def list_revisions(
        self, belief_id: UUID | str, *, limit: int = 20
    ) -> list[dict[str, Any]]:
        return self.fetch_all(
            """
            SELECT id, belief_id, revision_no, action, before_snapshot,
                   after_snapshot, reason, evidence_summary,
                   confidence_before, confidence_after, actor, created_at
            FROM beliefs.revisions
            WHERE belief_id = %s
            ORDER BY revision_no DESC
            LIMIT %s
            """,
            (str(belief_id), max(1, min(int(limit), 100))),
        )

    def add_evidence(
        self,
        belief_id: UUID | str,
        *,
        kind: str = "note",
        summary: str = "",
        ref_id: str | None = None,
        weight: float = 1.0,
        metadata: dict[str, Any] | None = None,
        touch_evidence: bool = True,
    ) -> dict[str, Any]:
        kind = (kind or "note").strip().lower()
        if kind not in EVIDENCE_KINDS:
            raise ValueError(f"invalid evidence kind: {kind}")
        row = self.fetch_one(
            """
            INSERT INTO beliefs.evidence_links (
                belief_id, kind, ref_id, summary, weight, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, belief_id, kind, ref_id, summary, weight, metadata, created_at
            """,
            (
                str(belief_id),
                kind,
                ref_id,
                summary or "",
                max(0.0, float(weight)),
                Jsonb(metadata or {}),
            ),
        )
        if touch_evidence:
            self.execute(
                """
                UPDATE beliefs.beliefs
                SET last_evidence_at = now(), updated_at = now()
                WHERE id = %s
                """,
                (str(belief_id),),
            )
        return row

    def list_evidence(
        self, belief_id: UUID | str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        return self.fetch_all(
            """
            SELECT id, belief_id, kind, ref_id, summary, weight, metadata, created_at
            FROM beliefs.evidence_links
            WHERE belief_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (str(belief_id), max(1, min(int(limit), 100))),
        )

    def add_contradiction(
        self,
        belief_id: UUID | str,
        *,
        summary: str,
        contrary_belief_id: UUID | str | None = None,
        status: str = "open",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.fetch_one(
            """
            INSERT INTO beliefs.contradictions (
                belief_id, contrary_belief_id, summary, status, metadata
            )
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, belief_id, contrary_belief_id, summary, status,
                      metadata, created_at, resolved_at
            """,
            (
                str(belief_id),
                str(contrary_belief_id) if contrary_belief_id else None,
                summary.strip(),
                status,
                Jsonb(metadata or {}),
            ),
        )

    def list_contradictions(
        self, belief_id: UUID | str, *, limit: int = 20
    ) -> list[dict[str, Any]]:
        return self.fetch_all(
            """
            SELECT id, belief_id, contrary_belief_id, summary, status,
                   metadata, created_at, resolved_at
            FROM beliefs.contradictions
            WHERE belief_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (str(belief_id), max(1, min(int(limit), 50))),
        )

    def add_influence(
        self,
        belief_id: UUID | str,
        *,
        target: str,
        strength: str = "advice",
        note: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        strength = (strength or "advice").strip().lower()
        if strength not in INFLUENCE_STRENGTHS:
            raise ValueError(
                f"Phase 1 influence must be advice-only; got strength={strength!r}"
            )
        return self.fetch_one(
            """
            INSERT INTO beliefs.influence (
                belief_id, target, strength, note, metadata
            )
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, belief_id, target, strength, note, active, metadata, created_at
            """,
            (
                str(belief_id),
                (target or "general").strip(),
                strength,
                note or "",
                Jsonb(metadata or {}),
            ),
        )

    def list_influence(
        self, belief_id: UUID | str, *, limit: int = 20
    ) -> list[dict[str, Any]]:
        return self.fetch_all(
            """
            SELECT id, belief_id, target, strength, note, active, metadata, created_at
            FROM beliefs.influence
            WHERE belief_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (str(belief_id), max(1, min(int(limit), 50))),
        )

    # --- consultations --------------------------------------------------
    def record_consultation(
        self,
        *,
        domain: str,
        purpose: str = "consult",
        belief_id: UUID | str | None = None,
        day_ist: date | None = None,
    ) -> dict[str, Any]:
        domain = (domain or "cross").strip().lower()
        if domain not in BELIEF_DOMAINS:
            domain = "cross"
        day = day_ist or date.today()
        return self.fetch_one(
            """
            INSERT INTO beliefs.consultations (belief_id, domain, purpose, day_ist)
            VALUES (%s, %s, %s, %s)
            RETURNING id, belief_id, domain, purpose, day_ist, created_at
            """,
            (
                str(belief_id) if belief_id else None,
                domain,
                purpose or "consult",
                day,
            ),
        )

    def consultation_counts(
        self, *, day_ist: date | None = None
    ) -> dict[str, Any]:
        day = day_ist or date.today()
        rows = self.fetch_all(
            """
            SELECT domain, COUNT(*)::int AS n
            FROM beliefs.consultations
            WHERE day_ist = %s
            GROUP BY domain
            """,
            (day,),
        )
        by_domain = {d: 0 for d in BELIEF_DOMAINS}
        total = 0
        for r in rows:
            d = str(r.get("domain") or "cross")
            n = int(r.get("n") or 0)
            by_domain[d] = by_domain.get(d, 0) + n
            total += n
        return {"day_ist": str(day), "total": total, "by_domain": by_domain}

    def revision_counts(self, *, days: int = 7) -> dict[str, Any]:
        rows = self.fetch_all(
            """
            SELECT action, COUNT(*)::int AS n
            FROM beliefs.revisions
            WHERE created_at >= now() - (%s || ' days')::interval
              AND action IN ('revise', 'promote', 'weaken', 'falsify', 'supersede')
            GROUP BY action
            """,
            (max(1, int(days)),),
        )
        by_action = {r["action"]: int(r["n"]) for r in rows}
        return {
            "days": int(days),
            "material_total": sum(by_action.values()),
            "by_action": by_action,
        }


class InMemoryBeliefRepository:
    """Hermetic stand-in for unit tests (same surface as BeliefRepository)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._identity: list[dict[str, Any]] = []
        self._beliefs: dict[str, dict[str, Any]] = {}
        self._revisions: list[dict[str, Any]] = []
        self._evidence: list[dict[str, Any]] = []
        self._contradictions: list[dict[str, Any]] = []
        self._influence: list[dict[str, Any]] = []
        self._consultations: list[dict[str, Any]] = []

    def latest_identity(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._identity[-1]) if self._identity else None

    def insert_identity(
        self,
        *,
        statement: str,
        title: str = "Atlas Identity",
        non_negotiables=None,
        voice=None,
        metadata=None,
        created_by: str = "operator",
    ) -> dict[str, Any]:
        with self._lock:
            version = (self._identity[-1]["version"] if self._identity else 0) + 1
            row = {
                "id": str(uuid.uuid4()),
                "version": version,
                "title": title,
                "statement": statement.strip(),
                "non_negotiables": list(non_negotiables or []),
                "voice": dict(voice or {}),
                "metadata": dict(metadata or {}),
                "created_by": created_by,
                "created_at": _utcnow(),
            }
            self._identity.append(row)
            return dict(row)

    def create_belief(
        self,
        *,
        statement: str,
        domain: str,
        level: str = "domain",
        status: str = "candidate",
        origin: str = "llm",
        confidence: float = 0.5,
        themes=None,
        applies_to=None,
        open_questions=None,
        belief_key: str | None = None,
        metadata=None,
        last_evidence_at=None,
        actor: str = "system",
        create_revision: bool = True,
    ) -> dict[str, Any]:
        domain = domain.strip().lower()
        if domain not in BELIEF_DOMAINS:
            raise ValueError(f"invalid belief domain: {domain}")
        if status not in BELIEF_STATUSES:
            raise ValueError(f"invalid belief status: {status}")
        bid = str(uuid.uuid4())
        now = last_evidence_at or _utcnow()
        row = {
            "id": bid,
            "belief_key": belief_key,
            "domain": domain,
            "level": (level or "domain").lower(),
            "themes": list(themes or []),
            "applies_to": list(applies_to or []),
            "statement": statement.strip(),
            "confidence": max(0.0, min(1.0, float(confidence))),
            "status": status,
            "origin": origin,
            "open_questions": list(open_questions or []),
            "last_evidence_at": now,
            "last_consulted_at": None,
            "last_revised_at": now,
            "metadata": dict(metadata or {}),
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            if belief_key and any(
                b.get("belief_key") == belief_key for b in self._beliefs.values()
            ):
                existing = next(
                    b for b in self._beliefs.values() if b.get("belief_key") == belief_key
                )
                return dict(existing)
            self._beliefs[bid] = row
        if create_revision:
            self.add_revision(
                bid,
                action="create",
                before=None,
                after=row,
                reason="belief created",
                confidence_after=row["confidence"],
                actor=actor,
            )
        return dict(row)

    def get_belief(self, belief_id) -> dict[str, Any] | None:
        with self._lock:
            row = self._beliefs.get(str(belief_id))
            return dict(row) if row else None

    def get_by_key(self, belief_key: str) -> dict[str, Any] | None:
        with self._lock:
            for row in self._beliefs.values():
                if row.get("belief_key") == belief_key:
                    return dict(row)
        return None

    def list_beliefs(
        self, *, domain=None, status=None, statuses=None, theme=None, limit=50
    ):
        with self._lock:
            rows = list(self._beliefs.values())
        if domain:
            rows = [r for r in rows if r["domain"] == domain]
        if status:
            rows = [r for r in rows if r["status"] == status]
        if statuses:
            rows = [r for r in rows if r["status"] in statuses]
        if theme:
            rows = [r for r in rows if theme in (r.get("themes") or [])]
        rows.sort(key=lambda r: r.get("updated_at") or _utcnow(), reverse=True)
        return [dict(r) for r in rows[: max(1, min(int(limit), 200))]]

    def search_beliefs(self, query: str, *, limit: int = 20):
        q = (query or "").strip()
        if not q:
            return []
        tokens = _search_tokens(q)
        with self._lock:
            rows = []
            for r in self._beliefs.values():
                if r["status"] not in {"active", "weakened", "candidate"}:
                    continue
                blob = (
                    f"{r['statement']} {r.get('belief_key') or ''} "
                    f"{r.get('themes') or ''}"
                ).lower()
                if any(t in blob for t in tokens):
                    rows.append(r)
        return _rank_belief_hits(rows, q, limit=limit)

    def update_belief(self, belief_id, **kwargs):
        with self._lock:
            row = self._beliefs.get(str(belief_id))
            if not row:
                return None
            before = dict(row)
            if kwargs.get("statement") is not None:
                row["statement"] = kwargs["statement"]
            if kwargs.get("confidence") is not None:
                row["confidence"] = max(0.0, min(1.0, float(kwargs["confidence"])))
            if kwargs.get("status") is not None:
                st = kwargs["status"].strip().lower()
                if st not in BELIEF_STATUSES:
                    raise ValueError(f"invalid belief status: {st}")
                row["status"] = st
            for key in ("open_questions", "themes", "applies_to", "metadata"):
                if kwargs.get(key) is not None:
                    row[key] = kwargs[key]
            if kwargs.get("last_evidence_at") is not None:
                row["last_evidence_at"] = kwargs["last_evidence_at"]
            if kwargs.get("touch_revised", True):
                row["last_revised_at"] = _utcnow()
            row["updated_at"] = _utcnow()
            self._beliefs[str(belief_id)] = row
            return dict(row)

    def touch_consulted(self, belief_id):
        with self._lock:
            row = self._beliefs.get(str(belief_id))
            if row:
                row["last_consulted_at"] = _utcnow()

    def next_revision_no(self, belief_id):
        with self._lock:
            n = max(
                (
                    int(r["revision_no"])
                    for r in self._revisions
                    if str(r["belief_id"]) == str(belief_id)
                ),
                default=0,
            )
        return n + 1

    def add_revision(self, belief_id, *, action, before, after, reason="",
                     evidence_summary="", confidence_before=None,
                     confidence_after=None, actor="system"):
        action = action.strip().lower()
        if action not in REVISION_ACTIONS:
            raise ValueError(f"invalid revision action: {action}")
        rev = {
            "id": str(uuid.uuid4()),
            "belief_id": str(belief_id),
            "revision_no": self.next_revision_no(belief_id),
            "action": action,
            "before_snapshot": before,
            "after_snapshot": after,
            "reason": reason or "",
            "evidence_summary": evidence_summary or "",
            "confidence_before": confidence_before,
            "confidence_after": confidence_after,
            "actor": actor,
            "created_at": _utcnow(),
        }
        with self._lock:
            self._revisions.append(rev)
        return dict(rev)

    def list_revisions(self, belief_id, *, limit=20):
        with self._lock:
            rows = [
                r for r in self._revisions if str(r["belief_id"]) == str(belief_id)
            ]
        rows.sort(key=lambda r: r["revision_no"], reverse=True)
        return [dict(r) for r in rows[: max(1, min(int(limit), 100))]]

    def add_evidence(self, belief_id, *, kind="note", summary="", ref_id=None,
                     weight=1.0, metadata=None, touch_evidence=True):
        kind = (kind or "note").lower()
        if kind not in EVIDENCE_KINDS:
            raise ValueError(f"invalid evidence kind: {kind}")
        row = {
            "id": str(uuid.uuid4()),
            "belief_id": str(belief_id),
            "kind": kind,
            "ref_id": ref_id,
            "summary": summary or "",
            "weight": max(0.0, float(weight)),
            "metadata": dict(metadata or {}),
            "created_at": _utcnow(),
        }
        with self._lock:
            self._evidence.append(row)
            if touch_evidence and str(belief_id) in self._beliefs:
                self._beliefs[str(belief_id)]["last_evidence_at"] = _utcnow()
                self._beliefs[str(belief_id)]["updated_at"] = _utcnow()
        return dict(row)

    def list_evidence(self, belief_id, *, limit=50):
        with self._lock:
            rows = [
                r for r in self._evidence if str(r["belief_id"]) == str(belief_id)
            ]
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        return [dict(r) for r in rows[:limit]]

    def add_contradiction(self, belief_id, *, summary, contrary_belief_id=None,
                          status="open", metadata=None):
        row = {
            "id": str(uuid.uuid4()),
            "belief_id": str(belief_id),
            "contrary_belief_id": (
                str(contrary_belief_id) if contrary_belief_id else None
            ),
            "summary": summary.strip(),
            "status": status,
            "metadata": dict(metadata or {}),
            "created_at": _utcnow(),
            "resolved_at": None,
        }
        with self._lock:
            self._contradictions.append(row)
        return dict(row)

    def list_contradictions(self, belief_id, *, limit=20):
        with self._lock:
            rows = [
                r
                for r in self._contradictions
                if str(r["belief_id"]) == str(belief_id)
            ]
        return [dict(r) for r in rows[:limit]]

    def add_influence(self, belief_id, *, target, strength="advice", note="",
                      metadata=None):
        strength = (strength or "advice").lower()
        if strength not in INFLUENCE_STRENGTHS:
            raise ValueError(
                f"Phase 1 influence must be advice-only; got strength={strength!r}"
            )
        row = {
            "id": str(uuid.uuid4()),
            "belief_id": str(belief_id),
            "target": target or "general",
            "strength": strength,
            "note": note or "",
            "active": True,
            "metadata": dict(metadata or {}),
            "created_at": _utcnow(),
        }
        with self._lock:
            self._influence.append(row)
        return dict(row)

    def list_influence(self, belief_id, *, limit=20):
        with self._lock:
            rows = [
                r for r in self._influence if str(r["belief_id"]) == str(belief_id)
            ]
        return [dict(r) for r in rows[:limit]]

    def record_consultation(self, *, domain, purpose="consult", belief_id=None,
                            day_ist=None):
        domain = (domain or "cross").lower()
        if domain not in BELIEF_DOMAINS:
            domain = "cross"
        row = {
            "id": str(uuid.uuid4()),
            "belief_id": str(belief_id) if belief_id else None,
            "domain": domain,
            "purpose": purpose or "consult",
            "day_ist": day_ist or date.today(),
            "created_at": _utcnow(),
        }
        with self._lock:
            self._consultations.append(row)
        return dict(row)

    def consultation_counts(self, *, day_ist=None):
        day = day_ist or date.today()
        by_domain = {d: 0 for d in BELIEF_DOMAINS}
        total = 0
        with self._lock:
            for c in self._consultations:
                d = c.get("day_ist")
                if d != day and str(d) != str(day):
                    continue
                dom = c.get("domain") or "cross"
                by_domain[dom] = by_domain.get(dom, 0) + 1
                total += 1
        return {"day_ist": str(day), "total": total, "by_domain": by_domain}

    def revision_counts(self, *, days: int = 7):
        cutoff = time.time() - max(1, int(days)) * 86400
        by_action: dict[str, int] = {}
        material = {
            "revise",
            "promote",
            "weaken",
            "falsify",
            "supersede",
        }
        with self._lock:
            for r in self._revisions:
                if r["action"] not in material:
                    continue
                created = r.get("created_at")
                ts = created.timestamp() if hasattr(created, "timestamp") else cutoff
                if ts < cutoff:
                    continue
                by_action[r["action"]] = by_action.get(r["action"], 0) + 1
        return {
            "days": int(days),
            "material_total": sum(by_action.values()),
            "by_action": by_action,
        }
