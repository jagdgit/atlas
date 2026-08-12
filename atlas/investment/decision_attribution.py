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

ATTR_VERSION = "di.attr.2"
STORE_REL = Path("investment") / "decisions" / "attributions"
_IST = ZoneInfo("Asia/Kolkata")

GRADE_ORDER = ("A", "B", "C", "D", "E", "F")
TRIGGERS = frozenset({"exit", "revisit", "manual"})

# LQ.4 — material exit densify thresholds (honest; never invent)
MATERIAL_ABS_PCT = 2.0


def rank_feature_drivers(
    contrib: dict[str, Any] | None,
    *,
    top_n: int = 5,
) -> list[dict[str, Any]]:
    """LQ.4 — rank decide-time feature contributions by |contrib| (skip zeros)."""
    if not isinstance(contrib, dict):
        return []
    skip = {"version", "note", "sum", "total", "heuristic"}
    rows: list[dict[str, Any]] = []
    for key, raw in contrib.items():
        if key in skip or str(key).startswith("_"):
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if val == 0:
            continue
        rows.append(
            {
                "feature": str(key),
                "contrib": int(val) if float(val).is_integer() else round(val, 2),
                "abs": abs(val),
            }
        )
    rows.sort(key=lambda r: (-float(r["abs"]), str(r["feature"])))
    return [{"feature": r["feature"], "contrib": r["contrib"]} for r in rows[: max(1, int(top_n))]]


def is_material_exit(
    *,
    trigger: str,
    pnl: float | None = None,
    price_change_pct: float | None = None,
    grades: dict[str, Any] | None = None,
) -> bool:
    """True for exit triggers with measured adverse/favorable path or thesis miss."""
    if str(trigger or "") != "exit":
        return False
    g = grades if isinstance(grades, dict) else {}
    if g.get("thesis_correct") == "no":
        return True
    try:
        if price_change_pct is not None and abs(float(price_change_pct)) >= MATERIAL_ABS_PCT:
            return True
    except (TypeError, ValueError):
        pass
    try:
        if pnl is not None and abs(float(pnl)) > 0:
            return True
    except (TypeError, ValueError):
        pass
    return False


def infer_primary_root_cause(
    packet: dict[str, Any] | None,
    grades: dict[str, Any] | None,
    *,
    pnl: float | None = None,
    what_changed: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
    what_atlas_missed: list[str] | None = None,
) -> str | None:
    """LQ.4 — map grades/packet signals → LI.0a.10 primary root cause (or None).

    Never invent outside the locked taxonomy. Winning / unknown paths stay None.
    """
    from atlas.investment.learning_intelligence import normalize_failure_cause

    packet = packet if isinstance(packet, dict) else {}
    g = grades if isinstance(grades, dict) else {}
    notes = [str(n).lower() for n in (g.get("notes") or [])]
    notes_blob = " ".join(notes)
    missed = [str(x).lower() for x in (what_atlas_missed or packet.get("unknowns") or [])]
    missed_blob = " ".join(missed)
    extra = extra if isinstance(extra, dict) else {}
    wc = what_changed if isinstance(what_changed, dict) else {}
    chg = g.get("price_change_pct")
    if chg is None:
        chg = wc.get("price_change_pct")
    try:
        chg_f = float(chg) if chg is not None else None
    except (TypeError, ValueError):
        chg_f = None

    action = str(packet.get("action") or "").lower()
    gates = packet.get("gates") if isinstance(packet.get("gates"), dict) else {}
    rg = gates.get("research") if isinstance(gates.get("research"), dict) else {}
    pg = gates.get("portfolio") if isinstance(gates.get("portfolio"), dict) else {}
    unknowns = list(packet.get("unknowns") or [])

    # Specific → general (single primary)
    if any("conflict" in u or u.endswith("_conflict") for u in unknowns) or "provider_conflict" in missed_blob:
        return normalize_failure_cause("provider_conflict")
    if "host_guard" in missed_blob or "resource" in missed_blob or extra.get("host_guard"):
        return normalize_failure_cause("resource_limitation")
    if str(g.get("market_quality") or "").upper() == "F" and (
        (chg_f is not None and abs(chg_f) >= 8) or "regime" in notes_blob
    ):
        return normalize_failure_cause("market_regime_failure")
    if (
        "bought through research block" in notes_blob
        or (rg.get("allowed") is False and action == "buy")
    ):
        return normalize_failure_cause("research_failure")
    if (
        "portfolio gate" in notes_blob
        or pg.get("allowed") is False
        or str(g.get("portfolio_quality") or "").upper() == "F"
    ):
        return normalize_failure_cause("portfolio_failure")
    if "fee" in notes_blob or (
        str(g.get("execution_quality") or "").upper() in {"E", "F"}
        and ("trim" in notes_blob or "fee" in notes_blob)
    ):
        return normalize_failure_cause("execution_failure")
    if unknowns and float((packet.get("meta") or {}).get("completeness") or 1.0) < 0.45:
        return normalize_failure_cause("evidence_failure")
    if any("missing" in u or "unavailable" in u for u in unknowns):
        return normalize_failure_cause("data_unavailable")
    if g.get("thesis_correct") == "no":
        if str(g.get("market_quality") or "").upper() in {"E", "F"} and chg_f is not None and abs(chg_f) >= 8:
            return normalize_failure_cause("market_regime_failure")
        return normalize_failure_cause("research_failure")
    # Correct / partial / unknown — no failure tag
    return None


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
        failure_cause: str | None = None,
    ) -> dict[str, Any]:
        """Append one attribution. LI.5a: optional ``failure_cause`` (LI.0a.10 taxonomy)."""
        from atlas.investment.learning_intelligence import normalize_failure_cause

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
        cause = normalize_failure_cause(failure_cause)
        extra_payload = dict(extra or {})
        # LQ.4 — densify material exits: primary root cause + feature drivers
        material = is_material_exit(
            trigger=trig,
            pnl=pnl,
            price_change_pct=price_change_pct
            if price_change_pct is not None
            else grades.get("price_change_pct"),
            grades=grades,
        )
        if not cause and material:
            cause = infer_primary_root_cause(
                pkt,
                grades,
                pnl=pnl,
                what_changed=what_changed,
                extra=extra_payload,
                what_atlas_missed=missed,
            )
        if cause and "failure_cause" not in extra_payload:
            extra_payload["failure_cause"] = cause
        if "exit_reason" not in extra_payload and extra_payload.get("why"):
            extra_payload["exit_reason"] = str(extra_payload.get("why"))[:300]
        drivers: list[dict[str, Any]] = []
        if trig == "exit" and isinstance(pkt, dict):
            drivers = rank_feature_drivers(pkt.get("feature_contributions"), top_n=5)
            # Optional: surface news_delta as an explicit driver hint (not invented PE)
            nd = (what_changed or {}).get("news_delta") if isinstance(what_changed, dict) else None
            if isinstance(nd, dict) and int(nd.get("count") or 0) > 0:
                if not any(d.get("feature") == "news" for d in drivers):
                    drivers = [{"feature": "news", "contrib": int(nd.get("count") or 1)}, *drivers][
                        :5
                    ]

        # DAV.1 — helped / hurt / unknown factor outcomes (fail-closed)
        causal_factors: dict[str, Any] | None = None
        try:
            from atlas.investment.causal_attribution import evaluate_causal_factors

            wc = what_changed if isinstance(what_changed, dict) else {}
            nd = wc.get("news_delta") if isinstance(wc.get("news_delta"), dict) else {}
            sector_rel = wc.get("sector_rel_pct")
            if sector_rel is None:
                sector_rel = wc.get("sector_relative_pct")
            if sector_rel is None:
                sector_rel = wc.get("rs_vs_nifty")
            if sector_rel is None and isinstance(extra_payload.get("sector_rel_pct"), (int, float)):
                sector_rel = extra_payload.get("sector_rel_pct")
            if sector_rel is None and isinstance(extra_payload.get("rs_vs_nifty"), (int, float)):
                sector_rel = extra_payload.get("rs_vs_nifty")
            # Densify on material exits always; on revisits when price moved enough
            densify = material or (
                trig == "revisit"
                and grades.get("price_change_pct") is not None
                and abs(float(grades.get("price_change_pct") or 0)) >= MATERIAL_ABS_PCT
            )
            if densify or trig == "exit":
                causal_factors = evaluate_causal_factors(
                    pkt if isinstance(pkt, dict) else None,
                    price_change_pct=price_change_pct
                    if price_change_pct is not None
                    else grades.get("price_change_pct"),
                    pnl=pnl,
                    sector_rel_pct=float(sector_rel) if sector_rel is not None else None,
                    news_count=int(nd.get("count") or 0) if nd else int(wc.get("news_count") or 0),
                    news_sentiment=(
                        str(nd.get("sentiment") or wc.get("news_sentiment") or "")
                        or None
                    ),
                    news_titles=list(nd.get("titles") or [])[:4] if nd else None,
                    regime_tags=list(wc.get("regime_tags") or [])[:6],
                    thesis_correct=str(grades.get("thesis_correct") or "") or None,
                    exit_reason_code=str(
                        extra_payload.get("exit_reason_code")
                        or extra_payload.get("exit_reason")
                        or ""
                    )
                    or None,
                    grades=grades,
                )
                if causal_factors:
                    extra_payload["causal_factors"] = {
                        "version": causal_factors.get("version"),
                        "narrative": causal_factors.get("narrative"),
                        "helped": causal_factors.get("helped"),
                        "hurt": causal_factors.get("hurt"),
                        "unknown": causal_factors.get("unknown"),
                        "missing_evidence": causal_factors.get("missing_evidence"),
                    }
        except Exception:  # noqa: BLE001
            _log.debug("DAV.1 causal densify skipped", exc_info=True)
            causal_factors = None
        from atlas.investment.laboratory import (
            extract_experiment_id,
            normalize_experiment_id,
            normalize_laboratory_id,
            stamp_laboratory_identity,
        )

        lab = normalize_laboratory_id(
            laboratory_id=(pkt or {}).get("laboratory_id") if isinstance(pkt, dict) else None,
            portfolio_key=portfolio_key
            or ((pkt or {}).get("portfolio_key") if isinstance(pkt, dict) else None),
        )
        exp = normalize_experiment_id(
            (pkt or {}).get("experiment_id")
            if isinstance(pkt, dict)
            else None
        )
        if isinstance(pkt, dict) and not pkt.get("experiment_id"):
            exp = extract_experiment_id(extra_payload) if extra_payload else exp
        if "experiment_id" not in extra_payload:
            extra_payload["experiment_id"] = exp
        if "strategy_tag" not in extra_payload and isinstance(pkt, dict) and pkt.get("strategy_tag"):
            extra_payload["strategy_tag"] = pkt.get("strategy_tag")
        if "laboratory_id" not in extra_payload:
            extra_payload["laboratory_id"] = lab
        if material:
            extra_payload["material_exit"] = True
        # LQ.6 — stamp regime on closed/material attribution payload (unknown OK)
        regime_tags: list[str] = []
        if trig in {"exit", "stop", "target", "time_stop", "manual"} or material:
            try:
                from atlas.investment.decision_packets import regime_tags_for_closed_row

                regime_tags = regime_tags_for_closed_row(pkt, {"payload": extra_payload})
                extra_payload["regime_tags"] = regime_tags
            except Exception:  # noqa: BLE001
                regime_tags = ["unknown"]
                extra_payload["regime_tags"] = regime_tags
        doc = {
            "id": str(uuid4()),
            "created_at": datetime.now(_IST).isoformat(),
            "decision_id": str(decision_id) if decision_id else None,
            "symbol": symbol,
            "portfolio_key": lab,
            "laboratory_id": lab,
            "experiment_id": exp,
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
                "extra": extra_payload,
                "failure_cause": cause,
                "feature_drivers": drivers,
                "causal_factors": causal_factors,
                "experiment_id": exp,
                "laboratory_id": lab,
                "regime_tags": regime_tags or None,
                "lq": (
                    "dav.1"
                    if causal_factors
                    else ("lq.6" if regime_tags else ("lq.4" if (cause or drivers) else None))
                ),
            },
            "payload_version": ATTR_VERSION,
        }
        stamp_laboratory_identity(doc, lab)
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
                        "failure_cause": cause,
                        "feature_drivers": drivers[:5],
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

    def build_replay(
        self,
        decision_id: str,
        *,
        laboratory_id: str | None = None,
        strategy_tag: str | None = None,
        experiment_id: str | None = None,
    ) -> dict[str, Any]:
        """Frozen packet + timeline since + attribution (+ Stage-3 stub).

        LI.4: optional filters — if provided and the decision does not match,
        return ``matched=False`` (does not invent data).
        """
        from atlas.investment.laboratory import (
            extract_experiment_id,
            extract_strategy_tag,
            normalize_experiment_id,
            normalize_laboratory_id,
            extract_laboratory_id,
        )

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
        filters = {
            "laboratory_id": laboratory_id,
            "strategy_tag": strategy_tag,
            "experiment_id": experiment_id,
        }
        matched = True
        mismatch_reasons: list[str] = []
        if laboratory_id:
            want = normalize_laboratory_id(laboratory_id=laboratory_id)
            got = extract_laboratory_id(packet) or extract_laboratory_id(latest)
            if got and got != want:
                matched = False
                mismatch_reasons.append(f"laboratory_id want={want} got={got}")
        if strategy_tag:
            want_tag = str(strategy_tag).strip()
            got_tag = (
                str((packet or {}).get("strategy_tag") or "")
                if isinstance(packet, dict)
                else ""
            ) or extract_strategy_tag(latest)
            if got_tag and got_tag != want_tag:
                matched = False
                mismatch_reasons.append(f"strategy_tag want={want_tag} got={got_tag}")
        if experiment_id is not None and str(experiment_id).strip() != "":
            want_exp = normalize_experiment_id(experiment_id)
            got_exp = (
                normalize_experiment_id((packet or {}).get("experiment_id"))
                if isinstance(packet, dict)
                else extract_experiment_id(latest)
            )
            if got_exp != want_exp:
                matched = False
                mismatch_reasons.append(f"experiment_id want={want_exp} got={got_exp}")
        return {
            "version": "di.replay.1",
            "decision_id": decision_id,
            "packet": packet if matched else None,
            "timeline": timeline_events if matched else [],
            "attributions": attrs if matched else [],
            "latest_attribution": latest if matched else None,
            "matched": matched,
            "filters": filters,
            "mismatch_reasons": mismatch_reasons,
            "would_current_priors_still_act": None,  # Stage 3
            "note": (
                "Replay freezes decide-time belief; timeline/attribution are append-only. "
                "Priors re-score stub reserved for Stage 3. "
                "LI.4 filters: laboratory_id / strategy_tag / experiment_id."
            ),
        }

    def list_replay_candidates(
        self,
        *,
        laboratory_id: str,
        strategy_tag: str | None = None,
        experiment_id: str | None = None,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        """LI.4 — list closed attributions for a lab, optionally filtered."""
        from atlas.investment.laboratory import (
            extract_experiment_id,
            extract_strategy_tag,
            normalize_experiment_id,
            normalize_laboratory_id,
        )

        lab = normalize_laboratory_id(laboratory_id=laboratory_id)
        want_exp = (
            normalize_experiment_id(experiment_id)
            if experiment_id is not None and str(experiment_id).strip() != ""
            else None
        )
        want_tag = str(strategy_tag).strip() if strategy_tag else None
        rows = self.list_portfolio(portfolio_key=lab, limit=max(limit * 3, 50))
        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("trigger") or "") not in {"exit", "manual", "revisit"}:
                continue
            if want_tag:
                tag = extract_strategy_tag(row)
                pkt_tag = None
                if self._packets is not None and row.get("decision_id"):
                    try:
                        pkt = self._packets.get(str(row["decision_id"]))
                        if isinstance(pkt, dict):
                            pkt_tag = pkt.get("strategy_tag")
                    except Exception:  # noqa: BLE001
                        pkt_tag = None
                if str(pkt_tag or tag) != want_tag:
                    continue
            if want_exp is not None:
                exp = extract_experiment_id(row)
                if self._packets is not None and row.get("decision_id"):
                    try:
                        pkt = self._packets.get(str(row["decision_id"]))
                        if isinstance(pkt, dict) and pkt.get("experiment_id"):
                            exp = normalize_experiment_id(pkt.get("experiment_id"))
                    except Exception:  # noqa: BLE001
                        pass
                if exp != want_exp:
                    continue
            out.append(
                {
                    "decision_id": row.get("decision_id"),
                    "attribution_id": row.get("id"),
                    "symbol": row.get("symbol"),
                    "trigger": row.get("trigger"),
                    "laboratory_id": lab,
                    "strategy_tag": want_tag or extract_strategy_tag(row),
                    "experiment_id": want_exp or extract_experiment_id(row),
                }
            )
            if len(out) >= limit:
                break
        return out


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
    lines = ["", f"Outcome attribution (DI.Attr / LQ.4) ({len(attrs)}):"]
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
        payload = a.get("payload") if isinstance(a.get("payload"), dict) else {}
        cause = payload.get("failure_cause")
        if not cause and isinstance(payload.get("extra"), dict):
            cause = payload["extra"].get("failure_cause")
        if cause:
            lines.append(f"     Root cause: {cause}")
        drivers = payload.get("feature_drivers")
        if isinstance(drivers, list) and drivers:
            bits = [
                f"{d.get('feature')}({d.get('contrib'):+})"
                for d in drivers[:5]
                if isinstance(d, dict) and d.get("feature") is not None
            ]
            if bits:
                lines.append(f"     Drivers: {', '.join(bits)}")
        causal = payload.get("causal_factors")
        if not isinstance(causal, dict) and isinstance(payload.get("extra"), dict):
            causal = payload["extra"].get("causal_factors")
        if isinstance(causal, dict) and causal.get("narrative"):
            lines.append(f"     Causes: {causal.get('narrative')}")
        if g.get("priors_block_reason"):
            lines.append(f"     {g.get('priors_block_reason')}")
    return lines
