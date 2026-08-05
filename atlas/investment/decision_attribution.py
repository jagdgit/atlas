"""Outcome Attribution + Replay (DI.Attr).

Separates decision quality from market P&L. Heuristic grades v1 (A–F).

Hard rule (locked): do **not** update strategy priors from raw P&L alone when
``market_quality`` is F and ``decision_quality`` is A or B.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

_log = logging.getLogger("atlas.investment.decision_attribution")

ATTR_VERSION = "di.attr.1"
STORE_REL = Path("investment") / "decisions" / "attributions"
_IST = ZoneInfo("Asia/Kolkata")

GRADE_ORDER = ("A", "B", "C", "D", "E", "F")
TRIGGERS = frozenset({"exit", "revisit", "manual"})


def _letter(score_0_to_1: float) -> str:
    x = max(0.0, min(1.0, float(score_0_to_1)))
    if x >= 0.85:
        return "A"
    if x >= 0.70:
        return "B"
    if x >= 0.55:
        return "C"
    if x >= 0.40:
        return "D"
    if x >= 0.25:
        return "E"
    return "F"


def may_update_priors(grades: dict[str, Any] | None) -> bool:
    """Hard rule: market catastrophe + sound decision → do not teach from P&L."""
    g = grades if isinstance(grades, dict) else {}
    mq = str(g.get("market_quality") or "").upper()
    dq = str(g.get("decision_quality") or "").upper()
    if mq == "F" and dq in {"A", "B"}:
        return False
    return True


def grade_attribution(
    packet: dict[str, Any] | None,
    *,
    pnl: float | None = None,
    price_change_pct: float | None = None,
    what_changed: dict[str, Any] | None = None,
    trigger: str = "exit",
) -> dict[str, Any]:
    """Deterministic heuristic grades — never invent fundamentals."""
    packet = packet if isinstance(packet, dict) else {}
    action = str(packet.get("action") or "").lower()
    unknowns = list(packet.get("unknowns") or [])
    completeness = float((packet.get("meta") or {}).get("completeness") or 0.0)
    reasons = list(packet.get("reasons_for") or [])
    gates = packet.get("gates") if isinstance(packet.get("gates"), dict) else {}
    contrib = (
        packet.get("feature_contributions")
        if isinstance(packet.get("feature_contributions"), dict)
        else {}
    )
    notes: list[str] = []

    # --- decision_quality: process soundness at decide-time ---
    dq = 0.45 + 0.40 * completeness
    if reasons:
        dq += 0.08
    if unknowns:
        dq -= min(0.25, 0.04 * len(unknowns))
        notes.append(f"unknowns={len(unknowns)}")
    tech = contrib.get("technical") or 0
    val = contrib.get("valuation") or 0
    if action == "buy" and tech < 0 and val < 0:
        dq -= 0.15
        notes.append("buy vs negative tech+valuation contributions")
    if action == "sell" and tech > 0 and val > 0:
        dq -= 0.10
        notes.append("sell vs positive contributions")
    rg = gates.get("research") if isinstance(gates.get("research"), dict) else {}
    if rg.get("allowed") is False and action == "buy":
        dq -= 0.20
        notes.append("bought through research block")
    decision_quality = _letter(dq)

    # --- market_quality: did regime/noise dominate? ---
    chg = price_change_pct
    if chg is None and isinstance(what_changed, dict):
        chg = what_changed.get("price_change_pct")
    mq_score = 0.65
    if chg is not None:
        try:
            c = float(chg)
            # Large moves → market dominated (worse market_quality grade)
            mag = abs(c)
            if mag >= 12:
                mq_score = 0.15
                notes.append(f"regime-size move {c:+.1f}%")
            elif mag >= 8:
                mq_score = 0.30
            elif mag >= 4:
                mq_score = 0.50
            else:
                mq_score = 0.75
            # Direction adverse to action → slightly worse market grade (luck against)
            adverse = (action == "buy" and c < -4) or (action == "sell" and c > 4)
            if adverse:
                mq_score = max(0.1, mq_score - 0.15)
                notes.append("adverse market path")
        except (TypeError, ValueError):
            pass
    else:
        notes.append("price_change unknown")
        mq_score = 0.50
    market_quality = _letter(mq_score)

    # --- execution_quality ---
    eq = 0.70
    prices = packet.get("prices") if isinstance(packet.get("prices"), dict) else {}
    if prices.get("trimmed_from") or gates.get("trimmed_from"):
        eq -= 0.05
        notes.append("size trimmed")
    fees = prices.get("fees")
    fill = prices.get("fill_price") or prices.get("mark")
    try:
        if fees is not None and fill is not None and float(fill) > 0:
            qty = float(prices.get("filled_qty") or prices.get("suggested_qty") or 1)
            fee_pct = 100.0 * float(fees) / (abs(float(fill) * qty) or 1.0)
            if fee_pct > 1.0:
                eq -= 0.15
            elif fee_pct > 0.4:
                eq -= 0.05
    except (TypeError, ValueError):
        pass
    if not prices.get("filled_qty") and trigger == "exit":
        eq -= 0.10
    execution_quality = _letter(eq)

    # --- portfolio_quality ---
    pq = 0.65
    pg = gates.get("portfolio") if isinstance(gates.get("portfolio"), dict) else {}
    if pg.get("allowed") is False:
        pq = 0.35
        notes.append("portfolio gate would block")
    elif gates.get("binding"):
        pq -= 0.08
        notes.append(f"binding={gates.get('binding')}")
    portfolio_quality = _letter(pq)

    # --- thesis_correct ---
    thesis_correct = "unknown"
    if chg is not None and action in {"buy", "sell", "reduce"}:
        try:
            c = float(chg)
            if action == "buy":
                if c > 2:
                    thesis_correct = "yes"
                elif c < -2:
                    thesis_correct = "no"
                else:
                    thesis_correct = "partial"
            elif action in {"sell", "reduce"}:
                if c < -2:
                    thesis_correct = "yes"  # sold before further drop
                elif c > 2:
                    thesis_correct = "no"
                else:
                    thesis_correct = "partial"
        except (TypeError, ValueError):
            thesis_correct = "unknown"

    grades = {
        "decision_quality": decision_quality,
        "market_quality": market_quality,
        "execution_quality": execution_quality,
        "portfolio_quality": portfolio_quality,
        "thesis_correct": thesis_correct,
        "heuristic": "di.attr.v1",
        "notes": notes[:12],
        "pnl": pnl,
        "price_change_pct": chg,
    }
    grades["may_update_priors"] = may_update_priors(grades)
    if not grades["may_update_priors"]:
        grades["priors_block_reason"] = (
            "market_quality=F with decision_quality A/B — do not teach from raw P&L"
        )
    return grades


def mirror_root(data_dir: str | Path) -> Path:
    return Path(data_dir) / STORE_REL


def _mirror(data_dir: str | Path | None, doc: dict[str, Any]) -> str | None:
    if not data_dir:
        return None
    try:
        path = mirror_root(data_dir) / "by_id" / f"{doc['id']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")
        did = str(doc.get("decision_id") or "unknown")
        dpath = mirror_root(data_dir) / "by_decision" / f"{did}.jsonl"
        dpath.parent.mkdir(parents=True, exist_ok=True)
        with dpath.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(doc, default=str) + "\n")
        return str(path)
    except Exception:  # noqa: BLE001
        _log.warning("attribution mirror failed", exc_info=True)
        return None


class DecisionAttributionStore:
    def __init__(
        self,
        *,
        data_dir: str | Path | None = None,
        repo: Any | None = None,
        packet_store: Any | None = None,
        timeline: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._data_dir = str(data_dir) if data_dir else None
        self._repo = repo
        self._packets = packet_store
        self._timeline = timeline
        self._logger = logger or _log
        self._mem: list[dict[str, Any]] = []

    def bind(self, *, packets: Any = None, timeline: Any = None) -> None:
        if packets is not None:
            self._packets = packets
        if timeline is not None:
            self._timeline = timeline

    def record(
        self,
        *,
        decision_id: str | None,
        symbol: str,
        portfolio_key: str,
        trigger: str = "exit",
        checkpoint: str | None = None,
        packet: dict[str, Any] | None = None,
        pnl: float | None = None,
        price_change_pct: float | None = None,
        what_changed: dict[str, Any] | None = None,
        what_changed_event_ids: list[str] | None = None,
        what_atlas_missed: list[str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        trig = str(trigger or "exit")
        if trig not in TRIGGERS:
            trig = "manual"
        pkt = packet
        if pkt is None and self._packets is not None and decision_id:
            try:
                pkt = self._packets.get(str(decision_id))
            except Exception:  # noqa: BLE001
                pkt = None
        grades = grade_attribution(
            pkt,
            pnl=pnl,
            price_change_pct=price_change_pct,
            what_changed=what_changed,
            trigger=trig,
        )
        missed = list(what_atlas_missed or [])
        if pkt and not missed:
            missed = list(pkt.get("unknowns") or [])[:8]
        doc = {
            "id": str(uuid4()),
            "created_at": datetime.now(_IST).isoformat(),
            "decision_id": str(decision_id) if decision_id else None,
            "symbol": symbol,
            "portfolio_key": portfolio_key or "unknown",
            "trigger": trig,
            "checkpoint": checkpoint,
            "grades": grades,
            "payload": {
                "what_changed": what_changed or {},
                "what_changed_event_ids": list(what_changed_event_ids or []),
                "what_atlas_missed": missed,
                "pnl": pnl,
                "mae": None,  # Stage 2+
                "mfe": None,
                "extra": dict(extra or {}),
            },
            "payload_version": ATTR_VERSION,
        }
        if self._repo is not None:
            try:
                self._repo.insert(doc)
            except Exception:  # noqa: BLE001
                self._logger.warning("attribution postgres insert failed", exc_info=True)
        else:
            self._mem.append(doc)
        mirror = _mirror(self._data_dir, doc)
        # Timeline outcome event
        if self._timeline is not None and symbol:
            try:
                self._timeline.append_event(
                    symbol=symbol,
                    kind="outcome",
                    decision_id=decision_id,
                    payload={
                        "attribution_id": doc["id"],
                        "trigger": trig,
                        "checkpoint": checkpoint,
                        "grades": grades,
                        "may_update_priors": grades.get("may_update_priors"),
                    },
                )
            except Exception:  # noqa: BLE001
                self._logger.debug("attribution→timeline failed", exc_info=True)
        return {
            "attribution": doc,
            "mirror_path": mirror,
            "may_update_priors": bool(grades.get("may_update_priors")),
            "version": ATTR_VERSION,
        }

    def get(self, attribution_id: str) -> dict[str, Any] | None:
        if self._repo is not None:
            try:
                r = self._repo.get(attribution_id)
                if r:
                    return _row_to_doc(r)
            except Exception:  # noqa: BLE001
                self._logger.debug("attribution get failed", exc_info=True)
        if self._data_dir:
            path = mirror_root(self._data_dir) / "by_id" / f"{attribution_id}.json"
            if path.is_file():
                try:
                    doc = json.loads(path.read_text(encoding="utf-8"))
                    return doc if isinstance(doc, dict) else None
                except Exception:  # noqa: BLE001
                    return None
        for r in self._mem:
            if r.get("id") == attribution_id:
                return dict(r)
        return None

    def list_for_decision(self, decision_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        if self._repo is not None:
            try:
                rows = self._repo.list_for_decision(decision_id=decision_id, limit=limit)
                if rows:
                    return [_row_to_doc(r) for r in rows]
            except Exception:  # noqa: BLE001
                self._logger.debug("list_for_decision attr failed", exc_info=True)
        out = [r for r in self._mem if r.get("decision_id") == decision_id]
        if self._data_dir:
            path = mirror_root(self._data_dir) / "by_decision" / f"{decision_id}.jsonl"
            if path.is_file():
                try:
                    for line in path.read_text(encoding="utf-8").splitlines():
                        if not line.strip():
                            continue
                        try:
                            doc = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(doc, dict):
                            out.append(doc)
                except Exception:  # noqa: BLE001
                    pass
        # dedupe
        seen: set[str] = set()
        uniq = []
        for r in reversed(out):
            oid = str(r.get("id") or "")
            if oid in seen:
                continue
            seen.add(oid)
            uniq.append(r)
        uniq.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
        return uniq[:limit]

    def list_portfolio(self, *, portfolio_key: str, limit: int = 50) -> list[dict[str, Any]]:
        if self._repo is not None:
            try:
                rows = self._repo.list_portfolio(portfolio_key=portfolio_key, limit=limit)
                if rows:
                    return [_row_to_doc(r) for r in rows]
            except Exception:  # noqa: BLE001
                self._logger.debug("list_portfolio attr failed", exc_info=True)
        items: list[dict[str, Any]] = [
            r for r in self._mem if r.get("portfolio_key") == portfolio_key
        ]
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
                    if isinstance(doc, dict) and doc.get("portfolio_key") == portfolio_key:
                        items.append(doc)
        seen: set[str] = set()
        uniq = []
        for r in items:
            oid = str(r.get("id") or "")
            if oid in seen:
                continue
            seen.add(oid)
            uniq.append(r)
        uniq.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
        return uniq[:limit]

    def build_replay(self, decision_id: str) -> dict[str, Any]:
        """Frozen packet + timeline since + attribution (+ Stage-3 stub)."""
        packet = None
        if self._packets is not None:
            try:
                packet = self._packets.get(decision_id)
            except Exception:  # noqa: BLE001
                packet = None
        timeline_events: list[dict[str, Any]] = []
        if self._timeline is not None and packet:
            try:
                timeline_events = self._timeline.list_symbol(
                    symbol=str(packet.get("symbol") or ""), limit=100
                )
                # Keep events at/after decision or linked to this decision
                linked = [
                    e
                    for e in timeline_events
                    if str(e.get("decision_id") or "") == decision_id
                    or e.get("kind") in {"decision", "revisit", "observation", "outcome"}
                ]
                timeline_events = linked[:80]
            except Exception:  # noqa: BLE001
                timeline_events = []
        attrs = self.list_for_decision(decision_id, limit=5)
        latest = attrs[0] if attrs else None
        return {
            "version": "di.replay.1",
            "decision_id": decision_id,
            "packet": packet,
            "timeline": timeline_events,
            "attributions": attrs,
            "latest_attribution": latest,
            "would_current_priors_still_act": None,  # Stage 3
            "note": (
                "Replay freezes decide-time belief; timeline/attribution are append-only. "
                "Priors re-score stub reserved for Stage 3."
            ),
        }


def _row_to_doc(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(r["id"]),
        "created_at": r.get("created_at").isoformat()
        if hasattr(r.get("created_at"), "isoformat")
        else r.get("created_at"),
        "decision_id": str(r["decision_id"]) if r.get("decision_id") else None,
        "symbol": r.get("symbol"),
        "portfolio_key": r.get("portfolio_key"),
        "trigger": r.get("trigger"),
        "checkpoint": r.get("checkpoint"),
        "grades": r.get("grades") or {},
        "payload": r.get("payload") or {},
        "payload_version": r.get("payload_version") or ATTR_VERSION,
    }


def format_attribution_section(attrs: list[dict[str, Any]] | None) -> list[str]:
    attrs = list(attrs or [])
    lines = ["", f"Outcome attribution (DI.Attr) ({len(attrs)}):"]
    if not attrs:
        lines.append("  (none — need exits/revisits)")
        return lines
    for a in attrs[:10]:
        g = a.get("grades") or {}
        lines.append(
            f"  · {a.get('symbol')} [{a.get('trigger')}] "
            f"DQ={g.get('decision_quality')} MQ={g.get('market_quality')} "
            f"EQ={g.get('execution_quality')} PQ={g.get('portfolio_quality')} "
            f"thesis={g.get('thesis_correct')} "
            f"priors={'ok' if g.get('may_update_priors') else 'BLOCKED'}"
        )
        if g.get("priors_block_reason"):
            lines.append(f"     {g.get('priors_block_reason')}")
    return lines
