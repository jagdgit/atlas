"""NewsIntelligenceWorker — Market Intelligence M3 (MI.4 / IL.4 / LQ.3).

Ingest configured headlines/items → typed knowledge candidates → CandidateConsumer.
LQ.3: denser news_event obs (§8.1 fields), per-symbol news jsonl, open-book
decision_id linking, citeable on revisits.

Hermetic by default (config headlines); live RSS optional.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from atlas.investment import watchlists as wl
from atlas.investment.observations import infer_news_topic_tags, normalize_news_sentiment
from atlas.knowledge.media_extraction import MediaKnowledgeExtractor
from atlas.workers.base import PersistentWorker, TickContext, TickResult


class NewsIntelligenceWorker(PersistentWorker):
    type = "news_intelligence"
    VERSION = 3
    journal_ticks = True

    def __init__(
        self,
        *,
        candidates: Any,
        extractor: Any | None = None,
        knowledge_verification: Any | None = None,
        events: Any | None = None,
        observations: Any | None = None,
        decision_packets: Any | None = None,
        portfolio: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._candidates = candidates
        self._extractor = extractor or MediaKnowledgeExtractor(max_claims=8)
        self._verify = knowledge_verification
        self._events = events
        self._observations = observations
        self._packets = decision_packets
        self._portfolio = portfolio
        self._logger = logger or logging.getLogger("atlas.workers.news_intelligence")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        ticks = int(state.get("ticks", 0)) + 1
        state["ticks"] = ticks

        open_syms = self._open_symbols(cfg)
        state["open_book_symbols"] = open_syms[:40]

        items, auto = wl.resolve_news_items(cfg)
        # IIP.9 — optional RSS allow-list (enabled feeds only)
        rss_note = ""
        if cfg.get("rss_feeds") or cfg.get("use_rss_allowlist") or cfg.get("fetch_rss"):
            try:
                from atlas.investment import rss_feeds as rss

                feeds = rss.merge_allowlist(
                    cfg.get("rss_feeds") if isinstance(cfg.get("rss_feeds"), list) else None,
                    include_defaults=bool(cfg.get("rss_include_defaults", True)),
                )
                enable_ids = {
                    str(x).strip()
                    for x in (cfg.get("rss_enable") or [])
                    if str(x).strip()
                }
                if enable_ids:
                    for row in feeds:
                        if row.get("id") in enable_ids:
                            row["enabled"] = True
                result = rss.fetch_allowlist(
                    feeds,
                    kinds=None
                    if cfg.get("rss_kinds") is None
                    else [str(k) for k in (cfg.get("rss_kinds") or [])],
                    max_per_feed=int(cfg.get("rss_max_per_feed") or 12),
                )
                data_dir = cfg.get("data_dir")
                if data_dir:
                    rss.save_last_fetch(str(data_dir), result)
                rss_items = rss.items_as_news(result)
                if rss_items:
                    items = list(items) + rss_items
                    auto = False
                    rss_note = f"; rss={result.get('ok_feeds')}/{len(result.get('feeds') or [])} feeds"
                else:
                    rss_note = f"; rss=0 items ({result.get('ok_feeds') or 0} ok feeds)"
                state["rss"] = {
                    "ok_feeds": result.get("ok_feeds"),
                    "item_count": result.get("item_count"),
                    "feeds": result.get("feeds"),
                }
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("rss allow-list skipped: %s", exc)
                rss_note = f"; rss skipped ({exc})"
                state["rss_error"] = str(exc)[:200]

        # Operator live inputs still append
        for inp in ctx.inputs or []:
            if inp.get("headline"):
                items.append(
                    {
                        "text": str(inp["headline"]),
                        "symbol": str(inp.get("symbol") or ""),
                        "source": "operator_input",
                        "topic_tags": inp.get("topic_tags"),
                        "sentiment": inp.get("sentiment"),
                        "link": inp.get("link"),
                    }
                )
                auto = False
            if inp.get("text"):
                items.append(
                    {
                        "text": str(inp["text"]),
                        "symbol": str(inp.get("symbol") or ""),
                        "source": "operator_input",
                        "topic_tags": inp.get("topic_tags"),
                        "sentiment": inp.get("sentiment"),
                        "link": inp.get("link"),
                    }
                )
                auto = False

        # LQ.3 — when open books exist, prefer their seeds / tagged items first
        open_set = {s.upper() for s in open_syms}
        if open_set and items:
            preferred = [
                i
                for i in items
                if str(i.get("symbol") or "").strip().upper() in open_set
            ]
            if preferred:
                rest = [
                    i
                    for i in items
                    if str(i.get("symbol") or "").strip().upper() not in open_set
                ]
                items = preferred + rest
            elif auto:
                # Watchlist seeds only for open books when we hold them
                items = [
                    {
                        "text": (
                            f"Monitor material news for open book "
                            f"{sym}: earnings, orders, regulation, management."
                        ),
                        "symbol": sym,
                        "source": "open_book_seed",
                        "seed": True,
                        "evidence_class": "non_evidence",
                    }
                    for sym in open_syms[:15]
                ]
                auto = True

        state["auto_watchlist"] = auto
        if auto:
            state["auto_symbols"] = [
                str(i.get("symbol") or "") for i in items if i.get("symbol")
            ]

        if not items:
            return TickResult(
                state=state,
                note=(
                    "idle: no headlines — set headlines=['…'] or items="
                    "[{symbol,text}], enable rss_feeds / use_rss_allowlist, "
                    "or start M0 / India learner so watchlist seeds auto-load"
                    f"{rss_note}"
                ),
            )

        seen = set(state.get("seen_hashes") or [])
        emitted = 0
        skipped = 0
        news_obs = 0
        open_book_news = 0
        new_hashes: list[str] = []
        for item in items:
            text = str(item.get("text") or "").strip()
            if len(text) < 12:
                skipped += 1
                continue
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
            if digest in seen:
                skipped += 1
                continue
            symbol = str(item.get("symbol") or "").strip()
            source = str(item.get("source") or "news_config").strip()
            is_open = bool(symbol and symbol.upper() in open_set)
            decision_id = None
            if is_open and self._packets is not None:
                decision_id = self._latest_buy_decision_id(
                    symbol,
                    portfolio_key=str(cfg.get("portfolio_key") or "india_equity_learner"),
                )
            evidence = {
                "source": source,
                "symbol": symbol or None,
                "mission_id": ctx.mission_id,
                "open_book": is_open,
            }
            payloads = self._extractor.extract(
                text,
                evidence_ref=evidence,
                domain="markets",
            )
            for payload in payloads:
                try:
                    self._candidates.emit(payload)
                    emitted += 1
                except Exception as exc:  # noqa: BLE001
                    self._logger.warning("candidate emit failed: %s", exc)
            if self._observations is not None:
                try:
                    tags = item.get("topic_tags")
                    if not tags:
                        tags = infer_news_topic_tags(text)
                    self._observations.record_news_event(
                        text=text,
                        symbol=symbol or None,
                        source=source,
                        topic_tags=list(tags) if tags else None,
                        sentiment=normalize_news_sentiment(item.get("sentiment")),
                        link=str(item.get("link") or "") or None,
                        observed_before_move=item.get("observed_before_move"),
                        link_decision_id=decision_id,
                        open_book=is_open,
                        extra={"digest": digest, "lq": "lq.3"},
                    )
                    news_obs += 1
                    if is_open:
                        open_book_news += 1
                except Exception:  # noqa: BLE001
                    self._logger.debug("DI.Obs news_event skipped", exc_info=True)
            seen.add(digest)
            new_hashes.append(digest)

        if emitted and hasattr(self._candidates, "consume_pending"):
            try:
                self._candidates.consume_pending(limit=max(emitted, 20))
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("candidate consolidate failed: %s", exc)

        state["seen_hashes"] = list(seen)[-200:]
        state["last_news"] = {
            "news_observations": news_obs,
            "open_book_news": open_book_news,
            "emitted_candidates": emitted,
            "skipped": skipped,
        }

        verify_note = ""
        if emitted and cfg.get("verify") and self._verify is not None:
            try:
                result = self._verify.verify_batch(
                    limit=int(cfg.get("verify_batch_limit") or 5),
                    gather=bool(cfg.get("gather") or False),
                )
                verify_note = (
                    f"; verify status={result.get('status')} "
                    f"n={result.get('selected', len(result.get('results') or []))}"
                )
            except Exception as exc:  # noqa: BLE001
                verify_note = f"; verify skipped ({exc})"

        if self._events is not None and (emitted or news_obs):
            try:
                self._events.emit(
                    "NewsIntelligenceExtracted",
                    {
                        "mission_id": ctx.mission_id,
                        "emitted": emitted,
                        "items": len(new_hashes),
                        "news_observations": news_obs,
                        "open_book_news": open_book_news,
                    },
                    source=self.type,
                )
            except Exception:  # noqa: BLE001
                pass

        auto_note = f"auto watchlist ({len(items)}); " if auto else ""
        return TickResult(
            state=state,
            note=(
                f"{auto_note}news: emitted {emitted} candidate(s), "
                f"obs={news_obs} open_book={open_book_news}, skipped {skipped}"
                f"{verify_note}{rss_note}"
            ),
        )

    def _open_symbols(self, cfg: dict[str, Any]) -> list[str]:
        raw = cfg.get("open_symbols") or cfg.get("symbols") or []
        if isinstance(raw, str):
            raw = [s.strip() for s in raw.split(",") if s.strip()]
        out = [str(s).strip().upper() for s in raw if str(s).strip()]
        if out:
            return out[:40]
        if self._portfolio is None:
            return []
        portfolio_key = str(cfg.get("portfolio_key") or "india_equity_learner").strip()
        try:
            from atlas.investment import portfolios as pf

            meta = pf.get(portfolio_key) or {}
            pid = meta.get("sim_portfolio_id") or meta.get("portfolio_id")
            mission_id = meta.get("mission_id") or meta.get("ledger_mission_id")
            persona = meta.get("persona") if isinstance(meta.get("persona"), dict) else {}
            if (
                not pid
                and mission_id
                and hasattr(self._portfolio, "ensure_portfolio")
            ):
                ensured = self._portfolio.ensure_portfolio(
                    mission_id=mission_id,
                    name=portfolio_key,
                    starting_cash=float(persona.get("capital") or 0),
                    base_currency=str(persona.get("currency") or "INR"),
                )
                pid = (ensured or {}).get("id")
            positions: list[dict[str, Any]] = []
            repo = getattr(self._portfolio, "_repo", None)
            if pid and repo is not None and hasattr(repo, "list_positions"):
                positions = list(repo.list_positions(pid) or [])
            elif pid and hasattr(self._portfolio, "snapshot"):
                snap = self._portfolio.snapshot(pid) or {}
                positions = list(snap.get("positions") or snap.get("holdings") or [])
            for p in positions:
                if not isinstance(p, dict):
                    continue
                qty = float(p.get("qty") or p.get("quantity") or p.get("shares") or 0)
                sym = str(p.get("symbol") or "").strip().upper()
                if sym and qty > 0 and sym not in out:
                    out.append(sym)
                if len(out) >= 40:
                    break
        except Exception:  # noqa: BLE001
            self._logger.debug("LQ.3 open positions resolve failed", exc_info=True)
        return out

    def _latest_buy_decision_id(
        self, symbol: str, *, portfolio_key: str
    ) -> str | None:
        if self._packets is None:
            return None
        try:
            rows = self._packets.list_symbol(
                symbol=symbol, limit=20, portfolio_key=portfolio_key
            )
        except Exception:  # noqa: BLE001
            return None
        for p in rows or []:
            if isinstance(p, dict) and str(p.get("action") or "").lower() == "buy":
                did = p.get("decision_id")
                return str(did) if did else None
        return None
