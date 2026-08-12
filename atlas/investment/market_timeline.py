"""OI-MTL0 — Market Timeline (open-book MVP).

Aligns what Atlas knew on a day across lanes:

  Price · Technical · Fundamentals · Sector · Market · News · Policy · Atlas

Missing lanes stay ``unknown`` (never invent). Used for revisit honesty and
evening mail — bridge from event logging to learning.

Layout::
    {data}/market/timelines/{laboratory_id}/{as_of_ist}.jsonl
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "rld.mtl.v1"
_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.market_timeline")


def ist_today() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def timeline_dir(
    data_dir: str | Path | None, laboratory_id: str = "india_equity_learner"
) -> Path | None:
    if not data_dir:
        return None
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in laboratory_id)[
        :80
    ]
    return Path(data_dir) / "market" / "timelines" / (safe or "india_equity_learner")


def timeline_day_path(
    data_dir: str | Path | None,
    *,
    laboratory_id: str = "india_equity_learner",
    as_of_ist: str | None = None,
) -> Path | None:
    root = timeline_dir(data_dir, laboratory_id)
    if root is None:
        return None
    return root / f"{(as_of_ist or ist_today()).strip()}.jsonl"


def _sma(closes: list[float], n: int) -> float | None:
    if len(closes) < n or n <= 0:
        return None
    return round(sum(closes[-n:]) / float(n), 4)


def _rsi(closes: list[float], n: int = 14) -> float | None:
    if len(closes) < n + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(-n, 0):
        d = closes[i] - closes[i - 1]
        if d >= 0:
            gains += d
        else:
            losses -= d
    if losses == 0:
        return 100.0
    rs = (gains / n) / (losses / n)
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def _vol_pct(closes: list[float], n: int = 20) -> float | None:
    if len(closes) < n + 1:
        return None
    rets: list[float] = []
    for i in range(-n, 0):
        prev = closes[i - 1]
        if prev == 0:
            continue
        rets.append((closes[i] - prev) / abs(prev))
    if len(rets) < max(5, n // 2):
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    return round(100.0 * math.sqrt(var), 3)


def _lane_unknown(*keys: str) -> dict[str, Any]:
    return {"status": "unknown", "missing": list(keys)}


def build_symbol_timeline(
    *,
    symbol: str,
    as_of_ist: str | None = None,
    bars: list[dict[str, Any]] | None = None,
    fundamentals: dict[str, Any] | None = None,
    open_book_pack: dict[str, Any] | None = None,
    sector: str | None = None,
    nifty_last: float | None = None,
    nifty_ret_pct: float | None = None,
    decisions: list[dict[str, Any]] | None = None,
    thesis: dict[str, Any] | None = None,
    news: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One-day multi-lane snapshot for a symbol. Missing → unknown."""
    day = (as_of_ist or ist_today()).strip()
    sym = str(symbol or "").strip().upper()
    unknowns: list[str] = []
    pack = open_book_pack if isinstance(open_book_pack, dict) else {}

    # --- Price ---
    closes: list[float] = []
    last_px = None
    last_date = None
    for b in bars or []:
        if not isinstance(b, dict):
            continue
        c = b.get("close")
        if c is None:
            continue
        try:
            closes.append(float(c))
        except (TypeError, ValueError):
            continue
        last_px = closes[-1]
        last_date = str(b.get("date") or b.get("ts") or "")[:10] or last_date
    ret_1d = None
    if len(closes) >= 2 and closes[-2] != 0:
        ret_1d = round(100.0 * (closes[-1] - closes[-2]) / abs(closes[-2]), 3)
    if last_px is None and isinstance(pack.get("market"), dict):
        last_px = pack["market"].get("last_close") or pack["market"].get("close")
        ret_1d = pack["market"].get("return_1d_pct") or ret_1d
    price_lane: dict[str, Any]
    if last_px is None:
        price_lane = _lane_unknown("last_price")
        unknowns.append("price")
    else:
        price_lane = {
            "status": "ok",
            "last_price": last_px,
            "last_date": last_date,
            "return_1d_pct": ret_1d,
            "bar_count": len(closes),
        }

    # --- Technical ---
    sma20 = _sma(closes, 20)
    sma50 = _sma(closes, 50) if len(closes) >= 50 else _sma(closes, min(40, len(closes))) if len(closes) >= 20 else None
    rsi14 = _rsi(closes, 14)
    vol20 = _vol_pct(closes, 20)
    tech: dict[str, Any] = {"status": "ok"}
    if sma20 is not None:
        tech["sma20"] = sma20
    if sma50 is not None:
        tech["sma50"] = sma50
    if rsi14 is not None:
        tech["rsi14"] = rsi14
    if vol20 is not None:
        tech["vol20_pct"] = vol20
    if last_px is not None and sma20 is not None:
        tech["above_sma20"] = bool(last_px >= sma20)
    if len(tech) <= 1:
        tech = _lane_unknown("sma", "rsi", "volatility")
        unknowns.append("technical")

    # --- Fundamentals ---
    fund = fundamentals if isinstance(fundamentals, dict) else {}
    if not fund and isinstance(pack.get("fundamentals"), dict):
        fund = pack["fundamentals"]
    fund_fields = {
        "pe": fund.get("pe"),
        "fcf": fund.get("fcf") or fund.get("free_cash_flow"),
        "roe": fund.get("roe"),
        "pb": fund.get("pb"),
        "roic": fund.get("roic"),
        "debt_to_equity": fund.get("debt_to_equity"),
    }
    present = {k: v for k, v in fund_fields.items() if v is not None}
    missing_f = [k for k, v in fund_fields.items() if v is None]
    if present:
        fund_lane: dict[str, Any] = {
            "status": "partial" if missing_f else "ok",
            **present,
        }
        if missing_f:
            fund_lane["missing"] = missing_f
            unknowns.extend(f"fundamentals.{m}" for m in missing_f)
    else:
        fund_lane = _lane_unknown("pe", "fcf", "roe")
        unknowns.append("fundamentals")

    # --- Sector ---
    sector_lane: dict[str, Any]
    mkt_pack = pack.get("market") if isinstance(pack.get("market"), dict) else {}
    rs = mkt_pack.get("rs_vs_benchmark_pct")
    bench = mkt_pack.get("benchmark_symbol")
    if sector or rs is not None or bench:
        sector_lane = {
            "status": "ok" if rs is not None else "partial",
            "sector": sector,
            "benchmark": bench,
            "rs_vs_benchmark_pct": rs,
        }
        if rs is None:
            unknowns.append("sector_rs")
    else:
        sector_lane = _lane_unknown("sector", "relative_strength")
        unknowns.append("sector")

    # --- Market (NIFTY / regime) ---
    regime = mkt_pack.get("regime_tags") or []
    if nifty_last is not None or nifty_ret_pct is not None or regime:
        market_lane: dict[str, Any] = {
            "status": "ok",
            "nifty_last": nifty_last,
            "nifty_return_1d_pct": nifty_ret_pct,
            "regime_tags": list(regime)[:8] if regime else [],
        }
    else:
        market_lane = _lane_unknown("nifty", "regime")
        unknowns.append("market")

    # --- News ---
    news_doc = news if isinstance(news, dict) else (
        pack.get("news") if isinstance(pack.get("news"), dict) else {}
    )
    company_n = len(news_doc.get("company") or [])
    if company_n or news_doc.get("observation_ids"):
        news_lane: dict[str, Any] = {
            "status": "ok" if company_n else "partial",
            "company_headlines": (news_doc.get("company") or [])[:3],
            "sector_headlines": (news_doc.get("sector") or [])[:2],
            "unknowns": list(news_doc.get("unknowns") or []),
        }
        if not company_n:
            unknowns.append("news")
    else:
        news_lane = _lane_unknown("company_news", "sector_news")
        unknowns.append("news")

    # --- Policy ---
    pol = policy if isinstance(policy, dict) else {}
    gov_items = news_doc.get("gov") if isinstance(news_doc, dict) else None
    if pol or gov_items:
        policy_lane: dict[str, Any] = {
            "status": "ok" if (pol or gov_items) else "unknown",
            "events": list(gov_items or [])[:3],
            **({k: pol[k] for k in list(pol)[:6]} if pol else {}),
        }
    else:
        policy_lane = _lane_unknown("policy_events")
        unknowns.append("policy")

    # --- Atlas belief / decision ---
    thesis_doc = thesis if isinstance(thesis, dict) else (
        pack.get("thesis") if isinstance(pack.get("thesis"), dict) else {}
    )
    conf = pack.get("confidence") if isinstance(pack.get("confidence"), dict) else {}
    dec_rows = [d for d in (decisions or []) if isinstance(d, dict)]
    last_dec = dec_rows[-1] if dec_rows else None
    atlas_lane: dict[str, Any] = {
        "status": "ok" if (thesis_doc or last_dec or conf) else "unknown",
        "thesis_stance": thesis_doc.get("stance") or thesis_doc.get("path"),
        "thesis_summary": (thesis_doc.get("summary") or thesis_doc.get("thesis") or "")[
            :180
        ]
        or None,
        "confidence": conf.get("label") or conf.get("confidence") or thesis_doc.get(
            "confidence"
        ),
        "last_action": (last_dec or {}).get("action"),
        "last_strategy_tag": (last_dec or {}).get("strategy_tag"),
        "decision_id": (last_dec or {}).get("decision_id"),
    }
    if atlas_lane["status"] == "unknown":
        unknowns.append("atlas_belief")

    revisit_qs = [
        "What changed since the prior pack / decision?",
        "What did Atlas know (which lanes were OK vs unknown)?",
        "What did Atlas believe (thesis / confidence)?",
        "What actually moved price / fundamentals?",
        "Which lane best explains the move (with evidence)?",
        "Was the decision correct vs thesis falsifiers?",
        "What remains unknown / data required?",
    ]

    return {
        "version": VERSION,
        "kind": "open_book_market_timeline",
        "symbol": sym,
        "as_of_ist": day,
        "lanes": {
            "price": price_lane,
            "technical": tech,
            "fundamentals": fund_lane,
            "sector": sector_lane,
            "market": market_lane,
            "news": news_lane,
            "policy": policy_lane,
            "atlas": atlas_lane,
        },
        "unknowns": sorted(set(unknowns)),
        "revisit_questions": revisit_qs,
        "honesty": (
            "Market Timeline MVP — lanes with missing evidence stay unknown. "
            "Unknown ≠ learning. Expand to full watchlist after open books stabilize."
        ),
    }


def persist_timeline_day(
    data_dir: str | Path | None,
    rows: list[dict[str, Any]],
    *,
    laboratory_id: str = "india_equity_learner",
    as_of_ist: str | None = None,
) -> dict[str, Any]:
    path = timeline_day_path(
        data_dir, laboratory_id=laboratory_id, as_of_ist=as_of_ist
    )
    if path is None:
        return {"ok": False, "reason": "no_data_dir"}
    path.parent.mkdir(parents=True, exist_ok=True)
    day = (as_of_ist or ist_today()).strip()
    meta = {
        "version": VERSION,
        "kind": "timeline_day_meta",
        "as_of_ist": day,
        "laboratory_id": laboratory_id,
        "count": len(rows),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(meta, default=str) + "\n")
        for row in rows:
            if isinstance(row, dict):
                fh.write(json.dumps(row, default=str) + "\n")
    return {"ok": True, "path": str(path), "count": len(rows), "as_of_ist": day}


def load_timeline_day(
    data_dir: str | Path | None,
    *,
    laboratory_id: str = "india_equity_learner",
    as_of_ist: str | None = None,
) -> dict[str, Any]:
    path = timeline_day_path(
        data_dir, laboratory_id=laboratory_id, as_of_ist=as_of_ist
    )
    if path is None or not path.is_file():
        return {"ok": False, "reason": "missing", "rows": []}
    rows: list[dict[str, Any]] = []
    meta: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        if obj.get("kind") == "timeline_day_meta":
            meta = obj
        elif obj.get("symbol"):
            rows.append(obj)
    return {"ok": True, "meta": meta, "rows": rows, "path": str(path)}


def build_open_book_timelines(
    data_dir: str | Path | None,
    symbols: list[str],
    *,
    laboratory_id: str = "india_equity_learner",
    program_id: str = "market_intelligence",
    as_of_ist: str | None = None,
    decisions_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    open_book_packs_by_symbol: dict[str, dict[str, Any]] | None = None,
    persist: bool = True,
    observations: Any | None = None,
) -> dict[str, Any]:
    """Build timelines for open-book (or priority) symbols from durable stores."""
    day = (as_of_ist or ist_today()).strip()
    from atlas.investment.bar_store import load_bars
    from atlas.investment.fundamentals import get_symbol
    from atlas.investment.open_book_packs import (
        last_bar_return_pct,
        rs_vs_benchmark_pct,
        _news_block_from_observations,
    )
    from atlas.investment.sector_benchmarks import (
        NIFTY_BENCHMARK_YAHOO,
        yahoo_index_for_sector,
    )

    packs = open_book_packs_by_symbol or {}
    decs = decisions_by_symbol or {}
    obs_store = observations
    if obs_store is None and data_dir:
        try:
            from atlas.investment.observations import DecisionObservationStore

            obs_store = DecisionObservationStore(data_dir=data_dir)
        except Exception:  # noqa: BLE001
            obs_store = None

    # NIFTY from durable bars if present
    nifty_bars = load_bars(data_dir, NIFTY_BENCHMARK_YAHOO, limit=60)
    nifty_last = None
    nifty_ret = last_bar_return_pct(nifty_bars)
    if nifty_bars:
        try:
            nifty_last = float(nifty_bars[-1]["close"])
        except (TypeError, ValueError, KeyError):
            pass

    bench_cache: dict[str, list[dict[str, Any]]] = {
        NIFTY_BENCHMARK_YAHOO: nifty_bars
    }

    rows: list[dict[str, Any]] = []
    for sym in symbols:
        s = str(sym or "").strip().upper()
        if not s:
            continue
        bars = load_bars(data_dir, s, limit=80)
        fund = get_symbol(data_dir, s, program_id=program_id) or {}
        pack = dict(packs.get(s) or packs.get(sym) or {})
        sector = None
        if isinstance(fund, dict):
            sector = fund.get("sector") or fund.get("industry")

        # Sector RS from durable sector index bars (fall back to NIFTY if empty)
        bench_sym = yahoo_index_for_sector(sector=str(sector) if sector else None)
        if bench_sym not in bench_cache:
            bench_cache[bench_sym] = load_bars(data_dir, bench_sym, limit=60)
        bench_bars = bench_cache.get(bench_sym) or []
        if (
            not bench_bars
            and bench_sym != NIFTY_BENCHMARK_YAHOO
            and nifty_bars
        ):
            bench_sym = NIFTY_BENCHMARK_YAHOO
            bench_bars = nifty_bars
        rs = rs_vs_benchmark_pct(bars, bench_bars)
        rs_nifty = rs_vs_benchmark_pct(bars, nifty_bars)
        market_block = dict(pack.get("market") or {}) if isinstance(pack.get("market"), dict) else {}
        if rs is not None:
            market_block["rs_vs_benchmark_pct"] = rs
            market_block["benchmark_symbol"] = bench_sym
        if rs_nifty is not None:
            market_block["rs_vs_nifty_pct"] = rs_nifty
        if nifty_ret is not None:
            market_block["nifty_return_1d_pct"] = nifty_ret
        if market_block:
            pack["market"] = market_block

        # News / policy from observation store (JSON + DB when wired)
        news_block = None
        policy_block = None
        if obs_store is not None:
            try:
                recent = list(obs_store.list_symbol(symbol=s, limit=25) or [])
                news_block = _news_block_from_observations(recent)
                gov = list(news_block.get("gov") or [])
                if gov:
                    policy_block = {"events": gov[:4], "source": "observations"}
                # Also pull program-level macro/policy if symbol-scoped empty
                if not gov and hasattr(obs_store, "list_since"):
                    try:
                        broad = obs_store.list_since(since_hours=72.0, limit=30) or []
                        macro_pol = [
                            r
                            for r in broad
                            if isinstance(r, dict)
                            and str(r.get("kind") or "")
                            in {"macro_event", "policy_event", "market_event"}
                        ]
                        if macro_pol:
                            extra = _news_block_from_observations(macro_pol)
                            if extra.get("gov") or extra.get("macro"):
                                news_block = news_block or {}
                                if not news_block.get("macro"):
                                    news_block["macro"] = extra.get("macro") or []
                                if not news_block.get("gov"):
                                    news_block["gov"] = extra.get("gov") or []
                                if extra.get("gov"):
                                    policy_block = {
                                        "events": (extra.get("gov") or [])[:4],
                                        "source": "observations",
                                    }
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                _log.debug("timeline news load failed for %s", s, exc_info=True)

        row = build_symbol_timeline(
            symbol=s,
            as_of_ist=day,
            bars=bars,
            fundamentals=fund if isinstance(fund, dict) else {},
            open_book_pack=pack if isinstance(pack, dict) else {},
            sector=str(sector) if sector else None,
            nifty_last=nifty_last,
            nifty_ret_pct=nifty_ret,
            decisions=decs.get(s) or decs.get(sym) or [],
            news=news_block,
            policy=policy_block,
        )
        # Attach RS onto sector lane when computed
        if rs is not None and isinstance(row.get("lanes"), dict):
            sec = dict(row["lanes"].get("sector") or {})
            sec["status"] = "ok"
            sec["benchmark"] = bench_sym
            sec["rs_vs_benchmark_pct"] = rs
            if rs_nifty is not None:
                sec["rs_vs_nifty_pct"] = rs_nifty
            if sector:
                sec["sector"] = sector
            row["lanes"]["sector"] = sec
            row["unknowns"] = [
                u
                for u in (row.get("unknowns") or [])
                if u not in {"sector", "sector_rs"}
            ]
        if nifty_last is not None and isinstance(row.get("lanes"), dict):
            mkt = dict(row["lanes"].get("market") or {})
            mkt["status"] = "ok"
            mkt["nifty_last"] = nifty_last
            mkt["nifty_return_1d_pct"] = nifty_ret
            row["lanes"]["market"] = mkt
            row["unknowns"] = [u for u in (row.get("unknowns") or []) if u != "market"]
        rows.append(row)

    out: dict[str, Any] = {
        "version": VERSION,
        "ok": True,
        "as_of_ist": day,
        "laboratory_id": laboratory_id,
        "count": len(rows),
        "rows": rows,
        "nifty_last": nifty_last,
        "nifty_return_1d_pct": nifty_ret,
        "honesty": (
            "Open-book Market Timeline (OI-MTL0 densify). "
            "FCF/news/policy unknowns stay explicit until evidence lands."
        ),
    }
    if persist and data_dir:
        try:
            saved = persist_timeline_day(
                data_dir, rows, laboratory_id=laboratory_id, as_of_ist=day
            )
            out["persist"] = saved
        except OSError as exc:
            _log.debug("timeline persist failed: %s", exc)
            out["persist"] = {"ok": False, "reason": type(exc).__name__}
    return out


def format_market_timeline_evening_lines(
    doc: dict[str, Any] | None,
    *,
    limit: int = 5,
) -> list[str]:
    lines = ["", "Market Timeline (open books · OI-MTL0):"]
    if not isinstance(doc, dict) or not doc.get("ok"):
        lines.append(
            "  (unavailable — build after durable bars; open books first)"
        )
        return lines
    rows = [r for r in (doc.get("rows") or []) if isinstance(r, dict)]
    if not rows:
        lines.append("  (no open-book timeline rows today)")
        return lines
    lines.append(
        f"  as_of={doc.get('as_of_ist')} · symbols={doc.get('count')} · "
        "lanes: price/tech/fund/sector/market/news/policy/atlas"
    )
    if doc.get("nifty_last") is not None:
        lines.append(
            f"  NIFTY: {doc.get('nifty_last')} "
            f"(1d={doc.get('nifty_return_1d_pct') if doc.get('nifty_return_1d_pct') is not None else '—'}%)"
        )
    for r in rows[: max(1, int(limit))]:
        lanes = r.get("lanes") if isinstance(r.get("lanes"), dict) else {}
        px = (lanes.get("price") or {}).get("last_price")
        ret = (lanes.get("price") or {}).get("return_1d_pct")
        rsi = (lanes.get("technical") or {}).get("rsi14")
        pe = (lanes.get("fundamentals") or {}).get("pe")
        fcf = (lanes.get("fundamentals") or {}).get("fcf")
        rs = (lanes.get("sector") or {}).get("rs_vs_benchmark_pct")
        bench = (lanes.get("sector") or {}).get("benchmark")
        action = (lanes.get("atlas") or {}).get("last_action")
        unk = r.get("unknowns") or []
        rs_bit = (
            f"rs={rs} vs {bench}"
            if rs is not None and bench
            else (f"rs={rs}" if rs is not None else "rs=—")
        )
        lines.append(
            f"  · {r.get('symbol')}: px={px if px is not None else '—'} "
            f"ret1d={ret if ret is not None else '—'}% "
            f"rsi={rsi if rsi is not None else '—'} "
            f"pe={pe if pe is not None else '—'} "
            f"fcf={'yes' if fcf is not None else 'missing'} "
            f"{rs_bit} "
            f"atlas={action or '—'} "
            f"unknowns={len(unk)}"
        )
        if unk:
            lines.append(f"      could not determine: {', '.join(str(u) for u in unk[:6])}")
    lines.append("  Revisit questions (every open book):")
    qs = (rows[0].get("revisit_questions") or [])[:4]
    for q in qs:
        lines.append(f"    · {q}")
    lines.append(f"  Honesty: {doc.get('honesty')}")
    return lines
