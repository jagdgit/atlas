"""InvestmentUniverseWorker — Market Intelligence M0 (OI-IL0 / IL.2–IL.3).

Refreshes an index membership (default NIFTY50), ranks with WHY ± explanations
(IL.3), publishes the watchlist for Decision Simulation auto-mode, and journals.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.investment import watchlists as wl
from atlas.investment.quality_seed import resolve_quality_seed
from atlas.investment.ranking import rank_universe, summarize_phase
from atlas.investment.universe import INDEX_NIFTY50, as_instruments
from atlas.investment.universe_manager import resolve_members
from atlas.workers.base import PersistentWorker, TickContext, TickResult

EVENT_UNIVERSE_UPDATED = "InvestmentUniverseUpdated"


class InvestmentUniverseWorker(PersistentWorker):
    type = "investment_universe"
    VERSION = 4
    journal_ticks = True

    def __init__(
        self,
        *,
        events: Any | None = None,
        market_reader: Any | None = None,
        policy_engine: Any | None = None,
        experience_os: Any | None = None,
        investment_research: Any | None = None,
        data_dir: str | None = None,
        decision_packets: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._events = events
        self._reader = market_reader
        self._policy = policy_engine
        self._experience = experience_os
        self._research = investment_research
        self._data_dir = data_dir
        self._decision_packets = decision_packets
        self._logger = logger or logging.getLogger("atlas.workers.investment_universe")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        ticks = int(state.get("ticks", 0)) + 1
        state["ticks"] = ticks

        index = str(cfg.get("index") or INDEX_NIFTY50).strip() or INDEX_NIFTY50
        universes_cfg = cfg.get("universes")
        if isinstance(universes_cfg, str):
            universes_cfg = [u.strip() for u in universes_cfg.split(",") if u.strip()]
        max_watch = max(1, int(cfg.get("max_watchlist") or 15))
        max_active = cfg.get("max_active_research")
        mode = str(cfg.get("mode") or "auto").strip().lower() or "auto"
        program_id = str(cfg.get("program_id") or wl.DEFAULT_PROGRAM)
        pinned = [str(s).strip() for s in (cfg.get("pinned_symbols") or []) if str(s).strip()]
        lookback = max(5, int(cfg.get("lookback_bars") or 40))
        provider = str(cfg.get("provider") or "").strip() or None
        weights = cfg.get("rank_weights") if isinstance(cfg.get("rank_weights"), dict) else None
        use_default_seed = cfg.get("use_quality_seed")
        if use_default_seed is None:
            use_default_seed = True
        quality_seed = resolve_quality_seed(
            cfg.get("quality_seed"),
            index=index,
            use_default=bool(use_default_seed),
        )

        try:
            extras = cfg.get("extra_members") or cfg.get("custom_members") or []
            use_enabled = cfg.get("use_enabled_universes")
            if use_enabled is None:
                use_enabled = True
            if universes_cfg:
                resolved = resolve_members(
                    universes=list(universes_cfg),
                    extra_members=extras if isinstance(extras, list) else None,
                    data_dir=self._data_dir,
                    max_members=int(max_active) if max_active else None,
                )
            elif use_enabled and self._data_dir:
                resolved = resolve_members(
                    universes=None,
                    extra_members=extras if isinstance(extras, list) else None,
                    data_dir=self._data_dir,
                    max_members=int(max_active) if max_active else None,
                )
                # If only default NIFTY50 enabled and operator set a different index, honor index.
                en = list(resolved.get("universes") or [])
                if en == [INDEX_NIFTY50] and index and index != INDEX_NIFTY50:
                    resolved = resolve_members(
                        index=index,
                        extra_members=extras if isinstance(extras, list) else None,
                        max_members=int(max_active) if max_active else None,
                    )
            else:
                resolved = resolve_members(
                    index=index,
                    extra_members=extras if isinstance(extras, list) else None,
                    max_members=int(max_active) if max_active else None,
                )
            members = list(resolved.get("members") or [])
            index_label = "+".join(resolved.get("universes") or [index]) or index
            state["universes"] = resolved.get("universes") or []
            state["universes_skipped"] = resolved.get("skipped") or []
        except KeyError as exc:
            return TickResult(state=state, note=f"idle: {exc}")
        except Exception as exc:  # noqa: BLE001
            return TickResult(state=state, note=f"idle: universe resolve failed ({exc})")

        # Always allow pinned symbols into the pool (IRA.10 / on-demand names).
        if pinned and mode != "pin":
            have = {m["symbol"] for m in members}
            for p in pinned:
                sym = p if p.endswith(".NS") else f"{p}.NS"
                if sym in have:
                    continue
                members.append(
                    {
                        "symbol": sym,
                        "name": p,
                        "sector": "",
                        "nse_symbol": p.replace(".NS", ""),
                        "exchange": "NSE",
                        "asset_class": "cash_equity",
                    }
                )
                have.add(sym)
        if mode == "pin" and pinned:
            want = {p if p.endswith(".NS") else f"{p}.NS" for p in pinned}
            watch_members = [m for m in members if m["symbol"] in want]
            if not watch_members:
                watch_members = [
                    {
                        "symbol": (p if p.endswith(".NS") else f"{p}.NS"),
                        "name": p,
                        "sector": "",
                        "nse_symbol": p.replace(".NS", ""),
                        "exchange": "NSE",
                        "asset_class": "cash_equity",
                    }
                    for p in pinned
                ]
            # Pin mode: still score for WHY, but only among pinned set.
            pool = watch_members
            top_n = len(watch_members)
        else:
            pool = members
            top_n = max_watch

        bars_by_symbol = self._collect_bars(
            [str(m["symbol"]) for m in pool],
            lookback=lookback,
            provider=provider,
            state=state,
        )
        # IL.8 — merge operator screener snapshot (+ optional computed) into quality
        use_screener = cfg.get("use_screener_signals")
        if use_screener is None:
            use_screener = True
        screener_meta: dict[str, Any] = {}
        if use_screener:
            from atlas.investment.screener_signals import merge_into_quality

            quality_seed, screener_meta = merge_into_quality(
                quality_seed,
                program_id=program_id,
                bars_by_symbol=bars_by_symbol,
                use_computed=bool(cfg.get("screener_computed", True)),
                config_snapshot=cfg.get("screener_snapshot")
                if isinstance(cfg.get("screener_snapshot"), dict)
                else None,
            )
        policy_deltas = self._policy_deltas(pool)
        # Government budget/policy sector nudges (Market Program).
        try:
            from atlas.config import get_config
            from atlas.investment.government_policy import (
                ensure_defaults,
                policy_delta_by_symbol,
            )

            data_dir = str(get_config().paths.data)
            ensure_defaults(data_dir, logger=self._logger)
            gov = policy_delta_by_symbol(pool, data_dir=data_dir)
            for sym, delta in gov.items():
                policy_deltas[sym] = float(policy_deltas.get(sym, 0.0)) + float(delta)
        except Exception:  # noqa: BLE001
            self._logger.debug("government policy deltas skipped", exc_info=True)
        experience_bias = self._experience_bias(pool)
        research_bias = self._research_bias(pool)
        research_by_symbol = self._research_awareness_map(pool)

        ranked = rank_universe(
            pool,
            bars_by_symbol=bars_by_symbol,
            quality_by_symbol=quality_seed or None,
            policy_delta_by_symbol=policy_deltas or None,
            experience_bias_by_symbol=experience_bias or None,
            research_bias_by_symbol=research_bias or None,
            max_watchlist=top_n,
            weights=weights,
            lookback_short=int(cfg.get("lookback_short") or 5),
            lookback_long=int(cfg.get("lookback_long") or 20),
            min_bars=int(cfg.get("min_bars") or 5),
            cold_start_coverage=float(cfg.get("cold_start_coverage") or 0.25),
        )

        watch = [
            {
                "symbol": r["symbol"],
                "name": r.get("name", ""),
                "sector": r.get("sector", ""),
                "nse_symbol": r.get("nse_symbol", ""),
                "exchange": r.get("exchange", "NSE"),
                "asset_class": r.get("asset_class", "cash_equity"),
            }
            for r in ranked
        ]
        phase_info = summarize_phase(ranked)

        from atlas.investment.daily_plan import build_daily_plan
        from atlas.investment import portfolios as vp

        portfolio_key = str(cfg.get("portfolio_key") or "").strip() or None
        persona_capital = cfg.get("starting_cash") or cfg.get("capital")
        # Prefer live learner book capital when registered (avoids stale ₹10k plan).
        if portfolio_key:
            book = vp.get(portfolio_key)
            if book and isinstance(book.get("persona"), dict):
                try:
                    live = float((book.get("persona") or {}).get("capital") or 0)
                    if live > 0:
                        persona_capital = live
                except (TypeError, ValueError):
                    pass
        try:
            plan_capital = float(persona_capital) if persona_capital is not None else 10_000.0
        except (TypeError, ValueError):
            plan_capital = 10_000.0
        daily_plan = build_daily_plan(
            ranked,
            capital=plan_capital,
            program_id=program_id,
            portfolio_key=portfolio_key,
            index=index,
            max_candidates=min(5, max_watch),
            extra={
                "phase": phase_info["phase"],
                "confidence": phase_info["confidence"],
                "index": index_label,
            },
            research_by_symbol=research_by_symbol or None,
        )

        snap = wl.publish(
            program_id=program_id,
            index=index_label,
            watchlist=watch,
            ranked=ranked,
            mission_id=str(ctx.mission_id) if ctx.mission_id else None,
            mode=mode,
            extra={
                "universe_size": len(members),
                "universes": state.get("universes") or [index],
                "max_watchlist": max_watch,
                "max_active_research": max_active,
                "phase": phase_info["phase"],
                "confidence": phase_info["confidence"],
                "bars_symbols": len(bars_by_symbol),
                "feed_failures": int(state.get("feed_failure_count") or 0),
                "quality_seed_count": len(quality_seed),
                "provider": provider or "",
                "daily_plan": daily_plan,
                "screener": screener_meta,
                "ranking": "il.3+il.8" if screener_meta.get("merged_count") else "il.3",
            },
        )

        state["index"] = index_label
        state["primary_index"] = index
        state["program_id"] = program_id
        state["watchlist_symbols"] = [r["symbol"] for r in ranked]
        state["universe_size"] = len(members)
        state["updated_at"] = snap["updated_at"]
        state["phase"] = phase_info["phase"]
        state["confidence"] = phase_info["confidence"]
        state["quality_seed_count"] = len(quality_seed)
        state["provider"] = provider or ""
        state["screener_merged"] = int(screener_meta.get("merged_count") or 0)
        state["daily_plan_summary"] = daily_plan.get("summary")
        state["ranked"] = ranked
        state["watchlist"] = watch
        state["top_reasons"] = [
            {"symbol": r["symbol"], "reason": r.get("reason", ""), "score": r.get("score")}
            for r in ranked[:5]
        ]

        # DI.1 — once-per-day plan_watch packets for plan candidates (idempotent).
        if self._decision_packets is not None and portfolio_key:
            try:
                from atlas.investment.decision_packets import emit_plan_watch_packets

                written = emit_plan_watch_packets(
                    self._decision_packets,
                    daily_plan=daily_plan,
                    portfolio_key=portfolio_key,
                    mission_id=str(ctx.mission_id) if ctx.mission_id else None,
                    ts_ist=str(daily_plan.get("as_of") or ""),
                    session=str(cfg.get("market_session") or "nse_equity"),
                )
                state["plan_watch_packets"] = len(written)
            except Exception:  # noqa: BLE001
                self._logger.debug("DI.1 plan_watch emit skipped", exc_info=True)

        if self._events is not None:
            try:
                self._events.emit(
                    EVENT_UNIVERSE_UPDATED,
                    {
                        "mission_id": str(ctx.mission_id) if ctx.mission_id else None,
                        "program_id": program_id,
                        "index": index_label,
                        "universes": state.get("universes"),
                        "symbols": state["watchlist_symbols"],
                        "count": len(ranked),
                        "phase": phase_info["phase"],
                        "confidence": phase_info["confidence"],
                    },
                    source=self.type,
                )
            except Exception:  # noqa: BLE001
                self._logger.debug("universe event emit failed", exc_info=True)

        top = ", ".join(state["watchlist_symbols"][:5]) or "(none)"
        phase = phase_info["phase"]
        conf = phase_info["confidence"]
        qbit = f", quality_seed={len(quality_seed)}" if quality_seed else ""
        pbit = f", provider={provider}" if provider else ""
        sbit = (
            f", screener={screener_meta.get('merged_count')}"
            if screener_meta.get("merged_count")
            else ""
        )
        fail_n = int(state.get("feed_failure_count") or 0)
        fbit = f", feed_failures={fail_n}" if fail_n else ""
        plan_bit = f"; plan={daily_plan.get('summary')}" if daily_plan.get("summary") else ""
        return TickResult(
            state=state,
            note=(
                f"{index_label}: {len(members)} constituents → watchlist {len(ranked)} "
                f"(mode={mode}, phase={phase}, confidence={conf}{qbit}{pbit}{sbit}{fbit}); top={top}"
                f"{plan_bit}"
            ),
        )

    def _collect_bars(
        self,
        symbols: list[str],
        *,
        lookback: int,
        provider: str | None,
        state: dict[str, Any] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        if self._reader is None:
            return {}
        from atlas.decision.rules import CapabilityGap
        from atlas.investment.feed_failures import record_failure

        out: dict[str, list[dict[str, Any]]] = {}
        failures = 0
        for sym in symbols:
            try:
                result = self._reader.bars_for(sym, provider=provider, limit=lookback)
            except CapabilityGap as exc:
                failures += 1
                record_failure(
                    self._data_dir,
                    provider=provider or "default",
                    symbol=sym,
                    reason=str(exc)[:400],
                    capability=getattr(exc, "capability", "") or "market_data",
                    source="investment_universe",
                )
                self._logger.debug("bars_for gap for %s: %s", sym, exc)
                continue
            except Exception as exc:  # noqa: BLE001 — network: honest empty
                failures += 1
                record_failure(
                    self._data_dir,
                    provider=provider or "default",
                    symbol=sym,
                    reason=f"fetch_error: {exc}"[:400],
                    capability="market_data",
                    source="investment_universe",
                )
                self._logger.debug("bars_for failed for %s", sym, exc_info=True)
                continue
            bars = list((result or {}).get("bars") or [])
            if bars:
                out[sym] = bars
            else:
                failures += 1
                record_failure(
                    self._data_dir,
                    provider=(result or {}).get("provider") or provider or "default",
                    symbol=sym,
                    reason="empty_live_feed",
                    capability="market_data",
                    source="investment_universe",
                )
        if state is not None:
            state["feed_failure_count"] = failures
        return out

    def _policy_deltas(self, members: list[dict[str, Any]]) -> dict[str, float]:
        if self._policy is None:
            return {}
        out: dict[str, float] = {}
        for m in members:
            sym = str(m.get("symbol") or "").strip()
            if not sym:
                continue
            try:
                verdict = self._policy.evaluate(
                    action={"kind": "buy", "symbol": sym},
                    context={"domain": "finance", "text": sym},
                )
            except Exception:  # noqa: BLE001
                continue
            if isinstance(verdict, dict):
                try:
                    out[sym] = float(verdict.get("soft_delta") or 0.0)
                except (TypeError, ValueError):
                    continue
        return out

    def _experience_bias(self, members: list[dict[str, Any]]) -> dict[str, float]:
        if self._experience is None:
            return {}
        out: dict[str, float] = {}
        caution = ("loss", "caution", "avoid", "drawdown", "failed", "mistake")
        support = ("win", "lesson applied", "improved", "success")
        for m in members:
            sym = str(m.get("symbol") or "").strip()
            if not sym:
                continue
            try:
                advice = self._experience.advice_for(sym, limit=5)
            except Exception:  # noqa: BLE001
                continue
            text = ""
            if isinstance(advice, dict):
                text = str(advice.get("advice") or "").lower()
            bias = 0.0
            if any(w in text for w in caution):
                bias -= 0.2
            if any(w in text for w in support):
                bias += 0.1
            if bias:
                out[sym] = bias
        return out

    def _research_bias(self, members: list[dict[str, Any]]) -> dict[str, float]:
        if self._research is None or not hasattr(self._research, "research_bias_map"):
            return {}
        try:
            syms = [str(m.get("symbol") or "") for m in members if m.get("symbol")]
            return dict(self._research.research_bias_map(syms) or {})
        except Exception:  # noqa: BLE001
            self._logger.debug("research bias skipped", exc_info=True)
            return {}

    def _research_awareness_map(self, members: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        if self._research is None or not hasattr(self._research, "awareness"):
            return {}
        out: dict[str, dict[str, Any]] = {}
        for m in members[:40]:
            sym = str(m.get("symbol") or "").strip()
            if not sym:
                continue
            try:
                # Only cite symbols that already have a dossier (avoid creating noise).
                if hasattr(self._research, "_store"):
                    if self._research._store.get(sym) is None:
                        continue
                out[sym] = self._research.awareness(sym)
            except Exception:  # noqa: BLE001
                continue
        return out


def auto_instruments(
    *,
    program_id: str = wl.DEFAULT_PROGRAM,
    max_n: int = 10,
    fallback_index: str = INDEX_NIFTY50,
) -> list[dict[str, str]]:
    """Resolve instruments for M5 when config.instruments is empty."""
    got = wl.instruments_for(program_id, max_n=max_n)
    if got:
        return got
    # Cold start before first M0 tick: seed from static universe.
    return as_instruments(fallback_index, limit=max_n)
