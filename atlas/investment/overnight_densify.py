"""OI-CU0 CU.C — overnight news densify (18:30–07:30 IST).

Connect existing RSS / curiosity / research_intelligence — not a second news product.
Acquire without Ollama; LOW LLM only inside the overnight window with free lane (CU.A).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from atlas.investment.llm_lanes import in_overnight_window
from atlas.investment.research_intelligence import drain_news_curiosity, research_roi_gate

VERSION = "cu0.overnight_densify.v1"
STORE_REL = Path("investment") / "overnight"
_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.overnight_densify")

_LABS = (
    "india_equity_learner",
    "india_fno_learner",
    "equity_intraday_learner",
)


def ist_now() -> datetime:
    return datetime.now(_IST)


def ist_today() -> str:
    return ist_now().strftime("%Y-%m-%d")


def day_path(data_dir: str | Path | None, as_of_ist: str | None = None) -> Path | None:
    if not data_dir:
        return None
    return Path(data_dir) / STORE_REL / f"{as_of_ist or ist_today()}.json"


def allow_low_llm(*, now: datetime | None = None) -> bool:
    """C1/C5 — LOW LLM only inside overnight window (stop by 07:30)."""
    return in_overnight_window(now)


def resolve_overnight_symbol_set(
    data_dir: str | Path | None,
    *,
    laboratory_ids: tuple[str, ...] | list[str] | None = None,
    open_symbols: list[str] | None = None,
    as_of_ist: str | None = None,
    portfolio: Any | None = None,
) -> dict[str, Any]:
    """C2 — open books ∪ allocation blockers (not full-universe scrape)."""
    from atlas.investment.capital_allocation import (
        allocation_blocking_unknowns,
        load_allocation_table,
    )

    labs = tuple(laboratory_ids or _LABS)
    day = as_of_ist or ist_today()
    open_set: set[str] = {str(s).upper() for s in (open_symbols or []) if s}
    blockers: list[dict[str, Any]] = []

    if portfolio is not None and not open_set:
        try:
            from atlas.investment.open_book_packs import resolve_open_symbols

            for lab in labs:
                for s in resolve_open_symbols(
                    portfolio=portfolio, portfolio_key=lab, limit=40
                ):
                    open_set.add(str(s).upper())
        except Exception:  # noqa: BLE001
            _log.debug("open symbol resolve skipped", exc_info=True)

    for lab in labs:
        table = load_allocation_table(data_dir, lab, as_of_ist=day)
        for b in allocation_blocking_unknowns(table):
            if not isinstance(b, dict):
                continue
            blockers.append({**b, "laboratory_id": lab})
            sym = str(b.get("symbol") or "").strip().upper()
            if sym:
                open_set.add(sym)

    return {
        "version": VERSION,
        "as_of_ist": day,
        "symbols": sorted(open_set),
        "blockers": blockers[:40],
        "laboratories": list(labs),
        "honesty": (
            "Symbol set = open books + allocation blockers only — "
            "not a full-universe scrape."
        ),
    }


def _stamp_item(item: dict[str, Any]) -> dict[str, Any]:
    out = dict(item)
    try:
        from atlas.investment.market_events import classify_source_tier

        tier = classify_source_tier(
            source=str(out.get("source") or "") or None,
            feed_id=str(out.get("feed_id") or "") or None,
            url=str(out.get("link") or "") or None,
            kind=str(out.get("kind") or "") or None,
        )
        out["source_tier"] = out.get("source_tier") or tier
    except Exception:  # noqa: BLE001
        out.setdefault("source_tier", 3)
    out.setdefault("retrieved_at", datetime.now(timezone.utc).isoformat())
    return out


def _item_relevant(item: dict[str, Any], symbols: set[str]) -> bool:
    kind = str(item.get("kind") or "").lower()
    source = str(item.get("source") or "").lower()
    if kind in {"policy", "gov", "budget"} or "policy" in source or "pib" in source:
        return True
    sym = str(item.get("symbol") or "").strip().upper()
    if sym and (not symbols or sym in symbols):
        return True
    if not symbols:
        return True
    text = str(item.get("text") or item.get("title") or "").upper()
    for s in symbols:
        bare = s.replace(".NS", "").replace(".BO", "")
        if bare and re.search(rf"\b{re.escape(bare)}\b", text):
            return True
    return False


def acquire_rss_batch(
    data_dir: str | Path | None,
    *,
    rss_enable: list[str] | None = None,
    max_per_feed: int = 12,
    opener: Any | None = None,
) -> dict[str, Any]:
    """HIGH — fetch allow-list RSS with no Ollama."""
    from atlas.investment import rss_feeds as rss

    enable = {str(x).strip() for x in (rss_enable or ["pib_press"]) if str(x).strip()}
    feeds = rss.merge_allowlist(None, include_defaults=True)
    for row in feeds:
        if row.get("id") in enable:
            row["enabled"] = True
    kwargs: dict[str, Any] = {"max_per_feed": max_per_feed}
    if opener is not None:
        kwargs["opener"] = opener
    result = rss.fetch_allowlist(feeds, kinds=None, **kwargs)
    if data_dir:
        try:
            rss.save_last_fetch(str(data_dir), result)
        except Exception:  # noqa: BLE001
            pass
    news = [_stamp_item(x) for x in rss.items_as_news(result)]
    policy = [_stamp_item(x) for x in rss.items_as_policy(result)]
    return {
        "ok_feeds": result.get("ok_feeds"),
        "feed_count": len(result.get("feeds") or []),
        "item_count": int(result.get("item_count") or 0),
        "news_items": news,
        "policy_items": policy,
        "feeds": result.get("feeds"),
        "honesty": "RSS allow-list only — no HTML scrape, no invented headlines.",
    }


def _ensure_news_curiosity_items(
    queue_doc: dict[str, Any],
    *,
    symbols: list[str],
    blockers: list[dict[str, Any]],
    laboratory_id: str,
) -> dict[str, Any]:
    doc = dict(queue_doc or {})
    items = [i for i in (doc.get("items") or []) if isinstance(i, dict)]
    existing = {
        (str(i.get("symbol") or "").upper(), str(i.get("unknown") or "").lower())
        for i in items
    }
    added = 0
    for sym in symbols:
        for unk in ("news", "policy"):
            gate = research_roi_gate(
                unk,
                symbol=sym,
                allocation_blockers=blockers,
                is_open=True,
            )
            if not gate.get("admit"):
                continue
            key = (sym.upper(), unk)
            if key in existing:
                continue
            items.append(
                {
                    "symbol": sym,
                    "unknown": unk,
                    "status": "queued",
                    "source": "overnight_densify",
                    "laboratory_id": laboratory_id,
                    "roi": gate,
                }
            )
            existing.add(key)
            added += 1
    doc["items"] = items
    doc["overnight_enqueued"] = int(doc.get("overnight_enqueued") or 0) + added
    return doc


def run_overnight_densify(
    data_dir: str | Path | None,
    *,
    as_of_ist: str | None = None,
    now: datetime | None = None,
    portfolio: Any | None = None,
    open_symbols: list[str] | None = None,
    rss_enable: list[str] | None = None,
    allow_llm: bool = False,
    llm: Any | None = None,
    opener: Any | None = None,
    force: bool = False,
    icr5_drain_passes: int = 3,
    bre3_drain_passes: int = 2,
) -> dict[str, Any]:
    """Full CU.C pass. Outside window → skipped (unless force for tests)."""
    day = as_of_ist or ist_today()
    when = now or ist_now()
    if not force and not in_overnight_window(when):
        return {
            "version": VERSION,
            "ok": True,
            "skipped": True,
            "reason": "outside_overnight_window",
            "window": "18:30–07:30 IST",
            "as_of_ist": day,
            "honesty": "Overnight densify only runs 18:30–07:30 IST (CU.C1).",
        }

    symbol_doc = resolve_overnight_symbol_set(
        data_dir,
        open_symbols=open_symbols,
        as_of_ist=day,
        portfolio=portfolio,
    )
    symbols = list(symbol_doc.get("symbols") or [])
    blockers = list(symbol_doc.get("blockers") or [])
    sym_set = {str(s).upper() for s in symbols}

    scientist_compact: dict[str, Any] = {}
    try:
        from atlas.investment.incumbent_scientist import compact_legacy_scientist_notes

        for lab in _LABS:
            scientist_compact[lab] = compact_legacy_scientist_notes(
                data_dir, laboratory_id=lab, dry_run=False
            )
    except Exception:  # noqa: BLE001
        _log.debug("overnight scientist note compact skipped", exc_info=True)

    rss = acquire_rss_batch(data_dir, rss_enable=rss_enable, opener=opener)
    news_kept = [
        i
        for i in (rss.get("news_items") or [])
        if isinstance(i, dict) and _item_relevant(i, sym_set)
    ]
    policy_kept = [i for i in (rss.get("policy_items") or []) if isinstance(i, dict)]

    observations_recorded = 0
    if data_dir and (news_kept or policy_kept):
        try:
            from atlas.investment.observations import (
                DecisionObservationStore,
                infer_news_topic_tags,
                normalize_news_sentiment,
            )

            store = DecisionObservationStore(data_dir=str(data_dir))
            for item in (news_kept + policy_kept)[:40]:
                text = str(item.get("text") or item.get("title") or "").strip()
                if len(text) < 12:
                    continue
                store.record_news_event(
                    text=text,
                    symbol=str(item.get("symbol") or "") or None,
                    source=str(item.get("source") or "overnight_rss"),
                    topic_tags=list(
                        item.get("topic_tags") or infer_news_topic_tags(text) or []
                    ),
                    sentiment=normalize_news_sentiment(item.get("sentiment")),
                    link=str(item.get("link") or "") or None,
                    open_book=bool(str(item.get("symbol") or "").upper() in sym_set),
                    extra={
                        "cu": "cu.c",
                        "source_tier": item.get("source_tier"),
                        "feed_id": item.get("feed_id"),
                        "kind": item.get("kind") or "news_event",
                        "overnight": True,
                    },
                )
                observations_recorded += 1
        except Exception:  # noqa: BLE001
            _log.debug("overnight observation record skipped", exc_info=True)

    # OI-WEB-EVID0 Phase A — open-book DuckDuckGo search → durable candidates
    web_evid: dict[str, Any] = {"skipped": "not_run"}
    try:
        from atlas.investment.open_book_web_evidence import (
            densify_open_book_web_evidence,
        )

        web_evid = densify_open_book_web_evidence(
            str(data_dir) if data_dir else None,
            symbols,
            max_symbols=3,
            max_hits=4,
            laboratory_id="india_equity_learner",
        )
        observations_recorded += int(web_evid.get("hits_stored") or 0)
    except Exception:  # noqa: BLE001
        _log.debug("overnight open-book web evidence skipped", exc_info=True)
        web_evid = {"skipped": "error", "ok": False}

    drains: dict[str, Any] = {}
    try:
        from atlas.investment import curiosity as cur

        qdoc = cur.load_queue(data_dir, day)
        if not isinstance(qdoc, dict):
            qdoc = {"items": [], "ist_date": day}
        qdoc.setdefault("ist_date", day)
        # Enqueue once for primary swing lab; drain once (global day queue)
        qdoc = _ensure_news_curiosity_items(
            qdoc,
            symbols=symbols,
            blockers=blockers,
            laboratory_id="india_equity_learner",
        )
        qdoc = drain_news_curiosity(
            qdoc, str(data_dir) if data_dir else None, laboratory_id="india_equity_learner"
        )
        cur.save_queue(data_dir, qdoc)
        drains["india_equity_learner"] = qdoc.get("news_drain") or {}
        drains["overnight_enqueued"] = qdoc.get("overnight_enqueued")
    except Exception:  # noqa: BLE001
        _log.debug("overnight curiosity drain skipped", exc_info=True)
        drains["error"] = "drain_failed"

    llm_pass: dict[str, Any] = {
        "attempted": False,
        "skipped": True,
        "reason": "low_llm_deferred_default",
    }
    if allow_llm and allow_low_llm(now=when) and llm is not None:
        try:
            busy = hasattr(llm, "lane_busy") and llm.lane_busy()
        except Exception:  # noqa: BLE001
            busy = True
        if busy:
            llm_pass = {
                "attempted": False,
                "skipped": True,
                "reason": "lane_busy_cu_a2",
                "honesty": "Never starve chat/market — LOW overnight LLM deferred.",
            }
        else:
            llm_pass = {
                "attempted": False,
                "skipped": True,
                "reason": "synthesis_not_required",
                "honesty": (
                    "Acquire/extract complete without LLM. "
                    "No invented thesis from overnight pass."
                ),
            }
            # Off-market densify — drain ICR5/BRE3 under free overnight lane
            try:
                from atlas.investment.incumbent_scientist import (
                    drain_pending_scientist_notes,
                )
                from atlas.investment.decide_rationale import drain_pending_rationales

                sci_n = max(1, min(int(icr5_drain_passes or 3), 8))
                bre_n = max(1, min(int(bre3_drain_passes or 2), 5))
                sci_drains: dict[str, Any] = {}
                bre_drains: dict[str, Any] = {}
                for lab in _LABS:
                    sci_drains[lab] = drain_pending_scientist_notes(
                        data_dir,
                        laboratory_id=lab,
                        llm=llm,
                        max_passes=sci_n,
                        limit=max(sci_n, 8),
                    )
                    bre_drains[lab] = drain_pending_rationales(
                        data_dir,
                        laboratory_id=lab,
                        llm=llm,
                        max_passes=bre_n,
                        limit=max(bre_n, 6),
                    )
                llm_pass = {
                    "attempted": True,
                    "skipped": False,
                    "reason": "icr5_bre3_drain",
                    "scientist": sci_drains,
                    "decide_rationale": bre_drains,
                    "honesty": (
                        f"Overnight LOW LLM: ≤{sci_n} ICR5 + ≤{bre_n} BRE3 "
                        "passes per lab when lane free — research backlog densify."
                    ),
                }
            except Exception:  # noqa: BLE001
                _log.debug("overnight ICR5/BRE3 drain skipped", exc_info=True)

            # OI-LEARN-AUDIT0 — refresh instrument after overnight densify
            try:
                from atlas.investment.learning_audit import (
                    build_and_persist_learning_audit,
                )

                llm_pass["learning_audit"] = {}
                llm_pass["weekly_learning_report"] = {}
                for lab in _LABS:
                    aud = build_and_persist_learning_audit(
                        data_dir, laboratory_id=lab, as_of_ist=day
                    )
                    try:
                        from atlas.investment.learning_audit import (
                            build_and_persist_weekly_learning_report,
                        )

                        wk = build_and_persist_weekly_learning_report(
                            data_dir,
                            laboratory_id=lab,
                            as_of_ist=day,
                            ensure_dailies=False,
                        )
                        llm_pass["weekly_learning_report"][lab] = {
                            "week": wk.get("week"),
                            "overall_state": wk.get("overall_state"),
                            "learning_record_n": wk.get("learning_record_n"),
                        }
                    except Exception:  # noqa: BLE001
                        _log.debug("LA.2 weekly report skipped", exc_info=True)
                    llm_pass["learning_audit"][lab] = {
                        "overall_state": aud.get("overall_state"),
                        "learning_record_n": aud.get("learning_record_n"),
                    }
                    try:
                        from atlas.investment.l5_validation import promote_lab_l3_records

                        promo = promote_lab_l3_records(
                            data_dir, laboratory_id=lab, as_of_ist=day
                        )
                        llm_pass.setdefault("l3_to_l5", {})[lab] = {
                            "created_n": promo.get("created_n"),
                            "l5_claimed": False,
                        }
                    except Exception:  # noqa: BLE001
                        _log.debug("overnight l3→l5 promote skipped", exc_info=True)
            except Exception:  # noqa: BLE001
                _log.debug("overnight learning audit skipped", exc_info=True)

    found = int(rss.get("item_count") or 0) + observations_recorded
    doc: dict[str, Any] = {
        "version": VERSION,
        "kind": "OVERNIGHT_DENSIFY",
        "as_of_ist": day,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "window": "18:30–07:30 IST",
        "skipped": False,
        "symbol_set": symbol_doc,
        "rss": {
            "ok_feeds": rss.get("ok_feeds"),
            "feed_count": rss.get("feed_count"),
            "item_count": rss.get("item_count"),
            "news_kept": len(news_kept),
            "policy_kept": len(policy_kept),
        },
        "observations_recorded": observations_recorded,
        "web_evidence": web_evid,
        "news_drains": drains,
        "scientist_compact": scientist_compact,
        "llm": llm_pass,
        "intake": {
            "attempted": True,
            "items_found": found,
            "status": "items_found" if found > 0 else "unknown_explicit_after_attempt",
        },
        "honesty": (
            "Overnight densify: try real feeds; empty after attempt → "
            "unknown_explicit — never invent PE/FCF/news/thesis."
        ),
    }
    path = day_path(data_dir, day)
    if path is not None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
            doc["path"] = str(path)
        except OSError:
            _log.debug("overnight densify persist failed", exc_info=True)
    return doc


def load_overnight_densify(
    data_dir: str | Path | None, *, as_of_ist: str | None = None
) -> dict[str, Any] | None:
    path = day_path(data_dir, as_of_ist)
    if path is None or not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def format_overnight_morning_lines(doc: dict[str, Any] | None) -> list[str]:
    """C4 — morning-visible overnight intake (no invented thesis change)."""
    lines = ["", "── Overnight densify (OI-CU0 CU.C) ──"]
    if not isinstance(doc, dict) or doc.get("skipped"):
        reason = (doc or {}).get("reason") if isinstance(doc, dict) else "none"
        lines.append(f"  no overnight intake file yet (reason={reason or 'missing'})")
        lines.append(
            "  Honesty: silent zero without trying is not allowed once CU.C runs."
        )
        return lines
    intake = doc.get("intake") if isinstance(doc.get("intake"), dict) else {}
    rss = doc.get("rss") if isinstance(doc.get("rss"), dict) else {}
    syms = (
        (doc.get("symbol_set") or {}).get("symbols")
        if isinstance(doc.get("symbol_set"), dict)
        else []
    )
    lines.append(
        f"  day={doc.get('as_of_ist')} · status={intake.get('status')} · "
        f"symbols={len(syms or [])}"
    )
    lines.append(
        f"  RSS: ok_feeds={rss.get('ok_feeds')}/{rss.get('feed_count')} · "
        f"items={rss.get('item_count')} · kept news={rss.get('news_kept')} "
        f"policy={rss.get('policy_kept')} · obs_recorded={doc.get('observations_recorded', 0)}"
    )
    drains = doc.get("news_drains") if isinstance(doc.get("news_drains"), dict) else {}
    if drains and isinstance(drains.get("india_equity_learner"), dict):
        d = drains["india_equity_learner"]
        lines.append(
            f"  news drain: resolved={d.get('resolved', 0)} · "
            f"unknown_explicit={d.get('unknown_explicit', 0)} · "
            f"enqueued={drains.get('overnight_enqueued', 0)}"
        )
    llm = doc.get("llm") if isinstance(doc.get("llm"), dict) else {}
    lines.append(
        f"  LOW LLM: skipped={llm.get('skipped', True)} reason={llm.get('reason')}"
    )
    lines.append(str(doc.get("honesty") or ""))
    return lines
