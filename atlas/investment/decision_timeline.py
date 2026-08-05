"""Market Timeline + Decision Evolution (DI.2).

Append-only events per symbol. Evolution schedule: Day1 → Week1 → Month1 →
Quarter → Exit. Each completed revisit records a ``what_changed`` diff vs the
frozen Decision Packet (belief never rewritten).

Hybrid: Postgres via ``DecisionTimelineRepository`` when available; JSON mirrors
under ``investment/decisions/timeline/`` and ``…/revisits/``.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from atlas.repositories.decision_timeline_repo import CHECKPOINTS, TIMELINE_KINDS

_log = logging.getLogger("atlas.investment.decision_timeline")

TIMELINE_VERSION = "di.timeline.1"
REVISIT_VERSION = "di.revisit.1"
STORE_REL = Path("investment") / "decisions"
_IST = ZoneInfo("Asia/Kolkata")

# Offset in calendar days from packet ts_ist.
CHECKPOINT_OFFSETS: dict[str, int] = {
    "day1": 1,
    "week1": 7,
    "month1": 30,
    "quarter": 90,
}

# Actions that get a full evolution schedule (not every engine_hold spam).
SCHEDULE_ACTIONS = frozenset({"buy", "sell", "watch", "reduce"})


def ist_today() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def _parse_ist(day: str) -> date:
    return date.fromisoformat(str(day)[:10])


def due_ist_for(ts_ist: str, checkpoint: str) -> str:
    offset = CHECKPOINT_OFFSETS.get(checkpoint)
    if offset is None:
        raise ValueError(f"unknown checkpoint {checkpoint!r}")
    return (_parse_ist(ts_ist) + timedelta(days=offset)).isoformat()


def timeline_root(data_dir: str | Path) -> Path:
    return Path(data_dir) / STORE_REL / "timeline"


def revisits_root(data_dir: str | Path) -> Path:
    return Path(data_dir) / STORE_REL / "revisits"


def _mirror_event(data_dir: str | Path | None, event: dict[str, Any]) -> str | None:
    if not data_dir:
        return None
    try:
        path = timeline_root(data_dir) / f"{event['symbol'].replace('/', '_')}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, default=str) + "\n")
        return str(path)
    except Exception:  # noqa: BLE001
        _log.warning("timeline mirror failed", exc_info=True)
        return None


def _mirror_revisit_schedule(
    data_dir: str | Path | None, row: dict[str, Any]
) -> str | None:
    if not data_dir:
        return None
    try:
        did = str(row.get("decision_id") or "unknown")
        path = revisits_root(data_dir) / "by_decision" / f"{did}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
        return str(path)
    except Exception:  # noqa: BLE001
        _log.warning("revisit mirror failed", exc_info=True)
        return None


def _load_symbol_jsonl(data_dir: str | Path, symbol: str) -> list[dict[str, Any]]:
    path = timeline_root(data_dir) / f"{symbol.replace('/', '_')}.jsonl"
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(doc, dict):
                out.append(doc)
    except Exception:  # noqa: BLE001
        return []
    return out


def _load_pending_revisits_json(data_dir: str | Path) -> list[dict[str, Any]]:
    root = revisits_root(data_dir) / "by_decision"
    if not root.is_dir():
        return []
    pending: list[dict[str, Any]] = []
    for path in root.glob("*.jsonl"):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:  # noqa: BLE001
            continue
        # Last line wins per checkpoint for hermetic JSON mode
        by_cp: dict[str, dict[str, Any]] = {}
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(doc, dict) and doc.get("checkpoint"):
                by_cp[str(doc["checkpoint"])] = doc
        for doc in by_cp.values():
            if doc.get("status", "pending") == "pending":
                pending.append(doc)
    return pending


def what_changed(
    packet: dict[str, Any] | None,
    *,
    current_mark: float | None = None,
    current_score: dict[str, Any] | None = None,
    current_valuation: dict[str, Any] | None = None,
    current_unknowns: list[str] | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Diff current evidence vs frozen packet beliefs (DI.2 revisit answers)."""
    packet = packet if isinstance(packet, dict) else {}
    prices = packet.get("prices") if isinstance(packet.get("prices"), dict) else {}
    conf = (
        packet.get("confidence_breakdown")
        if isinstance(packet.get("confidence_breakdown"), dict)
        else {}
    )
    val0 = None
    # Packet gates may hold valuation indirectly; prefer expected/thesis later.
    mark0 = prices.get("fill_price") or prices.get("mark")
    deltas: list[str] = []
    price_chg_pct = None
    try:
        if mark0 is not None and current_mark is not None and float(mark0) != 0:
            price_chg_pct = round(
                100.0 * (float(current_mark) - float(mark0)) / abs(float(mark0)), 3
            )
            deltas.append(f"price {float(mark0):.2f}→{float(current_mark):.2f} ({price_chg_pct:+.2f}%)")
    except (TypeError, ValueError):
        pass

    score = current_score if isinstance(current_score, dict) else {}
    overall_now = score.get("overall")
    overall0 = conf.get("overall")
    conf_delta = None
    try:
        if overall_now is not None and overall0 is not None:
            conf_delta = round(float(overall_now) - float(overall0), 3)
            deltas.append(f"confidence {overall0}→{overall_now} (Δ{conf_delta:+})")
    except (TypeError, ValueError):
        pass

    val = current_valuation if isinstance(current_valuation, dict) else {}
    mos_now = val.get("margin_of_safety_pct")
    if mos_now is not None:
        deltas.append(f"mos_pct={mos_now}")

    unk0 = set(packet.get("unknowns") or [])
    unk1 = set(current_unknowns or [])
    resolved = sorted(unk0 - unk1)
    new_gaps = sorted(unk1 - unk0)
    if resolved:
        deltas.append("resolved:" + ",".join(resolved[:6]))
    if new_gaps:
        deltas.append("new_gaps:" + ",".join(new_gaps[:6]))

    thesis_improved = None
    if conf_delta is not None:
        thesis_improved = conf_delta > 0.02
    elif price_chg_pct is not None and packet.get("action") == "buy":
        thesis_improved = price_chg_pct > 0
    elif price_chg_pct is not None and packet.get("action") == "sell":
        thesis_improved = price_chg_pct < 0

    return {
        "thesis_improved": thesis_improved,
        "confidence_delta": conf_delta,
        "price_change_pct": price_chg_pct,
        "valuation_note": f"mos={mos_now}" if mos_now is not None else None,
        "management_note": None,  # DI.Attr / research later
        "resolved_unknowns": resolved,
        "new_unknowns": new_gaps,
        "deltas": deltas,
        "note": (note or "")[:300],
        "mark_at_decision": mark0,
        "mark_now": current_mark,
        "overall_at_decision": overall0,
        "overall_now": overall_now,
    }


class DecisionTimelineStore:
    """Hybrid timeline + revisit scheduler."""

    def __init__(
        self,
        *,
        data_dir: str | Path | None = None,
        repo: Any | None = None,
        packet_store: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._data_dir = str(data_dir) if data_dir else None
        self._repo = repo
        self._packets = packet_store
        self._logger = logger or _log
        # Hermetic pending revisits when repo is absent
        self._mem_revisits: list[dict[str, Any]] = []
        self._mem_events: list[dict[str, Any]] = []

    @property
    def data_dir(self) -> str | None:
        return self._data_dir

    def append_event(
        self,
        *,
        symbol: str,
        kind: str,
        decision_id: str | None = None,
        payload: dict[str, Any] | None = None,
        event_id: str | None = None,
    ) -> dict[str, Any]:
        if kind not in TIMELINE_KINDS:
            raise ValueError(f"invalid timeline kind {kind!r}")
        event = {
            "id": str(event_id or uuid4()),
            "created_at": datetime.now(_IST).isoformat(),
            "symbol": symbol,
            "kind": kind,
            "decision_id": str(decision_id) if decision_id else None,
            "payload": dict(payload or {}),
            "payload_version": TIMELINE_VERSION,
        }
        if self._repo is not None:
            try:
                self._repo.insert_event(event)
            except Exception:  # noqa: BLE001
                self._logger.warning("timeline postgres insert failed", exc_info=True)
        else:
            self._mem_events.append(event)
        _mirror_event(self._data_dir, event)
        return event

    def on_packet_saved(self, packet: dict[str, Any]) -> dict[str, Any]:
        """DI.2 hook after DI.1 packet write: decision event + evolution schedule."""
        if not isinstance(packet, dict):
            return {"events": 0, "scheduled": 0}
        symbol = str(packet.get("symbol") or "")
        did = str(packet.get("decision_id") or "")
        if not symbol or not did:
            return {"events": 0, "scheduled": 0}
        self.append_event(
            symbol=symbol,
            kind="decision",
            decision_id=did,
            payload={
                "action": packet.get("action"),
                "strategy_tag": packet.get("strategy_tag"),
                "portfolio_key": packet.get("portfolio_key"),
                "ts_ist": packet.get("ts_ist"),
                "completeness": (packet.get("meta") or {}).get("completeness"),
            },
        )
        scheduled = 0
        if packet.get("action") in SCHEDULE_ACTIONS:
            scheduled = self.schedule_evolution(packet)
        return {"events": 1, "scheduled": scheduled}

    def schedule_evolution(self, packet: dict[str, Any]) -> int:
        ts_ist = str(packet.get("ts_ist") or ist_today())
        did = str(packet.get("decision_id") or "")
        symbol = str(packet.get("symbol") or "")
        pk = str(packet.get("portfolio_key") or "unknown")
        if not did or not symbol:
            return 0
        n = 0
        for checkpoint in ("day1", "week1", "month1", "quarter"):
            row = {
                "id": str(uuid4()),
                "decision_id": did,
                "symbol": symbol,
                "portfolio_key": pk,
                "checkpoint": checkpoint,
                "due_ist": due_ist_for(ts_ist, checkpoint),
                "status": "pending",
                "payload": {
                    "action": packet.get("action"),
                    "strategy_tag": packet.get("strategy_tag"),
                    "packet_ts_ist": ts_ist,
                },
                "payload_version": REVISIT_VERSION,
            }
            inserted = None
            if self._repo is not None:
                try:
                    inserted = self._repo.insert_revisit(row)
                except Exception:  # noqa: BLE001
                    self._logger.debug("revisit schedule insert failed", exc_info=True)
                    inserted = None
            else:
                # Idempotent in-memory / JSON
                exists = any(
                    r.get("decision_id") == did
                    and r.get("checkpoint") == checkpoint
                    and r.get("status") == "pending"
                    for r in self._mem_revisits
                )
                if not exists and self._data_dir:
                    for existing in _load_pending_revisits_json(self._data_dir):
                        if (
                            existing.get("decision_id") == did
                            and existing.get("checkpoint") == checkpoint
                        ):
                            exists = True
                            break
                if not exists:
                    self._mem_revisits.append(row)
                    inserted = row
            if inserted:
                _mirror_revisit_schedule(self._data_dir, row)
                n += 1
        return n

    def list_symbol(
        self, *, symbol: str, limit: int = 100, kind: str | None = None
    ) -> list[dict[str, Any]]:
        if self._repo is not None:
            try:
                rows = self._repo.list_symbol(symbol=symbol, limit=limit, kind=kind)
                if rows:
                    return [
                        {
                            "id": str(r["id"]),
                            "created_at": r.get("created_at"),
                            "symbol": r.get("symbol"),
                            "kind": r.get("kind"),
                            "decision_id": str(r["decision_id"])
                            if r.get("decision_id")
                            else None,
                            "payload": r.get("payload") or {},
                            "payload_version": r.get("payload_version"),
                        }
                        for r in rows
                    ]
            except Exception:  # noqa: BLE001
                self._logger.debug("list_symbol timeline repo failed", exc_info=True)
        events = list(self._mem_events)
        if self._data_dir:
            events.extend(_load_symbol_jsonl(self._data_dir, symbol))
        events = [e for e in events if e.get("symbol") == symbol]
        if kind:
            events = [e for e in events if e.get("kind") == kind]
        events.sort(key=lambda e: str(e.get("created_at") or ""), reverse=True)
        return events[:limit]

    def list_due(
        self, *, as_of_ist: str | None = None, portfolio_key: str | None = None, limit: int = 40
    ) -> list[dict[str, Any]]:
        day = as_of_ist or ist_today()
        if self._repo is not None:
            try:
                rows = self._repo.list_due(
                    as_of_ist=day, portfolio_key=portfolio_key, limit=limit
                )
                return [
                    {
                        "id": str(r["id"]),
                        "decision_id": str(r["decision_id"]) if r.get("decision_id") else None,
                        "symbol": r.get("symbol"),
                        "portfolio_key": r.get("portfolio_key"),
                        "checkpoint": r.get("checkpoint"),
                        "due_ist": str(r.get("due_ist")),
                        "status": r.get("status"),
                        "payload": r.get("payload") or {},
                    }
                    for r in rows
                ]
            except Exception:  # noqa: BLE001
                self._logger.debug("list_due repo failed", exc_info=True)
        pending = list(self._mem_revisits)
        if self._data_dir:
            pending.extend(_load_pending_revisits_json(self._data_dir))
        out = []
        for r in pending:
            if r.get("status", "pending") != "pending":
                continue
            if portfolio_key and r.get("portfolio_key") != portfolio_key:
                continue
            if str(r.get("due_ist") or "") > day:
                continue
            out.append(r)
        out.sort(key=lambda x: str(x.get("due_ist") or ""))
        return out[:limit]

    def complete_revisit(
        self,
        revisit: dict[str, Any],
        *,
        diff: dict[str, Any],
        mark: float | None = None,
    ) -> dict[str, Any]:
        symbol = str(revisit.get("symbol") or "")
        did = revisit.get("decision_id")
        checkpoint = str(revisit.get("checkpoint") or "")
        event = self.append_event(
            symbol=symbol,
            kind="revisit",
            decision_id=str(did) if did else None,
            payload={
                "checkpoint": checkpoint,
                "due_ist": revisit.get("due_ist"),
                "what_changed": diff,
                "mark": mark,
                "portfolio_key": revisit.get("portfolio_key"),
            },
        )
        payload_update = {"what_changed": diff, "mark": mark}
        if self._repo is not None and revisit.get("id"):
            try:
                self._repo.complete_revisit(
                    str(revisit["id"]),
                    status="done",
                    timeline_event_id=event["id"],
                    payload=payload_update,
                )
            except Exception:  # noqa: BLE001
                self._logger.warning("complete_revisit repo failed", exc_info=True)
        else:
            rid = str(revisit.get("id") or "")
            for r in self._mem_revisits:
                if str(r.get("id")) == rid:
                    r["status"] = "done"
                    r["payload"] = {**(r.get("payload") or {}), **payload_update}
            done_row = {**revisit, "status": "done", "payload": payload_update}
            _mirror_revisit_schedule(self._data_dir, done_row)
        return event

    def run_due_revisits(
        self,
        *,
        as_of_ist: str | None = None,
        portfolio_key: str | None = None,
        limit: int = 20,
        mark_fn: Any | None = None,
        awareness_fn: Any | None = None,
    ) -> dict[str, Any]:
        due = self.list_due(as_of_ist=as_of_ist, portfolio_key=portfolio_key, limit=limit)
        done: list[dict[str, Any]] = []
        for rev in due:
            packet = None
            if self._packets is not None and rev.get("decision_id"):
                try:
                    packet = self._packets.get(str(rev["decision_id"]))
                except Exception:  # noqa: BLE001
                    packet = None
            mark = None
            score = None
            valuation = None
            unknowns = list((packet or {}).get("unknowns") or [])
            sym = str(rev.get("symbol") or "")
            if mark_fn is not None and sym:
                try:
                    mark = mark_fn(sym)
                except Exception:  # noqa: BLE001
                    mark = None
            if awareness_fn is not None and sym:
                try:
                    aw = awareness_fn(sym) or {}
                    if isinstance(aw, dict):
                        score = aw.get("investment_score")
                        valuation = aw.get("valuation")
                        # Prefer live unknowns from packet builder if we have fundamentals later
                except Exception:  # noqa: BLE001
                    pass
            diff = what_changed(
                packet,
                current_mark=mark,
                current_score=score if isinstance(score, dict) else None,
                current_valuation=valuation if isinstance(valuation, dict) else None,
                current_unknowns=unknowns,
                note=f"auto {rev.get('checkpoint')}",
            )
            event = self.complete_revisit(rev, diff=diff, mark=mark)
            done.append(
                {
                    "revisit_id": rev.get("id"),
                    "decision_id": rev.get("decision_id"),
                    "symbol": sym,
                    "checkpoint": rev.get("checkpoint"),
                    "timeline_event_id": event.get("id"),
                    "what_changed": diff,
                }
            )
        return {
            "as_of_ist": as_of_ist or ist_today(),
            "due": len(due),
            "completed": len(done),
            "items": done,
        }

    def learning_counts(self, *, portfolio_key: str | None = None) -> dict[str, Any]:
        if self._repo is not None:
            try:
                c = self._repo.counts(portfolio_key=portfolio_key)
                return {
                    "pending_revisits": c.get("pending", 0),
                    "done_revisits": c.get("done", 0),
                    "skipped_revisits": c.get("skipped", 0),
                    "open_evolution": c.get("pending", 0),
                    "closed_checkpoints": c.get("done", 0) + c.get("skipped", 0),
                }
            except Exception:  # noqa: BLE001
                self._logger.debug("learning_counts repo failed", exc_info=True)
        all_rows = list(self._mem_revisits)
        if self._data_dir:
            # Include completed markers from jsonl (last status wins already in pending loader —
            # scan all lines for done counts)
            root = revisits_root(self._data_dir) / "by_decision"
            if root.is_dir():
                for path in root.glob("*.jsonl"):
                    try:
                        for line in path.read_text(encoding="utf-8").splitlines():
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                doc = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            if isinstance(doc, dict):
                                all_rows.append(doc)
                    except Exception:  # noqa: BLE001
                        continue
        # Dedupe by (decision_id, checkpoint) keeping last status
        latest: dict[tuple[str, str], dict[str, Any]] = {}
        for r in all_rows:
            if portfolio_key and r.get("portfolio_key") != portfolio_key:
                continue
            key = (str(r.get("decision_id") or ""), str(r.get("checkpoint") or ""))
            if key[0] and key[1]:
                latest[key] = r
        pending = sum(1 for r in latest.values() if r.get("status", "pending") == "pending")
        done = sum(1 for r in latest.values() if r.get("status") == "done")
        skipped = sum(1 for r in latest.values() if r.get("status") == "skipped")
        return {
            "pending_revisits": pending,
            "done_revisits": done,
            "skipped_revisits": skipped,
            "open_evolution": pending,
            "closed_checkpoints": done + skipped,
            "note": "json/memory counts" if self._repo is None else None,
        }

    def append_observation(
        self,
        *,
        symbol: str,
        kind_detail: str,
        payload: dict[str, Any] | None = None,
        decision_id: str | None = None,
    ) -> dict[str, Any]:
        """Thin DI.Obs seam — observations feed the timeline (full Obs later)."""
        body = dict(payload or {})
        body.setdefault("observation_kind", kind_detail)
        return self.append_event(
            symbol=symbol,
            kind="observation",
            decision_id=decision_id,
            payload=body,
        )


def format_evolution_section(counts: dict[str, Any] | None) -> list[str]:
    counts = counts or {}
    lines = [
        "",
        "Decision evolution (DI.2):",
        f"  Open revisits pending: {counts.get('pending_revisits', 0)}",
        f"  Checkpoints completed: {counts.get('done_revisits', 0)}",
    ]
    return lines
