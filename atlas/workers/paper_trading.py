"""PaperTradingWorker — the Paper-Trading Mission's persistent worker (Phase D · §D.6, flagship e2e).

The applied mission that ties D-Core together. Each tick drives the ONE decision path:

    bars → indicators → DecisionEngine.decide → apply → journal → notify

Feed sources (config ``feed_mode``):
- **asset_replay** (default) — Asset Store ``market_data`` via :class:`~atlas.readers.market_data.MarketDataReader`
- **live** — :class:`~atlas.trading.market_reader.MarketReaderService` (Yahoo / keyed providers)

Buys/sells respect ``market_session`` when ``respect_market_hours`` is true (NSE/US regular hours).
Simulation fills only — no real broker (P10).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from atlas.decision.contracts import ACTION_RECOMMEND, DecisionRequest
from atlas.decision.rules import CapabilityGap
from atlas.investment.packs import pack_capability_need, resolve_pack
from atlas.trading.broker_profiles import compute_fees, get_broker_profile
from atlas.trading.indicators import compute_indicators
from atlas.workers.base import PersistentWorker, TickContext, TickResult

MISSION_TYPE_PAPER_TRADING = "paper_trading"
ASSET_KIND_MARKET_DATA = "market_data"


class PaperTradingWorker(PersistentWorker):
    type = "paper_trading"
    VERSION = 2
    journal_ticks = True

    def __init__(
        self,
        *,
        assets: Any,
        market_data: Any,
        decision_engine: Any,
        portfolio: Any,
        learning: Any = None,
        experience_os: Any = None,
        mission_context: Any = None,
        policy_engine: Any = None,
        events: Any = None,
        live_market: Any | None = None,
        investor_mailer: Any | None = None,
        investment_research: Any | None = None,
        decision_packets: Any | None = None,
        observations: Any | None = None,
        attributions: Any | None = None,
        clock: Callable[[], datetime] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._assets = assets
        self._reader = market_data
        self._engine = decision_engine
        self._portfolio = portfolio
        self._learning = learning
        self._experience_os = experience_os
        self._mission_context = mission_context
        self._policy_engine = policy_engine
        self._events = events
        self._live_market = live_market
        self._investor_mailer = investor_mailer
        self._investment_research = investment_research
        self._decision_packets = decision_packets
        self._observations = observations
        self._attributions = attributions
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._logger = logger or logging.getLogger("atlas.workers.paper_trading")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        instruments = cfg.get("instruments") or []
        auto_loaded = False
        if not instruments:
            # IL.2 / IL-Q3: empty instruments → auto-load M0 watchlist (or NIFTY50 seed).
            from atlas.workers.investment_universe import auto_instruments

            max_auto = max(1, int(cfg.get("auto_max_instruments") or 20))
            program_id = str(cfg.get("program_id") or "market_intelligence")
            index = str(cfg.get("universe_index") or "NIFTY50")
            instruments = auto_instruments(
                program_id=program_id, max_n=max_auto, fallback_index=index
            )
            if not instruments:
                return TickResult(
                    state=state,
                    note=(
                        "idle: no instruments in config and no Investment Universe "
                        "watchlist — start M0 / India learner, or set instruments=[...]"
                    ),
                )
            auto_loaded = True
            state["auto_instruments"] = True
            state["auto_symbols"] = [i.get("symbol") for i in instruments]
        else:
            state["auto_instruments"] = False

        config_note = ""
        if auto_loaded:
            config_note = f"auto universe ({len(instruments)} symbols); "
        if ctx.config_version is not None and ctx.config_version != state.get("config_version"):
            config_note += f"config v{ctx.config_version} picked up; "
            state["config_version"] = ctx.config_version

        # IL.10 — virtual book identity + persona (one Decision Simulation per portfolio).
        from atlas.investment import portfolios as vp

        book = vp.ensure_from_config(cfg, mission_id=str(ctx.mission_id) if ctx.mission_id else None)
        portfolio_key = str(book.get("portfolio_key") or "default")
        persona = vp.normalize_persona(book.get("persona"))
        state["portfolio_key"] = portfolio_key
        state["persona"] = persona
        state["experience_scope"] = book.get("experience_scope")
        # Filter instruments by persona.allowed_assets when asset_class is set on rows.
        asset_class_default = str(cfg.get("asset_class") or book.get("asset_class") or "cash_equity")
        # IL.11 — Simulation Engine instrument pack (shared engine + class rules).
        pack = resolve_pack(
            cfg.get("instrument_pack") or book.get("instrument_pack"),
            asset_class=asset_class_default,
            allowed_assets=list(persona.get("allowed_assets") or []),
            config=cfg,
        )
        state["instrument_pack"] = pack.id
        state["instrument_pack_ready"] = bool(pack.ready)
        if not pack.ready:
            need = pack_capability_need(pack)
            return TickResult(
                state=state,
                note=(
                    f"capability_gap: {need} — {pack.gap_detail or pack.label} "
                    f"(portfolio={portfolio_key}; no sim fills)"
                ),
            )
        filtered: list[dict] = []
        for inst in instruments:
            if not isinstance(inst, dict):
                continue
            ac = str(inst.get("asset_class") or asset_class_default).strip() or asset_class_default
            if not vp.asset_allowed(persona, ac):
                continue
            if not pack.accepts_asset_class(ac):
                continue
            filtered.append(inst)
        if instruments and not filtered:
            return TickResult(
                state=state,
                note=(
                    f"idle: persona allowed_assets={persona.get('allowed_assets')} "
                    f"or pack={pack.id} excludes configured instruments "
                    f"(portfolio={portfolio_key})"
                ),
            )
        if filtered:
            instruments = filtered

        # Live operator inputs: block/unblock a symbol ("don't trade SYM"), or force a tick.
        blocked = {str(s).lower() for s in (state.get("blocked_symbols") or [])}
        for item in ctx.inputs:
            if item.get("block_symbol"):
                blocked.add(str(item["block_symbol"]).lower())
            if item.get("unblock_symbol"):
                blocked.discard(str(item["unblock_symbol"]).lower())
        state["blocked_symbols"] = sorted(blocked)

        portfolio = self._portfolio.ensure_portfolio(
            mission_id=ctx.mission_id,
            name=portfolio_key,
            starting_cash=float(
                persona.get("capital")
                or cfg.get("starting_cash", 100_000.0)
            ),
            base_currency=str(persona.get("currency") or cfg.get("base_currency") or "INR"),
        )
        portfolio_id = portfolio["id"]
        state["portfolio_id"] = str(portfolio_id)
        # Keep durable registry capital in lockstep with live sim cash (survives restart).
        try:
            live_cash = float(portfolio.get("cash") if portfolio.get("cash") is not None else persona.get("capital") or 0)
            synced = vp.sync_live_cash(
                portfolio_key,
                live_cash,
                mission_id=str(ctx.mission_id) if ctx.mission_id else None,
            )
            if synced and isinstance(synced.get("persona"), dict):
                persona = vp.normalize_persona(synced.get("persona"))
                state["persona"] = persona
        except Exception:  # noqa: BLE001
            pass
        config_note = f"book={portfolio_key}; pack={pack.id}; " + config_note

        feed_mode = str(cfg.get("feed_mode") or "asset_replay").strip().lower()
        if feed_mode not in ("asset_replay", "live"):
            feed_mode = "asset_replay"

        respect_hours = bool(cfg.get("respect_market_hours", True))
        session_id = str(cfg.get("market_session") or "always_open").strip() or "always_open"
        sess = pack.session_status(session_id, clock=self._clock)
        session_open = True if not respect_hours else sess.open
        state["session"] = {
            "id": sess.session_id,
            "open": session_open,
            "reason": sess.reason if respect_hours else "hours_ignored",
            "local_now": sess.local_now,
            "pack": pack.id,
        }

        cursors: dict[str, int] = dict(state.get("cursors") or {})
        last_bar_keys: dict[str, str] = dict(state.get("last_bar_keys") or {})
        bars_per_tick = max(1, int(cfg.get("bars_per_tick", 1)))
        strategy = dict(cfg.get("strategy") or {})
        # Learner / small India books: never default to a crippling 10% budget.
        pk_for_strat = str(state.get("portfolio_key") or cfg.get("portfolio_key") or "").lower()
        if strategy.get("trade_fraction") is None:
            if "learner" in pk_for_strat or float(cfg.get("starting_cash") or 0) <= 100_000:
                strategy["trade_fraction"] = 1.0
            else:
                strategy["trade_fraction"] = 0.1
        if strategy.get("allow_min_lot") is None:
            strategy["allow_min_lot"] = True
        allowed = [str(i.get("symbol")) for i in instruments if i.get("symbol")]

        # Prefer ranked + affordable names; leave headroom for next-best alternatives.
        cash_hint = float(portfolio.get("cash") or 0)
        prev_marks = dict(state.get("last_marks") or {})
        instruments = self._order_tradeable_first(
            instruments, cash=cash_hint, marks=prev_marks
        )
        primary_count = len(instruments)

        totals = {
            "decisions": 0,
            "buys": 0,
            "sells": 0,
            "holds": 0,
            "gaps": 0,
            "errors": 0,
            "session_skips": 0,
        }
        marks: dict[str, float] = dict(prev_marks)
        exhausted = 0
        last_actions: list[str] = []
        reason_counts: dict[str, int] = {}
        feed_gap_days: float | None = None
        from atlas.investment.session_notes import classify_action

        def _record_action(action: str | None) -> None:
            if not action:
                return
            last_actions.append(action)
            bucket = classify_action(action)
            if bucket:
                reason_counts[bucket] = int(reason_counts.get(bucket, 0)) + 1

        def _process_batch(batch: list[dict[str, Any]], *, as_alt: bool = False) -> None:
            nonlocal exhausted, feed_gap_days, allowed
            allowed = sorted(
                {
                    *allowed,
                    *[str(i.get("symbol")) for i in batch if i.get("symbol")],
                }
            )
            for inst in batch:
                symbol = str(inst.get("symbol") or "").strip()
                asset_name = str(inst.get("asset") or symbol).strip()
                if not symbol:
                    continue
                try:
                    if feed_mode == "live":
                        bars = self._load_live_bars(symbol, cfg)
                    else:
                        bars = self._load_bars(asset_name)
                except CapabilityGap as exc:
                    totals["gaps"] += 1
                    _record_action(f"{symbol}: gap ({exc.capability})")
                    self._record_feed_failure(
                        provider=str(cfg.get("live_provider") or "yahoo"),
                        symbol=symbol,
                        reason=str(exc)[:400],
                        capability=str(getattr(exc, "capability", "") or "market_data"),
                    )
                    continue
                except Exception as exc:  # noqa: BLE001 - a bad feed must not stop the others
                    totals["errors"] += 1
                    self._logger.warning("feed load failed for %s (%s): %s", symbol, asset_name, exc)
                    _record_action(f"{symbol}: feed_error")
                    self._record_feed_failure(
                        provider=str(cfg.get("live_provider") or feed_mode),
                        symbol=symbol,
                        reason=f"feed_error: {exc}"[:400],
                    )
                    continue
                if not bars:
                    if feed_mode == "live":
                        _record_action(f"{symbol}: empty_live_feed")
                        self._record_feed_failure(
                            provider=str(cfg.get("live_provider") or "yahoo"),
                            symbol=symbol,
                            reason="empty_live_feed",
                        )
                    else:
                        exhausted += 1
                        _record_action(f"{symbol}: empty_feed")
                    continue

                if feed_mode == "live":
                    gap = self._detect_feed_gap(state, symbol, bars)
                    if gap is not None and (feed_gap_days is None or gap > feed_gap_days):
                        feed_gap_days = gap
                    cursor = len(bars) - 1
                    price = float(bars[cursor]["close"])
                    marks[symbol] = price
                    bar_key = str(
                        bars[cursor].get("t") if bars[cursor].get("t") is not None else cursor
                    )
                    if not session_open:
                        totals["session_skips"] += 1
                        _record_action(
                            f"{symbol}: session_closed ({sess.reason}) mark @ {price:.2f}"
                        )
                        continue
                    if last_bar_keys.get(symbol) == bar_key and not as_alt:
                        _record_action(f"{symbol}: mark_only @ {price:.2f} (same bar)")
                        continue
                    # Alternatives always get one decision attempt even if bar was marked,
                    # so "next better name" can still fire when the primary book was quiet.
                    if as_alt and last_bar_keys.get(symbol) == bar_key:
                        # still evaluate once per session via alt-cooldown in state
                        alt_done = set(state.get("alt_decided_bars") or [])
                        alt_key = f"{symbol}:{bar_key}"
                        if alt_key in alt_done:
                            _record_action(f"{symbol}: mark_only @ {price:.2f} (alt same bar)")
                            continue
                        alt_done.add(alt_key)
                        state["alt_decided_bars"] = list(alt_done)[-200:]
                    action = self._decide_bar(
                        symbol=symbol,
                        bars=bars,
                        cursor=cursor,
                        cfg=cfg,
                        strategy=strategy,
                        allowed=allowed,
                        blocked=sorted(blocked),
                        portfolio_id=portfolio_id,
                        mission_id=ctx.mission_id,
                        config_version=ctx.config_version,
                        totals=totals,
                        marks=marks,
                        state=state,
                        pack=pack,
                        instrument=inst,
                    )
                    last_bar_keys[symbol] = bar_key
                    if as_alt and action and ": hold @" not in action and "mark_only" not in action:
                        action = f"{action} [alt]"
                    _record_action(action)
                    bar_snapshot = self._portfolio.snapshot(portfolio_id, prices=marks)
                    self._check_drawdown(state, bar_snapshot, cfg, ctx.mission_id)
                    continue

                # --- asset_replay path ---
                cursor = int(cursors.get(symbol, 0))
                if cursor >= len(bars):
                    exhausted += 1
                    _record_action(f"{symbol}: feed_exhausted ({len(bars)} bars)")
                    continue

                if not session_open:
                    price = float(bars[min(cursor, len(bars) - 1)]["close"])
                    marks[symbol] = price
                    totals["session_skips"] += 1
                    _record_action(
                        f"{symbol}: session_closed ({sess.reason}) mark @ {price:.2f}"
                    )
                    continue

                processed = 0
                while cursor < len(bars) and processed < bars_per_tick:
                    action = self._decide_bar(
                        symbol=symbol,
                        bars=bars,
                        cursor=cursor,
                        cfg=cfg,
                        strategy=strategy,
                        allowed=allowed,
                        blocked=sorted(blocked),
                        portfolio_id=portfolio_id,
                        mission_id=ctx.mission_id,
                        config_version=ctx.config_version,
                        totals=totals,
                        marks=marks,
                        state=state,
                        pack=pack,
                        instrument=inst,
                    )
                    _record_action(action)
                    bar_snapshot = self._portfolio.snapshot(portfolio_id, prices=marks)
                    self._check_drawdown(state, bar_snapshot, cfg, ctx.mission_id)
                    cursor += 1
                    processed += 1
                cursors[symbol] = cursor
                if cursor >= len(bars):
                    exhausted += 1

        _process_batch(instruments, as_alt=False)

        # No fill yet → try next ranked alternatives (cheaper / next in watchlist).
        prefer_alt = cfg.get("prefer_next_alternatives")
        if prefer_alt is None:
            prefer_alt = True
        if (
            session_open
            and prefer_alt
            and int(totals.get("buys") or 0) == 0
            and feed_mode == "live"
        ):
            alts = self._next_alternative_instruments(
                have={str(i.get("symbol") or "") for i in instruments},
                program_id=str(cfg.get("program_id") or "market_intelligence"),
                cash=float(self._portfolio.snapshot(portfolio_id, prices=marks).get("cash") or cash_hint),
                marks=marks,
                max_n=max(1, int(cfg.get("max_next_alternatives") or 12)),
                fallback_index=str(cfg.get("universe_index") or "NIFTY50"),
            )
            if alts:
                _record_action(
                    f"next_alt: trying {len(alts)} alternative(s) after primary "
                    f"({primary_count}) held/untradeable"
                )
                _process_batch(alts, as_alt=True)
                state["last_alternatives"] = [a.get("symbol") for a in alts]
            else:
                state["last_alternatives"] = []
        else:
            state.setdefault("last_alternatives", [])

        state["cursors"] = cursors
        state["last_bar_keys"] = last_bar_keys
        state["last_marks"] = {k: float(v) for k, v in marks.items() if v is not None}
        state["ticks"] = int(state.get("ticks", 0)) + 1
        state["feed_mode"] = feed_mode
        if feed_gap_days is not None:
            state["feed_gap_days"] = feed_gap_days

        # Persist hold/feed reasons for evening honesty + outage catch-up digests.
        try:
            from zoneinfo import ZoneInfo

            from atlas.config import get_config
            from atlas.investment.session_notes import merge_day_notes

            ist_date = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
            data_dir = str(get_config().paths.data)
            merge_day_notes(
                data_dir,
                portfolio_key=portfolio_key,
                ist_date=ist_date,
                reason_counts=reason_counts,
                samples=last_actions[-12:],
                extra={"feed_gap_days": feed_gap_days} if feed_gap_days is not None else None,
            )
        except Exception:  # noqa: BLE001
            self._logger.debug("session notes merge skipped", exc_info=True)

        snapshot = self._portfolio.snapshot(portfolio_id, prices=marks)
        state["equity"] = snapshot["equity"]

        # Live tape never "exhausts"; replay completes when every feed is spent.
        done = (
            False
            if feed_mode == "live"
            else (exhausted >= len(instruments) and exhausted > 0)
        )
        action_bit = ""
        if last_actions:
            # Keep journal readable: last few actions only.
            action_bit = " | " + "; ".join(last_actions[-4:])
        session_bit = ""
        if respect_hours and not session_open:
            session_bit = f" | market {sess.session_id} closed ({sess.reason})"
        elif respect_hours and sess.session_id != "always_open":
            session_bit = f" | market {sess.session_id} open"
        note = (
            f"{config_note}tick [{feed_mode}]: {totals['decisions']} decision(s) "
            f"(+{totals['buys']} buy, +{totals['sells']} sell, {totals['holds']} hold"
            + (f", {totals['gaps']} gap" if totals["gaps"] else "")
            + (f", {totals['errors']} error" if totals["errors"] else "")
            + (
                f", {totals['session_skips']} session_skip"
                if totals["session_skips"]
                else ""
            )
            + f"); equity {snapshot['equity']:.2f} "
            f"(P&L {snapshot['realized_pnl'] + snapshot['unrealized_pnl']:+.2f})"
            f"{session_bit}{action_bit}"
            + (" | DONE: all feeds exhausted (fixture replay complete)" if done else "")
        ).strip()
        return TickResult(state=state, done=done, note=note)

    # --- instrument ordering / next-best alternatives --------------------
    @staticmethod
    def _order_tradeable_first(
        instruments: list[dict[str, Any]],
        *,
        cash: float,
        marks: dict[str, float],
    ) -> list[dict[str, Any]]:
        """Prefer ranked names we can actually buy a whole share of with cash."""

        def key(inst: dict[str, Any]) -> tuple[int, float, int]:
            sym = str(inst.get("symbol") or "")
            px = marks.get(sym)
            try:
                price = float(px) if px is not None else None
            except (TypeError, ValueError):
                price = None
            # 0 = affordable / unknown, 1 = too expensive for 1 share
            unaffordable = 0
            if price is not None and cash > 0 and price > cash:
                unaffordable = 1
            rank = inst.get("rank")
            try:
                rank_i = int(rank) if rank is not None else 999
            except (TypeError, ValueError):
                rank_i = 999
            score = inst.get("score")
            try:
                score_f = -float(score) if score is not None else 0.0
            except (TypeError, ValueError):
                score_f = 0.0
            return (unaffordable, score_f, rank_i)

        return sorted(list(instruments), key=key)

    def _name_target_pct(
        self, cfg: dict[str, Any], persona: dict[str, Any] | None
    ) -> float | None:
        """Per-name sizing target so one fill cannot absorb the whole book."""
        try:
            from atlas.investment.portfolio_optimizer import target_name_pct

            ceiling = cfg.get("max_name_pct") or cfg.get("max_exposure_pct")
            if ceiling is not None:
                ceiling = float(ceiling)
                if ceiling > 1.0:
                    ceiling /= 100.0
            return target_name_pct(persona, {"max_name_pct": ceiling})
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("name target sizing skipped: %s", exc)
            return None

    def _next_alternative_instruments(
        self,
        *,
        have: set[str],
        program_id: str,
        cash: float,
        marks: dict[str, float],
        max_n: int = 12,
        fallback_index: str = "NIFTY50",
    ) -> list[dict[str, Any]]:
        """Pull next ranked watchlist names not already in the primary batch."""
        from atlas.investment import watchlists as wl
        from atlas.investment.universe import as_instruments

        have_l = {str(s).strip().upper() for s in have if s}
        pool: list[dict[str, Any]] = []
        try:
            rows = wl.ranked_rows(program_id, max_n=max(40, max_n * 3))
        except Exception:  # noqa: BLE001
            rows = []
        for idx, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").strip()
            if not sym or sym.upper() in have_l:
                continue
            pool.append(
                {
                    "symbol": sym,
                    "asset": str(row.get("asset") or "").strip(),
                    "rank": row.get("rank", idx + 1),
                    "score": row.get("score"),
                    "alt": True,
                }
            )
        if not pool:
            for inst in as_instruments(fallback_index, limit=40):
                sym = str(inst.get("symbol") or "").strip()
                if not sym or sym.upper() in have_l:
                    continue
                pool.append({**inst, "alt": True})
        ordered = self._order_tradeable_first(pool, cash=cash, marks=marks)
        return ordered[: max(1, int(max_n))]

    def _record_di_packet(
        self,
        *,
        action: str,
        symbol: str,
        strategy_tag: str,
        portfolio_key: str,
        mission_id: Any,
        price: float,
        cfg: dict[str, Any],
        indicators: dict[str, Any] | None = None,
        reasons_for: list[str] | None = None,
        reasons_against: list[str] | None = None,
        engine_decision_id: Any = None,
        fill_trade_id: Any = None,
        qty: float | None = None,
        filled_qty: float | None = None,
        fill_price: float | None = None,
        fees: float | None = None,
        research_gate: dict[str, Any] | None = None,
        portfolio_gate: dict[str, Any] | None = None,
        as_alt: bool = False,
        sector: str | None = None,
        plan_link: dict[str, Any] | None = None,
        gap_pct: float | None = None,
        bars: list[dict[str, Any]] | None = None,
        cursor: int | None = None,
    ) -> None:
        """DI.1 — freeze a Decision Packet (best-effort; never raises)."""
        store = self._decision_packets
        if store is None:
            return
        try:
            from atlas.investment.decision_packets import (
                empty_market_snapshot,
                infer_strategy_tag,
                stamp_regime_on_snapshot,
            )

            tag = strategy_tag or infer_strategy_tag(kind=action, as_alt=as_alt)
            score = None
            valuation = None
            fundamentals = None
            coverage = None
            if self._investment_research is not None:
                try:
                    aw = self._investment_research.awareness(
                        symbol,
                        program_id=str(cfg.get("program_id") or "market_intelligence"),
                    )
                    if isinstance(aw, dict):
                        score = aw.get("investment_score")
                        valuation = aw.get("valuation") if isinstance(aw.get("valuation"), dict) else None
                        coverage = aw.get("coverage")
                        if isinstance(coverage, dict):
                            coverage = coverage.get("ratio") or coverage.get("score")
                except Exception:  # noqa: BLE001
                    pass
            try:
                from atlas.config import get_config
                from atlas.investment.fundamentals import get_symbol as fund_get

                fundamentals = fund_get(
                    str(get_config().paths.data),
                    symbol,
                    program_id=str(cfg.get("program_id") or "market_intelligence"),
                )
            except Exception:  # noqa: BLE001
                fundamentals = None
            session = str(cfg.get("market_session") or "nse_equity")
            obs_ids: list[str] = []
            macro_obs: list[dict] = []
            if self._observations is not None:
                try:
                    obs_ids = self._observations.ids_for_symbol(
                        symbol, limit=8, since_hours=72.0
                    )
                except Exception:  # noqa: BLE001
                    obs_ids = []
                try:
                    # LQ.6 — cite recent macro/policy regime tags when present
                    recent = self._observations.list_since(
                        since_hours=168.0, limit=40
                    )
                    macro_obs = [
                        o
                        for o in recent
                        if isinstance(o, dict)
                        and str(o.get("kind") or "")
                        in {"macro_event", "policy_event"}
                    ][:12]
                except Exception:  # noqa: BLE001
                    macro_obs = []

            # DI.5 — process proxy context
            from atlas.investment.process_proxies import (
                gap_pct_from_bars,
                plan_index,
            )

            gap = gap_pct
            if gap is None and bars:
                gap = gap_pct_from_bars(bars, cursor)
            plan_doc = None
            plink = dict(plan_link) if isinstance(plan_link, dict) else None
            try:
                from atlas.investment import watchlists as wl

                snap = wl.latest(
                    str(cfg.get("program_id") or "market_intelligence")
                )
                if isinstance(snap, dict):
                    plan_doc = (snap.get("extra") or {}).get("daily_plan") or snap.get(
                        "daily_plan"
                    )
                if plink is None and isinstance(plan_doc, dict):
                    cand = plan_index(plan_doc).get(str(symbol).upper())
                    if cand:
                        plink = {
                            "rank": cand.get("rank"),
                            "suggested_notional": cand.get("suggested_notional"),
                            "in_daily_plan": True,
                            "as_alt": as_alt,
                        }
                    else:
                        plink = {
                            "rank": None,
                            "suggested_notional": None,
                            "in_daily_plan": False,
                            "as_alt": as_alt,
                        }
            except Exception:  # noqa: BLE001
                if plink is None:
                    plink = {
                        "rank": None,
                        "suggested_notional": None,
                        "in_daily_plan": False,
                        "as_alt": as_alt,
                    }

            prices_doc = {
                "mark": price,
                "suggested_qty": qty,
                "filled_qty": filled_qty,
                "fill_price": fill_price,
                "fees": fees,
            }
            if gap is not None:
                prices_doc["gap_pct"] = gap

            store.record(
                action=action,
                symbol=symbol,
                portfolio_key=portfolio_key or "india_equity_learner",
                strategy_tag=tag,
                mission_id=str(mission_id) if mission_id else None,
                engine_decision_id=str(engine_decision_id) if engine_decision_id else None,
                fill_trade_id=str(fill_trade_id) if fill_trade_id else None,
                market_snapshot=stamp_regime_on_snapshot(
                    empty_market_snapshot(session=session, sector=sector),
                    macro_observations=macro_obs,
                ),
                prices=prices_doc,
                investment_score=score if isinstance(score, dict) else None,
                indicators=indicators,
                valuation=valuation,
                fundamentals=fundamentals,
                reasons_for=reasons_for or [],
                reasons_against=reasons_against or [],
                observation_ids=obs_ids,
                research_gate=research_gate,
                portfolio_gate=portfolio_gate,
                research_coverage=float(coverage) if coverage is not None else None,
                plan_link=plink,
                process_context={
                    "plan": plan_doc if isinstance(plan_doc, dict) else None,
                    "recent_losses": set(),
                    "gap_pct": gap,
                },
            )
        except Exception:  # noqa: BLE001
            self._logger.debug("DI.1 packet write skipped", exc_info=True)

    # --- per-bar decision ------------------------------------------------
    def _decide_bar(
        self,
        *,
        symbol: str,
        bars: list[dict[str, Any]],
        cursor: int,
        cfg: dict[str, Any],
        strategy: dict[str, Any],
        allowed: list[str],
        blocked: list[str],
        portfolio_id: Any,
        mission_id: str,
        config_version: int | None,
        totals: dict[str, int],
        marks: dict[str, float],
        state: dict[str, Any],
        pack: Any = None,
        instrument: dict[str, Any] | None = None,
    ) -> str | None:
        from atlas.investment.packs import resolve_pack_or_unknown

        if pack is None:
            pack = resolve_pack_or_unknown(state.get("instrument_pack") or "cash_equity")
        closes = [float(b["close"]) for b in bars[: cursor + 1]]
        indicators = compute_indicators(closes, strategy)
        price = closes[-1]
        marks[symbol] = price
        position = self._portfolio.position(portfolio_id, symbol) or {}
        held = float(position.get("quantity", 0.0))
        snapshot = self._portfolio.snapshot(portfolio_id, prices={symbol: price})
        inst_row = instrument if isinstance(instrument, dict) else {}

        mentor_advice = ""
        mission_ctx_summary = ""
        mission_ctx_citations: list[str] = []
        fact_findings: list[dict[str, Any]] = []
        predicted_findings: list[dict[str, Any]] = []
        portfolio_key = str(state.get("portfolio_key") or cfg.get("portfolio_key") or "").strip()
        persona = state.get("persona") if isinstance(state.get("persona"), dict) else (
            cfg.get("persona") if isinstance(cfg.get("persona"), dict) else {}
        )
        advice_query = f"markets trading {symbol}"
        if portfolio_key:
            advice_query = f"{advice_query} portfolio:{portfolio_key}"
        if self._mission_context is not None:
            try:
                gathered = self._mission_context.gather(
                    advice_query,
                    program_id="market",
                    limit=8,
                )
                mission_ctx_summary = str(gathered.get("summary") or "")[:400]
                mission_ctx_citations = list(gathered.get("citations") or [])[:8]
                # Prefer Experience block from shared API when present.
                for it in gathered.get("items") or []:
                    kind = str(it.get("item_kind") or it.get("kind") or "")
                    if kind == "experience_advice":
                        # IL.10 — drop other books' advice
                        from atlas.investment.portfolios import filter_journals_for_portfolio

                        journals = filter_journals_for_portfolio(
                            it.get("journals") or [it], portfolio_key or None
                        )
                        if portfolio_key and not journals and it.get("journals"):
                            continue
                        mentor_advice = str(it.get("advice") or "")[:500]
                    elif kind == "finding":
                        row = {
                            "id": it.get("id"),
                            "statement": it.get("statement"),
                            "truth_kind": it.get("truth_kind"),
                            "claim_type": it.get("claim_type"),
                            "status": it.get("status"),
                            "freshness": it.get("freshness"),
                            "valid_from": it.get("valid_from"),
                            "valid_until": it.get("valid_until"),
                        }
                        if str(it.get("truth_kind") or "") == "predicted":
                            predicted_findings.append(row)
                        else:
                            fact_findings.append(row)
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("mission_context gather skipped: %s", exc)
        if not mentor_advice and self._learning is not None:
            try:
                adv = self._learning.advice_for(advice_query, limit=3)
                from atlas.investment.portfolios import filter_journals_for_portfolio

                journals = filter_journals_for_portfolio(
                    (adv or {}).get("journals") or [], portfolio_key or None
                )
                if portfolio_key:
                    # Rebuild advice text only from this book's journals when present
                    if journals:
                        mentor_advice = str(adv.get("advice") or "")[:500]
                    else:
                        mentor_advice = ""
                else:
                    mentor_advice = str(adv.get("advice") or "")[:500]
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("mentor advice_for skipped: %s", exc)

        request = DecisionRequest(
            mission_id=mission_id,
            mission_type=MISSION_TYPE_PAPER_TRADING,
            config_version=config_version,
            context={
                "symbol": symbol,
                "domain": "markets",
                "domains": ["markets"],
                "mission_type": MISSION_TYPE_PAPER_TRADING,
                "price": price,
                "indicators": indicators,
                "position_qty": held,
                "equity": snapshot["equity"],
                "cash": snapshot["cash"],
                "allowed_symbols": allowed,
                "blocked_symbols": blocked,
                "max_position_qty": cfg.get("max_position_qty", 0),
                "max_exposure_pct": cfg.get("max_exposure_pct", 0)
                or strategy.get("max_exposure_pct", 0),
                "trade_fraction": strategy.get("trade_fraction", 0.1),
                "name_target_pct": self._name_target_pct(cfg, persona),
                "allow_min_lot": strategy.get(
                    "allow_min_lot", cfg.get("allow_min_lot", True)
                ),
                "rsi_overbought": strategy.get("rsi_overbought", 70.0),
                "rsi_oversold": strategy.get("rsi_oversold", 30.0),
                "mentor_advice": mentor_advice,
                "mission_context_summary": mission_ctx_summary,
                "mission_context_citations": mission_ctx_citations,
                # OI-F2 — keep forecasts out of the operative-fact bucket.
                "fact_findings": fact_findings[:8],
                "predicted_findings": predicted_findings[:8],
                # IL.10
                "portfolio_key": portfolio_key or None,
                "persona": persona or None,
                "persona_risk": (persona or {}).get("risk"),
                "persona_horizon": (persona or {}).get("time_horizon"),
                "allowed_assets": (persona or {}).get("allowed_assets"),
                "instrument_pack": getattr(pack, "id", None),
            },
        )
        decision = self._engine.decide(request)
        totals["decisions"] += 1
        why = (decision.why or "").strip()
        why_short = (why[:80] + "…") if len(why) > 80 else why
        as_alt = bool((inst_row or {}).get("alt"))
        sector = str((inst_row or {}).get("sector") or "") or None

        def _pkt(
            action: str,
            *,
            strategy_tag: str,
            line: str,
            qty_v: float | None = None,
            filled: float | None = None,
            fill_px: float | None = None,
            fee_v: float | None = None,
            trade_id: Any = None,
            rg: dict[str, Any] | None = None,
            pg: dict[str, Any] | None = None,
            against: list[str] | None = None,
        ) -> None:
            self._record_di_packet(
                action=action,
                symbol=symbol,
                strategy_tag=strategy_tag,
                portfolio_key=portfolio_key,
                mission_id=mission_id,
                price=price,
                cfg=cfg,
                indicators=indicators,
                reasons_for=[why_short or line, line] if why_short else [line],
                reasons_against=against,
                engine_decision_id=getattr(decision, "id", None),
                fill_trade_id=trade_id,
                qty=qty_v,
                filled_qty=filled,
                fill_price=fill_px,
                fees=fee_v,
                research_gate=rg,
                portfolio_gate=pg,
                as_alt=as_alt,
                sector=sector,
                bars=bars,
                cursor=cursor,
            )

        if decision.action_kind != ACTION_RECOMMEND:
            if decision.action_kind == "capability_gap":
                totals["gaps"] += 1
                line = f"{symbol}: gap ({why_short or 'missing capability'})"
                _pkt("hold", strategy_tag="capability_gap", line=line)
                return line
            totals["holds"] += 1
            line = f"{symbol}: hold @ {price:.2f}"
            _pkt("hold", strategy_tag="engine_hold", line=line)
            return line

        # The engine wraps the chosen option under action["payload"] (action["kind"] == "recommend").
        payload = (decision.action or {}).get("payload") or {}
        kind = payload.get("kind")
        if kind not in ("buy", "sell"):
            totals["holds"] += 1
            line = f"{symbol}: hold @ {price:.2f}"
            _pkt("hold", strategy_tag="engine_hold", line=line)
            return line

        qty = float(payload.get("quantity") or 0.0)
        if qty <= 0:
            totals["holds"] += 1
            line = f"{symbol}: hold @ {price:.2f}"
            _pkt("hold", strategy_tag="engine_hold", line=line)
            return line

        if self._policy_engine is not None:
            try:
                exposure = 0.0
                if float(snapshot.get("equity") or 0) > 0 and price > 0:
                    exposure = 100.0 * (held * price) / float(snapshot["equity"])
                verdict = self._policy_engine.evaluate(
                    action={"kind": kind, "symbol": symbol, "quantity": qty, "price": price},
                    context={
                        "equity": snapshot.get("equity"),
                        "position_qty": held,
                        "exposure_pct": exposure,
                        "drawdown_pct": state.get("last_drawdown_pct"),
                        "price": price,
                    },
                    scope="domain:markets",
                )
                if not verdict.get("allowed", True):
                    totals["holds"] += 1
                    detail = ""
                    viols = verdict.get("hard_violations") or []
                    if viols:
                        detail = str(viols[0].get("detail") or "")
                    line = f"{symbol}: policy_block ({detail or 'hard constraint'})"
                    _pkt(
                        "hold",
                        strategy_tag="policy_block",
                        line=line,
                        against=[detail or "hard constraint"],
                    )
                    return line
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("policy_engine evaluate skipped: %s", exc)

        # IRA — research-based buy gate (learner books default on).
        research_gate_result: dict[str, Any] | None = None
        portfolio_gate_result: dict[str, Any] | None = None
        if kind == "buy" and self._investment_research is not None:
            gate_note = self._research_buy_gate(
                symbol=symbol,
                cfg=cfg,
                portfolio_key=portfolio_key,
            )
            if gate_note:
                totals["holds"] += 1
                _pkt(
                    "hold",
                    strategy_tag="research_forced_hold",
                    line=gate_note,
                    against=[gate_note],
                )
                return gate_note
            # Capture last gate for portfolio optimizer (best-effort)
            try:
                research_gate_result = self._investment_research.gate_buy(
                    symbol,
                    program_id=str(cfg.get("program_id") or "market_intelligence"),
                    require_mvr=bool(
                        cfg.get("require_mvr")
                        if cfg.get("require_mvr") is not None
                        else ("learner" in (portfolio_key or "").lower())
                    ),
                    require_thesis=bool(
                        cfg.get("require_thesis")
                        if cfg.get("require_thesis") is not None
                        else True
                    ),
                    mos_mode=str(cfg.get("mos_mode") or "soft") if "learner" in (portfolio_key or "").lower() else cfg.get("mos_mode"),
                )
            except Exception:  # noqa: BLE001
                research_gate_result = {"allowed": True, "action": "buy_ok"}

        # IIP.7 — portfolio optimizer pre-trade gate (buys)
        if kind == "buy" and cfg.get("portfolio_gate", True):
            try:
                from atlas.investment.portfolio_optimizer import pre_trade_check

                score = None
                mos_pct = None
                if self._investment_research is not None:
                    try:
                        aw = self._investment_research.awareness(
                            symbol,
                            program_id=str(cfg.get("program_id") or "market_intelligence"),
                        )
                        score = aw.get("investment_score")
                        val = aw.get("valuation") if isinstance(aw.get("valuation"), dict) else {}
                        if val.get("margin_of_safety_pct") is not None:
                            mos_pct = float(val["margin_of_safety_pct"])
                    except Exception:  # noqa: BLE001
                        score = None
                port_cfg = {
                    "max_names": cfg.get("max_names"),
                    "max_name_pct": cfg.get("max_name_pct") or cfg.get("max_exposure_pct"),
                    "sector_cap_pct": cfg.get("sector_cap_pct"),
                    "min_cash_pct": cfg.get("min_cash_pct"),
                    "min_investment_confidence": cfg.get("min_investment_confidence") or "low",
                    "mos_pct": mos_pct,
                }
                # max_exposure_pct historically 0–100
                if port_cfg.get("max_name_pct") is not None:
                    try:
                        m = float(port_cfg["max_name_pct"])
                        if m > 1.0:
                            port_cfg["max_name_pct"] = m / 100.0
                    except (TypeError, ValueError):
                        pass
                pcheck = pre_trade_check(
                    side="buy",
                    symbol=symbol,
                    quantity=qty,
                    price=price,
                    snapshot=snapshot,
                    persona=persona,
                    investment_score=score if isinstance(score, dict) else {},
                    research_gate=research_gate_result or {"allowed": True},
                    asset_class=str(
                        cfg.get("asset_class")
                        or getattr(pack, "id", None)
                        or "cash_equity"
                    ),
                    require_research=bool(cfg.get("portfolio_require_research", True)),
                    require_score=bool(cfg.get("portfolio_require_score", True)),
                    cfg=port_cfg,
                )
                # Size caps should shrink an order, not veto it: a 40% target in a
                # 35%-capped sector used to block every name after the first fill.
                trimmed_from = None
                if (
                    not pcheck.get("allowed")
                    and pcheck.get("trimmable")
                    and cfg.get("portfolio_trim_to_fit", True)
                ):
                    room_qty = float(pcheck.get("max_quantity") or 0)
                    if room_qty >= 1.0 and room_qty < qty:
                        retry = pre_trade_check(
                            side="buy",
                            symbol=symbol,
                            quantity=room_qty,
                            price=price,
                            snapshot=snapshot,
                            persona=persona,
                            investment_score=score if isinstance(score, dict) else {},
                            research_gate=research_gate_result or {"allowed": True},
                            asset_class=str(
                                cfg.get("asset_class")
                                or getattr(pack, "id", None)
                                or "cash_equity"
                            ),
                            require_research=bool(
                                cfg.get("portfolio_require_research", True)
                            ),
                            require_score=bool(cfg.get("portfolio_require_score", True)),
                            cfg=port_cfg,
                        )
                        if retry.get("allowed"):
                            trimmed_from = qty
                            qty = room_qty
                            pcheck = retry
                portfolio_gate_result = pcheck
                if trimmed_from is not None:
                    portfolio_gate_result = dict(pcheck)
                    portfolio_gate_result["trimmed_from"] = trimmed_from
                state.setdefault("portfolio_gate_log", [])
                log = list(state.get("portfolio_gate_log") or [])
                log.append(
                    {
                        "symbol": symbol,
                        "allowed": pcheck.get("allowed"),
                        "action": pcheck.get("action"),
                        "reasons": pcheck.get("reasons"),
                        "qty": qty,
                        "trimmed_from": trimmed_from,
                        "binding": (pcheck.get("trim") or {}).get("binding"),
                        "price": price,
                    }
                )
                state["portfolio_gate_log"] = log[-40:]
                if not pcheck.get("allowed"):
                    totals["holds"] += 1
                    reasons = ",".join(pcheck.get("reasons") or []) or "portfolio_block"
                    line = f"{symbol}: portfolio_hold ({reasons})"
                    _pkt(
                        "hold",
                        strategy_tag="portfolio_trim",
                        line=line,
                        rg=research_gate_result,
                        pg=portfolio_gate_result,
                        against=list(pcheck.get("reasons") or []) or [reasons],
                    )
                    return line
                if trimmed_from:
                    why_short = (
                        f"{why_short} [size trimmed {trimmed_from:g}→{qty:g} by "
                        f"{(pcheck.get('trim') or {}).get('binding') or 'portfolio cap'}]"
                    )
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("portfolio gate skipped: %s", exc)

        pack_ctx: dict[str, Any] = {
            "portfolio_key": portfolio_key,
            "persona": persona,
            "position_qty": held,
            "equity": snapshot.get("equity"),
            "cash": snapshot.get("cash"),
            "instrument": inst_row,
        }
        if cfg.get("lot_size") is not None:
            pack_ctx["lot_size"] = cfg.get("lot_size")
        if cfg.get("margin_fraction") is not None:
            pack_ctx["margin_fraction"] = cfg.get("margin_fraction")
        if cfg.get("write_margin_fraction") is not None:
            pack_ctx["write_margin_fraction"] = cfg.get("write_margin_fraction")
        if cfg.get("expiry") is not None:
            pack_ctx["expiry"] = cfg.get("expiry")
        if inst_row.get("expiry") is not None:
            pack_ctx["expiry"] = inst_row.get("expiry")
        if inst_row.get("underlying_price") is not None:
            pack_ctx["underlying_price"] = inst_row.get("underlying_price")
        validation = pack.validate_order(
            side=kind,
            symbol=symbol,
            quantity=qty,
            price=price,
            context=pack_ctx,
        )
        if not validation.ok:
            if validation.capability_gap:
                totals["gaps"] += 1
                line = f"{symbol}: gap ({validation.reason})"
                _pkt("hold", strategy_tag="capability_gap", line=line, against=[str(validation.reason)])
                return line
            totals["holds"] += 1
            line = f"{symbol}: pack_block ({validation.reason})"
            _pkt("hold", strategy_tag="pack_block", line=line, against=[str(validation.reason)])
            return line

        fee = 0.0
        fees_doc: dict[str, Any] = {}
        profile_id = str(cfg.get("broker_profile") or "").strip() or pack.default_broker_profile()
        if profile_id:
            breakdown = compute_fees(
                get_broker_profile(profile_id),
                side=kind,
                quantity=qty,
                price=price,
            )
            breakdown = pack.fee_overlay(
                breakdown,
                side=kind,
                symbol=symbol,
                quantity=qty,
                price=price,
                context=pack_ctx,
            )
            fee = float(breakdown.total)
            fees_doc = breakdown.as_dict()
        try:
            trade = self._portfolio.apply_trade(
                portfolio_id,
                symbol=symbol,
                side=kind,
                quantity=qty,
                price=price,
                fee=fee,
                fees=fees_doc,
                mission_id=mission_id,
                decision_id=decision.id,
            )
        except Exception as exc:  # noqa: BLE001 - a rejected sim fill is reported, never fatal
            totals["errors"] += 1
            self._logger.warning("sim fill rejected (%s %s %s): %s", kind, qty, symbol, exc)
            line = f"{symbol}: fill_rejected ({exc})"
            _pkt(
                "hold",
                strategy_tag="fill_rejected",
                line=line,
                qty_v=qty,
                against=[str(exc)],
                rg=research_gate_result,
                pg=portfolio_gate_result,
            )
            return line

        totals["buys" if kind == "buy" else "sells"] += 1
        fill_payload = {
            "mission_id": str(mission_id), "decision_id": str(decision.id) if decision.id else None,
            "symbol": symbol, "side": kind, "quantity": qty, "price": price,
            "fee": fee,
            "fees": fees_doc,
            "broker_profile": profile_id,
            "realized_pnl": float(trade.get("realized_pnl", 0.0)),
        }
        self._emit("PaperTradingFill", fill_payload)
        self._record_research_outcome(
            symbol=symbol,
            kind=kind,
            trade=trade,
            why=why_short or "",
            cfg=cfg,
            portfolio_key=portfolio_key,
            engine_decision_id=getattr(decision, "id", None),
        )
        trade_id = trade.get("id") or trade.get("trade_id")
        line = f"{symbol}: {kind} {qty:g} @ {price:.2f} ({why_short or 'signal'})"
        _pkt(
            kind,
            strategy_tag="next_alternative" if as_alt else "sma_cross_rsi",
            line=line,
            qty_v=qty,
            filled=qty,
            fill_px=price,
            fee_v=fee,
            trade_id=trade_id,
            rg=research_gate_result,
            pg=portfolio_gate_result,
        )
        if self._investor_mailer is not None:
            try:
                decision_doc = {}
                if decision is not None:
                    decision_doc = {
                        "id": getattr(decision, "id", None),
                        "action": getattr(decision, "action", None)
                        or getattr(decision, "kind", None),
                        "rationale": getattr(decision, "rationale", None)
                        or getattr(decision, "reason", None),
                        "confidence": getattr(decision, "confidence", None),
                        "status": getattr(decision, "status", None),
                    }
                    if hasattr(decision, "as_dict"):
                        try:
                            decision_doc = {**decision_doc, **(decision.as_dict() or {})}
                        except Exception:  # noqa: BLE001
                            pass
                decision_doc["research_gate"] = research_gate_result
                decision_doc["portfolio_gate"] = portfolio_gate_result
                self._investor_mailer.send_trade(
                    side=kind,
                    symbol=symbol,
                    quantity=qty,
                    price=price,
                    fee=fee,
                    fees=fees_doc,
                    reason=why_short or "",
                    decision=decision_doc,
                    mission_id=str(mission_id) if mission_id else None,
                    realized_pnl=float(trade.get("realized_pnl", 0.0)),
                    laboratory_id=str(
                        state.get("portfolio_key")
                        or cfg.get("portfolio_key")
                        or "india_equity_learner"
                    ),
                    portfolio_key=str(
                        state.get("portfolio_key")
                        or cfg.get("portfolio_key")
                        or "india_equity_learner"
                    ),
                )
            except Exception:  # noqa: BLE001 - never fail a fill on email
                self._logger.debug("investor trade email failed", exc_info=True)
        if kind == "sell":
            learn_cfg = dict(cfg)
            learn_cfg.setdefault("portfolio_key", state.get("portfolio_key"))
            if state.get("persona") and not learn_cfg.get("persona"):
                learn_cfg["persona"] = state.get("persona")
            self._remember_outcome(
                symbol, trade, decision, indicators=indicators, cfg=learn_cfg
            )
        return line

    # --- IRA research gate + daily learning ------------------------------
    def _research_buy_gate(
        self,
        *,
        symbol: str,
        cfg: dict[str, Any],
        portfolio_key: str,
    ) -> str | None:
        """Return a hold note when research gate blocks; None if buy may proceed."""
        research = self._investment_research
        if research is None:
            return None
        pk = (portfolio_key or "").lower()
        learnerish = "learner" in pk
        if cfg.get("require_mvr") is None:
            require_mvr = learnerish or bool(cfg.get("research_gate", False))
        else:
            require_mvr = bool(cfg.get("require_mvr"))
        if cfg.get("require_thesis") is None:
            require_thesis = require_mvr
        else:
            require_thesis = bool(cfg.get("require_thesis"))
        require_mos = cfg.get("require_mos")
        mos_mode = str(cfg.get("mos_mode") or "").strip() or None
        if mos_mode is None and learnerish:
            # Soft: unknown MoS still allows learning fills; known adverse MoS blocks.
            mos_mode = "soft"
        min_mos_pct = cfg.get("min_mos_pct")
        min_coverage = float(cfg.get("research_min_coverage") or 0.0)
        program_id = str(cfg.get("program_id") or "market_intelligence")
        if not (require_mvr or require_thesis or require_mos is not None or min_coverage or mos_mode):
            return None

        auto = cfg.get("research_auto_mvr")
        if auto is None:
            auto = require_mvr
        gate_kw = dict(
            program_id=program_id,
            require_mvr=require_mvr,
            require_thesis=require_thesis,
            require_mos=bool(require_mos) if require_mos is not None else None,
            min_coverage=min_coverage,
            min_mos_pct=float(min_mos_pct) if min_mos_pct is not None else None,
            mos_mode=mos_mode,
        )
        try:
            gate = research.gate_buy(symbol, **gate_kw)
            if not gate.get("allowed") and auto:
                # Bounded hermetic MVR pass so paper trading can learn from research.
                research.start(
                    symbol,
                    program_id=program_id,
                    mode=str(cfg.get("research_mode") or "mvr"),
                    force=False,
                    trigger="paper_trading_gate",
                )
                gate = research.gate_buy(symbol, **gate_kw)
            if gate.get("allowed"):
                return None
            reasons = ",".join(gate.get("reasons") or []) or "research_incomplete"
            return f"{symbol}: research_hold ({reasons})"
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("research gate skipped: %s", exc)
            return None

    def _record_research_outcome(
        self,
        *,
        symbol: str,
        kind: str,
        trade: dict[str, Any],
        why: str,
        cfg: dict[str, Any],
        portfolio_key: str,
        engine_decision_id: Any = None,
        packet_decision_id: str | None = None,
    ) -> None:
        research = self._investment_research
        if research is None and self._attributions is None:
            return
        program_id = str(cfg.get("program_id") or "market_intelligence")
        pnl = float(trade.get("realized_pnl") or 0.0)
        if kind == "buy":
            result = "observed"
            note = f"Sim buy entered — {why or 'signal'}"
        elif pnl > 0:
            result = "held"
            note = f"Sim sell profit {pnl:+.2f} — thesis tentatively held"
        elif pnl < 0:
            result = "weakened"
            note = f"Sim sell loss {pnl:+.2f} — review falsifiers"
        else:
            result = "observed"
            note = f"Sim sell flat — {why or 'exit'}"

        di_grades = None
        if kind == "sell" and self._attributions is not None:
            try:
                did = packet_decision_id or (
                    str(engine_decision_id) if engine_decision_id else None
                )
                # Prefer DI packet id when we can find a recent buy packet for symbol
                packet = None
                if self._decision_packets is not None and did:
                    packet = self._decision_packets.get(str(did))
                if packet is None and self._decision_packets is not None:
                    recent = self._decision_packets.list_symbol(
                        symbol=symbol, limit=5, portfolio_key=portfolio_key or None
                    )
                    for p in recent:
                        if p.get("action") == "buy":
                            packet = p
                            did = str(p.get("decision_id") or did)
                            break
                fill_px = float(trade.get("price") or 0) or None
                entry = None
                if packet:
                    prices = packet.get("prices") or {}
                    entry = prices.get("fill_price") or prices.get("mark")
                chg = None
                try:
                    if entry is not None and fill_px is not None and float(entry) != 0:
                        chg = 100.0 * (float(fill_px) - float(entry)) / abs(float(entry))
                except (TypeError, ValueError):
                    chg = None
                attr = self._attributions.record(
                    decision_id=did,
                    symbol=symbol,
                    portfolio_key=portfolio_key or "india_equity_learner",
                    trigger="exit",
                    checkpoint="exit",
                    packet=packet,
                    pnl=pnl,
                    price_change_pct=chg,
                    extra={
                        "why": why,
                        "exit_reason": why,
                        "engine_decision_id": str(engine_decision_id)
                        if engine_decision_id
                        else None,
                    },
                )
                di_grades = (attr.get("attribution") or {}).get("grades")
            except Exception:  # noqa: BLE001
                self._logger.debug("DI.Attr record failed", exc_info=True)

        if research is None:
            return
        try:
            research.record_outcome(
                symbol,
                program_id=program_id,
                result=result,
                note=note,
                trade={
                    "side": kind,
                    "quantity": trade.get("quantity"),
                    "price": trade.get("price"),
                    "realized_pnl": pnl,
                    "portfolio_key": portfolio_key,
                },
                di_grades=di_grades,
            )
        except Exception:  # noqa: BLE001
            self._logger.debug("research outcome record failed", exc_info=True)

    # --- learning loop ---------------------------------------------------
    def _remember_outcome(
        self,
        symbol: str,
        trade: dict[str, Any],
        decision: Any,
        *,
        indicators: dict[str, Any] | None = None,
        cfg: dict[str, Any] | None = None,
    ) -> None:
        """Record Decision→Outcome via the OI-F4 feedback convention (OI-MP1 / OI-F1)."""
        if self._experience_os is None and self._learning is None:
            return
        from atlas.decision.feedback import (
            DIFF_MATCHED,
            DIFF_MISSED,
            DIFF_UNKNOWN,
            build_feedback_journal,
            record_feedback_loop,
        )
        from atlas.decision.knowledge import (
            bias_recommendations,
            decision_knowledge_tags,
            link_metadata,
            outcome_label,
            should_enable_decision_bias,
        )

        pnl = float(trade.get("realized_pnl", 0.0))
        outcome = outcome_label(pnl)
        difference = {
            "profit": DIFF_MATCHED,
            "loss": DIFF_MISSED,
            "flat": DIFF_UNKNOWN,
        }.get(outcome, DIFF_UNKNOWN)
        decision_id = str(getattr(decision, "id", None) or "") or None
        why = (decision.why or "").strip() or "strategy exit signal"
        ind = indicators if isinstance(indicators, dict) else {}
        observation_bits = []
        if ind.get("rsi") is not None:
            observation_bits.append(f"RSI={ind.get('rsi')}")
        if ind.get("sma_fast") is not None and ind.get("sma_slow") is not None:
            observation_bits.append(
                f"SMA fast/slow={ind.get('sma_fast')}/{ind.get('sma_slow')}"
            )
        observation = (
            "; ".join(str(b) for b in observation_bits)
            if observation_bits
            else f"Exit signal on {symbol} at realized P&L {pnl:+.2f}"
        )
        reflection = (
            "Outcome matched thesis."
            if pnl > 0
            else (
                "Outcome contradicted thesis — review entry timing and open risk events."
                if pnl < 0
                else "Flat outcome — little signal for strategy update."
            )
        )
        lesson = (
            "Reinforce setups that produced positive expectancy under current constraints."
            if pnl > 0
            else (
                "Before similar entries, re-check catalysts and risk limits; "
                "do not treat a single indicator as sufficient."
                if pnl < 0
                else "Treat flat outcomes as inconclusive; avoid overfitting to noise."
            )
        )
        title = f"Paper trade closed on {symbol}: {outcome} {pnl:+.2f}"
        recommendation = f"sell {symbol} (simulation)"
        outcome_text = f"{outcome} {pnl:+.2f}"
        cfg = cfg if isinstance(cfg, dict) else {}
        enable_bias = bool(cfg.get("enable_decision_soft_bias", True)) and should_enable_decision_bias(
            outcome
        )
        tags = decision_knowledge_tags(symbol, outcome, decision_id=decision_id)
        portfolio_key = str(cfg.get("portfolio_key") or "").strip()
        if portfolio_key:
            from atlas.investment.portfolios import experience_tag

            tags = list(tags) + [experience_tag(portfolio_key)]
        meta = link_metadata(
            decision_id=decision_id, symbol=symbol, outcome=outcome, pnl=pnl
        )
        meta["feedback_loop"] = True
        meta["difference"] = difference
        if portfolio_key:
            meta["portfolio_key"] = portfolio_key
            if isinstance(cfg.get("persona"), dict):
                meta["persona_objective"] = cfg["persona"].get("objective")
                meta["persona_risk"] = cfg["persona"].get("risk")
        journal_kwargs = build_feedback_journal(
            title=title,
            recommendation=recommendation,
            outcome=outcome_text,
            difference=difference,
            observation=observation,
            reasoning=why,
            reflection=reflection,
            lesson=lesson,
            domain="markets",
            mission_type=MISSION_TYPE_PAPER_TRADING,
            decision_id=decision_id,
            subject=symbol,
            recommendations=bias_recommendations(symbol, outcome, pnl),
            metadata_extra=meta,
            tags_extra=tags,
        )
        # Prefer OI-F1 decision_knowledge tags ordering / content.
        journal_kwargs["tags"] = tags + [
            t for t in journal_kwargs["tags"] if t not in tags
        ]
        journal_kwargs["metadata"] = {**journal_kwargs["metadata"], **meta}
        record_feedback_loop(
            experience_os=self._experience_os,
            learning=self._learning,
            journal_kwargs=journal_kwargs,
            enable_bias=enable_bias,
            difference=difference,
            logger=self._logger,
        )

    # --- notifications ---------------------------------------------------
    def _check_drawdown(
        self, state: dict[str, Any], snapshot: dict[str, Any], cfg: dict[str, Any], mission_id: str
    ) -> None:
        equity = float(snapshot["equity"])
        peak = float(state.get("peak_equity", equity))
        peak = max(peak, equity)
        state["peak_equity"] = peak
        threshold = float(cfg.get("drawdown_alert_pct", 0) or 0)
        if threshold <= 0 or peak <= 0:
            return
        drawdown = (peak - equity) / peak * 100.0
        state["last_drawdown_pct"] = round(drawdown, 2)
        if drawdown >= threshold and not state.get("drawdown_alerted"):
            state["drawdown_alerted"] = True
            self._emit("PaperTradingDrawdown", {
                "mission_id": str(mission_id), "equity": equity, "peak_equity": peak,
                "drawdown_pct": round(drawdown, 2), "threshold_pct": threshold,
            })
        elif drawdown < threshold:
            state["drawdown_alerted"] = False

    # --- helpers ---------------------------------------------------------
    def _load_bars(self, asset_name: str) -> list[dict[str, Any]]:
        asset = self._assets.get_by_name(ASSET_KIND_MARKET_DATA, asset_name)
        if asset is None:
            raise FileNotFoundError(f"no market_data asset named {asset_name!r}")
        artifact = self._reader.read(str(asset["id"]))
        if artifact.get("outcome") != "ok":
            raise RuntimeError(f"feed unreadable: {artifact.get('reason', 'unknown')}")
        return list(artifact.get("bars") or [])

    def _detect_feed_gap(
        self, state: dict[str, Any], symbol: str, bars: list[dict[str, Any]]
    ) -> float | None:
        """Calendar-day gap vs last successfully seen bar for this symbol (live resume)."""
        if not bars:
            return None
        last = bars[-1].get("t")
        if last is None:
            return None
        try:
            if isinstance(last, datetime):
                bar_dt = last
            else:
                raw = str(last).replace("Z", "+00:00")
                bar_dt = datetime.fromisoformat(raw)
            if bar_dt.tzinfo is None:
                bar_dt = bar_dt.replace(tzinfo=timezone.utc)
        except Exception:  # noqa: BLE001
            return None
        seen = dict(state.get("last_bar_seen_utc") or {})
        prev_raw = seen.get(symbol)
        gap: float | None = None
        if prev_raw:
            try:
                prev = datetime.fromisoformat(str(prev_raw).replace("Z", "+00:00"))
                if prev.tzinfo is None:
                    prev = prev.replace(tzinfo=timezone.utc)
                gap = max(0.0, (bar_dt - prev).total_seconds() / 86400.0)
                if gap < 1.0:
                    gap = None
            except Exception:  # noqa: BLE001
                gap = None
        seen[symbol] = bar_dt.astimezone(timezone.utc).isoformat()
        state["last_bar_seen_utc"] = seen
        return gap

    def _record_feed_failure(
        self,
        *,
        provider: str,
        symbol: str,
        reason: str,
        capability: str = "market_data",
    ) -> None:
        try:
            from atlas.config import get_config
            from atlas.investment.feed_failures import record_failure

            record_failure(
                str(get_config().paths.data),
                provider=provider,
                symbol=symbol,
                reason=reason,
                capability=capability,
                source="paper_trading",
            )
        except Exception:  # noqa: BLE001
            self._logger.debug("feed failure log skipped", exc_info=True)

    def _load_live_bars(self, symbol: str, cfg: dict[str, Any]) -> list[dict[str, Any]]:
        if self._live_market is None:
            raise CapabilityGap(
                "market_reader",
                "live feed_mode requires MarketReaderService (wire live_market= on worker)",
            )
        provider = str(cfg.get("live_provider") or "yahoo").strip() or "yahoo"
        limit = max(5, int(cfg.get("live_bars_limit", 100)))
        out = self._live_market.bars_for(symbol, provider=provider, limit=limit)
        return list(out.get("bars") or [])

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._events is None:
            return
        try:
            self._events.emit(event_type, payload, source=self.type)
        except Exception:  # noqa: BLE001 - telemetry must never break a tick
            self._logger.exception("failed to emit %s", event_type)
