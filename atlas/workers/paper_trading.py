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

# LOOP0 L0 — HBLPOWER is a dead Yahoo ticker; do not inject as a cash alt.
_SKIP_CASH_ALT_REQUESTED = frozenset({"HBLPOWER", "HBLPOWER.NS"})


def skip_cash_alts_for_lab(
    cfg: dict[str, Any] | None,
    *,
    pack_id: str = "",
    portfolio_key: str = "",
) -> bool:
    """True when this lab must not inject cash-equity watchlist alternatives.

    FNO isolation is the lab contract (buy/switch/replace). This helper still
    skips cash ``next_alt`` for FNO and the intraday Yahoo 5m budget.
    """
    from atlas.investment.lab_contracts import skip_cash_alts_for_lab as _skip

    return _skip(cfg, pack_id=pack_id, portfolio_key=portfolio_key)


def _f_peak(state: dict[str, Any], symbol: str, price: float) -> float | None:
    """Track per-symbol peak mark in worker state (for PLC.B trailing_stop)."""
    try:
        px = float(price)
    except (TypeError, ValueError):
        return None
    peaks = state.setdefault("peak_price", {})
    if not isinstance(peaks, dict):
        peaks = {}
        state["peak_price"] = peaks
    prev = peaks.get(symbol)
    try:
        if prev is None or px > float(prev):
            peaks[symbol] = px
            return px
        return float(prev)
    except (TypeError, ValueError):
        peaks[symbol] = px
        return px


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
        reasoning: Any | None = None,
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
        self._reasoning = reasoning
        self._consult_book_fp = ""
        self._consult_by_day: dict[str, dict[str, Any]] = {}
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._logger = logger or logging.getLogger("atlas.workers.paper_trading")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = dict(ctx.config or {})
        state = dict(ctx.state or {})
        # PLC.E — self-heal F&O/intraday missing mission fields (instruments/session)
        try:
            from atlas.investment import portfolios as vp

            book_early = vp.ensure_from_config(
                cfg, mission_id=str(ctx.mission_id) if ctx.mission_id else None
            )
            pk_early = str(book_early.get("portfolio_key") or "")
            ac_early = str(book_early.get("asset_class") or "").lower()
            if pk_early and (
                "intraday" in pk_early.lower()
                or "fno" in pk_early.lower()
                or ac_early in {"futures", "options"}
            ):
                try:
                    repaired = vp.repair_laboratory_pack_alignment(pk_early)
                    if repaired and isinstance(repaired.get("portfolio"), dict):
                        book_early = repaired["portfolio"]
                except Exception:  # noqa: BLE001
                    pass
            cfg = vp.enrich_decision_config_from_book(cfg, book_early)
            if cfg.get("_lab_seeded_instruments") and not state.get("_lab_seed_noted"):
                state["_lab_seed_noted"] = True
                state["_lab_seeded_symbols"] = [
                    i.get("symbol")
                    for i in (cfg.get("instruments") or [])
                    if isinstance(i, dict)
                ]
        except Exception:  # noqa: BLE001
            self._logger.debug("lab config enrich skipped", exc_info=True)

        instruments = cfg.get("instruments") or []
        auto_loaded = False
        if not instruments:
            # IL.2 / IL-Q3: empty instruments → auto-load M0 watchlist (or NIFTY50 seed).
            # F&O (PLC.E): auto_max_instruments=0 means never auto-pull cash universe.
            from atlas.workers.investment_universe import auto_instruments

            max_auto_raw = cfg.get("auto_max_instruments")
            max_auto = 20 if max_auto_raw is None else int(max_auto_raw)
            if max_auto <= 0:
                return TickResult(
                    state=state,
                    note=(
                        "idle: instruments=[] and auto_max_instruments=0 — "
                        "set explicit contracts (F&O) or raise auto_max for cash equity"
                    ),
                )
            program_id = str(cfg.get("program_id") or "market_intelligence")
            index = str(cfg.get("universe_index") or "NIFTY50")
            instruments = auto_instruments(
                program_id=program_id, max_n=max(1, max_auto), fallback_index=index
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
        state["portfolio_key"] = portfolio_key
        # Lab v1 experiment-scoped exit MUST run before any early return (MDPH / pack
        # / pause). Overnight option inventory blocks learning — never skip flatten.
        try:
            from atlas.investment.lab_contracts import LAB_FNO, lab_kind as _lk_flat

            if _lk_flat(portfolio_key, cfg=cfg) == LAB_FNO:
                persona_early = vp.normalize_persona(book.get("persona"))
                port_early = self._portfolio.ensure_portfolio(
                    mission_id=ctx.mission_id,
                    name=portfolio_key,
                    starting_cash=float(
                        persona_early.get("capital")
                        or cfg.get("starting_cash", 100_000.0)
                    ),
                    base_currency=str(
                        persona_early.get("currency")
                        or cfg.get("base_currency")
                        or "INR"
                    ),
                )
                state["portfolio_id"] = str(port_early["id"])
                pack_early = resolve_pack(
                    cfg.get("instrument_pack") or book.get("instrument_pack"),
                    asset_class=str(
                        cfg.get("asset_class") or book.get("asset_class") or "cash_equity"
                    ),
                    allowed_assets=list(persona_early.get("allowed_assets") or []),
                    config=cfg,
                )
                flat_lines = self._flatten_fno_lab_v1_experiments(
                    cfg=cfg,
                    portfolio_id=port_early["id"],
                    portfolio_key=portfolio_key,
                    mission_id=ctx.mission_id,
                    state=state,
                    pack=pack_early,
                )
                for line in flat_lines:
                    self._logger.info("FNO-LAB-v1 %s", line)
        except Exception:  # noqa: BLE001
            self._logger.warning(
                "FNO-LAB-v1 early experiment flatten failed",
                exc_info=True,
            )
        # OI-MDPH0 — live-required labs: Zerodha READY, else labeled fallback (not silent)
        try:
            from atlas.investment.lab_contracts import live_required as _live_required
            from atlas.investment.market_data_provider_health import (
                evaluate_zerodha_health,
                live_trading_allowed,
                not_evaluable_payload,
                record_mdph_event,
            )
            from atlas.investment.provider_fallback import resolve_live_provider_plan

            if _live_required(portfolio_key, cfg=cfg):
                data_dir = None
                try:
                    from atlas.config import get_config

                    data_dir = get_config().paths.data
                except Exception:  # noqa: BLE001
                    data_dir = None
                health = evaluate_zerodha_health(
                    data_dir, probe=True, refresh_instruments=False
                )
                plan = resolve_live_provider_plan(
                    portfolio_key=portfolio_key,
                    cfg=cfg,
                    zerodha_health=health,
                    live_required=True,
                )
                state["mdph"] = {
                    "provider_status": health.get("status"),
                    "reason_code": (not_evaluable_payload(health) or {}).get("reason_code"),
                    "decision_status": (not_evaluable_payload(health) or {}).get(
                        "decision_status"
                    ),
                    "fallback": plan.get("fallback"),
                    "fallback_reason": plan.get("reason"),
                    "effective_provider": plan.get("provider"),
                    "honesty": plan.get("honesty"),
                }
                if plan.get("paused"):
                    nev = not_evaluable_payload(health)
                    try:
                        from atlas.activity import record_activity

                        record_activity(
                            domain="market",
                            worker="paper_trading",
                            action="mdph_live_pause",
                            target=portfolio_key,
                            result="skipped",
                            summary=(
                                f"{portfolio_key} paused — {plan.get('reason')} "
                                f"(Zerodha {health.get('status')})"
                            ),
                            evidence={
                                "portfolio_key": portfolio_key,
                                "provider_status": health.get("status"),
                                "reason": plan.get("reason"),
                            },
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    cta = health.get("cta") or "/zerodha/login"
                    return TickResult(
                        state=state,
                        note=(
                            f"NOT_EVALUABLE:{nev.get('reason_code')} "
                            f"live_required lab paused (Zerodha {health.get('status')}; "
                            f"{plan.get('reason')}). Authenticate: {cta}"
                        ),
                    )
                # Labeled fallback — continue tick; stamp provider for this tick
                if plan.get("fallback"):
                    cfg = dict(cfg)
                    cfg["portfolio_key"] = portfolio_key
                    cfg["live_provider"] = str(plan.get("provider") or "yahoo")
                    cfg["_mdph_provider_fallback"] = plan.get("fallback")
                    cfg["_mdph_fallback_honesty"] = plan.get("honesty")
                    state["mdph"]["labeled_fallback"] = True
                    try:
                        record_mdph_event(
                            data_dir,
                            "live_provider_fallback",
                            portfolio_key=portfolio_key,
                            fallback=plan.get("fallback"),
                            provider=plan.get("provider"),
                            zerodha_status=health.get("status"),
                            reason=plan.get("reason"),
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    self._logger.info(
                        "MDPH labeled fallback lab=%s provider=%s zerodha=%s",
                        portfolio_key,
                        plan.get("provider"),
                        health.get("status"),
                    )
                elif not live_trading_allowed(health):
                    # Defensive: plan should have paused or labeled a fallback.
                    nev = not_evaluable_payload(health)
                    cta = health.get("cta") or "/zerodha/login"
                    return TickResult(
                        state=state,
                        note=(
                            f"NOT_EVALUABLE:{nev.get('reason_code')} "
                            f"live_required lab paused (Zerodha {health.get('status')}). "
                            f"Authenticate: {cta}"
                        ),
                    )
        except Exception:  # noqa: BLE001
            self._logger.debug("mdph live gate skipped", exc_info=True)

        # OI-STAB0 Lock 1 — FNO pause is opt-in (ATLAS_STAB0_PAUSE_FNO=1)
        if portfolio_key.strip().lower() in {"india_fno_learner", "fno_learner"}:
            from atlas.investment.session_readiness import fno_lab_paused

            if fno_lab_paused():
                try:
                    from atlas.activity import record_activity

                    record_activity(
                        domain="market",
                        worker="paper_trading",
                        action="fno_paused_stab0",
                        target=portfolio_key,
                        result="skipped",
                        summary=(
                            "FNO lab paused (ATLAS_STAB0_PAUSE_FNO) — equity-only"
                        ),
                        evidence={"portfolio_key": portfolio_key},
                    )
                except Exception:  # noqa: BLE001
                    pass
                return TickResult(
                    state=state,
                    note=(
                        "india_fno_learner paused (ATLAS_STAB0_PAUSE_FNO=1). "
                        "Unset the env to resume F&O ticks."
                    ),
                )
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

        try:
            from atlas.investment.lab_contracts import (
                LAB_FNO,
                filter_symbols_for_lab,
                lab_kind as _lab_kind,
            )

            if _lab_kind(portfolio_key, cfg=cfg) == LAB_FNO:
                instruments = filter_symbols_for_lab(
                    portfolio_key, instruments, cfg=cfg, path="buy"
                )
                try:
                    from atlas.investment.fno_contract import stamp_phase1_contracts

                    data_dir = None
                    try:
                        from atlas.config import get_config

                        data_dir = str(get_config().paths.data)
                    except Exception:  # noqa: BLE001
                        data_dir = None
                    instruments, cmap = stamp_phase1_contracts(
                        instruments,
                        feed=self._zerodha_feed(),
                        data_dir=data_dir,
                        now=self._clock(),
                    )
                    cfg["_fno_contracts"] = cmap
                    state["fno_phase1"] = {
                        k: {
                            "ok": bool(v.get("ok")),
                            "tradingsymbol": v.get("tradingsymbol"),
                            "expiry": v.get("expiry"),
                            "reason": v.get("reason"),
                        }
                        for k, v in cmap.items()
                        if isinstance(v, dict)
                    }
                except Exception:  # noqa: BLE001
                    self._logger.debug("fno phase1 contract stamp skipped", exc_info=True)
        except Exception:  # noqa: BLE001
            self._logger.debug("lab instrument filter skipped", exc_info=True)

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
        # OI-LAB-LOOP0 — rebuild wash lock from canonical fills (checkpoint can lag).
        try:
            from atlas.investment.wash_lock import applies_to_lab as _wash_lab
            from atlas.investment.wash_lock import hydrate_from_fills

            if _wash_lab(portfolio_key, cfg=cfg) and hasattr(self._portfolio, "trades"):
                open_pos = []
                try:
                    snap0 = self._portfolio.snapshot(portfolio_id, prices=None)
                    open_pos = list(snap0.get("positions") or [])
                except Exception:  # noqa: BLE001
                    open_pos = []
                hydrate_from_fills(
                    state,
                    list(self._portfolio.trades(portfolio_id, limit=500) or []),
                    now=self._clock(),
                    open_positions=open_pos,
                )
        except Exception:  # noqa: BLE001
            self._logger.debug("wash lock hydrate skipped", exc_info=True)
        try:
            from atlas.investment.lab_contracts import LAB_FNO, lab_kind as _lk_p2

            if _lk_p2(portfolio_key, cfg=cfg) == LAB_FNO:
                p2_lines = self._ensure_fno_p2_boundary(
                    portfolio_id=portfolio_id,
                    portfolio_key=portfolio_key,
                    mission_id=ctx.mission_id,
                    cfg=cfg,
                    state=state,
                )
                for line in p2_lines:
                    self._logger.info("FNO-P2-001 %s", line)
                p001_lines = self._run_fno_paper_001(
                    cfg=cfg,
                    portfolio_id=portfolio_id,
                    portfolio_key=portfolio_key,
                    mission_id=ctx.mission_id,
                    state=state,
                    pack=pack,
                )
                for line in p001_lines:
                    self._logger.info("FNO-PAPER-001 %s", line)
                try:
                    from atlas.investment import fno_lab_v1 as lab_v1
                    from atlas.config import get_config

                    dd = str(get_config().paths.data)
                    if not state.get("fno_lab_v1_stamped"):
                        lab_v1.persist_stock_seed(dd)
                        lab_v1.persist_policy(dd)
                        state["fno_lab_v1_stamped"] = True
                        state["fno_lab_v1"] = lab_v1.universe(dd)
                        self._logger.info(
                            "FNO-LAB-v1 stamped indices=%d stock_seed=%d",
                            len(lab_v1.index_underliers()),
                            len(lab_v1.load_stock_seed(dd)),
                        )
                    # Idempotent second pass (early path already flattens before gates).
                    flat_lines = self._flatten_fno_lab_v1_experiments(
                        cfg=cfg,
                        portfolio_id=portfolio_id,
                        portfolio_key=portfolio_key,
                        mission_id=ctx.mission_id,
                        state=state,
                        pack=pack,
                    )
                    for line in flat_lines:
                        self._logger.info("FNO-LAB-v1 %s", line)
                except Exception:  # noqa: BLE001
                    self._logger.warning(
                        "FNO-LAB-v1 stamp/flatten skipped",
                        exc_info=True,
                    )
        except Exception:  # noqa: BLE001
            self._logger.debug("FNO-P2-001 / FNO-PAPER-001 skipped", exc_info=True)
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

        try:
            from atlas.investment.lab_contracts import (
                LAB_INTRADAY,
                flatten_session_date,
                intraday_must_be_flat,
                lab_kind as _lab_kind,
            )

            if _lab_kind(portfolio_key, cfg=cfg) == LAB_INTRADAY:
                now_c = self._clock()
                must_flat = bool(intraday_must_be_flat(now_c))
                state["intraday_must_be_flat"] = must_flat
                state["intraday_eod_session"] = flatten_session_date(now_c)
                if must_flat:
                    self._eod_flatten_intraday(
                        cfg=cfg,
                        portfolio_id=portfolio_id,
                        portfolio_key=portfolio_key,
                        marks=dict(state.get("last_marks") or {}),
                        state=state,
                        mission_id=ctx.mission_id,
                        pack=pack,
                    )
                # NOW #3 — durable overnight_positions=0 proof (even mid-session snapshot)
                try:
                    from atlas.config import get_config
                    from atlas.investment.intraday_integrity import (
                        record_intraday_integrity,
                    )

                    snap_i = self._portfolio.snapshot(
                        portfolio_id, prices=dict(state.get("last_marks") or {}) or None
                    )
                    integ = record_intraday_integrity(
                        str(get_config().paths.data),
                        laboratory_id=portfolio_key,
                        positions=list(snap_i.get("positions") or []),
                        must_be_flat=must_flat,
                        flatten_outcomes=list(state.get("eod_flatten_outcomes") or []),
                        flatten_session=str(state.get("intraday_eod_session") or ""),
                        as_of_ist=str(state.get("intraday_eod_session") or None),
                    )
                    state["intraday_integrity"] = {
                        "status": integ.get("status"),
                        "overnight_positions": integ.get("overnight_positions"),
                        "overnight_positions_ok": integ.get("overnight_positions_ok"),
                    }
                except Exception:  # noqa: BLE001
                    self._logger.debug("intraday integrity record skipped", exc_info=True)
        except Exception:  # noqa: BLE001
            self._logger.debug("intraday EOD flatten skipped", exc_info=True)

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
        # Session-fresh Yahoo budget is tiny — refresh open positions first.
        try:
            snap0 = self._portfolio.snapshot(portfolio_id, prices=prev_marks)
            self._refresh_consult_book(snap0)
            open_syms = {
                str(p.get("symbol") or "").strip().upper()
                for p in (snap0.get("positions") or [])
                if abs(float(p.get("quantity") or 0)) > 1e-12
            }
            if open_syms:
                head = [
                    i
                    for i in instruments
                    if str(i.get("symbol") or "").strip().upper() in open_syms
                ]
                tail = [
                    i
                    for i in instruments
                    if str(i.get("symbol") or "").strip().upper() not in open_syms
                ]
                instruments = head + tail
        except Exception:  # noqa: BLE001
            pass
        try:
            from atlas.investment.intraday_bars import (
                MAX_SYMBOLS,
                clamp_intraday_universe,
                is_intraday_lab,
            )

            if is_intraday_lab(cfg, portfolio_key):
                open_now = {
                    str(p.get("symbol") or "").strip().upper()
                    for p in (
                        (self._portfolio.snapshot(portfolio_id, prices=prev_marks) or {}).get(
                            "positions"
                        )
                        or []
                    )
                    if abs(float(p.get("quantity") or 0)) > 1e-12
                }
                instruments = clamp_intraday_universe(
                    instruments, open_symbols=open_now, max_n=MAX_SYMBOLS
                )
                state["intraday_universe_cap"] = MAX_SYMBOLS
                state["live_interval"] = "5m"
        except Exception:  # noqa: BLE001
            pass
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
        from atlas.investment.session_notes import classify_action, samples_for_notes

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
            # CAP.1 — one cooldown note; prefer durable; no per-symbol failure spam
            yahoo_cd = False
            cd_rem = 0.0
            if feed_mode == "live" and str(cfg.get("live_provider") or "yahoo").lower() == "yahoo":
                try:
                    from atlas.config import get_config
                    from atlas.investment.yahoo_fundamentals import get_yahoo_rate_gate

                    data_dir = getattr(get_config().paths, "data", None)
                    if data_dir:
                        cd_rem = float(
                            get_yahoo_rate_gate(data_dir).remaining_cooldown_s() or 0
                        )
                        yahoo_cd = cd_rem > 0
                except Exception:  # noqa: BLE001
                    yahoo_cd = False
            if yahoo_cd and not state.get("_yahoo_cd_noted"):
                state["_yahoo_cd_noted"] = True
                _record_action(
                    f"yahoo_cooldown ({cd_rem:.0f}s) — durable prefer; skip live hammer"
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
                    reason = str(exc)[:400]
                    # CAP.1: do not journal cooldown as N feed_failures per symbol
                    if yahoo_cd or "cooldown" in reason.lower() or "paused" in reason.lower():
                        continue
                    self._record_feed_failure(
                        provider=str(cfg.get("live_provider") or "yahoo"),
                        symbol=symbol,
                        reason=reason,
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

        # UTS.D — hold-vs-challenger opportunity review (after primary marks).
        try:
            switch_actions = self._review_opportunity_switches(
                cfg=cfg,
                portfolio_id=portfolio_id,
                portfolio_key=portfolio_key,
                marks=marks,
                state=state,
                mission_id=ctx.mission_id,
                session_open=session_open,
                totals=totals,
                pack=pack,
            )
            for act in switch_actions:
                _record_action(act)
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("opportunity switch review skipped: %s", exc)

        # No fill yet → try next ranked alternatives (cash equity only).
        # FNO / futures: cash alts contaminate the lab (LOOP0 L0).
        prefer_alt = cfg.get("prefer_next_alternatives")
        if prefer_alt is None:
            prefer_alt = True
        if skip_cash_alts_for_lab(
            cfg,
            pack_id=str(getattr(pack, "id", "") or ""),
            portfolio_key=str(state.get("portfolio_key") or ""),
        ):
            prefer_alt = False
            if int(totals.get("buys") or 0) == 0:
                pk_now = str(state.get("portfolio_key") or "").lower()
                if "intraday" in pk_now:
                    _record_action("next_alt: skipped (intraday_yahoo_budget)")
                else:
                    _record_action("next_alt: skipped (fno_no_cash_alts)")
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
        snapshot = self._portfolio.snapshot(portfolio_id, prices=marks)
        state["equity"] = snapshot["equity"]
        # OI-STAB0 honesty: durable tips with multi-day gap are not "latest" marks
        basis = snapshot.get("valuation_basis")
        try:
            from atlas.investment.index_proxy_lot import VALUATION_BASIS, is_fno_lab
            from atlas.investment.intraday_bars import (
                VALUATION_BASIS as INTRADAY_BASIS,
                is_intraday_lab,
            )

            if is_fno_lab(cfg, portfolio_key):
                basis = VALUATION_BASIS
                snapshot = dict(snapshot)
                snapshot["valuation_basis"] = basis
            elif is_intraday_lab(cfg, portfolio_key):
                basis = INTRADAY_BASIS
                snapshot = dict(snapshot)
                snapshot["valuation_basis"] = basis
        except Exception:  # noqa: BLE001
            pass
        if feed_gap_days is not None:
            try:
                gap_f = float(feed_gap_days)
            except (TypeError, ValueError):
                gap_f = None
            if gap_f is not None and gap_f >= 1.0 and marks:
                gap_note = f"feed_gap≈{gap_f:.0f}d — not session-fresh"
                fno_now = False
                try:
                    from atlas.investment.index_proxy_lot import (
                        VALUATION_BASIS as _VB,
                        is_fno_lab as _fno,
                    )

                    fno_now = _fno(cfg, portfolio_key)
                except Exception:  # noqa: BLE001
                    _VB = "index_proxy daily underlier"
                if fno_now:
                    basis = f"{_VB} ({gap_note})"
                else:
                    basis = f"durable bars ({gap_note})"
                snapshot = dict(snapshot)
                snapshot["valuation_basis"] = basis
        state["valuation_basis"] = basis
        state["marks_pct"] = snapshot.get("marks_pct")
        # Persist hold/feed reasons for evening honesty + outage catch-up digests.
        try:
            from zoneinfo import ZoneInfo

            from atlas.config import get_config
            from atlas.investment.session_notes import merge_day_notes

            ist_date = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
            data_dir = str(get_config().paths.data)
            extra: dict[str, Any] = {
                "valuation_basis": snapshot.get("valuation_basis"),
                "marks_pct": snapshot.get("marks_pct"),
                "marks_available": snapshot.get("marks_available"),
                "marks_total": snapshot.get("marks_total"),
                "session_open": bool(session_open) if respect_hours else True,
            }
            try:
                from atlas.investment.index_proxy_lot import KPI_LABEL, is_fno_lab

                if is_fno_lab(cfg, portfolio_key):
                    extra["kpi_label"] = KPI_LABEL
            except Exception:  # noqa: BLE001
                pass
            if feed_gap_days is not None:
                extra["feed_gap_days"] = feed_gap_days
            merge_day_notes(
                data_dir,
                portfolio_key=portfolio_key,
                ist_date=ist_date,
                reason_counts=reason_counts,
                samples=samples_for_notes(last_actions),
                extra=extra,
            )
        except Exception:  # noqa: BLE001
            self._logger.debug("session notes merge skipped", exc_info=True)

        try:
            from zoneinfo import ZoneInfo as _ISTZone

            self._maybe_open_book_l3(
                portfolio_key=portfolio_key,
                snapshot=snapshot,
                marks=marks,
                ist_date=datetime.now(_ISTZone("Asia/Kolkata")).strftime("%Y-%m-%d"),
            )
        except Exception:  # noqa: BLE001
            self._logger.debug("LOOP0 L3 open-book skipped", exc_info=True)

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
        try:
            from atlas.activity import record_activity

            top_idle = ""
            if reason_counts:
                top_idle = max(reason_counts.items(), key=lambda kv: int(kv[1] or 0))[0]
            record_activity(
                domain="market",
                worker="paper_trading",
                action="paper_tick",
                target=portfolio_key,
                result="completed",
                summary=(
                    f"Paper tick on {portfolio_key}: "
                    f"+{totals.get('buys', 0)} buy / +{totals.get('sells', 0)} sell / "
                    f"{totals.get('holds', 0)} hold"
                    + (f"; top idle={top_idle}" if top_idle else "")
                    + (
                        f"; feed_gap={feed_gap_days}d"
                        if feed_gap_days is not None
                        else ""
                    )
                ),
                evidence={
                    "portfolio_key": portfolio_key,
                    "buys": totals.get("buys"),
                    "sells": totals.get("sells"),
                    "holds": totals.get("holds"),
                    "reason_counts": reason_counts,
                    "feed_gap_days": feed_gap_days,
                    "session_open": session_open,
                    "valuation_basis": snapshot.get("valuation_basis"),
                    "marks_pct": snapshot.get("marks_pct"),
                },
            )
        except Exception:  # noqa: BLE001
            self._logger.debug("activity journal paper tick skipped", exc_info=True)
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

            port_cfg = {
                "max_name_pct": cfg.get("max_name_pct"),
                "max_exposure_pct": cfg.get("max_exposure_pct"),
            }
            return target_name_pct(persona, port_cfg)
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
        skip_req = _SKIP_CASH_ALT_REQUESTED
        pool: list[dict[str, Any]] = []
        try:
            rows = wl.ranked_rows(program_id, max_n=max(40, max_n * 3))
        except Exception:  # noqa: BLE001
            rows = []
        for idx, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").strip()
            if not sym or sym.upper() in have_l or sym.upper() in skip_req:
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
                if not sym or sym.upper() in have_l or sym.upper() in skip_req:
                    continue
                pool.append({**inst, "alt": True})
        ordered = self._order_tradeable_first(pool, cash=cash, marks=marks)
        return ordered[: max(1, int(max_n))]

    def _review_opportunity_switches(
        self,
        *,
        cfg: dict[str, Any],
        portfolio_id: Any,
        portfolio_key: str,
        marks: dict[str, float],
        state: dict[str, Any],
        mission_id: Any,
        session_open: bool,
        totals: dict[str, Any],
        pack: Any,
    ) -> list[str]:
        """UTS.D — review every open hold vs watchlist/queue challengers.

        Always emits a decision (packet when DI store present). Executes at most
        ``max_switches_per_tick`` sell→buy rotations when advantage clears and
        session is open.
        """
        from atlas.investment.opportunity_switch import (
            DEFAULT_PENALTY_K,
            DEFAULT_PENALTY_M,
            DEFAULT_SWITCH_COST,
            DEFAULT_THRESHOLD,
            attach_opportunity_metrics,
            opportunity_switch_enabled,
            review_portfolio_switches,
        )

        actions: list[str] = []
        icr2_on = False
        try:
            from atlas.investment.incumbent_review import icr2_enabled

            icr2_on = icr2_enabled(cfg, portfolio_key)
        except Exception:  # noqa: BLE001
            icr2_on = False
        if not opportunity_switch_enabled(cfg, portfolio_key) and not icr2_on:
            state["opportunity_switch_reviews"] = []
            return actions

        program_id = str(cfg.get("program_id") or "market_intelligence")
        snapshot = self._portfolio.snapshot(portfolio_id, prices=marks)
        positions = list(snapshot.get("positions") or [])
        open_pos = []
        for p in positions:
            if not isinstance(p, dict):
                continue
            try:
                q = float(p.get("qty") or p.get("quantity") or p.get("shares") or 0)
            except (TypeError, ValueError):
                q = 0.0
            if q > 0:
                open_pos.append(p)
        # Flat book must still refresh Next-₹1 / competition (cash vs challengers).
        # Empty holds only means no switch *execution* — not "skip the economic center."
        if not open_pos:
            state["opportunity_switch_reviews"] = []
            state["opportunity_switch_flat_book"] = True

        ranked_by: dict[str, dict[str, Any]] = {}
        challengers: list[dict[str, Any]] = []
        try:
            from atlas.investment import watchlists as wl

            for row in wl.ranked_rows(program_id, max_n=40) or []:
                if not isinstance(row, dict):
                    continue
                sym = str(row.get("symbol") or "").strip().upper()
                if not sym:
                    continue
                ranked_by[sym] = row
                challengers.append(dict(row))
        except Exception:  # noqa: BLE001
            pass
        try:
            from atlas.config import get_config
            from atlas.investment.triage_memory import load_latest_triage_bundle

            triage = load_latest_triage_bundle(
                str(get_config().paths.data), program_id
            )
            seen_chal = {
                str(c.get("symbol") or "").strip().upper() for c in challengers
            }
            for item in triage.get("opportunity_queue") or []:
                if not isinstance(item, dict):
                    continue
                sym = str(item.get("symbol") or "").strip().upper()
                if not sym or sym in seen_chal:
                    continue
                challengers.append(dict(item))
                seen_chal.add(sym)
                ranked_by.setdefault(sym, item)
        except Exception:  # noqa: BLE001
            pass

        # Enrich holds with ranked evidence for E[R]×confidence.
        from atlas.investment.expected_return_prototype import overlay_fundamentals_for_er

        fund_cache: dict[str, dict[str, Any] | None] = {}
        data_dir_er: str | None = None
        try:
            from atlas.config import get_config

            data_dir_er = str(get_config().paths.data)
        except Exception:  # noqa: BLE001
            data_dir_er = None

        def _fund_for(sym: str) -> dict[str, Any] | None:
            key = str(sym or "").strip().upper()
            if not key or not data_dir_er:
                return None
            if key in fund_cache:
                return fund_cache[key]
            row = None
            try:
                from atlas.investment.fundamentals import get_symbol as fund_get

                row = fund_get(data_dir_er, key, program_id=program_id)
            except Exception:  # noqa: BLE001
                row = None
            fund_cache[key] = row if isinstance(row, dict) else None
            return fund_cache[key]

        _er_copy = (
            "score",
            "confidence",
            "phase",
            "components",
            "momentum",
            "pe",
            "industry_pe_median",
            "pe_sector_median",
            "roe",
            "debt_to_equity",
            "rs_vs_benchmark_pct",
            "sector",
            "belief_adj",
            "closed_trade_n",
            "closed_trade_hit_rate",
        )
        holds: list[dict[str, Any]] = []
        for pos in open_pos:
            row = dict(pos)
            sym = str(row.get("symbol") or "").strip().upper()
            src = ranked_by.get(sym) or ranked_by.get(sym.replace(".NS", "") + ".NS")
            if src:
                for k in _er_copy:
                    if row.get(k) is None and src.get(k) is not None:
                        row[k] = src.get(k)
                if isinstance(src.get("components"), dict) and not isinstance(
                    row.get("components"), dict
                ):
                    row["components"] = src["components"]
            overlay_fundamentals_for_er(row, _fund_for(sym))
            attach_opportunity_metrics(row, row)
            holds.append(row)
        for chal in challengers:
            csym = str(chal.get("symbol") or "").strip().upper()
            overlay_fundamentals_for_er(chal, _fund_for(csym))
            attach_opportunity_metrics(chal, chal)

        # PLC.A gate map for challengers (fail-closed when enabled).
        plc_ok: dict[str, bool] = {}
        try:
            from atlas.investment.plc_buy_gates import (
                evaluate_plc_a_buy,
                plc_a_enabled,
            )

            if plc_a_enabled(cfg, portfolio_key):
                from atlas.config import get_config
                from atlas.investment.fundamentals import get_symbol as fund_get

                data_dir = str(get_config().paths.data)
                for chal in challengers:
                    csym = str(chal.get("symbol") or "").strip().upper()
                    if not csym or csym in plc_ok:
                        continue
                    fund_row = None
                    aw_row = None
                    try:
                        fund_row = fund_get(data_dir, csym, program_id=program_id)
                    except Exception:  # noqa: BLE001
                        fund_row = None
                    if self._investment_research is not None:
                        try:
                            aw_row = self._investment_research.awareness(
                                csym, program_id=program_id
                            )
                        except Exception:  # noqa: BLE001
                            aw_row = None
                    gate = evaluate_plc_a_buy(
                        fundamentals=fund_row if isinstance(fund_row, dict) else None,
                        awareness=aw_row if isinstance(aw_row, dict) else None,
                        instrument_sector=chal.get("sector"),
                        engine_why=str(
                            chal.get("thesis_trigger")
                            or chal.get("why")
                            or "opportunity_switch_challenger"
                        ),
                        require_fundamentals=bool(
                            cfg.get("plc_a_require_fundamentals", True)
                        ),
                        require_thesis_trigger=bool(
                            cfg.get("plc_a_require_thesis_trigger", True)
                        ),
                        symbol=csym,
                    )
                    plc_ok[csym] = bool(gate.get("allowed"))
                    chal["plc_a"] = gate
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("PLC.A challenger map skipped: %s", exc)

        # Costs / thresholds from cfg (bps → fraction).
        try:
            cost_bps = cfg.get("switch_cost_bps")
            transaction_cost = (
                float(cost_bps) / 10_000.0
                if cost_bps is not None
                else float(cfg.get("switch_cost") or DEFAULT_SWITCH_COST)
            )
        except (TypeError, ValueError):
            transaction_cost = DEFAULT_SWITCH_COST
        try:
            threshold = float(cfg.get("switching_threshold") or DEFAULT_THRESHOLD)
        except (TypeError, ValueError):
            threshold = DEFAULT_THRESHOLD
        try:
            cold_thr = float(cfg.get("cold_start_switch_threshold") or 0.05)
        except (TypeError, ValueError):
            cold_thr = 0.05
        exploratory = bool(
            cfg.get("exploratory_turnover_ok")
            if cfg.get("exploratory_turnover_ok") is not None
            else True
        )
        # Prefer calibrated threshold once enough history exists; exploratory
        # raises the bar via cold_start_switch_threshold.
        reviews = review_portfolio_switches(
            holds,
            challengers,
            threshold=threshold,
            cold_start_threshold=cold_thr,
            transaction_cost=transaction_cost,
            penalty_k=float(cfg.get("confidence_penalty_k") or DEFAULT_PENALTY_K),
            penalty_m=float(cfg.get("confidence_penalty_m") or DEFAULT_PENALTY_M),
            exploratory=exploratory,
            challenger_plc_a_ok=plc_ok or None,
            laboratory_id=portfolio_key,
            cfg=cfg,
        )
        state["opportunity_switch_reviews"] = reviews[:20]

        try:
            from atlas.investment.capital_allocation import (
                build_challenger_table,
                persist_allocation_table,
            )

            cash_amt = float(snapshot.get("cash") or 0)
            alloc_table = build_challenger_table(
                holds=holds,
                challengers=challengers,
                cash=cash_amt,
                reviews=reviews,
                laboratory_id=portfolio_key,
                threshold=threshold,
                cold_start_threshold=cold_thr,
                transaction_cost=transaction_cost,
                penalty_k=float(cfg.get("confidence_penalty_k") or DEFAULT_PENALTY_K),
                penalty_m=float(cfg.get("confidence_penalty_m") or DEFAULT_PENALTY_M),
                exploratory=exploratory,
                cfg=cfg,
            )
            if data_dir_er:
                persist_allocation_table(data_dir_er, alloc_table)
            state["challenger_table"] = {
                "as_of_ist": alloc_table.get("as_of_ist"),
                "rows": len(alloc_table.get("rows") or []),
                "best_deploy": alloc_table.get("best_deploy"),
                "holdings_n": alloc_table.get("holdings_n"),
            }
            # MI.5+ — hermetic company profiles for open-book symbols (universe seed)
            if data_dir_er:
                try:
                    from atlas.investment.company_profiles import ensure_open_book_profiles
                    from atlas.trading.company import CompanyDataService

                    prof = ensure_open_book_profiles(
                        data_dir=data_dir_er,
                        company_data=CompanyDataService(),
                        portfolio=portfolio,
                        laboratory_id=str(portfolio_key or ""),
                    )
                    state["company_profiles"] = {
                        "ok": prof.get("ok"),
                        "count": prof.get("count"),
                    }
                except Exception as exc:  # noqa: BLE001
                    self._logger.debug("company_profiles skipped: %s", exc)
            # NOW #8 — Next-₹1 economic center packet (why this rupee)
            try:
                from atlas.investment.next_rupee import (
                    acp_summaries_from_disk,
                    build_and_persist_next_rupee,
                )

                hold_syms = [
                    str(h.get("symbol") or "").upper()
                    for h in (holds or [])
                    if isinstance(h, dict) and h.get("symbol")
                ]
                acp_sum = (
                    acp_summaries_from_disk(data_dir_er, str(portfolio_key or ""), hold_syms)
                    if data_dir_er
                    else []
                )
                nr = build_and_persist_next_rupee(
                    data_dir_er,
                    alloc_table,
                    laboratory_id=str(portfolio_key or ""),
                    acp_summaries=acp_sum,
                    reasoning=self._reasoning,
                    experience_os=self._experience_os,
                )
                state["next_rupee"] = {
                    "destination": nr.get("destination"),
                    "destination_action": nr.get("destination_action"),
                    "operator_answer": (nr.get("operator_answer") or "")[:220],
                    "as_of_ist": nr.get("as_of_ist"),
                    "worldview_beliefs": ((nr.get("worldview") or {}).get("belief_n")),
                    "worldview_lessons": ((nr.get("worldview") or {}).get("lesson_n")),
                    "competition": (nr.get("competition") or {}).get("winner"),
                }
                # Phase 4 — feed uncertainty queue (material to Next-₹1 only; no challenger spam)
                try:
                    from atlas.investment.capital_allocation import (
                        allocation_blocking_unknowns,
                    )
                    from atlas.investment.lab_contracts import LAB_FNO, lab_kind
                    from atlas.investment.uncertainty_queue import (
                        enqueue_from_awareness,
                        enqueue_from_unknowns,
                        prune_non_material_pending,
                    )

                    uq_n = 0
                    lab_id = str(portfolio_key or "")
                    # Material = destination + open holds + plan / SMA / PLC.A-blocked
                    material_syms: set[str] = set()
                    dest = str(nr.get("destination") or "").upper()
                    if dest and dest != "CASH":
                        material_syms.add(dest)
                    for h in holds:
                        s = str(h.get("symbol") or "").upper()
                        if s:
                            material_syms.add(s)
                    plan_doc_uq = None
                    try:
                        from atlas.investment import watchlists as wl_uq

                        snap_uq = wl_uq.latest(str(program_id or "market_intelligence"))
                        if isinstance(snap_uq, dict):
                            plan_doc_uq = (snap_uq.get("extra") or {}).get(
                                "daily_plan"
                            ) or snap_uq.get("daily_plan")
                    except Exception:  # noqa: BLE001
                        plan_doc_uq = None
                    plc_failed = [
                        str(s).upper()
                        for s, ok in (plc_ok or {}).items()
                        if s and not ok
                    ]
                    try:
                        from atlas.investment.uncertainty_queue import (
                            extra_material_from_lab,
                        )

                        material_syms |= extra_material_from_lab(
                            data_dir_er,
                            laboratory_id=lab_id,
                            daily_plan=plan_doc_uq if isinstance(plan_doc_uq, dict) else None,
                            plc_a_failed=plc_failed,
                        )
                    except Exception:  # noqa: BLE001
                        for s in plc_failed:
                            material_syms.add(s)
                    for gap in allocation_blocking_unknowns(alloc_table)[:12]:
                        if not isinstance(gap, dict):
                            continue
                        gsym = str(gap.get("symbol") or "").upper()
                        if gsym and gsym not in material_syms:
                            # ER gap on a non-chosen challenger → not worthwhile for Next-₹1
                            continue
                        code = str(gap.get("unknown") or "").lower()
                        if code in {"fcf", "free_cash_flow"}:
                            code = "fcf_missing"
                        elif code == "pe":
                            code = "pe_missing"
                        elif code in {"expected_return", "mos", "mos_unknown"}:
                            # mos/ER completeness alone is not an acquisition task
                            # unless it maps to a concrete fundamental code
                            if code == "mos" or code == "mos_unknown":
                                code = "mos_unknown"
                            else:
                                continue
                        out_uq = enqueue_from_unknowns(
                            data_dir_er,
                            laboratory_id=lab_id,
                            symbol=gsym,
                            unknowns=[code],
                        )
                        uq_n += len(out_uq.get("created_ids") or [])
                    # Equity fundamentals awareness — not for F&O allocator
                    if (
                        self._investment_research is not None
                        and lab_kind(lab_id, cfg=cfg) != LAB_FNO
                        and material_syms
                    ):
                        for sym_u in sorted(material_syms)[:8]:
                            try:
                                aw_u = self._investment_research.awareness(
                                    sym_u,
                                    program_id=str(
                                        cfg.get("program_id") or "market_intelligence"
                                    ),
                                )
                            except Exception:  # noqa: BLE001
                                continue
                            out_aw = enqueue_from_awareness(
                                data_dir_er,
                                laboratory_id=lab_id,
                                symbol=sym_u,
                                awareness=aw_u if isinstance(aw_u, dict) else None,
                            )
                            uq_n += len(out_aw.get("created_ids") or [])
                    # Decision Evidence Completeness Gate — WHAT NEED / HAVE / MISSING
                    completeness_rows: list[dict] = []
                    try:
                        from atlas.investment.evidence_completeness import (
                            apply_completeness_to_uncertainty,
                            evaluate_evidence_completeness,
                            format_why_not_evaluable,
                            persist_completeness,
                        )
                        from atlas.investment.lab_contracts import (
                            LAB_INTRADAY,
                            LAB_FNO as _LAB_FNO,
                        )
                        from atlas.investment.market_data_provider_health import (
                            load_health,
                        )

                        ph = None
                        try:
                            ph = load_health(data_dir_er)
                        except Exception:  # noqa: BLE001
                            ph = None
                        kind_c = lab_kind(lab_id, cfg=cfg)
                        for sym_c in sorted(material_syms)[:8]:
                            aw_c: dict | None = None
                            if (
                                self._investment_research is not None
                                and kind_c != _LAB_FNO
                            ):
                                try:
                                    aw_c = self._investment_research.awareness(
                                        sym_c,
                                        program_id=str(
                                            cfg.get("program_id")
                                            or "market_intelligence"
                                        ),
                                    )
                                except Exception:  # noqa: BLE001
                                    aw_c = None
                            # Prefer live mark from holds / next-rupee when present
                            mark_c = None
                            for h in holds:
                                if str(h.get("symbol") or "").upper() == sym_c:
                                    mark_c = h.get("mark") or h.get("price")
                                    break
                            if mark_c is None and dest == sym_c:
                                mark_c = nr.get("mark") or nr.get("price")
                            live_lab = kind_c in {LAB_INTRADAY, _LAB_FNO}
                            mkt_c = {
                                "ltp": mark_c,
                                "price": mark_c,
                                "provider": "zerodha" if live_lab else None,
                                "bars_ok": True if mark_c is not None and live_lab else None,
                                "hist_ok": True if mark_c is not None and live_lab else None,
                                "technical": {"label": "present"}
                                if mark_c is not None and kind_c == LAB_INTRADAY
                                else None,
                                "session": True,
                            }
                            prog_c = str(
                                cfg.get("program_id") or "market_intelligence"
                            )
                            comp = evaluate_evidence_completeness(
                                symbol=sym_c,
                                laboratory_id=lab_id,
                                awareness=aw_c if isinstance(aw_c, dict) else None,
                                market=mkt_c,
                                provider_health=ph if isinstance(ph, dict) else None,
                                cfg=cfg,
                                data_dir=data_dir_er,
                                program_id=prog_c,
                            )
                            persist_completeness(data_dir_er, comp)
                            uq_c = apply_completeness_to_uncertainty(
                                data_dir_er, comp
                            )
                            uq_n += len(uq_c.get("created_ids") or [])
                            completeness_rows.append(
                                {
                                    "symbol": sym_c,
                                    "decision": comp.get("decision"),
                                    "pct": comp.get("usable_evidence_pct"),
                                    "missing": comp.get("material_missing"),
                                    "why": format_why_not_evaluable(comp)[:180],
                                }
                            )
                    except Exception:  # noqa: BLE001
                        self._logger.debug(
                            "evidence completeness gate skipped", exc_info=True
                        )
                    pruned = prune_non_material_pending(
                        data_dir_er,
                        laboratory_id=lab_id,
                        material_symbols=material_syms,
                    )
                    state["uncertainty_queue"] = {
                        "enqueued_n": uq_n,
                        "material_symbols": sorted(material_syms)[:8],
                        "pruned_non_material_n": pruned.get("closed_n"),
                    }
                    if completeness_rows:
                        state["evidence_completeness"] = {
                            "n": len(completeness_rows),
                            "rows": completeness_rows,
                        }
                    try:
                        from atlas.investment.decision_packets import (
                            DecisionPacketStore,
                            ist_today as _ist_day,
                        )
                        from atlas.investment.swing_pipeline import (
                            build_swing_pipeline,
                            persist_swing_pipeline,
                        )

                        pkts: list[dict] = []
                        if data_dir_er:
                            pkts = DecisionPacketStore(data_dir=data_dir_er).list_day(
                                portfolio_key=lab_id, ts_ist=_ist_day(), limit=200
                            )
                        pipe = build_swing_pipeline(
                            data_dir_er,
                            laboratory_id=lab_id,
                            sma_symbols=sorted(material_syms),
                            packets=pkts,
                            fills_n=int((state.get("session") or {}).get("fills") or 0),
                        )
                        persist_swing_pipeline(data_dir_er, pipe)
                        state["swing_pipeline"] = {
                            "sma_candidates": pipe.get("sma_candidates"),
                            "counts": pipe.get("counts"),
                        }
                    except Exception:  # noqa: BLE001
                        self._logger.debug("swing pipeline skipped", exc_info=True)
                except Exception:  # noqa: BLE001
                    self._logger.debug("uncertainty queue feed skipped", exc_info=True)
                # OI-LEARN-AUDIT0 LA.1 — Learning Auditor instrument (not destination)
                try:
                    from atlas.investment.learning_audit import (
                        build_and_persist_learning_audit,
                    )

                    aud = build_and_persist_learning_audit(
                        data_dir_er,
                        laboratory_id=str(portfolio_key or ""),
                    )
                    state["learning_audit"] = {
                        "overall_state": aud.get("overall_state"),
                        "learning_record_n": aud.get("learning_record_n"),
                        "milestone_have": (
                            (aud.get("genuine_learning_milestone") or {}).get("have")
                        ),
                        "path": aud.get("path"),
                    }
                    # Parallel track — promote L3 → L4 candidates (never auto-L5)
                    try:
                        from atlas.investment.l5_validation import promote_lab_l3_records

                        promo = promote_lab_l3_records(
                            data_dir_er, laboratory_id=str(portfolio_key or "")
                        )
                        state["l3_to_l5"] = {
                            "created_n": promo.get("created_n"),
                            "skipped_n": promo.get("skipped_n"),
                            "l5_claimed": False,
                        }
                    except Exception:  # noqa: BLE001
                        self._logger.debug("l3→l5 promote skipped", exc_info=True)
                except Exception:  # noqa: BLE001
                    self._logger.debug("learning audit skipped", exc_info=True)
                # NOW #11 — virtual Capital Scale Lab (never mutates live capital)
                try:
                    from atlas.investment.capital_scale_lab import (
                        build_and_persist_capital_scale,
                    )

                    csl = build_and_persist_capital_scale(
                        data_dir_er,
                        laboratory_id=str(portfolio_key or ""),
                        next_rupee=nr,
                        live_cash=cash_amt,
                        live_equity=float(snapshot.get("equity") or 0) or None,
                    )
                    state["capital_scale"] = {
                        "as_of_ist": csl.get("as_of_ist"),
                        "destination": csl.get("next_rupee_destination"),
                        "summary": csl.get("summary"),
                        "mutates_live_capital": False,
                        "real_capital_increase": False,
                    }
                except Exception:  # noqa: BLE001
                    self._logger.debug("NOW #11 capital_scale skipped", exc_info=True)
            except Exception:  # noqa: BLE001
                self._logger.debug("NOW #8 next_rupee skipped", exc_info=True)
            # OI-ICR1 — durable Allocation Comparison Packet per open hold.
            try:
                from atlas.investment.allocation_comparison import (
                    build_and_persist_lab_acps,
                )
                from atlas.investment.lab_contracts import LAB_SWING, lab_kind

                if lab_kind(portfolio_key, cfg=cfg) == LAB_SWING:
                    aw_by: dict[str, dict] = {}
                    if self._investment_research is not None:
                        for h in holds:
                            if not isinstance(h, dict):
                                continue
                            sym_h = str(h.get("symbol") or "").strip().upper()
                            if not sym_h:
                                continue
                            try:
                                aw_by[sym_h] = self._investment_research.awareness(
                                    sym_h,
                                    program_id=str(
                                        cfg.get("program_id") or "market_intelligence"
                                    ),
                                )
                            except Exception:  # noqa: BLE001
                                continue
                    acp_build = build_and_persist_lab_acps(
                        data_dir=data_dir_er,
                        holds=holds,
                        challengers=challengers,
                        cash=cash_amt,
                        laboratory_id=str(portfolio_key or ""),
                        reviews=reviews,
                        awareness_by_symbol=aw_by,
                        equity=float(snapshot.get("equity") or 0) or None,
                        cfg=cfg,
                        challenger_plc_a_ok=plc_ok or None,
                    )
                    state["icr_acp"] = {
                        "count": acp_build.get("count"),
                        "persisted": acp_build.get("persisted"),
                        "lines": (acp_build.get("lines") or [])[:6],
                    }
                    # OI-ICR2 — densify EXIT_REVIEW / SWITCH_REVIEW
                    if icr2_on:
                        from atlas.investment.incumbent_review import (
                            enqueue_identity_curiosity,
                            resolve_lab_exit_reviews,
                        )

                        resolved = resolve_lab_exit_reviews(
                            acp_build.get("packets"),
                            data_dir=data_dir_er,
                            cfg=cfg,
                        )
                        state["icr2"] = {
                            "count": resolved.get("count"),
                            "execute_n": resolved.get("execute_n"),
                            "lines": (resolved.get("lines") or [])[:8],
                            "resolutions": resolved.get("resolutions") or [],
                        }
                        for res in resolved.get("resolutions") or []:
                            if isinstance(res, dict) and res.get("curiosity"):
                                enqueue_identity_curiosity(
                                    data_dir_er,
                                    laboratory_id=str(portfolio_key or ""),
                                    curiosity=res.get("curiosity"),
                                )
                            if res.get("operator_line"):
                                actions.append(str(res["operator_line"]))
                    # OI-ICR3 — schedule opportunity-cost objects (chosen vs rejected)
                    try:
                        from atlas.investment.allocation_regret import (
                            schedule_from_lab_acps,
                        )

                        oc = schedule_from_lab_acps(
                            data_dir_er,
                            acp_build.get("packets"),
                            laboratory_id=str(portfolio_key or ""),
                            resolutions=(state.get("icr2") or {}).get("resolutions"),
                            marks=marks,
                        )
                        state["icr3"] = {
                            "scheduled": oc.get("count"),
                            "oc_ids": (oc.get("oc_ids") or [])[:6],
                        }
                    except Exception as exc:  # noqa: BLE001
                        self._logger.debug("ICR.3 schedule skipped: %s", exc)
                    # OI-ICR5 — scientist notes (advice-only; draft now, LLM later)
                    try:
                        from atlas.investment.incumbent_scientist import (
                            schedule_from_lab_acps as schedule_icr5,
                        )

                        sci = schedule_icr5(
                            data_dir_er,
                            acp_build.get("packets"),
                            laboratory_id=str(portfolio_key or ""),
                            resolutions=(state.get("icr2") or {}).get("resolutions"),
                            cfg=cfg,
                            max_n=int(cfg.get("icr5_max_per_tick") or 4),
                        )
                        state["icr5"] = {
                            "scheduled": sci.get("count"),
                            "ids": (sci.get("ids") or [])[:6],
                        }
                    except Exception as exc:  # noqa: BLE001
                        self._logger.debug("ICR.5 schedule skipped: %s", exc)
                    # OI-ICR5 densify — LLM enrich when lane free.
                    # Off-hours: drain harder so Monday opens with REVIEWED research.
                    try:
                        drain_n = int(cfg.get("icr5_drain_passes") or 1)
                        if not session_open:
                            drain_n = max(
                                drain_n,
                                int(cfg.get("icr5_drain_passes_off_hours") or 3),
                            )
                        if drain_n > 0 and (
                            self._reasoning is not None
                            or getattr(self, "_llm", None) is not None
                        ):
                            from atlas.investment.incumbent_scientist import (
                                drain_pending_scientist_notes,
                            )

                            llm = getattr(self._reasoning, "_llm", None) if self._reasoning else None
                            cap = 5 if not session_open else 2
                            d = drain_pending_scientist_notes(
                                data_dir_er,
                                laboratory_id=str(portfolio_key or ""),
                                llm=llm,
                                reasoning=self._reasoning,
                                max_passes=max(1, min(drain_n, cap)),
                                limit=max(4, min(drain_n * 2, 10)),
                            )
                            state["icr5_drain"] = {
                                "done": d.get("done"),
                                "deferred": d.get("deferred"),
                                "pending": d.get("pending"),
                                "skipped": d.get("skipped"),
                                "off_hours": not bool(session_open),
                            }
                    except Exception as exc:  # noqa: BLE001
                        self._logger.debug("ICR.5 drain skipped: %s", exc)
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("ICR.1 ACP build skipped: %s", exc)
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("challenger table skipped: %s", exc)

        execute = bool(
            cfg.get("opportunity_switch_execute")
            if cfg.get("opportunity_switch_execute") is not None
            else True
        )
        max_sw = max(0, int(cfg.get("max_switches_per_tick") or 1))
        switched = 0
        switch_data_dir: str | None = None
        try:
            from atlas.config import get_config

            switch_data_dir = str(get_config().paths.data)
        except Exception:  # noqa: BLE001
            switch_data_dir = None

        for rev in reviews:
            hold_sym = str(rev.get("hold_symbol") or "")
            chal_sym = str(rev.get("challenger_symbol") or "") or None
            decision = str(rev.get("decision") or "hold")
            reason = str(rev.get("reason_code") or "hold_incumbent")
            adv = rev.get("expected_advantage")
            hold_px = float(marks.get(hold_sym) or 0) if hold_sym else 0.0
            line = (
                f"{hold_sym}: switch_review {decision}"
                + (f"→{chal_sym}" if chal_sym else "")
                + f" ({reason}"
                + (f" adv={float(adv):+.4f}" if adv is not None else "")
                + ")"
            )
            actions.append(line)
            if switch_data_dir and decision == "switch":
                try:
                    from atlas.investment.learning_objects import (
                        record_challenger_threshold_event,
                    )

                    record_challenger_threshold_event(
                        switch_data_dir,
                        laboratory_id=portfolio_key,
                        review=rev,
                        executed=False,
                    )
                except Exception:  # noqa: BLE001
                    pass
            did_execute = False
            # Packet on the hold symbol (silence = bug).
            try:
                self._record_di_packet(
                    action="hold" if decision != "switch" else "sell",
                    symbol=hold_sym or "UNKNOWN",
                    strategy_tag=reason,
                    portfolio_key=portfolio_key,
                    mission_id=mission_id,
                    price=hold_px or 0.0,
                    cfg=cfg,
                    reasons_for=[line] if decision == "switch" else [],
                    reasons_against=[] if decision == "switch" else [line],
                    plan_link={
                        "opportunity_switch": rev,
                        "version": rev.get("version"),
                        **(
                            {
                                "allocation": {
                                    "best_challenger": rev.get("challenger_symbol"),
                                    "challenger_advantage": rev.get("expected_advantage"),
                                    "allocation_action": (
                                        "ROTATE"
                                        if decision == "switch"
                                        else (
                                            "HOLD"
                                            if reason
                                            in {
                                                "switch_blocked_costs",
                                                "switch_blocked_missing_er",
                                            }
                                            else "KEEP"
                                        )
                                    ),
                                }
                            }
                        ),
                    },
                )
            except Exception:  # noqa: BLE001
                pass

            if (
                decision != "switch"
                or not execute
                or not session_open
                or switched >= max_sw
                or not hold_sym
                or not chal_sym
            ):
                # UTS.E — persist evaluated hold/block (not executed).
                try:
                    from atlas.investment.switch_learning import record_switch_decision

                    record_switch_decision(
                        switch_data_dir,
                        rev,
                        laboratory_id=portfolio_key,
                        portfolio_key=portfolio_key,
                        executed=False,
                    )
                except Exception:  # noqa: BLE001
                    pass
                continue

            # Ensure challenger mark exists (live one-shot).
            chal_px = marks.get(chal_sym)
            if chal_px is None:
                try:
                    bars = self._load_live_bars(chal_sym, cfg)
                    if bars:
                        chal_px = float(bars[-1]["close"])
                        marks[chal_sym] = chal_px
                except Exception:  # noqa: BLE001
                    chal_px = None
            if hold_px <= 0 or chal_px is None or float(chal_px) <= 0:
                actions.append(
                    f"{hold_sym}: switch_blocked_no_mark →{chal_sym}"
                )
                try:
                    from atlas.investment.switch_learning import record_switch_decision

                    record_switch_decision(
                        switch_data_dir,
                        rev,
                        laboratory_id=portfolio_key,
                        portfolio_key=portfolio_key,
                        executed=False,
                    )
                except Exception:  # noqa: BLE001
                    pass
                continue

            # OI-LINT0 — never replace an FNO/index-proxy position with cash equity.
            try:
                from atlas.investment.lab_contracts import (
                    is_instrument_permitted,
                    reject_message,
                )

                chal_ok = is_instrument_permitted(
                    portfolio_key, chal_sym, cfg=cfg, path="switch"
                )
                if not chal_ok.allowed:
                    msg = reject_message(chal_ok)
                    actions.append(f"{hold_sym}: switch_blocked_lab →{chal_sym} ({msg})")
                    try:
                        self._record_di_packet(
                            action="hold",
                            symbol=hold_sym,
                            strategy_tag="lab_instrument_rejected",
                            portfolio_key=portfolio_key,
                            mission_id=mission_id,
                            price=hold_px,
                            cfg=cfg,
                            reasons_against=[msg],
                            plan_link={"opportunity_switch": rev},
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        from atlas.activity import record_activity

                        record_activity(
                            domain="market",
                            worker="paper_trading",
                            action="lab_instrument_rejected",
                            target=chal_sym,
                            result="skipped",
                            summary=msg,
                            evidence={
                                "path": "switch",
                                "hold": hold_sym,
                                "laboratory_id": portfolio_key,
                            },
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        from atlas.investment.switch_learning import record_switch_decision

                        record_switch_decision(
                            switch_data_dir,
                            rev,
                            laboratory_id=portfolio_key,
                            portfolio_key=portfolio_key,
                            executed=False,
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    continue
            except Exception:  # noqa: BLE001
                self._logger.debug("lab contract switch gate skipped", exc_info=True)

            # Pre-check research gate before selling (avoid orphan cash).
            if self._investment_research is not None:
                gate_note = self._research_buy_gate(
                    symbol=chal_sym,
                    cfg=cfg,
                    portfolio_key=portfolio_key,
                )
                if gate_note:
                    actions.append(
                        f"{hold_sym}: switch_blocked_research →{chal_sym} ({gate_note})"
                    )
                    try:
                        self._record_di_packet(
                            action="hold",
                            symbol=hold_sym,
                            strategy_tag="switch_blocked_research",
                            portfolio_key=portfolio_key,
                            mission_id=mission_id,
                            price=hold_px,
                            cfg=cfg,
                            reasons_against=[gate_note],
                            plan_link={"opportunity_switch": rev},
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        from atlas.investment.switch_learning import record_switch_decision

                        record_switch_decision(
                            switch_data_dir,
                            rev,
                            laboratory_id=portfolio_key,
                            portfolio_key=portfolio_key,
                            executed=False,
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    continue

            hold_qty = 0.0
            for p in open_pos:
                if str(p.get("symbol") or "").strip().upper() == hold_sym.upper():
                    try:
                        hold_qty = float(
                            p.get("qty") or p.get("quantity") or p.get("shares") or 0
                        )
                    except (TypeError, ValueError):
                        hold_qty = 0.0
                    break
            if hold_qty <= 0:
                try:
                    from atlas.investment.switch_learning import record_switch_decision

                    record_switch_decision(
                        switch_data_dir,
                        rev,
                        laboratory_id=portfolio_key,
                        portfolio_key=portfolio_key,
                        executed=False,
                    )
                except Exception:  # noqa: BLE001
                    pass
                continue

            # P0-A — do not manufacture A→B→dump B→buy A wash on the same IST day.
            try:
                from atlas.investment.wash_lock import (
                    applies_to_lab as _wash_lab,
                    challenger_breaches_concentration,
                    reentry_blocked,
                )

                if _wash_lab(portfolio_key, cfg=cfg):
                    re_in = reentry_blocked(state, chal_sym, now=self._clock())
                    conc = challenger_breaches_concentration(
                        equity=float(snapshot.get("equity") or 0),
                        cash=float(snapshot.get("cash") or 0),
                        hold_qty=hold_qty,
                        hold_px=hold_px,
                        chal_px=float(chal_px),
                        cfg=cfg,
                    )
                    block = re_in if re_in.get("blocked") else conc
                    if block.get("blocked"):
                        tag = str(block.get("reason_code") or "switch_blocked_concentration")
                        msg = str(block.get("honesty") or tag)
                        actions.append(f"{hold_sym}: {tag} →{chal_sym} ({msg})")
                        if re_in.get("blocked"):
                            self._notify_blocked_buy(
                                symbol=chal_sym,
                                reason=str(
                                    re_in.get("email_subject_reason")
                                    or re_in.get("honesty")
                                    or tag
                                ),
                                portfolio_key=portfolio_key,
                                detail=msg,
                                prior_sale=str(re_in.get("prior_sale") or ""),
                            )
                        try:
                            self._record_di_packet(
                                action="hold",
                                symbol=hold_sym,
                                strategy_tag=tag,
                                portfolio_key=portfolio_key,
                                mission_id=mission_id,
                                price=hold_px,
                                cfg=cfg,
                                reasons_against=[msg],
                                plan_link={"opportunity_switch": rev, "wash_lock": block},
                            )
                        except Exception:  # noqa: BLE001
                            pass
                        try:
                            from atlas.investment.switch_learning import record_switch_decision

                            record_switch_decision(
                                switch_data_dir,
                                rev,
                                laboratory_id=portfolio_key,
                                portfolio_key=portfolio_key,
                                executed=False,
                            )
                        except Exception:  # noqa: BLE001
                            pass
                        continue
            except Exception:  # noqa: BLE001
                self._logger.debug("wash lock switch pre-check skipped", exc_info=True)

            fee_sell = 0.0
            fee_buy = 0.0
            fees_sell: dict[str, Any] = {}
            fees_buy: dict[str, Any] = {}
            profile_id = (
                str(cfg.get("broker_profile") or "").strip()
                or (pack.default_broker_profile() if pack is not None else "")
            )
            try:
                if profile_id:
                    bd = compute_fees(
                        get_broker_profile(profile_id),
                        side="sell",
                        quantity=hold_qty,
                        price=hold_px,
                    )
                    fee_sell = float(bd.total)
                    fees_sell = bd.as_dict()
            except Exception:  # noqa: BLE001
                fee_sell = 0.0

            try:
                sell_trade = self._portfolio.apply_trade(
                    portfolio_id,
                    symbol=hold_sym,
                    side="sell",
                    quantity=hold_qty,
                    price=hold_px,
                    fee=fee_sell,
                    fees=fees_sell,
                    mission_id=mission_id,
                    decision_id=None,
                    laboratory_id=portfolio_key,
                    instrument_path="switch",
                )
            except Exception as exc:  # noqa: BLE001
                actions.append(f"{hold_sym}: switch_sell_rejected ({exc})")
                totals["errors"] = int(totals.get("errors") or 0) + 1
                try:
                    from atlas.investment.switch_learning import record_switch_decision

                    record_switch_decision(
                        switch_data_dir,
                        rev,
                        laboratory_id=portfolio_key,
                        portfolio_key=portfolio_key,
                        executed=False,
                    )
                except Exception:  # noqa: BLE001
                    pass
                continue

            totals["sells"] = int(totals.get("sells") or 0) + 1
            totals["decisions"] = int(totals.get("decisions") or 0) + 1
            try:
                from atlas.investment.wash_lock import applies_to_lab as _wash_lab
                from atlas.investment.wash_lock import record_sale

                if _wash_lab(portfolio_key, cfg=cfg):
                    # Switch sells the full incumbent lot → flat exit for that name.
                    record_sale(
                        state,
                        hold_sym,
                        reason=reason,
                        now=self._clock(),
                        remaining_qty=0.0,
                    )
            except Exception:  # noqa: BLE001
                pass
            self._notify_fill(
                side="sell",
                symbol=hold_sym,
                quantity=hold_qty,
                price=hold_px,
                fee=fee_sell,
                fees=fees_sell,
                reason=f"opportunity_switch:{reason}",
                realized_pnl=float(sell_trade.get("realized_pnl") or 0.0),
                portfolio_key=portfolio_key,
                mission_id=mission_id,
                trade=sell_trade,
            )
            try:
                self._record_di_packet(
                    action="sell",
                    symbol=hold_sym,
                    strategy_tag=reason,
                    portfolio_key=portfolio_key,
                    mission_id=mission_id,
                    price=hold_px,
                    cfg=cfg,
                    qty=hold_qty,
                    filled_qty=hold_qty,
                    fill_price=hold_px,
                    fees=fee_sell,
                    fill_trade_id=sell_trade.get("id") or sell_trade.get("trade_id"),
                    reasons_for=[line],
                    plan_link={"opportunity_switch": rev},
                )
            except Exception:  # noqa: BLE001
                pass

            # Size challenger buy from freed cash (whole shares).
            snap2 = self._portfolio.snapshot(portfolio_id, prices=marks)
            cash = float(snap2.get("cash") or 0)
            buy_qty = int(cash // float(chal_px)) if float(chal_px) > 0 else 0
            if buy_qty <= 0:
                actions.append(
                    f"{chal_sym}: switch_buy_unaffordable after sell {hold_sym}"
                )
                switched += 1
                try:
                    from atlas.investment.switch_learning import record_switch_decision

                    record_switch_decision(
                        switch_data_dir,
                        rev,
                        laboratory_id=portfolio_key,
                        portfolio_key=portfolio_key,
                        executed=False,
                    )
                except Exception:  # noqa: BLE001
                    pass
                continue
            try:
                if profile_id:
                    bd = compute_fees(
                        get_broker_profile(profile_id),
                        side="buy",
                        quantity=float(buy_qty),
                        price=float(chal_px),
                    )
                    fee_buy = float(bd.total)
                    fees_buy = bd.as_dict()
                    # Leave room for fees.
                    while buy_qty > 0 and buy_qty * float(chal_px) + fee_buy > cash:
                        buy_qty -= 1
                        if buy_qty <= 0:
                            break
                        bd = compute_fees(
                            get_broker_profile(profile_id),
                            side="buy",
                            quantity=float(buy_qty),
                            price=float(chal_px),
                        )
                        fee_buy = float(bd.total)
                        fees_buy = bd.as_dict()
            except Exception:  # noqa: BLE001
                fee_buy = 0.0
            if buy_qty <= 0:
                actions.append(
                    f"{chal_sym}: switch_buy_unaffordable after sell {hold_sym}"
                )
                switched += 1
                try:
                    from atlas.investment.switch_learning import record_switch_decision

                    record_switch_decision(
                        switch_data_dir,
                        rev,
                        laboratory_id=portfolio_key,
                        portfolio_key=portfolio_key,
                        executed=False,
                    )
                except Exception:  # noqa: BLE001
                    pass
                continue
            # OI-ICR0 — challenger buy still subject to AVOID / quarantine (not ADD path).
            try:
                from atlas.investment.incumbent_capital import (
                    evaluate_icr0_buy,
                    icr0_enabled,
                )

                if icr0_enabled(cfg, portfolio_key) and self._investment_research is not None:
                    aw_sw = None
                    try:
                        aw_sw = self._investment_research.awareness(
                            chal_sym,
                            program_id=str(
                                cfg.get("program_id") or "market_intelligence"
                            ),
                        )
                    except Exception:  # noqa: BLE001
                        aw_sw = None
                    data_dir_sw = None
                    try:
                        from atlas.config import get_config

                        data_dir_sw = str(get_config().paths.data)
                    except Exception:  # noqa: BLE001
                        data_dir_sw = None
                    icr_sw = evaluate_icr0_buy(
                        laboratory_id=str(portfolio_key or ""),
                        symbol=chal_sym,
                        held=0.0,
                        awareness=aw_sw if isinstance(aw_sw, dict) else None,
                        cfg=cfg,
                        data_dir=data_dir_sw,
                        seen_state_hashes=None,
                    )
                    if not icr_sw.get("allowed", True):
                        actions.append(
                            str(icr_sw.get("line") or f"{chal_sym}: add_blocked_icr0")
                        )
                        switched += 1
                        continue
            except Exception:  # noqa: BLE001
                pass
            try:
                buy_trade = self._portfolio.apply_trade(
                    portfolio_id,
                    symbol=chal_sym,
                    side="buy",
                    quantity=float(buy_qty),
                    price=float(chal_px),
                    fee=fee_buy,
                    fees=fees_buy,
                    mission_id=mission_id,
                    decision_id=None,
                    laboratory_id=portfolio_key,
                    instrument_path="switch",
                )
            except Exception as exc:  # noqa: BLE001
                actions.append(f"{chal_sym}: switch_buy_rejected ({exc})")
                totals["errors"] = int(totals.get("errors") or 0) + 1
                switched += 1
                try:
                    from atlas.investment.switch_learning import record_switch_decision

                    record_switch_decision(
                        switch_data_dir,
                        rev,
                        laboratory_id=portfolio_key,
                        portfolio_key=portfolio_key,
                        executed=False,
                    )
                except Exception:  # noqa: BLE001
                    pass
                continue

            totals["buys"] = int(totals.get("buys") or 0) + 1
            totals["decisions"] = int(totals.get("decisions") or 0) + 1
            switched += 1
            did_execute = True
            buy_line = (
                f"{chal_sym}: switch_buy {buy_qty:g} @ {float(chal_px):.2f} "
                f"(from {hold_sym}; {reason})"
            )
            actions.append(buy_line)
            self._notify_fill(
                side="buy",
                symbol=chal_sym,
                quantity=float(buy_qty),
                price=float(chal_px),
                fee=fee_buy,
                fees=fees_buy,
                reason=f"opportunity_switch:{reason}",
                realized_pnl=0.0,
                portfolio_key=portfolio_key,
                mission_id=mission_id,
                trade=buy_trade,
            )
            try:
                self._record_di_packet(
                    action="buy",
                    symbol=chal_sym,
                    strategy_tag=reason,
                    portfolio_key=portfolio_key,
                    mission_id=mission_id,
                    price=float(chal_px),
                    cfg=cfg,
                    qty=float(buy_qty),
                    filled_qty=float(buy_qty),
                    fill_price=float(chal_px),
                    fees=fee_buy,
                    fill_trade_id=buy_trade.get("id") or buy_trade.get("trade_id"),
                    reasons_for=[buy_line],
                    plan_link={"opportunity_switch": rev, "from_symbol": hold_sym},
                )
            except Exception:  # noqa: BLE001
                pass
            try:
                from atlas.investment.switch_learning import record_switch_decision

                record_switch_decision(
                    switch_data_dir,
                    rev,
                    laboratory_id=portfolio_key,
                    portfolio_key=portfolio_key,
                    executed=did_execute,
                )
            except Exception:  # noqa: BLE001
                pass
            # Refresh open_pos so a second switch doesn't reuse sold qty.
            snapshot = self._portfolio.snapshot(portfolio_id, prices=marks)
            open_pos = [
                p
                for p in (snapshot.get("positions") or [])
                if isinstance(p, dict)
                and float(p.get("qty") or p.get("quantity") or p.get("shares") or 0)
                > 0
            ]

        # OI-ICR2 — execute EXIT_TO_CASH / SWITCH_TO from densified EXIT_REVIEW
        if icr2_on and session_open:
            try:
                icr2_actions = self._execute_icr2_resolutions(
                    cfg=cfg,
                    portfolio_id=portfolio_id,
                    portfolio_key=portfolio_key,
                    marks=marks,
                    state=state,
                    mission_id=mission_id,
                    totals=totals,
                    pack=pack,
                    open_pos=open_pos,
                )
                actions.extend(icr2_actions)
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("ICR.2 execute skipped: %s", exc)

        return actions

    def _execute_icr2_resolutions(
        self,
        *,
        cfg: dict[str, Any],
        portfolio_id: Any,
        portfolio_key: str,
        marks: dict[str, float],
        state: dict[str, Any],
        mission_id: Any,
        totals: dict[str, Any],
        pack: Any,
        open_pos: list[dict[str, Any]],
    ) -> list[str]:
        """Execute ICR.2 EXIT_TO_CASH / SWITCH_TO (paper). WAIT is log-only."""
        from atlas.investment.incumbent_review import (
            ACTION_EXIT_TO_CASH,
            ACTION_SWITCH_TO,
        )
        from atlas.trading.broker_profiles import compute_fees, get_broker_profile

        execute = bool(
            cfg.get("icr2_execute")
            if cfg.get("icr2_execute") is not None
            else True
        )
        max_n = max(0, int(cfg.get("icr2_max_actions_per_tick") or 1))
        resolutions = list((state.get("icr2") or {}).get("resolutions") or [])
        out: list[str] = []
        if not execute or max_n <= 0 or not resolutions:
            return out

        profile_id = (
            str(cfg.get("broker_profile") or "").strip()
            or (pack.default_broker_profile() if pack is not None else "")
        )
        done = 0
        pos_by = {
            str(p.get("symbol") or "").strip().upper(): p
            for p in open_pos
            if isinstance(p, dict) and p.get("symbol")
        }

        for res in resolutions:
            if done >= max_n:
                break
            if not isinstance(res, dict) or not res.get("execute"):
                continue
            action = str(res.get("action") or "")
            sym = str(res.get("symbol") or "").strip().upper()
            if not sym or sym not in pos_by:
                continue
            pos = pos_by[sym]
            try:
                qty = float(pos.get("qty") or pos.get("quantity") or pos.get("shares") or 0)
            except (TypeError, ValueError):
                qty = 0.0
            px = float(marks.get(sym) or pos.get("mark") or pos.get("avg_price") or 0)
            if qty <= 0 or px <= 0:
                continue

            if action == ACTION_EXIT_TO_CASH:
                fee = 0.0
                fees_doc: dict[str, Any] = {}
                try:
                    if profile_id:
                        bd = compute_fees(
                            get_broker_profile(profile_id),
                            side="sell",
                            quantity=qty,
                            price=px,
                        )
                        fee = float(bd.total)
                        fees_doc = bd.as_dict()
                except Exception:  # noqa: BLE001
                    fee = 0.0
                try:
                    trade = self._portfolio.apply_trade(
                        portfolio_id,
                        symbol=sym,
                        side="sell",
                        quantity=qty,
                        price=px,
                        fee=fee,
                        fees=fees_doc,
                        mission_id=mission_id,
                        decision_id=None,
                        laboratory_id=portfolio_key,
                        instrument_path="icr2_exit",
                    )
                except Exception as exc:  # noqa: BLE001
                    out.append(f"{sym}: icr2_exit_rejected ({exc})")
                    continue
                totals["sells"] = int(totals.get("sells") or 0) + 1
                totals["decisions"] = int(totals.get("decisions") or 0) + 1
                line = str(
                    res.get("operator_line")
                    or f"{sym}: icr2 EXIT_TO_CASH ({res.get('reason_code')})"
                )
                out.append(line + " [executed]")
                try:
                    from atlas.investment.wash_lock import applies_to_lab as _wash_lab
                    from atlas.investment.wash_lock import record_sale

                    if _wash_lab(portfolio_key, cfg=cfg):
                        record_sale(
                            state,
                            sym,
                            reason=str(res.get("reason_code") or "icr2_exit_to_cash"),
                            now=self._clock(),
                            remaining_qty=0.0,
                        )
                except Exception:  # noqa: BLE001
                    pass
                self._notify_fill(
                    side="sell",
                    symbol=sym,
                    quantity=qty,
                    price=px,
                    fee=fee,
                    fees=fees_doc,
                    reason=str(res.get("reason_code") or "icr2_exit_to_cash"),
                    realized_pnl=float(trade.get("realized_pnl") or 0.0),
                    portfolio_key=portfolio_key,
                    mission_id=mission_id,
                    trade=trade,
                )
                try:
                    self._record_di_packet(
                        action="sell",
                        symbol=sym,
                        strategy_tag=str(res.get("reason_code") or "icr2_exit_to_cash"),
                        portfolio_key=portfolio_key,
                        mission_id=mission_id,
                        price=px,
                        cfg=cfg,
                        qty=qty,
                        filled_qty=qty,
                        fill_price=px,
                        fees=fee,
                        fill_trade_id=trade.get("id") or trade.get("trade_id"),
                        reasons_for=[line],
                        plan_link={"icr2": res},
                    )
                except Exception:  # noqa: BLE001
                    pass
                done += 1
                pos_by.pop(sym, None)
                continue

            if action == ACTION_SWITCH_TO:
                chal = str(res.get("challenger_symbol") or "").strip().upper()
                chal_px = float(marks.get(chal) or 0) if chal else 0.0
                if not chal or chal_px <= 0:
                    out.append(f"{sym}: icr2_switch_missing_challenger_mark")
                    continue
                # Reuse UTS switch path by synthesizing a review and selling then buying.
                fee_sell = 0.0
                fees_sell: dict[str, Any] = {}
                try:
                    if profile_id:
                        bd = compute_fees(
                            get_broker_profile(profile_id),
                            side="sell",
                            quantity=qty,
                            price=px,
                        )
                        fee_sell = float(bd.total)
                        fees_sell = bd.as_dict()
                except Exception:  # noqa: BLE001
                    fee_sell = 0.0
                try:
                    sell_trade = self._portfolio.apply_trade(
                        portfolio_id,
                        symbol=sym,
                        side="sell",
                        quantity=qty,
                        price=px,
                        fee=fee_sell,
                        fees=fees_sell,
                        mission_id=mission_id,
                        decision_id=None,
                        laboratory_id=portfolio_key,
                        instrument_path="icr2_switch",
                    )
                except Exception as exc:  # noqa: BLE001
                    out.append(f"{sym}: icr2_switch_sell_rejected ({exc})")
                    continue
                totals["sells"] = int(totals.get("sells") or 0) + 1
                try:
                    from atlas.investment.wash_lock import applies_to_lab as _wash_lab
                    from atlas.investment.wash_lock import record_sale, reentry_blocked

                    if _wash_lab(portfolio_key, cfg=cfg):
                        record_sale(
                            state,
                            sym,
                            reason=str(res.get("reason_code") or "icr2_switch"),
                            now=self._clock(),
                            remaining_qty=0.0,
                        )
                        re_in = reentry_blocked(state, chal, now=self._clock())
                        if re_in.get("blocked"):
                            out.append(
                                f"{sym}: icr2_switch sold but {chal} "
                                f"{re_in.get('reason_code')} — cash"
                            )
                            self._notify_fill(
                                side="sell",
                                symbol=sym,
                                quantity=qty,
                                price=px,
                                fee=fee_sell,
                                fees=fees_sell,
                                reason=str(res.get("reason_code") or "icr2_switch"),
                                realized_pnl=float(
                                    sell_trade.get("realized_pnl") or 0.0
                                ),
                                portfolio_key=portfolio_key,
                                mission_id=mission_id,
                                trade=sell_trade,
                            )
                            self._notify_blocked_buy(
                                symbol=chal,
                                reason=str(
                                    re_in.get("email_subject_reason")
                                    or re_in.get("honesty")
                                    or "same_day_reentry_blocked"
                                ),
                                portfolio_key=portfolio_key,
                                detail=str(re_in.get("honesty") or ""),
                                prior_sale=str(re_in.get("prior_sale") or ""),
                            )
                            totals["decisions"] = int(totals.get("decisions") or 0) + 1
                            done += 1
                            pos_by.pop(sym, None)
                            continue
                except Exception:  # noqa: BLE001
                    pass
                self._notify_fill(
                    side="sell",
                    symbol=sym,
                    quantity=qty,
                    price=px,
                    fee=fee_sell,
                    fees=fees_sell,
                    reason=str(res.get("reason_code") or "icr2_switch"),
                    realized_pnl=float(sell_trade.get("realized_pnl") or 0.0),
                    portfolio_key=portfolio_key,
                    mission_id=mission_id,
                    trade=sell_trade,
                )
                snap2 = self._portfolio.snapshot(portfolio_id, prices=marks)
                cash = float(snap2.get("cash") or 0)
                buy_qty = int(cash // chal_px) if chal_px > 0 else 0
                fee_buy = 0.0
                fees_buy: dict[str, Any] = {}
                if buy_qty > 0 and profile_id:
                    try:
                        bd = compute_fees(
                            get_broker_profile(profile_id),
                            side="buy",
                            quantity=float(buy_qty),
                            price=chal_px,
                        )
                        fee_buy = float(bd.total)
                        fees_buy = bd.as_dict()
                        while buy_qty > 0 and buy_qty * chal_px + fee_buy > cash:
                            buy_qty -= 1
                            if buy_qty <= 0:
                                break
                            bd = compute_fees(
                                get_broker_profile(profile_id),
                                side="buy",
                                quantity=float(buy_qty),
                                price=chal_px,
                            )
                            fee_buy = float(bd.total)
                            fees_buy = bd.as_dict()
                    except Exception:  # noqa: BLE001
                        fee_buy = 0.0
                # ICR.0 gate on challenger
                try:
                    from atlas.investment.incumbent_capital import (
                        evaluate_icr0_buy,
                        icr0_enabled,
                    )

                    if icr0_enabled(cfg, portfolio_key) and self._investment_research:
                        aw = self._investment_research.awareness(
                            chal,
                            program_id=str(
                                cfg.get("program_id") or "market_intelligence"
                            ),
                        )
                        from atlas.config import get_config

                        gate = evaluate_icr0_buy(
                            laboratory_id=str(portfolio_key or ""),
                            symbol=chal,
                            held=0.0,
                            awareness=aw if isinstance(aw, dict) else None,
                            cfg=cfg,
                            data_dir=str(get_config().paths.data),
                        )
                        if not gate.get("allowed", True):
                            out.append(
                                f"{sym}: icr2_switch sold but challenger blocked "
                                f"({gate.get('reason_code')}) — cash"
                            )
                            totals["decisions"] = int(totals.get("decisions") or 0) + 1
                            done += 1
                            pos_by.pop(sym, None)
                            continue
                except Exception:  # noqa: BLE001
                    pass
                if buy_qty <= 0:
                    out.append(
                        f"{sym}: icr2_switch sold→cash (challenger unaffordable)"
                    )
                    done += 1
                    pos_by.pop(sym, None)
                    continue
                try:
                    buy_trade = self._portfolio.apply_trade(
                        portfolio_id,
                        symbol=chal,
                        side="buy",
                        quantity=float(buy_qty),
                        price=chal_px,
                        fee=fee_buy,
                        fees=fees_buy,
                        mission_id=mission_id,
                        decision_id=None,
                        laboratory_id=portfolio_key,
                        instrument_path="icr2_switch",
                    )
                except Exception as exc:  # noqa: BLE001
                    out.append(f"{chal}: icr2_switch_buy_rejected ({exc})")
                    done += 1
                    continue
                totals["buys"] = int(totals.get("buys") or 0) + 1
                totals["decisions"] = int(totals.get("decisions") or 0) + 1
                line = str(
                    res.get("operator_line")
                    or f"{sym}: icr2 SWITCH_TO {chal}"
                )
                out.append(line + f" [executed sell→buy ×{buy_qty}]")
                self._notify_fill(
                    side="buy",
                    symbol=chal,
                    quantity=float(buy_qty),
                    price=chal_px,
                    fee=fee_buy,
                    fees=fees_buy,
                    reason=str(res.get("reason_code") or "icr2_switch"),
                    realized_pnl=0.0,
                    portfolio_key=portfolio_key,
                    mission_id=mission_id,
                    trade=buy_trade,
                )
                try:
                    self._record_di_packet(
                        action="sell",
                        symbol=sym,
                        strategy_tag=str(res.get("reason_code") or "icr2_switch"),
                        portfolio_key=portfolio_key,
                        mission_id=mission_id,
                        price=px,
                        cfg=cfg,
                        qty=qty,
                        filled_qty=qty,
                        fill_price=px,
                        fees=fee_sell,
                        fill_trade_id=sell_trade.get("id") or sell_trade.get("trade_id"),
                        reasons_for=[line],
                        plan_link={"icr2": res},
                    )
                    self._record_di_packet(
                        action="buy",
                        symbol=chal,
                        strategy_tag=str(res.get("reason_code") or "icr2_switch"),
                        portfolio_key=portfolio_key,
                        mission_id=mission_id,
                        price=chal_px,
                        cfg=cfg,
                        qty=float(buy_qty),
                        filled_qty=float(buy_qty),
                        fill_price=chal_px,
                        fees=fee_buy,
                        fill_trade_id=buy_trade.get("id") or buy_trade.get("trade_id"),
                        reasons_for=[line],
                        plan_link={"icr2": res, "from_symbol": sym},
                    )
                except Exception:  # noqa: BLE001
                    pass
                done += 1
                pos_by.pop(sym, None)

        return out

    def _refresh_consult_book(self, snapshot: dict[str, Any] | None) -> None:
        """Book fingerprint for unique-state consult (material change = new state)."""
        from atlas.reasoning.decision_consult import book_fingerprint

        snap = snapshot if isinstance(snapshot, dict) else {}
        held: list[str] = []
        for p in snap.get("positions") or []:
            if not isinstance(p, dict):
                continue
            try:
                q = float(p.get("qty") or p.get("quantity") or p.get("shares") or 0)
            except (TypeError, ValueError):
                q = 0.0
            if q > 0 and p.get("symbol"):
                held.append(str(p.get("symbol")))
        equity = snap.get("equity")
        cash = snap.get("cash")
        cash_pct = None
        try:
            if equity and float(equity) > 0 and cash is not None:
                cash_pct = float(cash) / float(equity)
        except (TypeError, ValueError):
            cash_pct = None
        self._consult_book_fp = book_fingerprint(held, cash_pct)

    def _belief_context_for_packet(
        self,
        *,
        action: str,
        symbol: str,
        strategy_tag: str,
        portfolio_key: str,
        thesis_trigger: str | None,
        plan_link: dict[str, Any] | None,
        expected_doc: dict[str, Any] | None,
        research_gate: dict[str, Any] | None,
        portfolio_gate: dict[str, Any] | None,
        indicators: dict[str, Any] | None,
        fundamentals: dict[str, Any] | None,
        sector: str | None,
        ist_day: str,
    ) -> dict[str, Any]:
        """LOOP0 L2 — consult unique decision state; advice-only; no LLM."""
        from atlas.reasoning.decision_consult import (
            consult_unique_decision,
            evidence_fingerprint,
            load_day_cache,
            regime_bucket,
        )

        data_dir = None
        try:
            from atlas.config import get_config

            data_dir = str(get_config().paths.data)
        except Exception:  # noqa: BLE001
            data_dir = None
        plink = plan_link if isinstance(plan_link, dict) else {}
        sw = plink.get("opportunity_switch") if isinstance(plink.get("opportunity_switch"), dict) else {}
        rg = research_gate if isinstance(research_gate, dict) else {}
        pg = portfolio_gate if isinstance(portfolio_gate, dict) else {}
        fund = fundamentals if isinstance(fundamentals, dict) else {}
        exp = expected_doc if isinstance(expected_doc, dict) else {}
        cache_key = f"{portfolio_key}|{ist_day}"
        mem = getattr(self, "_consult_by_day", None)
        if not isinstance(mem, dict):
            mem = {}
            self._consult_by_day = mem
        if cache_key not in mem:
            mem[cache_key] = load_day_cache(data_dir, portfolio_key, ist_day)
        snap_tags = None
        try:
            snap_tags = list((indicators or {}).get("regime_tags") or [])
        except Exception:  # noqa: BLE001
            snap_tags = None
        return consult_unique_decision(
            self._reasoning,
            symbol=symbol,
            laboratory_id=portfolio_key,
            action_kind=action,
            strategy_tag=strategy_tag,
            ist_day=ist_day,
            cache=mem[cache_key],
            data_dir=data_dir,
            experience_os=self._experience_os,
            thesis_id=str(thesis_trigger or plink.get("thesis_id") or sw.get("thesis_id") or ""),
            rank=plink.get("rank"),
            book_fp=str(getattr(self, "_consult_book_fp", "") or ""),
            evidence_fp=evidence_fingerprint(
                research_ok=rg.get("allowed"),
                portfolio_ok=pg.get("allowed"),
                pe_present=fund.get("pe") is not None,
                plc_reason=str(rg.get("reason") or pg.get("action") or strategy_tag or ""),
                er_completeness=exp.get("er_completeness"),
            ),
            regime=regime_bucket(indicators, snap_tags),
            sector=str(sector or ""),
            persist=True,
            knowledge=getattr(self, "_knowledge", None),
            candidate={
                "action": action,
                "strategy_tag": strategy_tag,
                "setup_tag": str((indicators or {}).get("setup_tag") or ""),
                "regime": regime_bucket(indicators, snap_tags),
                "regime_tags": list(snap_tags or []),
                "features": list((indicators or {}).get("features") or []),
                "decision_type": str((indicators or {}).get("decision_type") or ""),
            },
        )

    def _record_blocked_buy_experience(
        self,
        *,
        symbol: str,
        portfolio_key: str,
        strategy_tag: str,
        line: str,
        cfg: dict[str, Any],
        indicators: dict[str, Any] | None = None,
        instrument: dict[str, Any] | None = None,
        gate: dict[str, Any] | None = None,
        price: float | None = None,
        against: list[str] | None = None,
        decision_id: Any = None,
    ) -> None:
        """L24 — gated technical BUY → blocked_buy experience (no P&L/reward)."""
        try:
            from atlas.config import get_config
            from atlas.investment.lab_experience import record_blocked_buy

            record_blocked_buy(
                str(get_config().paths.data),
                laboratory_id=str(portfolio_key or "india_equity_learner"),
                symbol=symbol,
                strategy_tag=strategy_tag,
                reason=line,
                reasons_against=against,
                indicators=indicators,
                instrument=instrument,
                gate=gate,
                price=price,
                cfg=cfg,
                decision_id=str(decision_id) if decision_id else None,
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("blocked_buy experience skipped: %s", exc)

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
        expected: dict[str, Any] | None = None,
        plan_link: dict[str, Any] | None = None,
        gap_pct: float | None = None,
        bars: list[dict[str, Any]] | None = None,
        cursor: int | None = None,
        thesis_trigger: str | None = None,
        position_qty: float | None = None,
        fno_contract: dict[str, Any] | None = None,
        lesson_refs: list[dict[str, Any]] | None = None,
        experience_refs: list[Any] | None = None,
    ) -> dict[str, Any] | None:
        """DI.1 — freeze a Decision Packet (best-effort; never raises).

        OI-EXP0: routine HOLD / switch_blocked packets are recorded at most once
        per symbol+reason per IST day so activity cannot inflate learning metrics.
        """
        store = self._decision_packets
        if store is None:
            return None
        try:
            from atlas.investment.experience_integrity import (
                classify_experience_kind,
                fingerprint,
                ist_day,
                should_record_packet,
            )

            day = ist_day()
            reason_code = str(strategy_tag or "")
            existing: list = []
            try:
                existing = store.list_day(
                    portfolio_key=portfolio_key or "india_equity_learner",
                    ts_ist=day,
                    limit=200,
                ) or []
            except Exception:  # noqa: BLE001
                existing = []
            ok, skip_reason = should_record_packet(
                existing,
                portfolio_key=portfolio_key or "india_equity_learner",
                symbol=symbol,
                action=action,
                strategy_tag=str(strategy_tag or ""),
                reason_code=reason_code,
                ist_day_s=day,
            )

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

            expected_doc = dict(expected) if isinstance(expected, dict) else None
            if expected_doc is None and isinstance(plink, dict):
                sw = plink.get("opportunity_switch")
                if isinstance(sw, dict) and isinstance(sw.get("hold_metrics"), dict):
                    try:
                        from atlas.investment.expected_return_prototype import (
                            expected_block_from_metrics,
                        )

                        expected_doc = expected_block_from_metrics(sw.get("hold_metrics"))
                    except Exception:  # noqa: BLE001
                        expected_doc = None

            belief_ctx = self._belief_context_for_packet(
                action=action,
                symbol=symbol,
                strategy_tag=tag,
                portfolio_key=portfolio_key or "india_equity_learner",
                thesis_trigger=thesis_trigger,
                plan_link=plink if isinstance(plink, dict) else None,
                expected_doc=expected_doc,
                research_gate=research_gate,
                portfolio_gate=portfolio_gate,
                indicators=indicators,
                fundamentals=fundamentals if isinstance(fundamentals, dict) else None,
                sector=sector,
                ist_day=day,
            )
            if lesson_refs or experience_refs:
                try:
                    from atlas.investment.lesson_influence import stamp_belief_context

                    existing = list(belief_ctx.get("lesson_refs") or [])
                    seen = {str(r.get("id")) for r in existing if isinstance(r, dict)}
                    merged = existing + [
                        r
                        for r in (lesson_refs or [])
                        if isinstance(r, dict) and str(r.get("id")) not in seen
                    ]
                    belief_ctx = stamp_belief_context(belief_ctx, merged)
                    ids = list(belief_ctx.get("experience_refs") or [])
                    for xid in experience_refs or []:
                        sx = str(xid)
                        if sx and sx not in ids:
                            ids.append(sx)
                    belief_ctx["experience_refs"] = ids
                    if ids:
                        belief_ctx["no_match"] = False
                        belief_ctx.pop("no_match_reason", None)
                except Exception:  # noqa: BLE001
                    self._logger.debug("lesson merge onto packet skipped", exc_info=True)
            if not ok:
                return {
                    "skipped": True,
                    "reason": skip_reason,
                    "symbol": symbol,
                    "strategy_tag": strategy_tag,
                    "belief_context": belief_ctx,
                }

            _decomp: dict[str, Any] | None = None
            try:
                from atlas.investment.lab_contracts import decompose_decision

                aw_d = {}
                if isinstance(valuation, dict):
                    aw_d["valuation"] = valuation
                _decomp = decompose_decision(
                    laboratory_id=portfolio_key,
                    symbol=symbol,
                    action=action,
                    cfg=cfg,
                    awareness=aw_d or None,
                    held=float(position_qty or 0),
                    research_confidence=(
                        (research_gate or {}).get("confidence")
                        if isinstance(research_gate, dict)
                        else None
                    ),
                    risk_gate=(
                        "PASS"
                        if not portfolio_gate
                        or (isinstance(portfolio_gate, dict) and portfolio_gate.get("allowed", True))
                        else "FAIL"
                    ),
                    path="buy" if str(action).lower() == "buy" else str(action or "hold"),
                )
                if isinstance(plink, dict) and plink.get("opportunity_switch"):
                    _decomp["challenger_vs_book"] = str(
                        (plink.get("opportunity_switch") or {}).get("decision") or ""
                    ) or None
            except Exception:  # noqa: BLE001
                _decomp = None

            # PLC.D — hypothesis on every buy (learner default)
            hypothesis_id: str | None = None
            data_dir: str | None = None
            try:
                from atlas.config import get_config

                data_dir = str(get_config().paths.data)
            except Exception:  # noqa: BLE001
                data_dir = getattr(store, "data_dir", None)
            try:
                from atlas.investment.plc_hypothesis import (
                    create_buy_hypothesis,
                    find_open_buy_hypothesis_for_symbol,
                    plc_d_enabled,
                    complete_hypothesis_check,
                )

                pk = portfolio_key or "india_equity_learner"
                if (
                    action == "buy"
                    and plc_d_enabled(cfg, pk)
                    and bool(cfg.get("plc_d_hypothesis", True))
                ):
                    hyp_out = create_buy_hypothesis(
                        data_dir,
                        symbol=symbol,
                        thesis_trigger=thesis_trigger,
                        laboratory_id=pk,
                        portfolio_key=pk,
                        strategy_tag=tag,
                    )
                    hypothesis_id = str(
                        ((hyp_out or {}).get("hypothesis") or {}).get("hypothesis_id")
                        or ""
                    ) or None
                elif action == "sell" and plc_d_enabled(cfg, pk):
                    open_hyp = find_open_buy_hypothesis_for_symbol(
                        data_dir, symbol=symbol, laboratory_id=pk, portfolio_key=pk
                    )
                    if open_hyp and open_hyp.get("hypothesis_id"):
                        hypothesis_id = str(open_hyp["hypothesis_id"])
                        complete_hypothesis_check(
                            data_dir,
                            hypothesis_id=hypothesis_id,
                            checkpoint="exit",
                            laboratory_id=pk,
                            note="sell fill — PLC.D exit check",
                            mark_exit=True,
                        )
            except Exception:  # noqa: BLE001
                self._logger.debug("PLC.D hypothesis skipped", exc_info=True)
                hypothesis_id = None

            # GENE.1 — stamp parent_decision_id on material buy/sell follow-ons
            parent_decision_id: str | None = None
            if str(action or "").lower() in {"buy", "sell"}:
                try:
                    from atlas.investment.decision_genealogy import (
                        find_parent_decision_id,
                    )

                    parent_decision_id = find_parent_decision_id(
                        store,
                        symbol=symbol,
                        portfolio_key=portfolio_key or "india_equity_learner",
                    )
                except Exception:  # noqa: BLE001
                    parent_decision_id = None

            _alloc_meta: dict[str, Any] = {}
            if data_dir:
                try:
                    from atlas.investment.capital_allocation import (
                        load_allocation_table,
                        packet_allocation_fields,
                    )

                    _alloc_meta = packet_allocation_fields(
                        load_allocation_table(
                            data_dir, portfolio_key or "india_equity_learner"
                        ),
                        symbol,
                    )
                except Exception:  # noqa: BLE001
                    _alloc_meta = {}

            tape_ref = None
            try:
                from atlas.investment.intraday_bars import (
                    is_intraday_lab,
                    tape_ref_for_decision,
                )

                if is_intraday_lab(cfg, portfolio_key):
                    tape_ref = tape_ref_for_decision(
                        data_dir,
                        symbol,
                        bars=bars,
                        cursor=cursor,
                        provider=str(cfg.get("live_provider") or "") or None,
                    )
            except Exception:  # noqa: BLE001
                tape_ref = None

            snap = empty_market_snapshot(session=session, sector=sector)
            if tape_ref:
                snap["intraday_tape"] = tape_ref

            saved = store.record(
                action=action,
                symbol=symbol,
                portfolio_key=portfolio_key or "india_equity_learner",
                strategy_tag=tag,
                mission_id=str(mission_id) if mission_id else None,
                engine_decision_id=str(engine_decision_id) if engine_decision_id else None,
                fill_trade_id=str(fill_trade_id) if fill_trade_id else None,
                market_snapshot=stamp_regime_on_snapshot(
                    snap,
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
                expected=expected_doc,
                belief_context=belief_ctx,
                process_context={
                    "plan": plan_doc if isinstance(plan_doc, dict) else None,
                    "recent_losses": set(),
                    "gap_pct": gap,
                },
                hypothesis_id=hypothesis_id,
                parent_decision_id=parent_decision_id,
                meta_extra={
                    "ist_day": day,
                    "experience_kind": classify_experience_kind(
                        action=action, strategy_tag=tag
                    ),
                    "experience_fingerprint": fingerprint(
                        portfolio_key=portfolio_key or "india_equity_learner",
                        symbol=symbol,
                        action=action,
                        strategy_tag=tag,
                        ist_day_s=day,
                        reason_code=reason_code,
                    ),
                    "experience_integrity": "exp.integrity.v1",
                    # BRE.3 — async rationale marker (never blocks fill; drain elsewhere)
                    **(
                        {"llm_pending": True}
                        if str(action or "").lower() in {"buy", "sell"}
                        else {}
                    ),
                    **(
                        {"decision_decomposition": _decomp}
                        if _decomp
                        else {}
                    ),
                    **({"allocation": _alloc_meta} if _alloc_meta else {}),
                    **(
                        {"fno_contract": fno_contract}
                        if isinstance(fno_contract, dict)
                        else (
                            {"fno_contract": (cfg.get("_fno_contracts") or {}).get(str(symbol).upper())}
                            if isinstance((cfg.get("_fno_contracts") or {}).get(str(symbol).upper()), dict)
                            else {}
                        )
                    ),
                    **({"intraday_tape": tape_ref} if tape_ref else {}),
                },
            )
            # Link packet id back onto hypothesis after durable write
            if hypothesis_id and data_dir:
                try:
                    packet = (saved or {}).get("packet") or {}
                    did = packet.get("decision_id") or packet.get("id")
                    if did:
                        from atlas.investment.plc_hypothesis import (
                            attach_decision_to_hypothesis,
                        )

                        attach_decision_to_hypothesis(
                            data_dir,
                            hypothesis_id=hypothesis_id,
                            decision_id=str(did),
                            laboratory_id=portfolio_key or "india_equity_learner",
                        )
                except Exception:  # noqa: BLE001
                    self._logger.debug("PLC.D link after packet failed", exc_info=True)
            # CF.1 — schedule +30d counterfactual panels on material buys
            if action == "buy" and data_dir and saved and not saved.get("skipped"):
                try:
                    packet = (saved or {}).get("packet") or {}
                    did = packet.get("decision_id") or packet.get("id")
                    fill_px = fill_price if fill_price is not None else price
                    from atlas.investment.counterfactual_learning import schedule_cf

                    schedule_cf(
                        data_dir,
                        decision_id=str(did) if did else None,
                        symbol=symbol,
                        action="buy",
                        entry_price=fill_px,
                        entry_ist=day,
                        laboratory_id=portfolio_key or "india_equity_learner",
                        portfolio_key=portfolio_key or "india_equity_learner",
                        program_id=str(
                            cfg.get("program_id") or "market_intelligence"
                        ),
                    )
                except Exception:  # noqa: BLE001
                    self._logger.debug("CF.1 schedule skipped", exc_info=True)
            # BRE.3 — enqueue async decide-time rationale (never calls LLM here)
            if (
                str(action or "").lower() in {"buy", "sell"}
                and data_dir
                and saved
                and not saved.get("skipped")
            ):
                try:
                    packet = (saved or {}).get("packet") or {}
                    did = packet.get("decision_id") or packet.get("id")
                    from atlas.investment.decide_rationale import schedule_decide_rationale

                    schedule_decide_rationale(
                        data_dir,
                        decision_id=str(did) if did else None,
                        symbol=symbol,
                        action=str(action),
                        laboratory_id=portfolio_key or "india_equity_learner",
                        portfolio_key=portfolio_key or "india_equity_learner",
                        packet=packet if isinstance(packet, dict) else None,
                    )
                except Exception:  # noqa: BLE001
                    self._logger.debug("BRE.3 schedule skipped", exc_info=True)
            # OI-LINT0 Phase 3 — queue research-scientist (never LLM on the fill path)
            if saved and not saved.get("skipped"):
                try:
                    from atlas.reasoning.research_scientist import (
                        enqueue_unreviewed,
                        is_scientist_event,
                    )

                    pkt_saved = (saved or {}).get("packet") or {}
                    decomp = {}
                    meta = pkt_saved.get("meta") if isinstance(pkt_saved, dict) else {}
                    if isinstance(meta, dict) and isinstance(meta.get("decision_decomposition"), dict):
                        decomp = meta["decision_decomposition"]
                    if is_scientist_event(
                        action=action,
                        strategy_tag=tag,
                        contradictions=list(decomp.get("contradictions") or []),
                    ):
                        enqueue_unreviewed(
                            data_dir,
                            laboratory_id=portfolio_key or "india_equity_learner",
                            packet={
                                "symbol": symbol,
                                "laboratory": portfolio_key or "india_equity_learner",
                                "action": action,
                                "strategy_tag": tag,
                                "decomposition": decomp,
                                "ts_ist": day,
                                "price": {"mark": price, "fill": fill_price},
                                "fundamentals": fundamentals if isinstance(fundamentals, dict) else {},
                                "expected": expected_doc if isinstance(expected_doc, dict) else {},
                            },
                            reason="pending_event",
                        )
                except Exception:  # noqa: BLE001
                    self._logger.debug("research scientist schedule skipped", exc_info=True)
            return saved
        except Exception:  # noqa: BLE001
            self._logger.debug("DI.1 packet write skipped", exc_info=True)
            return None

    def _zerodha_feed(self):
        try:
            ad = getattr(self._live_market, "_adapters", {}).get("zerodha")
            if ad is None:
                return None
            feed = getattr(ad, "_feed", None)
            if feed is None and hasattr(ad, "_get_feed"):
                feed = ad._get_feed()
            return feed
        except Exception:  # noqa: BLE001
            return None

    def _nfo_ltp(self, tsym: str | None) -> float | None:
        feed = self._zerodha_feed()
        if feed is None or not tsym:
            return None
        try:
            out = feed.get_ltp(str(tsym))
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(out, dict) or not out.get("ok"):
            return None
        prices = out.get("prices") if isinstance(out.get("prices"), dict) else {}
        row = prices.get(str(tsym)) or prices.get(str(tsym).upper())
        last = None
        if isinstance(row, dict):
            last = row.get("last")
        elif prices:
            for val in prices.values():
                if isinstance(val, dict) and val.get("last") is not None:
                    last = val.get("last")
                    break
        try:
            px = float(last)
        except (TypeError, ValueError):
            return None
        return px if px > 0 else None

    def _fno_atm_overlay(
        self,
        *,
        symbol: str,
        price: float,
        held: float,
        snapshot: dict[str, Any],
        indicators: dict[str, Any],
        control_action: str | None = None,
    ) -> dict[str, Any]:
        from atlas.investment.fno_contract import (
            choose_atm_overlay,
            persist_phase2_bundle,
            resolve_phase2_bundle,
            sma_margin as _sma_margin,
        )
        from atlas.investment.fno_lab_v1 import is_eligible_underlier

        try:
            from atlas.config import get_config

            data_dir = str(get_config().paths.data)
        except Exception:  # noqa: BLE001
            data_dir = None
        if not is_eligible_underlier(symbol, data_dir=data_dir):
            return {
                "used": False,
                "fallback_l4": False,
                "reason": "not_in_lab_v1_universe",
            }
        feed = self._zerodha_feed()
        dump: list[dict[str, Any]] = []
        if feed is not None:
            try:
                dump.extend(list(feed.list_nfo_futures() or []))
            except Exception:  # noqa: BLE001
                self._logger.debug("nfo futures list for ATM overlay skipped", exc_info=True)
            try:
                dump.extend(list(feed.list_nfo_options() or []))
            except Exception:  # noqa: BLE001
                self._logger.debug("nfo options list for ATM overlay skipped", exc_info=True)
        bundle = resolve_phase2_bundle(dump, symbol=symbol, spot=price, as_of=self._clock())
        if bundle.get("ok"):
            try:
                if data_dir:
                    persist_phase2_bundle(data_dir, bundle)
            except Exception:  # noqa: BLE001
                self._logger.debug("phase2 ATM persist skipped", exc_info=True)
        ce = bundle.get("ce") if isinstance(bundle.get("ce"), dict) else {}
        pe = bundle.get("pe") if isinstance(bundle.get("pe"), dict) else {}
        fut = bundle.get("fut") if isinstance(bundle.get("fut"), dict) else {}
        ce_ltp = self._nfo_ltp(str(ce.get("tradingsymbol") or "") or None) if ce.get("ok") else None
        pe_ltp = self._nfo_ltp(str(pe.get("tradingsymbol") or "") or None) if pe.get("ok") else None
        fut_ltp = self._nfo_ltp(str(fut.get("tradingsymbol") or "") or None) if fut.get("ok") else None
        overlay = choose_atm_overlay(
            sma_margin=_sma_margin(indicators),
            underlier_held=held,
            positions=list(snapshot.get("positions") or []),
            bundle=bundle,
            cash=float(snapshot.get("cash") or 0),
            ce_ltp=ce_ltp,
            pe_ltp=pe_ltp,
            control_action=control_action,
            underlying_price=price,
            future_price=fut_ltp,
        )
        if overlay.get("used"):
            try:
                from atlas.investment import fno_lab_v1 as lab_v1

                right = str(overlay.get("right") or "")
                overlay["attribution"] = lab_v1.attribution(
                    underlying=symbol,
                    future_contract=fut if fut.get("ok") else None,
                    option_contract=(ce if right == "CE" else pe),
                    entry_ltp=overlay.get("price"),
                    experiment_id=lab_v1.experiment_family_id(symbol, right=right),
                    entry_reason=str(overlay.get("reason") or ""),
                    cognitive_review="UNREVIEWED",
                )
                overlay["experiment_family"] = overlay["attribution"]["experiment_family"]
                # Decide-time E[R] BEFORE fill/outcome — only on option BUY.
                if str(overlay.get("kind") or "").lower() == "buy":
                    pred = lab_v1.build_entry_prediction(
                        underlying=symbol,
                        option_symbol=str(overlay.get("symbol") or ""),
                        right=right,
                        entry_premium=overlay.get("price"),
                        sma_margin=_sma_margin(indicators),
                        control_action=control_action,
                        entry_reason=str(overlay.get("reason") or ""),
                        entry_time=self._clock(),
                    )
                    overlay["entry_prediction"] = pred
                    overlay["expected"] = lab_v1.expected_block_from_prediction(pred)
                    if data_dir:
                        lab_v1.persist_entry_prediction(data_dir, pred)
            except Exception:  # noqa: BLE001
                self._logger.debug("fno lab v1 attribution/prediction skipped", exc_info=True)
        return overlay

    def _run_fno_paper_001(
        self,
        *,
        cfg: dict[str, Any],
        portfolio_id: Any,
        portfolio_key: str,
        mission_id: Any,
        state: dict[str, Any],
        pack: Any,
    ) -> list[str]:
        """FNO-PAPER-001 — controlled paper ATM entry/exit via real apply_trade."""
        from atlas.config import get_config
        from atlas.investment import fno_paper_001 as p001
        from atlas.investment.fno_contract import PHASE2_UNDERLYING
        from atlas.trading.broker_profiles import compute_fees, get_broker_profile

        data_dir = str(get_config().paths.data)
        # Durable experiment doc is the source of truth across ticks — worker
        # checkpoints historically omitted fno_paper_001, so env-arm alone
        # would re-enter every tick after a "complete" that only lived on disk.
        disk = p001.load_experiment(data_dir)
        if isinstance(disk, dict) and disk.get("status"):
            cur = state.get(p001.STATE_KEY)
            if not isinstance(cur, dict) or not cur.get("status"):
                state[p001.STATE_KEY] = dict(disk)
            else:
                # Prefer the more advanced durable status when checkpoint lags.
                rank = {"armed": 0, "entered": 1, "complete": 2, "exited": 2, "failed": 2}
                if rank.get(str(disk.get("status")), -1) >= rank.get(
                    str(cur.get("status")), -1
                ):
                    merged = dict(disk)
                    merged.update({k: v for k, v in cur.items() if v is not None})
                    # Disk terminal status wins over a stale in-memory entered.
                    if str(disk.get("status")) in {"complete", "exited", "failed"}:
                        merged["status"] = disk["status"]
                        if disk.get("exit"):
                            merged["exit"] = disk["exit"]
                        if disk.get("cognitive"):
                            merged["cognitive"] = disk["cognitive"]
                        if disk.get("acceptance"):
                            merged["acceptance"] = disk["acceptance"]
                    state[p001.STATE_KEY] = merged
        if not p001.is_armed(cfg, state, data_dir=data_dir):
            return []

        lines: list[str] = []
        doc = dict(state.get(p001.STATE_KEY) or {})
        doc.setdefault("experiment_id", p001.EXPERIMENT_ID)
        doc.setdefault("version", p001.VERSION)
        doc["live_orders"] = False
        doc["cash_equity_alts"] = False
        doc["armed"] = True
        doc["uses_l4_index_proxy"] = False

        snap = self._portfolio.snapshot(portfolio_id, prices={})
        cash = float(snap.get("cash") or 0)
        positions = list(snap.get("positions") or [])
        exit_same = bool(
            cfg.get("fno_paper_001_exit_same_tick")
            if cfg.get("fno_paper_001_exit_same_tick") is not None
            else True
        )

        # --- EXIT path (open experiment lot) ---------------------------------
        entry = doc.get("entry") if isinstance(doc.get("entry"), dict) else {}
        if str(doc.get("status") or "") == "entered" and entry.get("symbol"):
            tsym = str(entry.get("symbol") or "")
            held = 0.0
            for pos in positions:
                if str(pos.get("symbol") or "").upper() == tsym.upper():
                    held = float(pos.get("quantity") or pos.get("qty") or 0)
                    break
            if held <= 1e-12:
                doc["status"] = "failed"
                doc["fail_reason"] = "entered_but_position_missing"
                state[p001.STATE_KEY] = doc
                p001.persist_experiment(data_dir, doc)
                lines.append(f"{tsym}: FNO-PAPER-001 exit aborted (position missing)")
                return lines
            px = self._nfo_ltp(tsym)
            plan = p001.plan_exit(symbol=tsym, qty=held, option_ltp=px, entry=entry)
            if not plan.get("ok"):
                doc["status"] = "entered"
                doc["last_exit_attempt"] = plan
                state[p001.STATE_KEY] = doc
                p001.persist_experiment(data_dir, {**doc, **plan})
                lines.append(
                    f"{tsym}: FNO-PAPER-001 exit blocked ({plan.get('reason')})"
                )
                return lines
            fee = 0.0
            fees_doc: dict[str, Any] = {}
            profile_id = str(cfg.get("broker_profile") or "").strip() or (
                pack.default_broker_profile() if pack is not None else ""
            )
            try:
                if profile_id:
                    bd = compute_fees(
                        get_broker_profile(profile_id),
                        side="sell",
                        quantity=held,
                        price=float(plan["price"]),
                    )
                    fee = float(bd.total)
                    fees_doc = bd.as_dict()
            except Exception:  # noqa: BLE001
                fee = 0.0
            try:
                trade = self._portfolio.apply_trade(
                    portfolio_id,
                    symbol=tsym,
                    side="sell",
                    quantity=held,
                    price=float(plan["price"]),
                    fee=fee,
                    fees=fees_doc,
                    mission_id=mission_id,
                    decision_id=None,
                    laboratory_id=portfolio_key,
                    instrument_path=p001.INSTRUMENT_PATH,
                )
            except Exception as exc:  # noqa: BLE001
                lines.append(f"{tsym}: FNO-PAPER-001 exit rejected ({exc})")
                doc["last_exit_attempt"] = {"ok": False, "reason": str(exc)}
                state[p001.STATE_KEY] = doc
                return lines
            pnl = float(trade.get("realized_pnl") or 0.0)
            exit_doc = {
                "trade_id": trade.get("id") or trade.get("trade_id"),
                "symbol": tsym,
                "qty": held,
                "price": float(plan["price"]),
                "fee": fee,
                "realized_pnl": pnl,
                "reason": plan.get("reason"),
            }
            doc["exit"] = exit_doc
            doc["status"] = "complete"
            doc["acceptance"] = p001.acceptance_checklist(doc)
            # Optional Cognitive Core pass — UNREVIEWED is honest if LLM silent.
            advice: dict[str, Any] | None = None
            try:
                from atlas.reasoning.cognitive_core import (
                    build_evidence_packet,
                    reason_as_scientist,
                )

                pkt = build_evidence_packet(
                    question=(
                        "Interpret this controlled F&O paper round-trip. "
                        "What provisional lesson about ATM premium vs underlier "
                        "is supported? Do not recommend orders."
                    ),
                    laboratory_id=portfolio_key,
                    symbol=tsym,
                    action="sell",
                    evidence=[
                        f"experiment={p001.EXPERIMENT_ID}",
                        f"entry={entry}",
                        f"exit={exit_doc}",
                        "control=sma_cross_rsi.v1",
                        "live_orders=false",
                    ],
                    known=[
                        "Paper sim fill only",
                        "One controlled sample",
                        "Not a strategy edge claim",
                    ],
                    unknowns=[
                        "Regime / vol path between entry and exit",
                        "Whether premium move generalizes",
                    ],
                    experiences=[
                        {
                            "id": p001.EXPERIMENT_ID,
                            "lesson": p001.provisional_lesson_candidate(doc),
                        }
                    ],
                )
                llm = None
                if self._reasoning is not None:
                    llm = getattr(self._reasoning, "_llm", None)
                if llm is not None:
                    advice = reason_as_scientist(packet=pkt, llm=llm)
            except Exception:  # noqa: BLE001
                advice = None
            cog = p001.build_cognitive_block(doc, advice=advice)
            doc["cognitive"] = cog
            state[p001.STATE_KEY] = doc
            p001.persist_experiment(data_dir, doc)
            lines.append(
                f"{tsym}: FNO-PAPER-001 SELL {held:g} @ {plan['price']:.2f} "
                f"PnL={pnl:+.2f} trade_id={exit_doc.get('trade_id')}"
            )
            try:
                self._record_di_packet(
                    action="sell",
                    symbol=tsym,
                    strategy_tag=p001.STRATEGY_TAG,
                    portfolio_key=portfolio_key,
                    mission_id=mission_id,
                    price=float(plan["price"]),
                    cfg=cfg,
                    qty=held,
                    filled_qty=held,
                    fill_price=float(plan["price"]),
                    fees=fee,
                    fill_trade_id=exit_doc.get("trade_id"),
                    reasons_for=[lines[-1]],
                    plan_link={"fno_paper_001": doc},
                )
            except Exception:  # noqa: BLE001
                pass
            self._notify_fill(
                side="sell",
                symbol=tsym,
                quantity=held,
                price=float(plan["price"]),
                fee=fee,
                fees=fees_doc,
                reason=str(plan.get("reason") or "fno_paper_001_exit"),
                realized_pnl=pnl,
                portfolio_key=portfolio_key,
                mission_id=mission_id,
                trade=trade,
                decision=p001.fill_decision_doc(side="sell", doc=doc, plan=plan),
            )
            if self._investor_mailer is not None:
                try:
                    send_fn = getattr(
                        self._investor_mailer, "send_fno_paper_experience", None
                    )
                    if callable(send_fn):
                        send_fn(doc, advice=advice, laboratory_id=portfolio_key)
                except Exception:  # noqa: BLE001
                    self._logger.debug(
                        "FNO-PAPER-001 experience email failed", exc_info=True
                    )
            return lines

        # --- ENTRY path ------------------------------------------------------
        feed = self._zerodha_feed()
        dump: list[dict[str, Any]] = []
        if feed is not None:
            try:
                dump.extend(list(feed.list_nfo_futures() or []))
            except Exception:  # noqa: BLE001
                pass
            try:
                dump.extend(list(feed.list_nfo_options() or []))
            except Exception:  # noqa: BLE001
                pass
        if not dump:
            doc["status"] = "failed"
            doc["fail_reason"] = "no_nfo_instrument_dump"
            state[p001.STATE_KEY] = doc
            p001.persist_experiment(data_dir, doc)
            lines.append("FNO-PAPER-001 entry blocked (no NFO instrument dump)")
            return lines

        spot = None
        marks = dict(state.get("last_marks") or {})
        if marks.get(PHASE2_UNDERLYING):
            try:
                spot = float(marks[PHASE2_UNDERLYING])
            except (TypeError, ValueError):
                spot = None
        if spot is None or spot <= 0:
            fut_guess = None
            for row in dump:
                if str(row.get("instrument_type") or "").upper() == "FUT" and str(
                    row.get("name") or ""
                ).upper() in {"NIFTY", "NIFTY 50", "NIFTY50"}:
                    fut_guess = str(row.get("tradingsymbol") or "")
                    break
            if fut_guess:
                spot = self._nfo_ltp(fut_guess)
        if spot is None or spot <= 0:
            try:
                if self._live_market is not None and hasattr(self._live_market, "last_price"):
                    spot = float(self._live_market.last_price(PHASE2_UNDERLYING) or 0) or None
            except Exception:  # noqa: BLE001
                spot = None

        from atlas.investment.fno_contract import resolve_phase2_bundle

        pre = resolve_phase2_bundle(
            dump, symbol=PHASE2_UNDERLYING, spot=float(spot or 0), as_of=self._clock()
        )
        ce = pre.get("ce") if isinstance(pre.get("ce"), dict) else {}
        pe = pre.get("pe") if isinstance(pre.get("pe"), dict) else {}
        ce_ts = str(ce.get("tradingsymbol") or "") if ce.get("ok") else ""
        pe_ts = str(pe.get("tradingsymbol") or "") if pe.get("ok") else ""
        ce_ltp = self._nfo_ltp(ce_ts) if ce_ts else None
        pe_ltp = self._nfo_ltp(pe_ts) if pe_ts else None

        plan = p001.plan_entry(
            spot=spot,
            instrument_rows=dump,
            cash=cash,
            ce_ltp=ce_ltp,
            pe_ltp=pe_ltp,
            now=self._clock(),
            right=str(cfg.get("fno_paper_001_right") or "CE"),
            open_positions=positions,
            data_dir=data_dir,
        )
        if not plan.get("ok"):
            doc["status"] = "failed"
            doc["fail_reason"] = plan.get("reason")
            doc["last_entry_attempt"] = plan
            state[p001.STATE_KEY] = doc
            p001.persist_experiment(data_dir, {**doc, **plan})
            lines.append(f"FNO-PAPER-001 entry blocked ({plan.get('reason')})")
            return lines

        tsym = str(plan["symbol"])
        qty = float(plan["qty"])
        px = float(plan["price"])
        fee = 0.0
        fees_doc: dict[str, Any] = {}
        profile_id = str(cfg.get("broker_profile") or "").strip() or (
            pack.default_broker_profile() if pack is not None else ""
        )
        try:
            if profile_id:
                bd = compute_fees(
                    get_broker_profile(profile_id),
                    side="buy",
                    quantity=qty,
                    price=px,
                )
                fee = float(bd.total)
                fees_doc = bd.as_dict()
        except Exception:  # noqa: BLE001
            fee = 0.0
        try:
            trade = self._portfolio.apply_trade(
                portfolio_id,
                symbol=tsym,
                side="buy",
                quantity=qty,
                price=px,
                fee=fee,
                fees=fees_doc,
                mission_id=mission_id,
                decision_id=None,
                laboratory_id=portfolio_key,
                instrument_path=p001.INSTRUMENT_PATH,
            )
        except Exception as exc:  # noqa: BLE001
            lines.append(f"{tsym}: FNO-PAPER-001 entry rejected ({exc})")
            doc["status"] = "failed"
            doc["fail_reason"] = f"fill_rejected:{exc}"
            state[p001.STATE_KEY] = doc
            p001.persist_experiment(data_dir, doc)
            return lines

        entry_doc = {
            "trade_id": trade.get("id") or trade.get("trade_id"),
            "symbol": tsym,
            "qty": qty,
            "price": px,
            "fee": fee,
            "right": plan.get("right"),
            "lot_size": plan.get("lot_size"),
            "atm_strike": plan.get("atm_strike"),
            "expiry": plan.get("expiry"),
            "spot": plan.get("spot"),
            "as_of_ist": plan.get("as_of_ist"),
            "bundle_ok": True,
            "reason": plan.get("reason"),
        }
        doc["entry"] = entry_doc
        doc["status"] = "entered"
        state[p001.STATE_KEY] = doc
        p001.persist_experiment(data_dir, doc)
        lines.append(
            f"{tsym}: FNO-PAPER-001 BUY {qty:g} @ {px:.2f} "
            f"({plan.get('right')} ATM) trade_id={entry_doc.get('trade_id')}"
        )
        try:
            self._record_di_packet(
                action="buy",
                symbol=tsym,
                strategy_tag=p001.STRATEGY_TAG,
                portfolio_key=portfolio_key,
                mission_id=mission_id,
                price=px,
                cfg=cfg,
                qty=qty,
                filled_qty=qty,
                fill_price=px,
                fees=fee,
                fill_trade_id=entry_doc.get("trade_id"),
                reasons_for=[lines[-1]],
                plan_link={"fno_paper_001": doc},
                fno_contract=plan.get("contract"),
            )
        except Exception:  # noqa: BLE001
            pass
        self._notify_fill(
            side="buy",
            symbol=tsym,
            quantity=qty,
            price=px,
            fee=fee,
            fees=fees_doc,
            reason=str(plan.get("reason") or "fno_paper_001_entry"),
            realized_pnl=0.0,
            portfolio_key=portfolio_key,
            mission_id=mission_id,
            trade=trade,
            decision=p001.fill_decision_doc(side="buy", doc=doc, plan=plan),
        )

        if exit_same:
            state[p001.STATE_KEY] = doc
            more = self._run_fno_paper_001(
                cfg={**cfg, "fno_paper_001_exit_same_tick": False},
                portfolio_id=portfolio_id,
                portfolio_key=portfolio_key,
                mission_id=mission_id,
                state=state,
                pack=pack,
            )
            lines.extend(more)
        return lines

    def _ensure_fno_p2_boundary(
        self,
        *,
        portfolio_id: Any,
        portfolio_key: str,
        mission_id: Any,
        cfg: dict[str, Any],
        state: dict[str, Any],
    ) -> list[str]:
        """Stamp FNO-P2-001 once and flatten leftover option inventory as pre-P2."""
        from atlas.config import get_config
        from atlas.investment.fno_contract import (
            load_phase2_experiment,
            option_right,
            stamp_phase2_experiment,
        )

        data_dir = str(get_config().paths.data)
        snap = self._portfolio.snapshot(portfolio_id, prices={})
        stamped = stamp_phase2_experiment(
            data_dir,
            snapshot=snap,
            contract=(cfg.get("_fno_contracts") or {}).get("NIFTY"),
        )
        state["fno_p2"] = {
            "experiment_id": stamped.get("experiment_id"),
            "already_stamped": bool(stamped.get("already_stamped")),
            "initial_n": len(stamped.get("initial_position") or []),
            "path": stamped.get("path"),
        }
        initial = list(
            (load_phase2_experiment(data_dir) or stamped).get("initial_position") or []
        )
        lines: list[str] = []
        if not initial:
            return lines
        live = self._portfolio.snapshot(portfolio_id, prices={})
        held_by = {
            str(p.get("symbol") or "").upper(): p
            for p in (live.get("positions") or [])
            if isinstance(p, dict)
        }
        for row in initial:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").strip()
            if not option_right(sym):
                continue
            pos = held_by.get(sym.upper())
            if not pos:
                continue
            try:
                qty = float(pos.get("quantity") or pos.get("qty") or 0)
            except (TypeError, ValueError):
                qty = 0.0
            if qty <= 1e-12:
                continue
            avg = float(pos.get("avg_price") or row.get("avg_price") or 0)
            px = self._nfo_ltp(sym)
            mark_src = "option_ltp"
            if px is None or px <= 0:
                px = avg if avg > 0 else None
                mark_src = "avg_cost_mark_unavailable"
            if px is None or px <= 0:
                lines.append(f"{sym}: fno_p2_boundary flatten skipped (no mark)")
                continue
            try:
                trade = self._portfolio.apply_trade(
                    portfolio_id,
                    symbol=sym,
                    side="sell",
                    quantity=qty,
                    price=float(px),
                    fee=0.0,
                    fees={},
                    mission_id=mission_id,
                    decision_id=None,
                    laboratory_id=portfolio_key,
                    instrument_path="fno_p2_boundary",
                )
            except Exception as exc:  # noqa: BLE001
                lines.append(f"{sym}: fno_p2_boundary flatten rejected ({exc})")
                continue
            lines.append(
                f"{sym}: fno_p2_boundary flatten {qty:g} @ {px:.2f} ({mark_src})"
            )
            try:
                self._record_di_packet(
                    action="sell",
                    symbol=sym,
                    strategy_tag="fno_p2_boundary",
                    portfolio_key=portfolio_key,
                    mission_id=mission_id,
                    price=float(px),
                    cfg=cfg,
                    qty=qty,
                    filled_qty=qty,
                    fill_price=float(px),
                    fill_trade_id=trade.get("id") or trade.get("trade_id"),
                    reasons_for=[
                        "FNO-P2-001 boundary flatten — leftover is not Phase-2 evidence"
                    ],
                    plan_link={
                        "fno_p2": {
                            "experiment_id": stamped.get("experiment_id"),
                            "mark_source": mark_src,
                            "not_phase2": True,
                        }
                    },
                )
            except Exception:  # noqa: BLE001
                pass
        return lines

    def _flatten_fno_lab_v1_experiments(
        self,
        *,
        cfg: dict[str, Any],
        portfolio_id: Any,
        portfolio_key: str,
        mission_id: Any,
        state: dict[str, Any],
        pack: Any,
    ) -> list[str]:
        """Close open Lab v1 option lots — experiment-scoped, no overnight inventory.

        ENTRY → experiment_close SELL → realized P&L → experience (UNREVIEWED honest
        until Cognitive Core reviews). Idempotent per IST flatten session date when
        already flat; retries while positions remain open.
        """
        from atlas.config import get_config
        from atlas.investment import fno_lab_v1 as lab_v1
        from atlas.trading.broker_profiles import compute_fees, get_broker_profile

        data_dir = str(get_config().paths.data)
        now = self._clock()
        must_flat = lab_v1.must_flatten_experiments(now)
        state["fno_lab_v1_must_flat"] = must_flat
        sess_day = lab_v1.flatten_session_date(now)
        snap = self._portfolio.snapshot(portfolio_id, prices=dict(state.get("last_marks") or {}) or None)
        open_opts = lab_v1.open_option_positions(list(snap.get("positions") or []))
        lines: list[str] = []
        outcomes: list[dict[str, Any]] = list(state.get("fno_lab_v1_flatten_outcomes") or [])

        if not must_flat and not open_opts:
            return lines
        if not must_flat:
            # In-session: leave open experiments to control/overlay exits.
            return lines
        if not open_opts:
            state["fno_lab_v1_flat_ist"] = sess_day
            try:
                if not outcomes:
                    outcomes = lab_v1.load_flatten_outcomes(data_dir, as_of_ist=sess_day)
                    if outcomes:
                        state["fno_lab_v1_flatten_outcomes"] = outcomes[-50:]
                integ = lab_v1.record_experiment_integrity(
                    data_dir,
                    positions=[],
                    must_be_flat=True,
                    flatten_outcomes=outcomes,
                    as_of_ist=sess_day,
                )
                state["fno_lab_v1_integrity"] = {
                    "status": integ.get("status"),
                    "overnight_option_positions": integ.get("overnight_option_positions"),
                    "flatten_closed_n": integ.get("flatten_closed_n"),
                }
            except Exception:  # noqa: BLE001
                pass
            return lines

        profile_id = str(cfg.get("broker_profile") or "").strip() or (
            pack.default_broker_profile() if pack is not None else ""
        )
        for pos in open_opts:
            sym = str(pos.get("symbol") or "").strip()
            if not sym:
                continue
            try:
                qty = float(pos.get("quantity") or pos.get("qty") or 0)
            except (TypeError, ValueError):
                qty = 0.0
            if qty <= 1e-12:
                continue
            avg = float(pos.get("avg_price") or pos.get("avg_cost") or 0)
            px = self._nfo_ltp(sym)
            mark_src = "option_ltp"
            if px is None or px <= 0:
                marks = dict(state.get("last_marks") or {})
                try:
                    px = float(marks.get(sym) or 0) or None
                except (TypeError, ValueError):
                    px = None
                if px and px > 0:
                    mark_src = "last_marks"
            if px is None or px <= 0:
                px = avg if avg > 0 else None
                mark_src = "avg_cost_mark_unavailable"
            if px is None or px <= 0:
                lines.append(f"{sym}: experiment_close blocked (no mark)")
                outcomes.append(
                    {
                        "symbol": sym,
                        "qty": qty,
                        "price": None,
                        "status": "blocked_no_mark",
                        "session_date": sess_day,
                        "reason": lab_v1.REASON_EXPERIMENT_CLOSE,
                    }
                )
                continue
            fee = 0.0
            fees_doc: dict[str, Any] = {}
            try:
                if profile_id:
                    bd = compute_fees(
                        get_broker_profile(profile_id),
                        side="sell",
                        quantity=qty,
                        price=float(px),
                    )
                    fee = float(bd.total)
                    fees_doc = bd.as_dict()
            except Exception:  # noqa: BLE001
                fee = 0.0
            try:
                trade = self._portfolio.apply_trade(
                    portfolio_id,
                    symbol=sym,
                    side="sell",
                    quantity=qty,
                    price=float(px),
                    fee=fee,
                    fees=fees_doc,
                    mission_id=mission_id,
                    decision_id=None,
                    laboratory_id=portfolio_key,
                    instrument_path=lab_v1.REASON_EXPERIMENT_CLOSE,
                )
            except Exception as exc:  # noqa: BLE001
                lines.append(f"{sym}: experiment_close rejected ({exc})")
                outcomes.append(
                    {
                        "symbol": sym,
                        "qty": qty,
                        "price": float(px),
                        "status": "blocked_reject",
                        "error": str(exc),
                        "session_date": sess_day,
                        "reason": lab_v1.REASON_EXPERIMENT_CLOSE,
                    }
                )
                continue
            realized = float(trade.get("realized_pnl") or 0.0)
            trade_id = trade.get("id") or trade.get("trade_id")
            und = lab_v1.underlying_from_option_tsym(sym)
            right = None
            try:
                from atlas.investment.fno_contract import option_right as _or

                right = _or(sym)
            except Exception:  # noqa: BLE001
                right = None
            att = lab_v1.attribution(
                underlying=und,
                option_contract={
                    "tradingsymbol": sym,
                    "instrument_type": right,
                    "lot_size": qty,
                },
                entry_ltp=avg if avg > 0 else None,
                exit_ltp=float(px),
                experiment_id=lab_v1.experiment_family_id(und, right=right),
                trade_id=str(trade_id) if trade_id else None,
                entry_reason="lab_v1_open_experiment",
                exit_reason=lab_v1.REASON_EXPERIMENT_CLOSE,
                cognitive_review="UNREVIEWED",
                learning_status="PROVISIONAL — experiment closed pending Core review",
            )
            att["mark_source"] = mark_src
            att["realized_pnl"] = realized
            # Observable F&O evidence BEFORE Core — Core interprets, never invents.
            fno_evidence: dict[str, Any] | None = None
            fno_causal: dict[str, Any] | None = None
            try:
                from atlas.investment.fno_option_attribution import (
                    build_fno_rt_evidence,
                    evaluate_fno_causal_factors,
                    evidence_lines_for_core,
                )

                entry_pred = None
                try:
                    pred_doc = lab_v1.load_entry_prediction(
                        data_dir, option_symbol=sym
                    )
                    if isinstance(pred_doc, dict):
                        entry_pred = pred_doc
                except Exception:  # noqa: BLE001
                    entry_pred = None
                fno_evidence = build_fno_rt_evidence(
                    underlying=und,
                    option_symbol=sym,
                    option_right=right,
                    entry_premium=float(avg) if avg and avg > 0 else None,
                    exit_premium=float(px),
                    entry_time=(entry_pred or {}).get("entry_time")
                    or (entry_pred or {}).get("recorded_at"),
                    exit_time=None,
                    realized_pnl=realized,
                    prediction_error=None,
                    data_dir=data_dir,
                    as_of_ist=sess_day,
                    mark_source=mark_src,
                )
                fno_causal = evaluate_fno_causal_factors(fno_evidence)
                att["fno_rt_evidence"] = fno_evidence
                att["causal_factors"] = fno_causal
                att["attribution_status"] = fno_causal.get("status")
            except Exception:  # noqa: BLE001
                fno_evidence = None
                fno_causal = None
            # Cognitive Core — honest UNREVIEWED if LLM silent / busy / fails.
            advice: dict[str, Any] | None = None
            try:
                from atlas.reasoning.cognitive_core import (
                    build_evidence_packet,
                    reason_as_scientist,
                )

                evidence_rows = [
                    f"experiment_family={att.get('experiment_family')}",
                    f"underlying={und}",
                    f"option={sym}",
                    f"entry_ltp={avg}",
                    f"exit_ltp={float(px)}",
                    f"mark_source={mark_src}",
                    f"realized_pnl={realized}",
                    f"exit_reason={lab_v1.REASON_EXPERIMENT_CLOSE}",
                ]
                unknowns = [
                    "IV change (not in durable store)",
                    "Option delta/gamma at entry/exit",
                    "Whether ATM premium move generalizes",
                ]
                if fno_evidence:
                    try:
                        evidence_rows = evidence_lines_for_core(fno_evidence)
                    except Exception:  # noqa: BLE001
                        pass
                    if fno_causal:
                        evidence_rows.append(
                            f"pre_core_attribution_status={fno_causal.get('status')}"
                        )
                        evidence_rows.append(
                            f"pre_core_narrative={fno_causal.get('narrative')}"
                        )
                else:
                    unknowns.insert(
                        0, "Decide-time E[R] / underlier session bar may be absent"
                    )

                pkt = build_evidence_packet(
                    question=(
                        "Interpret this F&O Lab v1 session_flat paper close using "
                        "ONLY the listed observable evidence. State which causes are "
                        "supported vs still unknown. Do not invent IV, delta, news, "
                        "or sector moves. Do not recommend orders. "
                        "Not a validated lesson."
                    ),
                    laboratory_id=portfolio_key,
                    symbol=sym,
                    action="sell",
                    evidence=evidence_rows,
                    known=[
                        "Paper sim fill only",
                        "Experiment-scoped session_flat exit",
                        "live_orders=false",
                        "Single controlled sample is not L5",
                    ],
                    unknowns=unknowns,
                    experiences=[
                        {
                            "id": att.get("experiment_family"),
                            "lesson": lab_v1.provisional_lesson_candidate(att),
                        }
                    ],
                )
                llm = None
                if self._reasoning is not None:
                    llm = getattr(self._reasoning, "_llm", None)
                if llm is not None:
                    advice = reason_as_scientist(packet=pkt, llm=llm)
            except Exception:  # noqa: BLE001
                advice = None
            att = lab_v1.apply_cognitive_to_attribution(att, advice=advice)
            if fno_evidence and "fno_rt_evidence" not in att:
                att["fno_rt_evidence"] = fno_evidence
            if fno_causal and "causal_factors" not in att:
                att["causal_factors"] = fno_causal
            cog = att.get("cognitive") if isinstance(att.get("cognitive"), dict) else {}
            lines.append(
                f"{sym}: experiment_close SELL {qty:g} @ {float(px):.2f} "
                f"PnL={realized:+.2f} ({mark_src}) family={att.get('experiment_family')} "
                f"review={att.get('cognitive_review')} "
                f"attr={att.get('attribution_status') or (fno_causal or {}).get('status')}"
            )
            outcomes.append(
                {
                    "symbol": sym,
                    "qty": qty,
                    "price": float(px),
                    "realized_pnl": realized,
                    "trade_id": trade_id,
                    "status": "closed",
                    "session_date": sess_day,
                    "reason": lab_v1.REASON_EXPERIMENT_CLOSE,
                    "mark_source": mark_src,
                    "attribution": att,
                    "cognitive_review": att.get("cognitive_review"),
                }
            )
            try:
                self._record_di_packet(
                    action="sell",
                    symbol=sym,
                    strategy_tag=lab_v1.REASON_EXPERIMENT_CLOSE,
                    portfolio_key=portfolio_key,
                    mission_id=mission_id,
                    price=float(px),
                    cfg=cfg,
                    qty=qty,
                    filled_qty=qty,
                    fill_price=float(px),
                    fees=fee,
                    fill_trade_id=trade_id,
                    reasons_for=[
                        "F&O Lab v1 experiment-scoped exit — no overnight option inventory"
                    ],
                    plan_link={"fno_lab_v1": att},
                )
            except Exception:  # noqa: BLE001
                pass
            try:
                from types import SimpleNamespace

                self._notify_fill(
                    side="sell",
                    symbol=sym,
                    quantity=qty,
                    price=float(px),
                    fee=fee,
                    fees=fees_doc,
                    reason=lab_v1.REASON_EXPERIMENT_CLOSE,
                    realized_pnl=realized,
                    portfolio_key=portfolio_key,
                    mission_id=mission_id,
                    trade=trade,
                    decision=SimpleNamespace(
                        action="sell",
                        kind="sell",
                        rationale="session_flat experiment close",
                        why="session_flat experiment close",
                        status=lab_v1.REASON_EXPERIMENT_CLOSE,
                        confidence="medium",
                        cognitive_review=att.get("cognitive_review") or "UNREVIEWED",
                        experiment_family=att.get("experiment_family"),
                        lab_role=lab_v1.LAB_ROLE,
                        attribution=att,
                    ),
                )
            except Exception:  # noqa: BLE001
                self._logger.debug("FNO-LAB-v1 close email failed", exc_info=True)
            try:
                learn_cfg = dict(cfg)
                learn_cfg["strategy_tag"] = lab_v1.REASON_EXPERIMENT_CLOSE
                learn_cfg["portfolio_key"] = portfolio_key
                # Consume decide-time prediction if present (else honest prediction_absent).
                entry_pred = None
                try:
                    entry_pred = lab_v1.load_entry_prediction(data_dir, option_symbol=sym)
                    if not entry_pred:
                        open_preds = dict(state.get("fno_lab_v1_open_predictions") or {})
                        entry_pred = open_preds.get(sym.upper())
                except Exception:  # noqa: BLE001
                    entry_pred = None
                expected = lab_v1.expected_block_from_prediction(entry_pred)
                # Observed direction from realized premium return (percent space).
                try:
                    cost = abs(float(avg) * float(qty)) if avg and qty else None
                    realized_pct = (
                        (100.0 * float(realized) / cost) if cost and cost > 1e-12 else None
                    )
                except (TypeError, ValueError):
                    realized_pct = None
                obs_dir = None
                if realized_pct is not None:
                    if realized_pct > 1e-9:
                        obs_dir = "up"
                    elif realized_pct < -1e-9:
                        obs_dir = "down"
                    else:
                        obs_dir = "flat"
                learn_cfg["_learning_packet"] = {
                    "fno_lab_v1": att,
                    "cognitive": cog,
                    "exit_reason": lab_v1.REASON_EXPERIMENT_CLOSE,
                    "mark_source": mark_src,
                    "strategy_tag": lab_v1.REASON_EXPERIMENT_CLOSE,
                    "action": "sell",
                    "expected": expected,
                    "entry_prediction": entry_pred,
                    "outcome_check": {
                        "expected_direction": expected.get("expected_direction"),
                        "observed_direction": obs_dir,
                        "realized_return_pct": realized_pct,
                    },
                }
                self._remember_outcome(
                    sym,
                    trade,
                    SimpleNamespace(
                        id=None,
                        action="sell",
                        kind="sell",
                        symbol=sym,
                        rationale="F&O Lab v1 experiment-scoped session_flat exit",
                        why="F&O Lab v1 experiment-scoped session_flat exit",
                        confidence="medium",
                        status=lab_v1.REASON_EXPERIMENT_CLOSE,
                        cognitive_review=att.get("cognitive_review") or "UNREVIEWED",
                        reasons_for=[
                            "F&O Lab v1 experiment-scoped session_flat exit"
                        ],
                        reasons_against=[],
                    ),
                    indicators={},
                    cfg=learn_cfg,
                )
            except Exception:  # noqa: BLE001
                self._logger.debug("FNO-LAB-v1 experience skipped", exc_info=True)

        state["fno_lab_v1_flatten_outcomes"] = outcomes[-50:]
        # Re-check book
        snap2 = self._portfolio.snapshot(portfolio_id, prices={})
        still = lab_v1.open_option_positions(list(snap2.get("positions") or []))
        if not still:
            state["fno_lab_v1_flat_ist"] = sess_day
        try:
            integ = lab_v1.record_experiment_integrity(
                data_dir,
                positions=list(snap2.get("positions") or []),
                must_be_flat=True,
                flatten_outcomes=outcomes,
                as_of_ist=sess_day,
            )
            state["fno_lab_v1_integrity"] = {
                "status": integ.get("status"),
                "overnight_option_positions": integ.get("overnight_option_positions"),
                "path": integ.get("path"),
            }
        except Exception:  # noqa: BLE001
            pass
        return lines

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
        er_src = dict(inst_row)
        er_src["symbol"] = symbol
        if len(closes) >= 21 and closes[-21]:
            er_src.setdefault("pct_move", closes[-1] / closes[-21] - 1.0)
        elif len(closes) >= 2 and closes[0]:
            er_src.setdefault("pct_move", closes[-1] / closes[0] - 1.0)

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

        lesson_refs_for_engine: list[dict[str, Any]] = []
        try:
            from atlas.investment.experience_integrity import ist_day as _ist_day_fn

            _bc_decide = self._belief_context_for_packet(
                action="buy" if held <= 0 else "hold",
                symbol=symbol,
                strategy_tag=str(
                    strategy.get("strategy_tag") or cfg.get("strategy_tag") or "sma_cross_rsi"
                ),
                portfolio_key=portfolio_key or "india_equity_learner",
                thesis_trigger=None,
                plan_link=None,
                expected_doc=None,
                research_gate=None,
                portfolio_gate=None,
                indicators=indicators,
                fundamentals=None,
                sector=str(inst_row.get("sector") or "") or None,
                ist_day=_ist_day_fn(),
            )
            lesson_refs_for_engine = list(_bc_decide.get("lesson_refs") or [])
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("lesson consult skipped: %s", exc)

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
                "lesson_refs": lesson_refs_for_engine,
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
        # PLC.A — set after gate; must exist before _pkt closure is invoked
        thesis_trigger_for_packet: str | None = None
        research_gate_result: dict[str, Any] | None = None
        portfolio_gate_result: dict[str, Any] | None = None
        plc_a_result: dict[str, Any] | None = None

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
            extra_reasons: list[str] | None = None,
            gate: dict[str, Any] | None = None,
        ) -> None:
            reasons: list[str] = []
            if action == "buy" and thesis_trigger_for_packet:
                reasons.append(f"thesis: {thesis_trigger_for_packet}")
            if action == "sell" and exit_reason_code:
                reasons.append(f"exit:{exit_reason_code}")
            if why_short:
                reasons.append(why_short)
            reasons.append(line)
            for er in extra_reasons or []:
                if er and er not in reasons:
                    reasons.append(er)
            expected_doc = None
            try:
                # Lab v1 option BUY: use decide-time prediction (not equity prototype ER).
                if (
                    option_overlay
                    and option_overlay.get("used")
                    and action == "buy"
                    and isinstance(option_overlay.get("expected"), dict)
                ):
                    expected_doc = dict(option_overlay["expected"])
                else:
                    from atlas.investment.expected_return_prototype import (
                        compute_prototype_er,
                        expected_block_from_metrics,
                    )

                    expected_doc = expected_block_from_metrics(compute_prototype_er(er_src))
            except Exception:  # noqa: BLE001
                expected_doc = None
            plan_link = None
            if option_overlay and option_overlay.get("used"):
                plan_link = {
                    "fno_lab_v1": option_overlay.get("attribution"),
                    "entry_prediction": option_overlay.get("entry_prediction"),
                }
            self._record_di_packet(
                action=action,
                symbol=symbol,
                strategy_tag=strategy_tag,
                portfolio_key=portfolio_key,
                mission_id=mission_id,
                price=price,
                cfg=cfg,
                indicators=indicators,
                reasons_for=reasons,
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
                thesis_trigger=thesis_trigger_for_packet if action == "buy" else None,
                expected=expected_doc,
                plan_link=plan_link,
                position_qty=held,
                fno_contract=(inst_row or {}).get("fno_contract"),
                lesson_refs=lesson_refs_for_engine,
                experience_refs=list(getattr(decision, "experience_refs", None) or []),
            )
            if action == "hold" and str(kind or "") == "buy":
                self._record_blocked_buy_experience(
                    symbol=symbol,
                    portfolio_key=portfolio_key,
                    strategy_tag=strategy_tag,
                    line=line,
                    cfg=cfg,
                    indicators=indicators,
                    instrument=inst_row,
                    gate=gate or rg or pg or plc_a_result,
                    price=price,
                    against=against,
                    decision_id=getattr(decision, "id", None),
                )

        # PLC.B — evaluate richer exits while holding (SMA remains a separate lane)
        exit_reason_code: str | None = None
        plc_b_prop: dict[str, Any] | None = None
        if held > 0:
            try:
                from atlas.investment.plc_exits import evaluate_plc_b_exits, plc_b_enabled

                if plc_b_enabled(cfg, portfolio_key):
                    fund_row = None
                    aw_row = None
                    try:
                        from atlas.config import get_config
                        from atlas.investment.fundamentals import get_symbol as fund_get

                        fund_row = fund_get(
                            str(get_config().paths.data),
                            symbol,
                            program_id=str(
                                cfg.get("program_id") or "market_intelligence"
                            ),
                        )
                    except Exception:  # noqa: BLE001
                        fund_row = None
                    if self._investment_research is not None:
                        try:
                            aw_row = self._investment_research.awareness(
                                symbol,
                                program_id=str(
                                    cfg.get("program_id") or "market_intelligence"
                                ),
                            )
                        except Exception:  # noqa: BLE001
                            aw_row = None
                    entry_ist = (
                        str(position.get("opened_at") or position.get("entry_ist") or "")
                        [:10]
                        or None
                    )
                    if not entry_ist:
                        entry_ist = (state.get("entry_ist") or {}).get(symbol)
                    plc_b_prop = evaluate_plc_b_exits(
                        symbol=symbol,
                        price=price,
                        held=held,
                        avg_price=float(position.get("avg_price") or 0) or None,
                        peak_price=_f_peak(state, symbol, price),
                        equity=float(snapshot.get("equity") or 0) or None,
                        entry_ist=entry_ist,
                        fundamentals=fund_row if isinstance(fund_row, dict) else None,
                        awareness=aw_row if isinstance(aw_row, dict) else None,
                        cfg=cfg,
                    )
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("PLC.B exit eval skipped: %s", exc)
                plc_b_prop = None

        def _force_plc_b_sell() -> tuple[str, float, str]:
            assert plc_b_prop is not None
            code = str(plc_b_prop.get("exit_code") or "stop_loss")
            q = float(plc_b_prop.get("quantity") or held)
            rationale = str(plc_b_prop.get("rationale") or code)
            return code, q, rationale

        kind: str | None = None
        qty = 0.0
        index_proxy_tag: str | None = None
        option_overlay: dict[str, Any] | None = None
        fno_lab = False
        try:
            from atlas.investment.index_proxy_lot import is_fno_lab as _is_fno_lab

            fno_lab = _is_fno_lab(cfg, portfolio_key)
        except Exception:  # noqa: BLE001
            fno_lab = False

        if decision.action_kind != ACTION_RECOMMEND:
            if plc_b_prop:
                exit_reason_code, qty, why = _force_plc_b_sell()
                why_short = (why[:80] + "…") if len(why) > 80 else why
                kind = "sell"
            elif decision.action_kind == "capability_gap":
                totals["gaps"] += 1
                line = f"{symbol}: gap ({why_short or 'missing capability'})"
                _pkt("hold", strategy_tag="capability_gap", line=line)
                return line
            else:
                kind = None
                qty = 0.0
        else:
            # The engine wraps the chosen option under action["payload"].
            payload = (decision.action or {}).get("payload") or {}
            kind = payload.get("kind")
            qty = float(payload.get("quantity") or 0.0)
            if kind == "sell":
                exit_reason_code = "sma_crossunder"
            if plc_b_prop and (
                kind != "sell"
                or int(plc_b_prop.get("priority") or 0)
                > 50  # beat SMA when risk/thesis exits fire
            ):
                exit_reason_code, qty, why = _force_plc_b_sell()
                why_short = (why[:80] + "…") if len(why) > 80 else why
                kind = "sell"
            if kind not in ("buy", "sell") or qty <= 0:
                kind = None
                qty = 0.0

        # LOOP0 L4 / Phase-2 ATM CE-PE — SMA/RSI V1 is the control; adapter picks ATM CE/PE.
        if fno_lab:
            # Lab v1 session_flat: do not open new option experiments while flatten is due.
            try:
                from atlas.investment.fno_lab_v1 import must_flatten_experiments

                if must_flatten_experiments(self._clock()) and kind == "buy":
                    return (
                        f"{symbol}: fno_lab_v1_no_new_entry (session_flat — "
                        "close open experiments first)"
                    )
            except Exception:  # noqa: BLE001
                pass
            try:
                option_overlay = self._fno_atm_overlay(
                    symbol=symbol,
                    price=price,
                    held=held,
                    snapshot=snapshot,
                    indicators=indicators,
                    control_action=kind or "hold",
                )
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("F&O ATM overlay skipped: %s", exc)
                option_overlay = None
            if option_overlay and option_overlay.get("used"):
                from atlas.investment.packs.derivatives import OptionsPack

                kind = str(option_overlay.get("kind") or "")
                qty = float(option_overlay.get("qty") or 0.0)
                symbol = str(option_overlay.get("symbol") or symbol)
                price = float(option_overlay.get("price") or price)
                marks[symbol] = price
                held = float(option_overlay.get("held") if option_overlay.get("held") is not None else held)
                index_proxy_tag = None
                why_short = str(option_overlay.get("reason") or why_short)
                if option_overlay.get("exit_code"):
                    exit_reason_code = str(option_overlay.get("exit_code"))
                inst_row = dict(inst_row or {})
                if option_overlay.get("lot_size"):
                    inst_row["lot_size"] = option_overlay["lot_size"]
                if option_overlay.get("expiry"):
                    inst_row["expiry"] = option_overlay["expiry"]
                inst_row["asset_class"] = "options"
                if isinstance(option_overlay.get("bundle"), dict):
                    inst_row["fno_contract"] = dict(option_overlay["bundle"])
                    inst_row["fno_contract"]["adapter_id"] = option_overlay.get("adapter_id")
                    inst_row["fno_contract"]["control_action"] = option_overlay.get("control_action")
                    if isinstance(option_overlay.get("marks"), dict):
                        inst_row["fno_contract"]["option_marks"] = option_overlay["marks"]
                if isinstance(option_overlay.get("marks"), dict):
                    inst_row["option_marks"] = option_overlay["marks"]
                    inst_row["nfo_tradingsymbol"] = option_overlay.get("symbol")
                pack = OptionsPack()
                try:
                    snapshot = self._portfolio.snapshot(
                        portfolio_id, prices={**dict(marks), symbol: price}
                    )
                except Exception:  # noqa: BLE001
                    pass
            elif option_overlay and not option_overlay.get("fallback_l4"):
                kind = None
                qty = 0.0
            else:
                try:
                    from atlas.investment.index_proxy_lot import (
                        STRATEGY_TAG as INDEX_PROXY_TAG,
                        is_nifty_underlier,
                        size_one_lot,
                        underlier_family,
                    )

                    if underlier_family(symbol) is not None:
                        sized = size_one_lot(
                            symbol=symbol,
                            price=price,
                            cash=float(snapshot.get("cash") or 0),
                            held=held,
                            instrument=inst_row,
                            cfg=cfg,
                        )
                        if kind == "buy":
                            if sized.get("ok"):
                                qty = float(sized["qty"])
                                kind = "buy"
                                index_proxy_tag = INDEX_PROXY_TAG
                                why_short = (
                                    "L4 index-proxy laboratory lot "
                                    "(daily underlier; not live futures)"
                                )
                            elif str(sized.get("reason") or "").startswith("already_open"):
                                kind = None
                                qty = 0.0
                            else:
                                totals["holds"] += 1
                                line = f"{symbol}: margin ({sized.get('reason')})"
                                _pkt(
                                    "hold",
                                    strategy_tag="margin",
                                    line=line,
                                    against=[str(sized.get("reason") or "margin")],
                                )
                                return line
                        elif is_nifty_underlier(symbol) and held <= 0:
                            if sized.get("ok"):
                                qty = float(sized["qty"])
                                kind = "buy"
                                index_proxy_tag = INDEX_PROXY_TAG
                                why_short = (
                                    "L4 index-proxy laboratory lot "
                                    "(daily underlier; not live futures)"
                                )
                            else:
                                totals["holds"] += 1
                                line = f"{symbol}: margin ({sized.get('reason')})"
                                _pkt(
                                    "hold",
                                    strategy_tag="margin",
                                    line=line,
                                    against=[str(sized.get("reason") or "margin")],
                                )
                                return line
                except Exception as exc:  # noqa: BLE001
                    self._logger.debug("L4 index-proxy overlay skipped: %s", exc)

        if kind == "buy":
            try:
                from atlas.investment.wash_lock import (
                    applies_to_lab as _wash_lab,
                    reentry_blocked,
                )

                if _wash_lab(portfolio_key, cfg=cfg):
                    re_in = reentry_blocked(state, symbol, now=self._clock())
                    if re_in.get("blocked"):
                        totals["holds"] += 1
                        line = f"{symbol}: {re_in.get('reason_code')} ({re_in.get('honesty')})"
                        _pkt(
                            "hold",
                            strategy_tag=str(re_in.get("reason_code") or "same_day_reentry_blocked"),
                            line=line,
                            against=[str(re_in.get("honesty") or "same_day_reentry_blocked")],
                        )
                        self._notify_blocked_buy(
                            symbol=symbol,
                            reason=str(
                                re_in.get("email_subject_reason")
                                or re_in.get("honesty")
                                or "same_day_reentry_blocked"
                            ),
                            portfolio_key=portfolio_key,
                            detail=str(re_in.get("honesty") or ""),
                            prior_sale=str(re_in.get("prior_sale") or ""),
                        )
                        return line
            except Exception:  # noqa: BLE001
                self._logger.debug("wash lock reentry skipped", exc_info=True)
            try:
                from atlas.investment.lab_contracts import (
                    decompose_decision,
                    is_instrument_permitted,
                    reject_message,
                    thesis_stance_from_awareness,
                )

                inst_v = is_instrument_permitted(
                    portfolio_key,
                    symbol,
                    cfg=cfg,
                    instrument=inst_row,
                    path="buy",
                )
                if not inst_v.allowed:
                    totals["holds"] += 1
                    line = reject_message(inst_v)
                    try:
                        from atlas.activity import record_activity

                        record_activity(
                            domain="market",
                            worker="paper_trading",
                            action="lab_instrument_rejected",
                            target=symbol,
                            result="skipped",
                            summary=line,
                            evidence={
                                "path": "buy",
                                "laboratory_id": portfolio_key,
                            },
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    _pkt(
                        "hold",
                        strategy_tag="lab_instrument_rejected",
                        line=line,
                        against=[line],
                    )
                    return line
                if state.get("intraday_must_be_flat"):
                    totals["holds"] += 1
                    line = f"{symbol}: eod_flatten (no new intraday buys after 15:20 IST)"
                    _pkt(
                        "hold",
                        strategy_tag="eod_flatten",
                        line=line,
                        against=[line],
                    )
                    return line
                aw_row = None
                if self._investment_research is not None:
                    try:
                        aw_row = self._investment_research.awareness(
                            symbol,
                            program_id=str(
                                cfg.get("program_id") or "market_intelligence"
                            ),
                        )
                    except Exception:  # noqa: BLE001
                        aw_row = None
                decomp = decompose_decision(
                    laboratory_id=portfolio_key,
                    symbol=symbol,
                    action="buy",
                    cfg=cfg,
                    awareness=aw_row if isinstance(aw_row, dict) else None,
                    held=held,
                    path="buy",
                    instrument=inst_row,
                )
                if str(decomp.get("final_decision") or "") != "BUY":
                    totals["holds"] += 1
                    stance = decomp.get("fundamental_thesis") or thesis_stance_from_awareness(
                        aw_row if isinstance(aw_row, dict) else None
                    )
                    line = (
                        f"{symbol}: lab_policy_hold "
                        f"(technical=BUY thesis={stance} "
                        f"policy={decomp.get('lab_policy')})"
                    )
                    _pkt(
                        "hold",
                        strategy_tag="lab_policy_hold",
                        line=line,
                        against=list(decomp.get("contradictions") or [line]),
                        gate=decomp if isinstance(decomp, dict) else None,
                    )
                    return line
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("lab contract buy gate skipped: %s", exc)

        # OI-ICR0 — technical BUY ≠ capital permission (swing ADD / AVOID / quarantine).
        if kind == "buy" and not fno_lab:
            try:
                from atlas.investment.incumbent_capital import (
                    evaluate_icr0_buy,
                    icr0_enabled,
                )

                if icr0_enabled(cfg, portfolio_key):
                    aw_icr = None
                    if self._investment_research is not None:
                        try:
                            aw_icr = self._investment_research.awareness(
                                symbol,
                                program_id=str(
                                    cfg.get("program_id") or "market_intelligence"
                                ),
                            )
                        except Exception:  # noqa: BLE001
                            aw_icr = None
                    data_dir = None
                    try:
                        from atlas.config import get_config

                        data_dir = str(get_config().paths.data)
                    except Exception:  # noqa: BLE001
                        data_dir = None
                    seen_raw = state.get("icr0_add_state_hashes")
                    if isinstance(seen_raw, list):
                        seen_hashes: set[str] | None = set(str(x) for x in seen_raw)
                    elif isinstance(seen_raw, set):
                        seen_hashes = seen_raw
                    else:
                        seen_hashes = set()
                        state["icr0_add_state_hashes"] = seen_hashes
                    icr = evaluate_icr0_buy(
                        laboratory_id=str(portfolio_key or ""),
                        symbol=symbol,
                        held=float(held or 0),
                        awareness=aw_icr if isinstance(aw_icr, dict) else None,
                        cfg=cfg,
                        data_dir=data_dir,
                        seen_state_hashes=seen_hashes,
                    )
                    if not icr.get("allowed", True):
                        totals["holds"] += 1
                        code = str(icr.get("reason_code") or "add_blocked_icr0")
                        line = str(icr.get("line") or f"{symbol}: {code}")
                        _pkt(
                            "hold",
                            strategy_tag=code,
                            line=line,
                            against=[code],
                            gate=icr if isinstance(icr, dict) else None,
                        )
                        return line
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("ICR.0 buy gate skipped: %s", exc)

        if kind not in ("buy", "sell") or qty <= 0:
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
                        gate=verdict if isinstance(verdict, dict) else None,
                    )
                    return line
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("policy_engine evaluate skipped: %s", exc)

        # IRA — research-based buy gate (learner books default on).
        # FNO index-proxy lots skip cash MVR/thesis (NIFTY is not a stock).
        if kind == "buy" and not fno_lab and self._investment_research is not None:
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
                    gate={"note": gate_note},
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

        # PLC.A — fundamental sanity + explicit thesis trigger (learner default on)
        if kind == "buy":
            try:
                from atlas.investment.plc_buy_gates import (
                    evaluate_plc_a_buy,
                    plc_a_enabled,
                )

                if plc_a_enabled(cfg, portfolio_key):
                    fund_row = None
                    aw_row = None
                    try:
                        from atlas.config import get_config
                        from atlas.investment.fundamentals import get_symbol as fund_get

                        fund_row = fund_get(
                            str(get_config().paths.data),
                            symbol,
                            program_id=str(
                                cfg.get("program_id") or "market_intelligence"
                            ),
                        )
                    except Exception:  # noqa: BLE001
                        fund_row = None
                    if self._investment_research is not None:
                        try:
                            aw_row = self._investment_research.awareness(
                                symbol,
                                program_id=str(
                                    cfg.get("program_id") or "market_intelligence"
                                ),
                            )
                        except Exception:  # noqa: BLE001
                            aw_row = None
                    plc_a_result = evaluate_plc_a_buy(
                        fundamentals=fund_row if isinstance(fund_row, dict) else None,
                        awareness=aw_row if isinstance(aw_row, dict) else None,
                        instrument_sector=sector,
                        engine_why=why,
                        require_fundamentals=bool(
                            cfg.get("plc_a_require_fundamentals", True)
                        ),
                        require_thesis_trigger=bool(
                            cfg.get("plc_a_require_thesis_trigger", True)
                        ),
                        symbol=symbol,
                    )
                    if not plc_a_result.get("allowed"):
                        blocks = ",".join(plc_a_result.get("blocks") or []) or "plc_a"
                        note = f"{symbol}: plc_a_hold ({blocks})"
                        totals["holds"] += 1
                        _pkt(
                            "hold",
                            strategy_tag=str(
                                plc_a_result.get("strategy_tag") or "plc_a_hold"
                            ),
                            line=note,
                            against=list(plc_a_result.get("blocks") or [note]),
                            rg=research_gate_result,
                            gate=plc_a_result,
                        )
                        return note
                    thesis_trigger_for_packet = plc_a_result.get("thesis_trigger")
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("PLC.A buy gate skipped: %s", exc)

        # IIP.7 — portfolio optimizer pre-trade gate (buys)
        # FNO uses margin (pack), not cash-equity concentration 0%.
        if kind == "buy" and not fno_lab and cfg.get("portfolio_gate", True):
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
                    "max_name_pct": cfg.get("max_name_pct"),
                    "max_exposure_pct": cfg.get("max_exposure_pct"),
                    "sector_cap_pct": cfg.get("sector_cap_pct"),
                    "min_cash_pct": cfg.get("min_cash_pct"),
                    "min_investment_confidence": cfg.get("min_investment_confidence") or "low",
                    "mos_pct": mos_pct,
                }
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
            _pkt(
                "hold",
                strategy_tag="pack_block",
                line=line,
                against=[str(validation.reason)],
                gate={"reason": str(validation.reason)},
            )
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
                laboratory_id=portfolio_key,
                instrument_path="buy",
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
        try:
            from atlas.investment.wash_lock import applies_to_lab as _wash_lab
            from atlas.investment.wash_lock import record_sale

            if kind == "sell" and _wash_lab(portfolio_key, cfg=cfg):
                remaining = float(held) - float(qty)
                record_sale(
                    state,
                    symbol,
                    reason=str(exit_reason_code or "sell"),
                    now=self._clock(),
                    remaining_qty=remaining,
                )
        except Exception:  # noqa: BLE001
            pass
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
            exit_reason_code=exit_reason_code if kind == "sell" else None,
        )
        trade_id = trade.get("id") or trade.get("trade_id")
        line = f"{symbol}: {kind} {qty:g} @ {price:.2f} ({why_short or 'signal'})"
        sell_tag = "sma_cross_rsi"
        if kind == "sell" and exit_reason_code and exit_reason_code != "sma_crossunder":
            sell_tag = f"plc_b_{exit_reason_code}"
        if kind == "sell" and option_overlay and option_overlay.get("used"):
            sell_tag = "sma_cross_rsi"
        buy_tag = index_proxy_tag or "sma_cross_rsi"
        if option_overlay and option_overlay.get("used") and kind == "buy":
            buy_tag = "sma_cross_rsi"
            # Bind fill ids onto the decide-time prediction (already on disk).
            try:
                from atlas.config import get_config
                from atlas.investment import fno_lab_v1 as lab_v1

                lab_v1.bind_entry_prediction_trade(
                    str(get_config().paths.data),
                    option_symbol=symbol,
                    trade_id=str(trade_id) if trade_id else None,
                    decision_id=str(getattr(decision, "id", None) or "") or None,
                )
                open_preds = dict(state.get("fno_lab_v1_open_predictions") or {})
                pred = lab_v1.load_entry_prediction(
                    str(get_config().paths.data), option_symbol=symbol
                )
                if pred:
                    open_preds[str(symbol).upper()] = pred
                    state["fno_lab_v1_open_predictions"] = open_preds
            except Exception:  # noqa: BLE001
                self._logger.debug("fno lab v1 prediction bind skipped", exc_info=True)
        extra = None
        if index_proxy_tag:
            extra = ["index-proxy paper lot on daily underlier — not live futures"]
        elif option_overlay and option_overlay.get("used"):
            extra = [
                "paper ATM option adapter on SMA/RSI V1 — 1 lot, no writing, not live; "
                "premium × lot cash debit, never index level"
            ]
        _pkt(
            kind,
            strategy_tag="next_alternative"
            if as_alt
            else (sell_tag if kind == "sell" else buy_tag),
            line=line,
            qty_v=qty,
            filled=qty,
            fill_px=price,
            fee_v=fee,
            trade_id=trade_id,
            rg=research_gate_result,
            pg=portfolio_gate_result,
            extra_reasons=extra,
        )
        self._notify_fill(
            side=kind,
            symbol=symbol,
            quantity=qty,
            price=price,
            fee=fee,
            fees=fees_doc,
            reason=why_short or "",
            realized_pnl=float(trade.get("realized_pnl", 0.0)),
            portfolio_key=str(
                state.get("portfolio_key")
                or cfg.get("portfolio_key")
                or portfolio_key
                or "india_equity_learner"
            ),
            mission_id=mission_id,
            trade=trade,
            decision=decision,
            research_gate=research_gate_result,
            portfolio_gate=portfolio_gate_result,
        )
        if kind == "sell":
            learn_cfg = dict(cfg)
            learn_cfg.setdefault("portfolio_key", state.get("portfolio_key"))
            if state.get("persona") and not learn_cfg.get("persona"):
                learn_cfg["persona"] = state.get("persona")
            self._remember_outcome(
                symbol, trade, decision, indicators=indicators, cfg=learn_cfg
            )
        return line

    def _notify_fill(
        self,
        *,
        side: str,
        symbol: str,
        quantity: float,
        price: float,
        fee: float = 0.0,
        fees: dict[str, Any] | None = None,
        reason: str = "",
        realized_pnl: float = 0.0,
        portfolio_key: str = "india_equity_learner",
        mission_id: Any = None,
        trade: dict[str, Any] | None = None,
        decision: Any = None,
        research_gate: dict[str, Any] | None = None,
        portfolio_gate: dict[str, Any] | None = None,
    ) -> None:
        """BUY and SELL fills share one mail path (OI-LAB-LOOP0 email symmetry)."""
        if self._investor_mailer is None:
            return
        try:
            decision_doc: dict[str, Any] = {}
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
            if research_gate is not None:
                decision_doc["research_gate"] = research_gate
            if portfolio_gate is not None:
                decision_doc["portfolio_gate"] = portfolio_gate
            if trade and trade.get("id"):
                decision_doc["trade_id"] = trade.get("id") or trade.get("trade_id")
            lab_books = None
            try:
                from zoneinfo import ZoneInfo

                from atlas.config import get_config
                from atlas.workers.investor_reports import load_mail_lab_books

                ist_date = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
                lab_books = load_mail_lab_books(
                    portfolio=self._portfolio,
                    market_reader=self._live_market,
                    data_dir=str(get_config().paths.data),
                    ist_date=ist_date,
                    logger=self._logger,
                )
            except Exception:  # noqa: BLE001
                lab_books = None
            self._investor_mailer.send_trade(
                side=side,
                symbol=symbol,
                quantity=quantity,
                price=price,
                fee=fee,
                fees=fees or {},
                reason=reason,
                decision=decision_doc or None,
                mission_id=str(mission_id) if mission_id else None,
                realized_pnl=float(realized_pnl),
                laboratory_id=str(portfolio_key or "india_equity_learner"),
                portfolio_key=str(portfolio_key or "india_equity_learner"),
                lab_books=lab_books or None,
            )
        except Exception:  # noqa: BLE001 - never fail a fill on email
            self._logger.debug("investor trade email failed", exc_info=True)

    def _notify_blocked_buy(
        self,
        *,
        symbol: str,
        reason: str,
        portfolio_key: str,
        detail: str = "",
        prior_sale: str = "",
    ) -> None:
        """Auditable blocked-action mail — do not silently suppress."""
        if self._investor_mailer is None:
            return
        try:
            send_fn = getattr(self._investor_mailer, "send_blocked_action", None)
            if callable(send_fn):
                send_fn(
                    symbol=symbol,
                    reason=reason,
                    detail=detail,
                    prior_sale=prior_sale,
                    laboratory_id=portfolio_key,
                    portfolio_key=portfolio_key,
                )
                return
            # Fallback: reuse trade mailer with qty=0 blocked marker
            self._investor_mailer.send_trade(
                side="BUY",
                symbol=symbol,
                quantity=0,
                price=0.0,
                fee=0.0,
                reason=reason,
                decision={
                    "action": "blocked",
                    "rationale": detail or reason,
                    "prior_sale": prior_sale,
                    "status": "same_day_reentry_blocked",
                },
                laboratory_id=portfolio_key,
                portfolio_key=portfolio_key,
            )
        except Exception:  # noqa: BLE001
            self._logger.debug("blocked-buy email failed", exc_info=True)

    def _eod_flatten_intraday(
        self,
        *,
        cfg: dict[str, Any],
        portfolio_id: Any,
        portfolio_key: str,
        marks: dict[str, float],
        state: dict[str, Any],
        mission_id: Any,
        pack: Any,
    ) -> None:
        """Hard gate: equity_intraday_learner is cash-only overnight.

        Sells every open qty, records sell packet + experience/outcome, stamps
        ``eod_flatten``. Idempotent per IST flatten session date.
        """
        from atlas.investment.lab_contracts import (
            REASON_EOD_FLATTEN,
            flatten_session_date,
        )

        sess_day = flatten_session_date(self._clock())
        if str(state.get("intraday_eod_flat_ist") or "") == sess_day:
            return
        snapshot = self._portfolio.snapshot(portfolio_id, prices=marks or None)
        positions = [
            p
            for p in (snapshot.get("positions") or [])
            if isinstance(p, dict)
            and abs(float(p.get("quantity") or p.get("qty") or 0)) > 1e-12
        ]
        outcomes: list[dict[str, Any]] = list(state.get("eod_flatten_outcomes") or [])
        if not positions:
            state["intraday_eod_flat_ist"] = sess_day
            state["eod_flatten_outcomes"] = outcomes
            return

        from types import SimpleNamespace

        profile_id = (
            str(cfg.get("broker_profile") or "").strip()
            or (pack.default_broker_profile() if pack is not None else "")
        )
        for pos in positions:
            symbol = str(pos.get("symbol") or "").strip()
            if not symbol:
                continue
            qty = float(pos.get("quantity") or pos.get("qty") or 0)
            mark = float(
                pos.get("mark")
                or marks.get(symbol)
                or pos.get("avg_price")
                or pos.get("avg_cost")
                or pos.get("cost_basis")
                or 0
            )
            mark_source = str(pos.get("mark_source") or "avg_cost")
            if mark <= 0 and marks.get(symbol):
                mark = float(marks[symbol])
                mark_source = "last_marks"
            if qty <= 0:
                continue
            if mark <= 0:
                # Refuse to stamp flat_ok while a position cannot be sold honestly.
                self._logger.warning(
                    "intraday EOD flatten: no mark for %s qty=%s — will retry",
                    symbol,
                    qty,
                )
                outcomes.append(
                    {
                        "symbol": symbol,
                        "qty": qty,
                        "price": None,
                        "status": "blocked_no_mark",
                        "session_date": sess_day,
                    }
                )
                continue
            fee = 0.0
            fees_doc: dict[str, Any] = {}
            try:
                if profile_id:
                    bd = compute_fees(
                        get_broker_profile(profile_id),
                        side="sell",
                        quantity=qty,
                        price=mark,
                    )
                    fee = float(bd.total)
                    fees_doc = bd.as_dict()
            except Exception:  # noqa: BLE001
                fee = 0.0
            try:
                trade = self._portfolio.apply_trade(
                    portfolio_id,
                    symbol=symbol,
                    side="sell",
                    quantity=qty,
                    price=mark,
                    fee=fee,
                    fees=fees_doc,
                    mission_id=mission_id,
                    decision_id=None,
                    laboratory_id=portfolio_key,
                    instrument_path="eod_flatten",
                )
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("intraday EOD flatten sell rejected %s: %s", symbol, exc)
                continue
            pnl = float(trade.get("realized_pnl") or 0.0)
            line = (
                f"{symbol}: eod_flatten sell {qty:g} @ {mark:.2f} "
                f"(realized {pnl:+.2f}; mark_source={mark_source})"
            )
            try:
                self._record_di_packet(
                    action="sell",
                    symbol=symbol,
                    strategy_tag=REASON_EOD_FLATTEN,
                    portfolio_key=portfolio_key,
                    mission_id=mission_id,
                    price=mark,
                    cfg=cfg,
                    qty=qty,
                    filled_qty=qty,
                    fill_price=mark,
                    fees=fee,
                    fill_trade_id=trade.get("id") or trade.get("trade_id"),
                    reasons_for=[line],
                    position_qty=qty,
                )
            except Exception:  # noqa: BLE001
                pass
            decision = SimpleNamespace(
                id=None,
                why="intraday EOD flatten — lab contract (flat overnight)",
            )
            learn_cfg = dict(cfg)
            learn_cfg.setdefault("portfolio_key", portfolio_key)
            learn_cfg["strategy_tag"] = REASON_EOD_FLATTEN
            try:
                self._remember_outcome(
                    symbol, trade, decision, indicators=None, cfg=learn_cfg
                )
            except Exception:  # noqa: BLE001
                self._logger.debug("EOD flatten experience skipped", exc_info=True)
            try:
                from atlas.activity import record_activity

                record_activity(
                    domain="market",
                    worker="paper_trading",
                    action="eod_flatten",
                    target=symbol,
                    result="completed",
                    summary=line,
                    evidence={
                        "laboratory_id": portfolio_key,
                        "qty": qty,
                        "price": mark,
                        "realized_pnl": pnl,
                        "mark_source": mark_source,
                        "session_date": sess_day,
                    },
                )
            except Exception:  # noqa: BLE001
                pass
            outcomes.append(
                {
                    "symbol": symbol,
                    "qty": qty,
                    "price": mark,
                    "realized_pnl": pnl,
                    "mark_source": mark_source,
                    "trade_id": trade.get("id") or trade.get("trade_id"),
                    "session_date": sess_day,
                }
            )

        snap2 = self._portfolio.snapshot(portfolio_id, prices=marks or None)
        leftover = [
            p
            for p in (snap2.get("positions") or [])
            if isinstance(p, dict)
            and abs(float(p.get("quantity") or 0)) > 1e-12
        ]
        if not leftover:
            state["intraday_eod_flat_ist"] = sess_day
        state["eod_flatten_outcomes"] = outcomes

    def _research_buy_gate(
        self,
        *,
        symbol: str,
        cfg: dict[str, Any],
        portfolio_key: str,
    ) -> str | None:
        """Return a hold note when research gate blocks; None if buy may proceed."""
        try:
            from atlas.investment.index_proxy_lot import is_fno_lab, underlier_family

            if is_fno_lab(cfg, portfolio_key) and underlier_family(symbol):
                return None
        except Exception:  # noqa: BLE001
            pass
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
            # Soft MoS for all learner books: missing MoS must not permanently
            # idle a flat cash book. AVOID/INVALID still veto in lab_contracts;
            # negative MoS still fails the research gate.
            mos_mode = "soft"
        pk_l = (portfolio_key or "").lower()
        # Live missions may still carry baked-in when_available from older
        # presets — treat swing the same as soft so cash can redeploy.
        if (
            mos_mode == "when_available"
            and "learner" in pk_l
            and "intraday" not in pk_l
            and "fno" not in pk_l
        ):
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
        exit_reason_code: str | None = None,
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
                from atlas.investment.plc_exits import failure_cause_for_exit

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
                cause = failure_cause_for_exit(exit_reason_code, pnl=pnl)
                # DAV densify — pull RS vs NIFTY from latest open-book pack when present
                what_changed: dict[str, Any] = {}
                if chg is not None:
                    what_changed["price_change_pct"] = chg
                try:
                    obs = getattr(self, "_observations", None)
                    if obs is not None:
                        recent = obs.list_symbol(symbol=symbol, limit=20) or []
                        for o in recent:
                            if not isinstance(o, dict):
                                continue
                            pl = (
                                o.get("payload")
                                if isinstance(o.get("payload"), dict)
                                else {}
                            )
                            if str(pl.get("kind") or "") != "open_book_daily_pack":
                                continue
                            mkt = (
                                pl.get("market")
                                if isinstance(pl.get("market"), dict)
                                else {}
                            )
                            if mkt.get("rs_vs_nifty") is None:
                                continue
                            what_changed["rs_vs_nifty"] = float(mkt["rs_vs_nifty"])
                            what_changed["sector_rel_pct"] = float(mkt["rs_vs_nifty"])
                            what_changed["sector_rel_source"] = "open_book_rs_vs_nifty"
                            break
                except Exception:  # noqa: BLE001
                    pass
                attr = self._attributions.record(
                    decision_id=did,
                    symbol=symbol,
                    portfolio_key=portfolio_key or "india_equity_learner",
                    trigger="exit",
                    checkpoint="exit",
                    packet=packet,
                    pnl=pnl,
                    price_change_pct=chg,
                    failure_cause=cause,
                    what_changed=what_changed or None,
                    extra={
                        "why": why,
                        "exit_reason": why,
                        "exit_reason_code": exit_reason_code,
                        "engine_decision_id": str(engine_decision_id)
                        if engine_decision_id
                        else None,
                    },
                )
                di_grades = (attr.get("attribution") or {}).get("grades")
                # DAV — sizing learning journal (proposals only; no trade_fraction mutation)
                try:
                    from atlas.investment.sizing_learning import record_sizing_outcome

                    conf = None
                    size_frac = None
                    notional = None
                    filled_qty = None
                    if packet:
                        cb = packet.get("confidence_breakdown") or {}
                        conf = cb.get("overall") if isinstance(cb, dict) else None
                        prices = packet.get("prices") or {}
                        filled_qty = prices.get("filled_qty")
                        if prices.get("fill_price") and filled_qty:
                            try:
                                notional = float(prices["fill_price"]) * float(filled_qty)
                            except (TypeError, ValueError):
                                notional = None
                        plan_link = packet.get("plan_link") or {}
                        size_frac = plan_link.get("size_fraction") or plan_link.get(
                            "trade_fraction"
                        )
                    data_dir = None
                    if self._decision_packets is not None:
                        data_dir = getattr(self._decision_packets, "data_dir", None)
                    if not data_dir:
                        try:
                            from atlas.config import get_config

                            data_dir = str(get_config().paths.data)
                        except Exception:  # noqa: BLE001
                            data_dir = None
                    record_sizing_outcome(
                        data_dir,
                        laboratory_id=portfolio_key or "india_equity_learner",
                        symbol=symbol,
                        decision_id=str(did) if did else None,
                        confidence=float(conf) if conf is not None else None,
                        size_fraction=float(size_frac) if size_frac is not None else None,
                        notional=notional,
                        filled_qty=float(filled_qty) if filled_qty is not None else None,
                        pnl=pnl,
                        price_change_pct=chg,
                        thesis_correct=(di_grades or {}).get("thesis_correct")
                        if isinstance(di_grades, dict)
                        else None,
                    )
                except Exception:  # noqa: BLE001
                    self._logger.debug("sizing journal skipped", exc_info=True)
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
        """Record Decision→Outcome via the OI-F4 feedback convention (OI-MP1 / OI-F1).

        LAB-LOOP0 Step 6 — the JSONL round-trip experience (outcome + reward) is
        written even when Experience OS / learning journals are not wired.
        """
        cfg = cfg if isinstance(cfg, dict) else {}
        portfolio_key = str(cfg.get("portfolio_key") or "").strip()
        try:
            from atlas.config import get_config
            from atlas.investment.learning_objects import record_from_trade_close

            record_from_trade_close(
                str(get_config().paths.data),
                symbol=symbol,
                trade=trade,
                laboratory_id=portfolio_key or "india_equity_learner",
                strategy_tag=str(cfg.get("strategy_tag") or ""),
                packet=cfg.get("_learning_packet")
                if isinstance(cfg.get("_learning_packet"), dict)
                else None,
                indicators=indicators,
            )
        except Exception:  # noqa: BLE001
            self._logger.debug("Phase 4 learning object skipped", exc_info=True)

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

    def _maybe_open_book_l3(
        self,
        *,
        portfolio_key: str,
        snapshot: dict[str, Any],
        marks: dict[str, float],
        ist_date: str,
    ) -> dict[str, Any]:
        """LOOP0 L3 — write today's open-book outcome_check without waiting on day14 / 86400s evolution."""
        empty = {"wrote": 0, "skipped": 0, "items": []}
        packets = self._decision_packets
        timeline = getattr(packets, "timeline", None) if packets is not None else None
        if timeline is None or not hasattr(timeline, "record_open_book_outcomes"):
            return empty
        open_syms: list[str] = []
        for pos in snapshot.get("positions") or []:
            if not isinstance(pos, dict):
                continue
            try:
                qty = float(pos.get("qty") or pos.get("quantity") or pos.get("shares") or 0)
            except (TypeError, ValueError):
                qty = 0.0
            sym = str(pos.get("symbol") or "").strip()
            if qty > 0 and sym:
                open_syms.append(sym)
        if not open_syms:
            return empty
        prices = {str(k): float(v) for k, v in (marks or {}).items() if v is not None}

        def _mark(sym: str) -> float | None:
            key = str(sym or "").strip()
            if key in prices:
                return prices[key]
            alt = key.upper() if not key.endswith(".NS") else key
            if alt in prices:
                return prices[alt]
            return None

        out = timeline.record_open_book_outcomes(
            portfolio_key=portfolio_key,
            open_symbols=open_syms,
            as_of_ist=ist_date,
            mark_fn=_mark,
        )
        try:
            from atlas.reasoning.outcome_revision import record_belief_candidate

            for item in out.get("items") or []:
                oc = item.get("outcome_check")
                if isinstance(oc, dict):
                    recorded = record_belief_candidate(
                        self._reasoning, oc, actor="outcome_loop"
                    )
                    item["belief_candidate"] = recorded.get("belief_candidate")
                    item["belief_candidate_skip"] = recorded.get("skip_reason")
        except Exception:  # noqa: BLE001
            self._logger.debug("LOOP0 L3 belief candidate skipped", exc_info=True)
        return out

    def _load_live_bars(self, symbol: str, cfg: dict[str, Any]) -> list[dict[str, Any]]:
        if self._live_market is None:
            raise CapabilityGap(
                "market_reader",
                "live feed_mode requires MarketReaderService (wire live_market= on worker)",
            )
        provider = str(cfg.get("live_provider") or "yahoo").strip() or "yahoo"
        # OI-MDPH0 — live-required labs must not silently substitute Yahoo as Zerodha.
        # Labeled fallback (cfg._mdph_provider_fallback) is allowed and stamped.
        try:
            from atlas.investment.lab_contracts import live_required as _live_req
            from atlas.investment.market_data_provider_health import (
                record_mdph_event,
            )

            pk = str(cfg.get("portfolio_key") or "").strip()
            labeled = str(cfg.get("_mdph_provider_fallback") or "").strip()
            if _live_req(pk, cfg=cfg):
                if provider.lower() == "yahoo" and not labeled:
                    try:
                        from atlas.config import get_config

                        data_dir = get_config().paths.data
                    except Exception:  # noqa: BLE001
                        data_dir = None
                    record_mdph_event(
                        data_dir,
                        "silent_yahoo_blocked",
                        portfolio_key=pk,
                        symbol=symbol,
                        attempted_provider="yahoo",
                    )
                    raise CapabilityGap(
                        "market_data:live_required",
                        "Yahoo forbidden for live_required lab — use zerodha "
                        "(silent substitution blocked; set labeled MDPH fallback)",
                    )
                if not labeled:
                    provider = "zerodha"
                # else keep yahoo/groww as stamped fallback
        except CapabilityGap:
            raise
        except Exception:  # noqa: BLE001
            self._logger.debug("mdph live_provider guard skipped", exc_info=True)

        limit = max(5, int(cfg.get("live_bars_limit", 100)))
        interval = str(cfg.get("live_interval") or "1d").strip() or "1d"
        range_s = str(cfg.get("live_range") or "").strip() or None
        try:
            from atlas.investment.intraday_bars import is_intraday_lab

            pk = str(cfg.get("portfolio_key") or "").strip()
            if is_intraday_lab(cfg, pk):
                interval = str(cfg.get("live_interval") or "5m").strip() or "5m"
                range_s = str(cfg.get("live_range") or "1d").strip() or "1d"
                limit = max(limit, 80)
        except Exception:  # noqa: BLE001
            pass
        kwargs: dict[str, Any] = {
            "provider": provider,
            "limit": limit,
        }
        if interval and interval != "1d":
            kwargs["interval"] = interval
            if range_s:
                kwargs["range"] = range_s
        out = self._live_market.bars_for(symbol, **kwargs)
        return list(out.get("bars") or [])

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._events is None:
            return
        try:
            self._events.emit(event_type, payload, source=self.type)
        except Exception:  # noqa: BLE001 - telemetry must never break a tick
            self._logger.exception("failed to emit %s", event_type)
