"""Market Timeline + Decision Evolution (DI.2 / LQ.2).

Append-only events per symbol. Evolution schedule densifies open books:
Day1 → Day3 → Week1 → Day14 → Month1 → Quarter (Host Guard may thin drain).
Each completed revisit records a ``what_changed`` diff vs the frozen Decision
Packet (belief never rewritten).

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
REVISIT_VERSION = "di.revisit.2"
STORE_REL = Path("investment") / "decisions"
_IST = ZoneInfo("Asia/Kolkata")

# Offset in calendar days from packet ts_ist (LQ.2 denser set).
CHECKPOINT_OFFSETS: dict[str, int] = {
    "day1": 1,
    "day3": 3,
    "week1": 7,
    "day14": 14,
    "month1": 30,
    "quarter": 90,
}

# Default swing / equity laboratory density (LQ.2).
DEFAULT_SWING_CHECKPOINTS: tuple[str, ...] = (
    "day1",
    "day3",
    "week1",
    "day14",
    "month1",
    "quarter",
)

# Map LI.1b review_schedule tokens → checkpoint ids.
_SCHEDULE_TOKEN_MAP: dict[str, str] = {
    "D1": "day1",
    "D3": "day3",
    "W1": "week1",
    "D14": "day14",
    "M1": "month1",
    "Q": "quarter",
    "same_day": "day1",
    "next_open": "day3",
    "expiry": "week1",
    "day1": "day1",
    "day3": "day3",
    "week1": "week1",
    "day14": "day14",
    "month1": "month1",
    "quarter": "quarter",
}

# Actions that get a full evolution schedule (not every engine_hold spam).
SCHEDULE_ACTIONS = frozenset({"buy", "sell", "watch", "reduce"})


def checkpoints_for_personality(
    kind: str | None = None,
    *,
    review_schedule: list[str] | None = None,
) -> list[str]:
    """LQ.2 — checkpoint ids for a laboratory personality (swing denser by default)."""
    if review_schedule:
        out: list[str] = []
        seen: set[str] = set()
        for tok in review_schedule:
            cp = _SCHEDULE_TOKEN_MAP.get(str(tok).strip()) or _SCHEDULE_TOKEN_MAP.get(
                str(tok).strip().upper()
            )
            if cp and cp in CHECKPOINT_OFFSETS and cp not in seen:
                seen.add(cp)
                out.append(cp)
        if out:
            return out
    k = str(kind or "swing").strip().lower()
    if k in {"intraday", "equity_intraday"}:
        return ["day1", "day3"]
    if k in {"futures", "options", "f&o"}:
        return ["day1", "day3", "week1"]
    return list(DEFAULT_SWING_CHECKPOINTS)


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
    recent_observations: list[dict[str, Any]] | None = None,
    note: str = "",
    checkpoint: str | None = None,
) -> dict[str, Any]:
    """Diff current evidence vs frozen packet beliefs (DI.2 / LI.3b revisit answers)."""
    packet = packet if isinstance(packet, dict) else {}
    prices = packet.get("prices") if isinstance(packet.get("prices"), dict) else {}
    conf = (
        packet.get("confidence_breakdown")
        if isinstance(packet.get("confidence_breakdown"), dict)
        else {}
    )
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

    # LI.3b / LQ.3 — new observations since decide-time citation
    cited = {str(x) for x in (packet.get("observation_ids") or []) if x}
    obs_rows = [o for o in (recent_observations or []) if isinstance(o, dict)]
    new_obs = [o for o in obs_rows if str(o.get("id") or "") not in cited]
    new_obs_kinds = sorted(
        {str(o.get("kind") or "") for o in new_obs if o.get("kind")}
    )
    mgmt_notes = [
        str((o.get("payload") or {}).get("title") or o.get("kind"))
        for o in new_obs
        if o.get("kind") in {"mgmt_event", "filing_event"}
    ]
    management_note = None
    if mgmt_notes:
        management_note = "; ".join(mgmt_notes[:3])[:300]
        deltas.append(f"mgmt:{management_note[:80]}")

    news_rows = [o for o in new_obs if o.get("kind") == "news_event"]
    news_delta: dict[str, Any] | None = None
    if news_rows:
        titles: list[str] = []
        tags: list[str] = []
        sentiments: list[str] = []
        observed_flags: list[bool] = []
        for o in news_rows[:12]:
            pl = o.get("payload") if isinstance(o.get("payload"), dict) else {}
            t = str(pl.get("text") or pl.get("title") or "").strip()
            if t:
                titles.append(t[:120])
            for tag in pl.get("topic_tags") or []:
                if tag and tag not in tags:
                    tags.append(str(tag))
            sent = str(pl.get("sentiment") or "unknown")
            if sent and sent not in sentiments:
                sentiments.append(sent)
            obm = pl.get("observed_before_move")
            if isinstance(obm, bool):
                observed_flags.append(obm)
        news_delta = {
            "count": len(news_rows),
            "titles": titles[:6],
            "observation_ids": [str(o.get("id")) for o in news_rows[:12] if o.get("id")],
            "topic_tags": tags[:12],
            "sentiment": sentiments[0] if len(sentiments) == 1 else (
                "mixed" if len(sentiments) > 1 else "unknown"
            ),
            "observed_before_move": (
                any(observed_flags) if observed_flags else None
            ),
            "open_book": any(
                bool((o.get("payload") or {}).get("open_book")) for o in news_rows
            ),
        }
        head = titles[0] if titles else "news"
        deltas.append(f"news_delta:{news_delta['count']} {head[:70]}")

    if new_obs:
        deltas.append(
            f"new_observations={len(new_obs)}"
            + (f" kinds={','.join(new_obs_kinds[:6])}" if new_obs_kinds else "")
        )

    # PLC.E — open-book packs + policy + early-vs-wrong (honest unknowns OK)
    pack_ids: list[str] = []
    thesis_status = None
    policy_hits = 0
    sector_rel_pct = None
    rs_vs_nifty = None
    rs_source = None
    # Prefer newest open-book pack (including already-cited) for RS densify
    for o in list(reversed(obs_rows)) + list(reversed(new_obs)):
        pl = o.get("payload") if isinstance(o.get("payload"), dict) else {}
        kind = str(o.get("kind") or "")
        pack_kind = str(pl.get("kind") or "")
        if pack_kind != "open_book_daily_pack" and kind != "open_book_daily_pack":
            continue
        mkt = pl.get("market") if isinstance(pl.get("market"), dict) else {}
        raw_rs = mkt.get("rs_vs_nifty")
        if raw_rs is None:
            continue
        try:
            rs_vs_nifty = float(raw_rs)
            sector_rel_pct = rs_vs_nifty
            rs_source = "open_book_rs_vs_nifty"
            break
        except (TypeError, ValueError):
            continue
    for o in new_obs:
        pl = o.get("payload") if isinstance(o.get("payload"), dict) else {}
        kind = str(o.get("kind") or "")
        pack_kind = str(pl.get("kind") or "")
        if pack_kind == "open_book_daily_pack" or kind == "open_book_daily_pack":
            oid = str(o.get("id") or "")
            if oid:
                pack_ids.append(oid)
            th = pl.get("thesis") if isinstance(pl.get("thesis"), dict) else {}
            st = str(th.get("status") or "").strip().lower()
            if st and st not in {"unknown", "n/a", ""}:
                thesis_status = st
        if kind in {"macro_event", "policy_event"} or pack_kind in {
            "macro_event",
            "policy_event",
        }:
            policy_hits += 1
    if pack_ids:
        deltas.append(f"open_book_packs={len(pack_ids)}")
    if thesis_status:
        deltas.append(f"thesis_status={thesis_status}")
    if policy_hits:
        deltas.append(f"policy_events={policy_hits}")
    if sector_rel_pct is not None:
        deltas.append(f"rs_vs_nifty={sector_rel_pct:+.2f}")

    # Named news densify from open-book pack headlines when news_event rows absent
    if news_delta is None:
        pack_titles: list[str] = []
        pack_sents: list[str] = []
        pack_oids: list[str] = []
        for o in obs_rows:
            pl = o.get("payload") if isinstance(o.get("payload"), dict) else {}
            if str(pl.get("kind") or "") != "open_book_daily_pack":
                continue
            news_pl = pl.get("news") if isinstance(pl.get("news"), dict) else {}
            for bucket in ("company", "sector", "macro", "gov"):
                for item in news_pl.get(bucket) or []:
                    if not isinstance(item, dict):
                        continue
                    t = str(item.get("title") or item.get("text") or "").strip()
                    if t and t not in pack_titles:
                        pack_titles.append(t[:120])
                    s = str(item.get("sentiment") or "").strip()
                    if s and s not in pack_sents:
                        pack_sents.append(s)
                    oid = str(item.get("id") or "")
                    if oid:
                        pack_oids.append(oid)
            for oid in news_pl.get("observation_ids") or []:
                if oid and str(oid) not in pack_oids:
                    pack_oids.append(str(oid))
        if pack_titles:
            news_delta = {
                "count": len(pack_titles),
                "titles": pack_titles[:6],
                "observation_ids": pack_oids[:12],
                "topic_tags": [],
                "sentiment": (
                    pack_sents[0]
                    if len(pack_sents) == 1
                    else ("mixed" if len(pack_sents) > 1 else "unknown")
                ),
                "observed_before_move": None,
                "open_book": True,
                "source": "open_book_pack_headlines",
            }
            deltas.append(f"news_delta:{news_delta['count']} {pack_titles[0][:70]}")

    # Regime densify from open-book pack + direct macro/policy observations
    regime_tags: list[str] = []
    from atlas.investment.decision_packets import normalize_regime_tags
    from atlas.investment.sector_benchmarks import infer_event_regime_tags

    for o in list(reversed(obs_rows)):
        pl = o.get("payload") if isinstance(o.get("payload"), dict) else {}
        kind = str(o.get("kind") or "")
        if str(pl.get("kind") or "") == "open_book_daily_pack":
            mkt = pl.get("market") if isinstance(pl.get("market"), dict) else {}
            raw_tags = mkt.get("regime_tags") or []
            if isinstance(raw_tags, list) and raw_tags:
                regime_tags = normalize_regime_tags(raw_tags)
                if regime_tags:
                    break
        if kind in {"macro_event", "policy_event"}:
            raw = list(pl.get("regime_tags") or [])
            if not raw:
                raw = infer_event_regime_tags(
                    title=str(pl.get("title") or ""),
                    detail=str(pl.get("detail") or ""),
                    sectors=list(pl.get("sectors") or []),
                )
            for t in normalize_regime_tags(raw):
                if t != "unknown" and t not in regime_tags:
                    regime_tags.append(t)
    if regime_tags:
        deltas.append("regime=" + ",".join(regime_tags[:4]))

    thesis_improved = None
    if conf_delta is not None:
        thesis_improved = conf_delta > 0.02
    elif price_chg_pct is not None and packet.get("action") == "buy":
        thesis_improved = price_chg_pct > 0
    elif price_chg_pct is not None and packet.get("action") == "sell":
        thesis_improved = price_chg_pct < 0

    cp = str(checkpoint or "").lower()
    early_vs_wrong = None
    if packet.get("action") == "buy" and price_chg_pct is not None:
        if price_chg_pct <= -5.0 and cp in {"day1", "day3", "week1", ""}:
            early_vs_wrong = "early_pain"
            deltas.append("early_vs_wrong=early_pain")
        elif (
            thesis_improved is False
            and conf_delta is not None
            and conf_delta < -0.05
        ):
            early_vs_wrong = "thesis_weakening"
            deltas.append("early_vs_wrong=thesis_weakening")
        elif thesis_status in {"weakening", "broken", "falsified"}:
            early_vs_wrong = "thesis_weakening"
            deltas.append("early_vs_wrong=thesis_status")

    return {
        "thesis_improved": thesis_improved,
        "confidence_delta": conf_delta,
        "price_change_pct": price_chg_pct,
        "valuation_note": f"mos={mos_now}" if mos_now is not None else None,
        "management_note": management_note,
        "news_delta": news_delta,
        "new_observations": bool(new_obs),
        "new_observation_count": len(new_obs),
        "new_observation_kinds": new_obs_kinds,
        "new_observation_ids": [str(o.get("id")) for o in new_obs[:12] if o.get("id")],
        "open_book_pack_ids": pack_ids[:8],
        "thesis_status": thesis_status,
        "policy_event_count": policy_hits,
        "rs_vs_nifty": rs_vs_nifty,
        "sector_rel_pct": sector_rel_pct,
        "sector_rel_source": rs_source,
        "regime_tags": regime_tags,
        "early_vs_wrong": early_vs_wrong,
        "checkpoint": cp or None,
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

    def schedule_evolution(
        self,
        packet: dict[str, Any],
        *,
        checkpoints: list[str] | None = None,
        personality_kind: str | None = None,
    ) -> int:
        """LQ.2 — schedule denser checkpoints (idempotent per decision+checkpoint)."""
        ts_ist = str(packet.get("ts_ist") or ist_today())
        did = str(packet.get("decision_id") or "")
        symbol = str(packet.get("symbol") or "")
        pk = str(packet.get("portfolio_key") or "unknown")
        if not did or not symbol:
            return 0
        cps = list(checkpoints) if checkpoints else checkpoints_for_personality(
            personality_kind
            or (packet.get("meta") or {}).get("personality_kind")
            or packet.get("laboratory_kind")
        )
        n = 0
        for checkpoint in cps:
            if checkpoint not in CHECKPOINT_OFFSETS:
                continue
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
                    "density": "lq.2",
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
                    and r.get("status") in {"pending", "done", "skipped"}
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
                        # Also treat completed mirrors as already scheduled
                        for existing in self._all_revisit_rows_json():
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

    def _all_revisit_rows_json(self) -> list[dict[str, Any]]:
        if not self._data_dir:
            return []
        root = revisits_root(self._data_dir) / "by_decision"
        if not root.is_dir():
            return []
        out: list[dict[str, Any]] = []
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
                        out.append(doc)
            except Exception:  # noqa: BLE001
                continue
        return out

    def revisits_for_decision(self, decision_id: str) -> dict[str, dict[str, Any]]:
        """Latest revisit row per checkpoint for a decision."""
        did = str(decision_id or "")
        if not did:
            return {}
        latest: dict[str, dict[str, Any]] = {}
        rows = list(self._mem_revisits)
        if self._repo is not None:
            try:
                # Prefer listing due + completed via counts path — scan mem+json fallback
                pass
            except Exception:  # noqa: BLE001
                pass
        if self._data_dir:
            rows.extend(self._all_revisit_rows_json())
        if self._repo is not None:
            try:
                # Use list_due with high limit won't get done; use raw if available
                if hasattr(self._repo, "list_for_decision"):
                    for r in self._repo.list_for_decision(did) or []:
                        rows.append(dict(r))
            except Exception:  # noqa: BLE001
                self._logger.debug("list_for_decision failed", exc_info=True)
        for r in rows:
            if str(r.get("decision_id") or "") != did:
                continue
            cp = str(r.get("checkpoint") or "")
            if cp:
                latest[cp] = r
        return latest

    def ensure_open_book_schedules(
        self,
        *,
        portfolio_key: str,
        open_symbols: list[str] | None = None,
        personality_kind: str | None = None,
        review_schedule: list[str] | None = None,
    ) -> dict[str, Any]:
        """LQ.2 — ensure every open material symbol has denser checkpoint rows.

        Resolves latest buy packet per symbol. Does not invent marks/news —
        only schedules missing due rows (idempotent).
        """
        pk = str(portfolio_key or "").strip()
        syms = [
            str(s).strip().upper()
            for s in (open_symbols or [])
            if str(s).strip()
        ]
        cps = checkpoints_for_personality(
            personality_kind, review_schedule=review_schedule
        )
        ensured = 0
        scheduled_new = 0
        missing_packet = 0
        books: list[dict[str, Any]] = []
        for sym in syms:
            packet = self._latest_buy_packet(sym, portfolio_key=pk)
            if not packet:
                missing_packet += 1
                books.append(
                    {
                        "symbol": sym,
                        "status": "no_buy_packet",
                        "scheduled": 0,
                        "expected": list(cps),
                    }
                )
                continue
            n = self.schedule_evolution(
                packet, checkpoints=cps, personality_kind=personality_kind
            )
            scheduled_new += n
            ensured += 1
            books.append(
                {
                    "symbol": sym,
                    "decision_id": packet.get("decision_id"),
                    "status": "ensured",
                    "scheduled_new": n,
                    "expected": list(cps),
                }
            )
        return {
            "version": "lq.2",
            "portfolio_key": pk,
            "open_symbols": len(syms),
            "books_ensured": ensured,
            "scheduled_new": scheduled_new,
            "missing_buy_packet": missing_packet,
            "checkpoints": list(cps),
            "books": books[:40],
        }

    def _latest_buy_packet(
        self, symbol: str, *, portfolio_key: str | None = None
    ) -> dict[str, Any] | None:
        if self._packets is None:
            return None
        try:
            rows = self._packets.list_symbol(
                symbol=symbol, limit=40, portfolio_key=portfolio_key
            )
        except Exception:  # noqa: BLE001
            return None
        for p in rows or []:
            if not isinstance(p, dict):
                continue
            if str(p.get("action") or "").lower() == "buy":
                return p
        return None

    def open_book_timeline_coverage(
        self,
        *,
        portfolio_key: str,
        open_symbols: list[str] | None = None,
        as_of_ist: str | None = None,
        personality_kind: str | None = None,
        review_schedule: list[str] | None = None,
    ) -> dict[str, Any]:
        """LQ.2 honesty — per open book checkpoint coverage + overdue count."""
        day = as_of_ist or ist_today()
        pk = str(portfolio_key or "").strip()
        syms = [
            str(s).strip().upper()
            for s in (open_symbols or [])
            if str(s).strip()
        ]
        expected = checkpoints_for_personality(
            personality_kind, review_schedule=review_schedule
        )
        books: list[dict[str, Any]] = []
        with_full = 0
        overdue = 0
        for sym in syms:
            packet = self._latest_buy_packet(sym, portfolio_key=pk)
            if not packet:
                books.append(
                    {
                        "symbol": sym,
                        "status": "no_buy_packet",
                        "missing": list(expected),
                        "pending": [],
                        "done": [],
                        "next_due": None,
                    }
                )
                continue
            did = str(packet.get("decision_id") or "")
            by_cp = self.revisits_for_decision(did)
            missing = [c for c in expected if c not in by_cp]
            pending = [
                c
                for c in expected
                if (by_cp.get(c) or {}).get("status", "pending") == "pending"
            ]
            done = [
                c for c in expected if (by_cp.get(c) or {}).get("status") == "done"
            ]
            overdue_cps = [
                c
                for c in pending
                if str((by_cp.get(c) or {}).get("due_ist") or "") <= day
            ]
            overdue += len(overdue_cps)
            if not missing and expected:
                with_full += 1
            next_due = None
            for c in expected:
                row = by_cp.get(c) or {}
                if row.get("status", "pending") == "pending":
                    next_due = {"checkpoint": c, "due_ist": row.get("due_ist")}
                    break
            books.append(
                {
                    "symbol": sym,
                    "decision_id": did,
                    "status": "full" if not missing else "partial",
                    "missing": missing,
                    "pending": pending,
                    "done": done,
                    "overdue": overdue_cps,
                    "next_due": next_due,
                }
            )
        return {
            "version": "lq.2",
            "as_of_ist": day,
            "portfolio_key": pk,
            "open_books": len(syms),
            "open_books_with_full_schedule": with_full,
            "overdue_revisits": overdue,
            "expected_checkpoints": list(expected),
            "books": books[:40],
        }

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
        done_row = {**revisit, "status": "done", "payload": {
            **(revisit.get("payload") or {}),
            **payload_update,
        }}
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
        # LI.3a — always mirror done so evening JSON counts match Postgres drain
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
        observations_fn: Any | None = None,
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
            recent_obs: list[dict[str, Any]] = []
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
                        if aw.get("recent_observations"):
                            recent_obs = list(aw.get("recent_observations") or [])
                except Exception:  # noqa: BLE001
                    pass
            if observations_fn is not None and sym and not recent_obs:
                try:
                    recent_obs = list(observations_fn(sym) or [])
                except Exception:  # noqa: BLE001
                    recent_obs = []
            diff = what_changed(
                packet,
                current_mark=mark,
                current_score=score if isinstance(score, dict) else None,
                current_valuation=valuation if isinstance(valuation, dict) else None,
                current_unknowns=unknowns,
                recent_observations=recent_obs,
                note=f"auto {rev.get('checkpoint')}",
                checkpoint=str(rev.get("checkpoint") or ""),
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
        day = ist_today()
        if self._repo is not None:
            try:
                c = self._repo.counts(portfolio_key=portfolio_key)
                due_today = 0
                pending_future = 0
                try:
                    split = self._repo.pending_due_split(
                        as_of_ist=day, portfolio_key=portfolio_key
                    )
                    due_today = int(split.get("due_today") or 0)
                    pending_future = int(split.get("pending_future") or 0)
                except Exception:  # noqa: BLE001
                    self._logger.debug("pending_due_split failed", exc_info=True)
                return {
                    "pending_revisits": c.get("pending", 0),
                    "done_revisits": c.get("done", 0),
                    "skipped_revisits": c.get("skipped", 0),
                    "revisits_due_today": due_today,
                    "pending_future": pending_future,
                    "open_evolution": c.get("pending", 0),
                    "closed_checkpoints": c.get("done", 0) + c.get("skipped", 0),
                    "density": "lq.2",
                    "as_of_ist": day,
                    "honesty": (
                        "0 done with only future due dates ≠ mission dead — "
                        "checkpoints wait for due_ist"
                    ),
                }
            except Exception:  # noqa: BLE001
                self._logger.debug("learning_counts repo failed", exc_info=True)
        all_rows = list(self._mem_revisits)
        if self._data_dir:
            all_rows.extend(self._all_revisit_rows_json())
        # Dedupe by (decision_id, checkpoint) keeping last status
        latest: dict[tuple[str, str], dict[str, Any]] = {}
        for r in all_rows:
            if portfolio_key and r.get("portfolio_key") != portfolio_key:
                continue
            key = (str(r.get("decision_id") or ""), str(r.get("checkpoint") or ""))
            if key[0] and key[1]:
                latest[key] = r
        pending_rows = [
            r for r in latest.values() if r.get("status", "pending") == "pending"
        ]
        pending = len(pending_rows)
        done = sum(1 for r in latest.values() if r.get("status") == "done")
        skipped = sum(1 for r in latest.values() if r.get("status") == "skipped")
        due_today = sum(
            1 for r in pending_rows if str(r.get("due_ist") or "") <= day
        )
        pending_future = sum(
            1 for r in pending_rows if str(r.get("due_ist") or "") > day
        )
        return {
            "pending_revisits": pending,
            "done_revisits": done,
            "skipped_revisits": skipped,
            "revisits_due_today": due_today,
            "pending_future": pending_future,
            "open_evolution": pending,
            "closed_checkpoints": done + skipped,
            "density": "lq.2",
            "as_of_ist": day,
            "honesty": (
                "0 done with only future due dates ≠ mission dead — "
                "checkpoints wait for due_ist"
            ),
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
    due = counts.get("revisits_due_today")
    future = counts.get("pending_future")
    lines = [
        "",
        "Decision evolution (DI.2 / LQ.2 / PLC.E honesty):",
        f"  Due today: {due if due is not None else '—'}",
        f"  Pending future (not yet due): {future if future is not None else '—'}",
        f"  Open revisits pending (total): {counts.get('pending_revisits', 0)}",
        f"  Checkpoints completed: {counts.get('done_revisits', 0)}",
    ]
    if counts.get("skipped_revisits"):
        lines.append(f"  Checkpoints skipped: {counts.get('skipped_revisits')}")
    if (
        int(counts.get("done_revisits") or 0) == 0
        and int(future or 0) > 0
        and int(due or 0) == 0
    ):
        lines.append(
            "  Note: 0 done + all future due dates ≠ mission dead — waiting on due_ist"
        )
    if counts.get("open_books") is not None:
        lines.append(
            f"  Open books with full schedule: "
            f"{counts.get('open_books_with_full_schedule', 0)}/"
            f"{counts.get('open_books', 0)}"
        )
    if counts.get("overdue_revisits") is not None:
        lines.append(f"  Overdue revisits: {counts.get('overdue_revisits')}")
    if counts.get("host_guard_reason"):
        lines.append(
            f"  Host Guard: {counts.get('host_guard_reason')} "
            f"(budget={counts.get('host_guard_budget', '—')})"
        )
    return lines
