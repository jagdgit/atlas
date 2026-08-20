"""PLC.C — daily open-book observation packs (honest unknowns OK)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from atlas.investment.sector_benchmarks import (
    NIFTY_BENCHMARK_YAHOO,
    infer_event_regime_tags,
    resolve_sector_benchmark,
)

_log = logging.getLogger("atlas.investment.open_book_packs")
VERSION = "plc.c.open_book_daily"
_IST = ZoneInfo("Asia/Kolkata")


def ist_session_day(now: datetime | None = None) -> str:
    dt = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_IST).date().isoformat()


def resolve_open_symbols(
    *,
    portfolio: Any | None,
    portfolio_key: str = "india_equity_learner",
    limit: int = 40,
) -> list[str]:
    """Open qty>0 symbols for a lab ledger (same pattern as news_intelligence)."""
    out: list[str] = []
    if portfolio is None:
        return out
    try:
        from atlas.investment import portfolios as pf

        meta = pf.get(portfolio_key) or {}
        pid = meta.get("sim_portfolio_id") or meta.get("portfolio_id")
        mission_id = meta.get("mission_id") or meta.get("ledger_mission_id")
        persona = meta.get("persona") if isinstance(meta.get("persona"), dict) else {}
        if not pid and mission_id and hasattr(portfolio, "ensure_portfolio"):
            ensured = portfolio.ensure_portfolio(
                mission_id=mission_id,
                name=portfolio_key,
                starting_cash=float(persona.get("capital") or 0),
                base_currency=str(persona.get("currency") or "INR"),
            )
            pid = (ensured or {}).get("id")
        positions: list[dict[str, Any]] = []
        repo = getattr(portfolio, "_repo", None)
        if pid and repo is not None and hasattr(repo, "list_positions"):
            positions = list(repo.list_positions(pid) or [])
        elif pid and hasattr(portfolio, "snapshot"):
            snap = portfolio.snapshot(pid) or {}
            positions = list(snap.get("positions") or snap.get("holdings") or [])
        for p in positions:
            if not isinstance(p, dict):
                continue
            qty = float(p.get("qty") or p.get("quantity") or p.get("shares") or 0)
            sym = str(p.get("symbol") or "").strip().upper()
            if sym and qty > 0 and sym not in out:
                out.append(sym)
            if len(out) >= max(1, int(limit)):
                break
    except Exception:  # noqa: BLE001
        _log.debug("open_book resolve failed", exc_info=True)
    return out


def _already_packed_today(
    observations: Any,
    *,
    symbol: str,
    session_day: str,
) -> bool:
    try:
        rows = observations.list_symbol(symbol=symbol, limit=30) or []
    except Exception:  # noqa: BLE001
        return False
    for row in rows:
        if not isinstance(row, dict):
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        if payload.get("kind") != "open_book_daily_pack":
            continue
        if str(payload.get("session_day") or "") == session_day:
            return True
    return False


def _bar_close(row: dict[str, Any]) -> float | None:
    try:
        c = row.get("close") if row.get("close") is not None else row.get("c")
        return float(c) if c is not None else None
    except (TypeError, ValueError):
        return None


def last_bar_return_pct(bars: list[dict[str, Any]] | None) -> float | None:
    """Session return from last two closes (%). None when bars thin — never invent."""
    rows = [b for b in (bars or []) if isinstance(b, dict)]
    if len(rows) < 2:
        return None
    prev = _bar_close(rows[-2])
    last = _bar_close(rows[-1])
    if prev is None or last is None or prev == 0:
        return None
    return round(100.0 * (last - prev) / abs(prev), 3)


def rs_vs_benchmark_pct(
    bars: list[dict[str, Any]] | None,
    benchmark_bars: list[dict[str, Any]] | None,
) -> float | None:
    """Relative strength vs benchmark (name return − bench return), pct points."""
    name_ret = last_bar_return_pct(bars)
    bench_ret = last_bar_return_pct(benchmark_bars)
    if name_ret is None or bench_ret is None:
        return None
    return round(float(name_ret) - float(bench_ret), 3)


def _news_block_from_observations(
    news_rows: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Named headlines for open-book packs — never invent; empty → unknowns.

    E0: watchlist/open_book seeds are non-evidence and never count as news.
    """
    from atlas.investment.symbol_aliases import news_is_evidence

    company: list[dict[str, Any]] = []
    sector: list[dict[str, Any]] = []
    macro: list[dict[str, Any]] = []
    gov: list[dict[str, Any]] = []
    ids: list[str] = []
    seed_ignored = 0
    for row in news_rows or []:
        if not isinstance(row, dict):
            continue
        if not news_is_evidence(row):
            seed_ignored += 1
            continue
        pl = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        # Accept either observation row or already-normalized headline dict
        text = str(
            pl.get("text") or pl.get("title") or row.get("text") or row.get("title") or ""
        ).strip()
        if not text:
            continue
        oid = str(row.get("id") or pl.get("id") or "")
        if oid:
            ids.append(oid)
        tags = [str(t).lower() for t in (pl.get("topic_tags") or row.get("topic_tags") or [])]
        sent = str(pl.get("sentiment") or row.get("sentiment") or "unknown")
        item = {
            "id": oid or None,
            "title": text[:160],
            "sentiment": sent,
            "topic_tags": tags[:6],
            "source": str(row.get("source") or pl.get("source") or "") or None,
            "source_tier": pl.get("source_tier") or row.get("source_tier"),
            "published_at": pl.get("published_at") or row.get("published_at"),
            "observed_at": pl.get("observed_at") or row.get("created_at"),
        }
        if any(t in {"policy", "government", "budget", "election"} for t in tags):
            gov.append(item)
        elif any(t in {"macro", "rates", "fed", "rbi", "inflation"} for t in tags):
            macro.append(item)
        elif any(t in {"sector", "industry", "peer"} for t in tags):
            sector.append(item)
        else:
            company.append(item)
    unknowns: list[str] = []
    if not company:
        unknowns.append("company")
    if not sector:
        unknowns.append("sector")
    if not macro:
        unknowns.append("macro")
    if not gov:
        unknowns.append("gov")
    return {
        "company": company[:6],
        "sector": sector[:4],
        "macro": macro[:4],
        "gov": gov[:4],
        "observation_ids": ids[:12],
        "unknowns": unknowns,
        "seed_ignored": seed_ignored,
    }


def _merge_event_regimes(
    bar_tags: list[str],
    *,
    macro_rows: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Combine bar-derived tags with concrete macro/policy event tags."""
    from atlas.investment.decision_packets import normalize_regime_tags

    out = list(bar_tags or [])
    for o in macro_rows or []:
        if not isinstance(o, dict):
            continue
        pl = o.get("payload") if isinstance(o.get("payload"), dict) else {}
        kind = str(o.get("kind") or "")
        raw = list(pl.get("regime_tags") or [])
        if not raw and kind in {"macro_event", "policy_event"}:
            raw = infer_event_regime_tags(
                title=str(pl.get("title") or ""),
                detail=str(pl.get("detail") or ""),
                sectors=list(pl.get("sectors") or []),
            )
        for t in normalize_regime_tags(raw):
            if t != "unknown" and t not in out:
                out.append(t)
    return normalize_regime_tags(out)


def regime_tags_from_bars(
    bars: list[dict[str, Any]] | None,
    *,
    lookback: int = 5,
) -> list[str]:
    """Bar-derived regime tags only (LQ.6 vocab). Never invent event regimes.

    Uses trailing closes on the supplied series (typically NIFTY):
    - return over lookback → bull / bear / sideways
    - elevated day-to-day |moves| → high_vol
    Empty/thin bars → [].
    """
    from atlas.investment.decision_packets import normalize_regime_tags

    rows = [b for b in (bars or []) if isinstance(b, dict)]
    closes: list[float] = []
    for b in rows:
        c = _bar_close(b)
        if c is not None:
            closes.append(c)
    if len(closes) < 3:
        return []
    lb = max(2, min(int(lookback), len(closes) - 1))
    start = closes[-(lb + 1)]
    end = closes[-1]
    if not start:
        return []
    ret = 100.0 * (end - start) / abs(start)
    tags: list[str] = []
    if ret >= 2.0:
        tags.append("bull")
    elif ret <= -2.0:
        tags.append("bear")
    else:
        tags.append("sideways")
    # Realized vol proxy: mean abs daily % move
    moves: list[float] = []
    for i in range(1, len(closes)):
        p = closes[i - 1]
        if p:
            moves.append(abs(100.0 * (closes[i] - p) / abs(p)))
    if moves and (sum(moves) / len(moves)) >= 1.25:
        tags.append("high_vol")
    return normalize_regime_tags(tags)


def _bars_market_block(
    bars: list[dict[str, Any]] | None,
    *,
    benchmark_bars: list[dict[str, Any]] | None = None,
    benchmark_symbol: str | None = None,
    event_regime_tags: list[str] | None = None,
    macro_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    unknowns = [
        "close",
        "return_pct",
        "volume_delta",
        "rs_vs_nifty",
        "volatility_band",
        "regime_tags",
    ]
    out: dict[str, Any] = {
        "close": None,
        "return_pct": None,
        "volume_delta": None,
        "rs_vs_nifty": None,
        "benchmark_symbol": benchmark_symbol or NIFTY_BENCHMARK_YAHOO,
        "volatility_band": "unknown",
        "regime_tags": [],
        "unknowns": list(unknowns),
    }
    rows = [b for b in (bars or []) if isinstance(b, dict)]
    if not rows:
        # Still allow event regimes without bars
        tags = _merge_event_regimes(list(event_regime_tags or []), macro_rows=macro_rows)
        if tags:
            out["regime_tags"] = tags
            out["unknowns"] = [u for u in out["unknowns"] if u != "regime_tags"]
        return out
    last = rows[-1]
    out["close"] = _bar_close(last)
    if out["close"] is not None:
        out["unknowns"] = [u for u in out["unknowns"] if u != "close"]
    if len(rows) >= 2:
        out["return_pct"] = last_bar_return_pct(rows)
        if out["return_pct"] is not None:
            out["unknowns"] = [u for u in out["unknowns"] if u != "return_pct"]
        try:
            v0 = float(rows[-2].get("volume") or rows[-2].get("v") or 0)
            v1 = float(last.get("volume") or last.get("v") or 0)
            if v0:
                out["volume_delta"] = round((v1 - v0) / v0, 4)
                out["unknowns"] = [u for u in out["unknowns"] if u != "volume_delta"]
        except (TypeError, ValueError):
            pass
    rs = rs_vs_benchmark_pct(rows, benchmark_bars)
    if rs is not None:
        out["rs_vs_nifty"] = rs
        # Keep field name for compat; note when sector index used
        out["rs_vs_benchmark"] = rs
        out["unknowns"] = [u for u in out["unknowns"] if u != "rs_vs_nifty"]
    # Regime: bar-derived from benchmark (preferred) + event tags from macro obs
    regime_src = benchmark_bars if benchmark_bars else rows
    bar_tags = regime_tags_from_bars(regime_src)
    tags = _merge_event_regimes(
        list(event_regime_tags or []) + bar_tags, macro_rows=macro_rows
    )
    if tags:
        out["regime_tags"] = tags
        out["unknowns"] = [u for u in out["unknowns"] if u != "regime_tags"]
        if "high_vol" in tags:
            out["volatility_band"] = "elevated"
            out["unknowns"] = [u for u in out["unknowns"] if u != "volatility_band"]
        elif out["volatility_band"] == "unknown":
            out["volatility_band"] = "normal"
            out["unknowns"] = [u for u in out["unknowns"] if u != "volatility_band"]
    return out


def _fundamentals_block(row: dict[str, Any] | None) -> dict[str, Any]:
    """J2 open-book fund snapshot — copy known fields; leave gaps as unknowns."""
    unknowns = [
        "pe",
        "pb",
        "mcap",
        "roe",
        "roic",
        "debt_to_equity",
        "fcf",
        "promoter_holding",
        "earnings_proximity",
        "management_commentary",
    ]
    out: dict[str, Any] = {k: None for k in unknowns}
    out["unknowns"] = list(unknowns)
    if not isinstance(row, dict):
        return out
    for key in (
        "pe",
        "pb",
        "mcap",
        "roe",
        "roic",
        "debt_to_equity",
        "fcf",
        "promoter_holding",
    ):
        if row.get(key) is not None:
            out[key] = row.get(key)
            out["unknowns"] = [u for u in out["unknowns"] if u != key]
    if row.get("free_cash_flow") is not None and out.get("fcf") is None:
        out["fcf"] = row.get("free_cash_flow")
        out["unknowns"] = [u for u in out["unknowns"] if u != "fcf"]
    if row.get("market_cap") is not None and out.get("mcap") is None:
        out["mcap"] = row.get("market_cap")
        out["unknowns"] = [u for u in out["unknowns"] if u != "mcap"]
    # Earnings date from Yahoo/Screener → proximity known; commentary stays unknown
    if row.get("earnings_date") is not None:
        out["earnings_proximity"] = {"earnings_date": row.get("earnings_date")}
        out["unknowns"] = [u for u in out["unknowns"] if u != "earnings_proximity"]
    if row.get("management_commentary") is not None:
        out["management_commentary"] = row.get("management_commentary")
        out["unknowns"] = [u for u in out["unknowns"] if u != "management_commentary"]
    return out


def _thesis_block(awareness: dict[str, Any] | None) -> dict[str, Any]:
    """Heuristic only when evidence exists; else unknown (never invent)."""
    out = {"status": "unknown", "reason": None, "heuristic": None}
    aw = awareness if isinstance(awareness, dict) else {}
    thesis = aw.get("thesis") if isinstance(aw.get("thesis"), dict) else {}
    stance = str(thesis.get("stance") or "").lower()
    if stance in {"buy", "watch_positive", "positive"}:
        out["status"] = "unchanged"
        out["reason"] = f"stance={stance}"
        out["heuristic"] = "stance_present"
    elif stance in {"avoid", "sell", "watch_negative"}:
        out["status"] = "weakening"
        out["reason"] = f"stance={stance}"
        out["heuristic"] = "stance_present"
    elif thesis.get("summary"):
        out["status"] = "unchanged"
        out["reason"] = "thesis_summary_present"
        out["heuristic"] = "summary_present"
    return out


def _confidence_block(packets: Any | None, symbol: str, portfolio_key: str) -> dict[str, Any]:
    out = {"delta": "unknown", "vs_prior_packet_id": None}
    if packets is None:
        return out
    try:
        rows = packets.list_symbol(symbol=symbol, limit=5, portfolio_key=portfolio_key) or []
    except Exception:  # noqa: BLE001
        return out
    buys = [p for p in rows if isinstance(p, dict) and str(p.get("action") or "").lower() == "buy"]
    if not buys:
        return out
    prior = buys[0]
    out["vs_prior_packet_id"] = prior.get("decision_id") or prior.get("id")
    # Without calibrated confidence series, leave delta unknown (honest)
    return out


def build_open_book_daily_pack(
    *,
    symbol: str,
    portfolio_key: str,
    session_day: str | None = None,
    bars: list[dict[str, Any]] | None = None,
    benchmark_bars: list[dict[str, Any]] | None = None,
    benchmark_symbol: str | None = None,
    fundamentals: dict[str, Any] | None = None,
    awareness: dict[str, Any] | None = None,
    recent_news_ids: list[str] | None = None,
    recent_news_rows: list[dict[str, Any]] | None = None,
    macro_rows: list[dict[str, Any]] | None = None,
    packets: Any | None = None,
) -> dict[str, Any]:
    day = session_day or ist_session_day()
    market = _bars_market_block(
        bars,
        benchmark_bars=benchmark_bars,
        benchmark_symbol=benchmark_symbol,
        macro_rows=macro_rows,
    )
    fund = _fundamentals_block(fundamentals)
    if recent_news_rows:
        news = _news_block_from_observations(recent_news_rows)
    else:
        news_ids = list(recent_news_ids or [])[:8]
        news = {
            "company": [],
            "sector": [],
            "macro": [],
            "gov": [],
            "observation_ids": news_ids,
            "unknowns": (
                ["company", "sector", "macro", "gov"]
                if not news_ids
                else []
            ),
        }
    thesis = _thesis_block(awareness)
    confidence = _confidence_block(packets, symbol, portfolio_key)
    return {
        "kind": "open_book_daily_pack",
        "version": VERSION,
        "session_day": day,
        "portfolio_key": portfolio_key,
        "market": market,
        "fundamentals": fund,
        "news": news,
        "thesis": thesis,
        "confidence": confidence,
        "cited_observation_ids": list(news.get("observation_ids") or [])[:12],
        "honesty": (
            "Open-book daily pack — unknowns stay explicit; never invent PE/RS/news. "
            "RS = name return minus sector Yahoo index when known, else NIFTY (^NSEI). "
            "regime_tags = bar-derived + macro/policy event tags (election/budget/rates) — "
            "never invent event regimes without observations."
        ),
    }


def record_open_book_daily_packs(
    *,
    observations: Any,
    portfolio: Any | None,
    market_reader: Any | None = None,
    data_dir: str | None = None,
    packets: Any | None = None,
    investment_research: Any | None = None,
    portfolio_key: str = "india_equity_learner",
    program_id: str = "market_intelligence",
    budget: int = 5,
    provider: str | None = "yahoo",
) -> dict[str, Any]:
    """Once-per-IST-day pack per open position, Host Guard budgeted."""
    day = ist_session_day()
    symbols = resolve_open_symbols(portfolio=portfolio, portfolio_key=portfolio_key)
    if not symbols:
        return {
            "version": VERSION,
            "ok": True,
            "session_day": day,
            "recorded": 0,
            "skipped": 0,
            "symbols": [],
            "reason": "no_open_positions",
        }
    budget_n = max(0, int(budget))
    recorded = 0
    skipped = 0
    ids: list[str] = []
    errors: list[str] = []

    bench_cache: dict[str, list[dict[str, Any]]] = {}
    nifty_bars: list[dict[str, Any]] = []
    if market_reader is not None:
        try:
            bref = market_reader.bars_for(
                NIFTY_BENCHMARK_YAHOO, provider=provider, limit=30
            )
            nifty_bars = list((bref or {}).get("bars") or [])
            bench_cache[NIFTY_BENCHMARK_YAHOO] = nifty_bars
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{NIFTY_BENCHMARK_YAHOO}:bars:{type(exc).__name__}")

    macro_rows: list[dict[str, Any]] = []
    try:
        if hasattr(observations, "list_since"):
            recent_all = observations.list_since(since_hours=72.0, limit=40) or []
            macro_rows = [
                r
                for r in recent_all
                if isinstance(r, dict)
                and str(r.get("kind") or "") in {"macro_event", "policy_event"}
            ]
    except Exception:  # noqa: BLE001
        macro_rows = []

    for sym in symbols:
        if recorded >= budget_n:
            break
        if _already_packed_today(observations, symbol=sym, session_day=day):
            skipped += 1
            continue
        bars: list[dict[str, Any]] = []
        if market_reader is not None:
            try:
                result = market_reader.bars_for(sym, provider=provider, limit=30)
                bars = list((result or {}).get("bars") or [])
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{sym}:bars:{type(exc).__name__}")
        fund_row = None
        if data_dir:
            try:
                from atlas.investment.fundamentals import get_symbol as fund_get

                fund_row = fund_get(data_dir, sym, program_id=program_id)
            except Exception:  # noqa: BLE001
                fund_row = None
        aw = None
        if investment_research is not None:
            try:
                aw = investment_research.awareness(sym, program_id=program_id)
            except Exception:  # noqa: BLE001
                aw = None
        news_rows: list[dict[str, Any]] = []
        try:
            if hasattr(observations, "list_news_for_symbol"):
                news_rows = list(
                    observations.list_news_for_symbol(
                        symbol=sym, limit=8, since_hours=36.0
                    )
                    or []
                )
            if not news_rows:
                recent = observations.list_symbol(symbol=sym, limit=20) or []
                for row in recent:
                    if isinstance(row, dict) and str(row.get("kind") or "") == "news_event":
                        news_rows.append(row)
        except Exception:  # noqa: BLE001
            news_rows = []

        bench_meta = resolve_sector_benchmark(
            symbol=sym,
            awareness=aw if isinstance(aw, dict) else None,
            fundamentals=fund_row if isinstance(fund_row, dict) else None,
            data_dir=data_dir,
        )
        bench_sym = str(bench_meta.get("yahoo_symbol") or NIFTY_BENCHMARK_YAHOO)
        if bench_sym not in bench_cache and market_reader is not None:
            try:
                bref = market_reader.bars_for(bench_sym, provider=provider, limit=30)
                bench_cache[bench_sym] = list((bref or {}).get("bars") or [])
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{bench_sym}:bars:{type(exc).__name__}")
                bench_cache[bench_sym] = []
        bench_bars = bench_cache.get(bench_sym) or nifty_bars

        payload = build_open_book_daily_pack(
            symbol=sym,
            portfolio_key=portfolio_key,
            session_day=day,
            bars=bars,
            benchmark_bars=bench_bars or None,
            benchmark_symbol=bench_sym,
            fundamentals=fund_row if isinstance(fund_row, dict) else None,
            awareness=aw if isinstance(aw, dict) else None,
            recent_news_rows=news_rows,
            macro_rows=macro_rows,
            packets=packets,
        )
        if isinstance(payload.get("market"), dict):
            payload["market"]["sector_pack_id"] = bench_meta.get("pack_id")
            payload["market"]["sector_label"] = bench_meta.get("sector")

        try:
            row = observations.record(
                kind="market_event",
                symbol=sym,
                source="market_observer",
                confidence="estimated",
                ttl_hours=36.0,
                payload=payload,
            )
            recorded += 1
            rid = (row or {}).get("id") or (row or {}).get("observation_id")
            if rid:
                ids.append(str(rid))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{sym}:record:{type(exc).__name__}")

    return {
        "version": VERSION,
        "ok": True,
        "session_day": day,
        "recorded": recorded,
        "skipped": skipped,
        "symbols": symbols,
        "observation_ids": ids,
        "errors": errors[:12],
        "budget": budget_n,
    }
