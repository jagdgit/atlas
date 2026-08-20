"""Observation Layer (DI.Obs) — continuous low-interpretation facts.

Research interprets later; Decision Packets cite ``observation_ids``.
Each record appends to Market Timeline (kind=observation) when a timeline
store is bound.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from atlas.repositories.decision_observation_repo import OBSERVATION_KINDS

_log = logging.getLogger("atlas.investment.observations")

OBS_VERSION = "di.obs.2"
STORE_REL = Path("investment") / "decisions" / "observations"
_IST = ZoneInfo("Asia/Kolkata")

CONFIDENCE_LEVELS = frozenset({"high", "medium", "low", "estimated", "unknown"})

# LQ.3 / §8.1 — provisional topic tags (keyword hints; never invent facts)
NEWS_TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "earnings": ("earnings", "results", "quarterly", " q1", " q2", " q3", " q4", "profit"),
    "regulation": ("sebi", "rbi", "regulation", "regulatory", "approval", "ban "),
    "management": ("ceo", "cfo", "md ", "resignation", "appointed", "guidance"),
    "order": ("order win", "order book", "contract", "bagged order", "won order"),
    "lawsuit": ("lawsuit", "litigation", "court case", "probe"),
    "capex": ("capex", "capacity expansion", "new plant"),
    "sector": ("sector", "industry outlook"),
    "macro": ("inflation", "gdp", "rate hike", "budget", "fed ", "crude"),
}


def infer_news_topic_tags(text: str) -> list[str]:
    """Provisional topic tags from headline text — honest keyword hints only."""
    low = f" {(text or '').lower()} "
    tags: list[str] = []
    for tag, keys in NEWS_TOPIC_KEYWORDS.items():
        if any(k in low for k in keys):
            tags.append(tag)
    return tags[:8]


def normalize_news_sentiment(raw: Any) -> str:
    s = str(raw or "").strip().lower()
    if s in {"positive", "negative", "neutral", "mixed", "unknown"}:
        return s
    return "unknown"


def ist_now_iso() -> str:
    return datetime.now(_IST).isoformat()


def mirror_root(data_dir: str | Path) -> Path:
    return Path(data_dir) / STORE_REL


def _mirror(data_dir: str | Path | None, row: dict[str, Any]) -> str | None:
    if not data_dir:
        return None
    try:
        root = mirror_root(data_dir)
        by_id = root / "by_id" / f"{row['id']}.json"
        by_id.parent.mkdir(parents=True, exist_ok=True)
        by_id.write_text(json.dumps(row, indent=2, default=str), encoding="utf-8")
        sym = str(row.get("symbol") or "_macro").replace("/", "_")
        day = datetime.now(_IST).strftime("%Y-%m-%d")
        day_path = root / "by_day" / day / f"{sym}.jsonl"
        day_path.parent.mkdir(parents=True, exist_ok=True)
        with day_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
        # LQ.3 — dedicated per-symbol news timeline jsonl
        if row.get("kind") == "news_event" and row.get("symbol"):
            news_path = root / "news" / f"{sym}.jsonl"
            news_path.parent.mkdir(parents=True, exist_ok=True)
            with news_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, default=str) + "\n")
        return str(by_id)
    except Exception:  # noqa: BLE001
        _log.warning("observation mirror failed", exc_info=True)
        return None


def _load_news_jsonl(
    data_dir: str | Path, symbol: str, *, limit: int = 40
) -> list[dict[str, Any]]:
    path = mirror_root(data_dir) / "news" / f"{str(symbol).replace('/', '_')}.jsonl"
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        for line in reversed(path.read_text(encoding="utf-8").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(doc, dict):
                out.append(doc)
            if len(out) >= limit:
                break
    except Exception:  # noqa: BLE001
        return []
    return out


def _row_from_db(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(r["id"]),
        "created_at": r.get("created_at").isoformat()
        if hasattr(r.get("created_at"), "isoformat")
        else r.get("created_at"),
        "symbol": r.get("symbol"),
        "kind": r.get("kind"),
        "payload": r.get("payload") or {},
        "source": r.get("source"),
        "confidence": r.get("confidence"),
        "expires_at": r.get("expires_at").isoformat()
        if hasattr(r.get("expires_at"), "isoformat")
        else r.get("expires_at"),
        "payload_version": r.get("payload_version") or OBS_VERSION,
    }


def _load_symbol_json(
    data_dir: str | Path, symbol: str, *, limit: int = 40
) -> list[dict[str, Any]]:
    root = mirror_root(data_dir) / "by_id"
    if not root.is_dir():
        return []
    found: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(doc, dict):
            continue
        if doc.get("symbol") != symbol:
            continue
        found.append(doc)
        if len(found) >= limit:
            break
    return found


class DecisionObservationStore:
    """Hybrid observation store (Postgres + JSON) with timeline fan-out."""

    def __init__(
        self,
        *,
        data_dir: str | Path | None = None,
        repo: Any | None = None,
        timeline: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._data_dir = str(data_dir) if data_dir else None
        self._repo = repo
        self._timeline = timeline
        self._logger = logger or _log
        self._mem: list[dict[str, Any]] = []

    @property
    def data_dir(self) -> str | None:
        return self._data_dir

    def bind_timeline(self, timeline: Any) -> None:
        self._timeline = timeline

    def record(
        self,
        *,
        kind: str,
        payload: dict[str, Any] | None = None,
        symbol: str | None = None,
        source: str | None = None,
        confidence: str = "estimated",
        expires_at: datetime | str | None = None,
        ttl_hours: float | None = None,
        observation_id: str | None = None,
        link_decision_id: str | None = None,
    ) -> dict[str, Any]:
        k = str(kind or "").strip()
        if k not in OBSERVATION_KINDS:
            raise ValueError(f"invalid observation kind {kind!r}; expected one of {sorted(OBSERVATION_KINDS)}")
        conf = str(confidence or "estimated").lower()
        if conf not in CONFIDENCE_LEVELS:
            conf = "estimated"
        exp = expires_at
        if exp is None and ttl_hours is not None:
            exp = datetime.now(timezone.utc) + timedelta(hours=float(ttl_hours))
        if isinstance(exp, datetime):
            exp_out: str | None = exp.isoformat()
        else:
            exp_out = str(exp) if exp else None
        row = {
            "id": str(observation_id or uuid4()),
            "created_at": ist_now_iso(),
            "symbol": str(symbol).strip() if symbol else None,
            "kind": k,
            "payload": dict(payload or {}),
            "source": source,
            "confidence": conf,
            "expires_at": exp_out,
            "payload_version": OBS_VERSION,
        }
        stored = None
        if self._repo is not None:
            try:
                db_row = dict(row)
                if exp_out:
                    try:
                        db_row["expires_at"] = datetime.fromisoformat(
                            exp_out.replace("Z", "+00:00")
                        )
                    except ValueError:
                        db_row["expires_at"] = None
                else:
                    db_row["expires_at"] = None
                stored = self._repo.insert(db_row)
            except Exception:  # noqa: BLE001
                self._logger.warning("observation postgres insert failed", exc_info=True)
        else:
            self._mem.append(row)
        mirror = _mirror(self._data_dir, row)
        # Fan-out to Market Timeline
        if self._timeline is not None and row.get("symbol"):
            try:
                self._timeline.append_event(
                    symbol=str(row["symbol"]),
                    kind="observation",
                    decision_id=link_decision_id,
                    payload={
                        "observation_id": row["id"],
                        "observation_kind": k,
                        "source": source,
                        "confidence": conf,
                        "summary": _summarize_payload(k, row.get("payload") or {}),
                        "body": row.get("payload") or {},
                    },
                )
            except Exception:  # noqa: BLE001
                self._logger.debug("observation→timeline fan-out failed", exc_info=True)
        elif self._timeline is not None and not row.get("symbol"):
            # Macro / policy without symbol: use index placeholder stream
            try:
                self._timeline.append_event(
                    symbol="__MACRO__",
                    kind="observation",
                    decision_id=link_decision_id,
                    payload={
                        "observation_id": row["id"],
                        "observation_kind": k,
                        "source": source,
                        "confidence": conf,
                        "summary": _summarize_payload(k, row.get("payload") or {}),
                        "body": row.get("payload") or {},
                    },
                )
            except Exception:  # noqa: BLE001
                self._logger.debug("macro observation→timeline failed", exc_info=True)
        return {
            "observation": row,
            "row": _row_from_db(stored) if stored else None,
            "mirror_path": mirror,
            "version": OBS_VERSION,
        }

    def get(self, observation_id: str) -> dict[str, Any] | None:
        if self._repo is not None:
            try:
                r = self._repo.get(observation_id)
                if r:
                    return _row_from_db(r)
            except Exception:  # noqa: BLE001
                self._logger.debug("observation get failed", exc_info=True)
        if self._data_dir:
            path = mirror_root(self._data_dir) / "by_id" / f"{observation_id}.json"
            if path.is_file():
                try:
                    doc = json.loads(path.read_text(encoding="utf-8"))
                    return doc if isinstance(doc, dict) else None
                except Exception:  # noqa: BLE001
                    return None
        for r in self._mem:
            if r.get("id") == observation_id:
                return dict(r)
        return None

    def list_symbol(
        self,
        *,
        symbol: str,
        limit: int = 40,
        kind: str | None = None,
        since_hours: float | None = None,
    ) -> list[dict[str, Any]]:
        since = None
        if since_hours is not None:
            since = datetime.now(timezone.utc) - timedelta(hours=float(since_hours))
        if self._repo is not None:
            try:
                rows = self._repo.list_symbol(
                    symbol=symbol, limit=limit, kind=kind, since=since
                )
                if rows:
                    return [_row_from_db(r) for r in rows]
            except Exception:  # noqa: BLE001
                self._logger.debug("list_symbol obs failed", exc_info=True)
        items = list(self._mem)
        if self._data_dir:
            items.extend(_load_symbol_json(self._data_dir, symbol, limit=limit * 2))
        out = []
        for r in items:
            if r.get("symbol") != symbol:
                continue
            if kind and r.get("kind") != kind:
                continue
            if since is not None:
                try:
                    created = datetime.fromisoformat(
                        str(r.get("created_at")).replace("Z", "+00:00")
                    )
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    if created < since:
                        continue
                except Exception:  # noqa: BLE001
                    pass
            out.append(r)
        # dedupe by id
        seen: set[str] = set()
        uniq: list[dict[str, Any]] = []
        for r in out:
            oid = str(r.get("id") or "")
            if oid in seen:
                continue
            seen.add(oid)
            uniq.append(r)
        uniq.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
        return uniq[:limit]

    def list_since(
        self,
        *,
        since_hours: float = 24.0,
        limit: int = 100,
        symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        since = datetime.now(timezone.utc) - timedelta(hours=float(since_hours))
        if symbol:
            return self.list_symbol(symbol=symbol, limit=limit, since_hours=since_hours)
        if self._repo is not None:
            try:
                rows = self._repo.list_since(since=since, limit=limit)
                if rows:
                    return [_row_from_db(r) for r in rows]
            except Exception:  # noqa: BLE001
                self._logger.debug("list_since obs failed", exc_info=True)
        items = list(self._mem)
        if self._data_dir:
            root = mirror_root(self._data_dir) / "by_id"
            if root.is_dir():
                for path in sorted(
                    root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
                )[: limit * 2]:
                    try:
                        doc = json.loads(path.read_text(encoding="utf-8"))
                    except Exception:  # noqa: BLE001
                        continue
                    if isinstance(doc, dict):
                        items.append(doc)
        out = []
        for r in items:
            try:
                created = datetime.fromisoformat(
                    str(r.get("created_at")).replace("Z", "+00:00")
                )
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if created < since:
                    continue
            except Exception:  # noqa: BLE001
                continue
            out.append(r)
        seen: set[str] = set()
        uniq = []
        for r in out:
            oid = str(r.get("id") or "")
            if oid in seen:
                continue
            seen.add(oid)
            uniq.append(r)
        uniq.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
        return uniq[:limit]

    def ids_for_symbol(self, symbol: str, *, limit: int = 8, since_hours: float = 72.0) -> list[str]:
        """Recent observation ids for Decision Packet citation."""
        rows = self.list_symbol(symbol=symbol, limit=limit, since_hours=since_hours)
        return [str(r["id"]) for r in rows if r.get("id")]

    # --- source helpers -------------------------------------------------
    def record_market_event(
        self,
        *,
        symbol: str,
        event: dict[str, Any],
        source: str = "market_observer",
    ) -> dict[str, Any]:
        return self.record(
            kind="market_event",
            symbol=symbol,
            source=source,
            confidence="estimated",
            ttl_hours=72.0,
            payload={
                "pct_move": event.get("pct_move"),
                "score": event.get("score"),
                "kind": event.get("kind"),
                "volume_ratio": event.get("volume_ratio"),
                "provider": event.get("provider"),
                "reason": event.get("reason") or event.get("why"),
            },
        )

    def record_mark_snapshot(
        self,
        *,
        symbol: str,
        pct_move: float | None = None,
        provider: str | None = None,
        bar_count: int | None = None,
        source: str = "market_observer",
        density: str = "mark_snapshot",
    ) -> dict[str, Any]:
        """LI.3a — low-noise session mark so quiet books still get observations."""
        return self.record(
            kind="market_event",
            symbol=symbol,
            source=source,
            confidence="estimated",
            ttl_hours=24.0,
            payload={
                "pct_move": pct_move,
                "score": 0.15,
                "kind": density,
                "provider": provider,
                "bar_count": bar_count,
                "reason": "session_mark_snapshot",
            },
        )

    def record_news_event(
        self,
        *,
        text: str,
        symbol: str | None = None,
        source: str = "news_intelligence",
        extra: dict[str, Any] | None = None,
        topic_tags: list[str] | None = None,
        sentiment: str | None = None,
        link: str | None = None,
        observed_before_move: bool | None = None,
        link_decision_id: str | None = None,
        open_book: bool = False,
    ) -> dict[str, Any]:
        """LQ.3 — news_event with §8.1 fields; mirrors to news/{SYM}.jsonl."""
        extra = dict(extra or {})
        from atlas.investment.market_events import stamp_market_event

        stamped = stamp_market_event(
            {
                **extra,
                "text": (text or "")[:500],
                "source": source,
                "link": link or extra.get("link"),
                "kind": extra.get("kind") or "news_event",
                "published": extra.get("published") or extra.get("published_at"),
                "seed": extra.get("seed"),
                "evidence_class": extra.get("evidence_class"),
                "feed_id": extra.get("feed_id"),
            }
        )
        for k in (
            "observed_at",
            "published_at",
            "valid_from",
            "valid_until",
            "retrieved_at",
            "source_tier",
            "evidence_class",
            "event_class",
        ):
            extra.setdefault(k, stamped.get(k))
        tags = list(topic_tags) if topic_tags else infer_news_topic_tags(text)
        if extra.get("topic_tags") and not topic_tags:
            tags = list(extra.get("topic_tags") or [])[:8]
        sent = normalize_news_sentiment(
            sentiment if sentiment is not None else extra.get("sentiment")
        )
        body = {
            "text": (text or "")[:500],
            "topic_tags": tags[:8],
            "sentiment": sent,
            "observed_before_move": observed_before_move
            if observed_before_move is not None
            else extra.get("observed_before_move"),
            "open_book": bool(open_book or extra.get("open_book")),
            **{k: v for k, v in extra.items() if k not in {"topic_tags", "sentiment", "observed_before_move", "open_book"}},
        }
        if link or extra.get("link"):
            body["link"] = str(link or extra.get("link"))[:500]
        if link_decision_id or extra.get("decision_id"):
            body["decision_id"] = str(link_decision_id or extra.get("decision_id"))
        return self.record(
            kind="news_event",
            symbol=symbol,
            source=source,
            confidence="estimated",
            ttl_hours=168.0,
            payload=body,
            link_decision_id=link_decision_id or body.get("decision_id"),
        )

    def list_news_for_symbol(
        self,
        *,
        symbol: str,
        limit: int = 40,
        since_hours: float | None = None,
        open_book_only: bool = False,
    ) -> list[dict[str, Any]]:
        """LQ.3 — per-symbol news timeline (dedicated jsonl, else filtered obs)."""
        sym = str(symbol or "").strip()
        if not sym:
            return []
        items: list[dict[str, Any]] = []
        if self._data_dir:
            items.extend(_load_news_jsonl(self._data_dir, sym, limit=limit * 2))
        if not items:
            items = self.list_symbol(
                symbol=sym, limit=limit * 2, kind="news_event", since_hours=since_hours
            )
        else:
            # Merge in-memory / repo rows not yet on disk
            items.extend(
                self.list_symbol(
                    symbol=sym, limit=limit, kind="news_event", since_hours=since_hours
                )
            )
        # Dedupe by id, newest first
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for r in sorted(
            items,
            key=lambda x: str(x.get("created_at") or ""),
            reverse=True,
        ):
            oid = str(r.get("id") or "")
            if oid and oid in seen:
                continue
            if oid:
                seen.add(oid)
            if open_book_only and not (r.get("payload") or {}).get("open_book"):
                continue
            if since_hours is not None and r.get("created_at"):
                try:
                    created = r["created_at"]
                    if isinstance(created, str):
                        created = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    cutoff = datetime.now(timezone.utc) - timedelta(hours=float(since_hours))
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    if created < cutoff:
                        continue
                except Exception:  # noqa: BLE001
                    pass
            out.append(r)
            if len(out) >= limit:
                break
        return out

    def record_policy_event(
        self,
        *,
        title: str,
        sectors: list[str] | None = None,
        source: str = "government_intelligence",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        extra = dict(extra or {})
        from atlas.investment.market_events import stamp_market_event

        stamped = stamp_market_event(
            {
                **extra,
                "title": (title or "")[:300],
                "source": source,
                "kind": extra.get("kind") or "policy_event",
                "published": extra.get("published") or extra.get("published_at"),
                "feed_id": extra.get("feed_id"),
                "link": extra.get("link"),
                "catalog_summary": extra.get("catalog_summary"),
            }
        )
        for k in (
            "observed_at",
            "published_at",
            "valid_from",
            "valid_until",
            "retrieved_at",
            "source_tier",
            "evidence_class",
            "event_class",
        ):
            extra.setdefault(k, stamped.get(k))
        return self.record(
            kind="policy_event",
            symbol=None,
            source=source,
            confidence="estimated",
            ttl_hours=720.0,
            payload={
                "title": (title or "")[:300],
                "sectors": list(sectors or [])[:20],
                **extra,
            },
        )

    def record_mgmt_event(
        self,
        *,
        symbol: str,
        title: str,
        detail: str = "",
        source: str = "operator",
        confidence: str = "estimated",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """LI.3b — management commentary / guidance (company-scoped)."""
        return self.record(
            kind="mgmt_event",
            symbol=symbol,
            source=source,
            confidence=confidence,
            ttl_hours=720.0,
            payload={
                "title": (title or "")[:300],
                "detail": (detail or "")[:800],
                **(extra or {}),
            },
        )

    def record_operating_metric(
        self,
        *,
        symbol: str,
        metric: str,
        value: Any = None,
        unit: str | None = None,
        period: str | None = None,
        source: str = "operator",
        confidence: str = "estimated",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """LI.3b — operating KPI observation (not a valuation invent)."""
        return self.record(
            kind="operating_metric",
            symbol=symbol,
            source=source,
            confidence=confidence,
            ttl_hours=2160.0,
            payload={
                "metric": (metric or "")[:120],
                "value": value,
                "unit": unit,
                "period": period,
                **(extra or {}),
            },
        )

    def record_filing_event(
        self,
        *,
        symbol: str,
        filing_type: str,
        title: str = "",
        as_of: str | None = None,
        source: str = "operator",
        confidence: str = "medium",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """LI.3b — AR / quarterly / exchange filing notice."""
        return self.record(
            kind="filing_event",
            symbol=symbol,
            source=source,
            confidence=confidence,
            ttl_hours=2160.0,
            payload={
                "filing_type": (filing_type or "unknown")[:80],
                "title": (title or "")[:300],
                "as_of": as_of,
                **(extra or {}),
            },
        )

    def record_macro_event(
        self,
        *,
        title: str,
        regime_tags: list[str] | None = None,
        detail: str = "",
        source: str = "operator",
        confidence: str = "estimated",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """LI.3b — macro/regime observation (symbol=None → __MACRO__ timeline)."""
        return self.record(
            kind="macro_event",
            symbol=None,
            source=source,
            confidence=confidence,
            ttl_hours=720.0,
            payload={
                "title": (title or "")[:300],
                "detail": (detail or "")[:800],
                "regime_tags": list(regime_tags or [])[:12],
                **(extra or {}),
            },
        )


def _summarize_payload(kind: str, payload: dict[str, Any]) -> str:
    if kind == "market_event":
        move = payload.get("pct_move")
        return f"market move {move:+.2f}%" if isinstance(move, (int, float)) else "market event"
    if kind == "news_event":
        return str(payload.get("text") or "")[:120]
    if kind == "policy_event":
        return str(payload.get("title") or "policy")[:120]
    if kind == "mgmt_event":
        return str(payload.get("title") or "mgmt")[:120]
    if kind == "operating_metric":
        m = payload.get("metric") or "metric"
        v = payload.get("value")
        return f"{m}={v}" if v is not None else str(m)[:120]
    if kind == "filing_event":
        return f"{payload.get('filing_type') or 'filing'}: {payload.get('title') or ''}"[:120]
    if kind == "macro_event":
        tags = payload.get("regime_tags") or []
        tag_s = ",".join(str(t) for t in tags[:4])
        return f"{payload.get('title') or 'macro'} [{tag_s}]"[:120]
    return kind


def summarize_observation(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "symbol": row.get("symbol"),
        "kind": row.get("kind"),
        "source": row.get("source"),
        "confidence": row.get("confidence"),
        "created_at": row.get("created_at"),
        "summary": _summarize_payload(
            str(row.get("kind") or ""), row.get("payload") if isinstance(row.get("payload"), dict) else {}
        ),
    }


def format_observations_section(rows: list[dict[str, Any]] | None) -> list[str]:
    rows = list(rows or [])
    lines = ["", f"Observations (DI.Obs) recent ({len(rows)}):"]
    if not rows:
        lines.append("  (none recorded)")
        return lines
    for r in rows[:15]:
        s = summarize_observation(r)
        sym = s.get("symbol") or "MACRO"
        lines.append(
            f"  · {s.get('kind')} {sym} — {s.get('summary')} "
            f"[{s.get('source') or '—'}]"
        )
    return lines
