"""FundamentalsEnrichWorker — LQ.7 Tier C Yahoo enrich on watchlist gaps.

Scheduled medium-confidence fill for missing PE/FCF/ROE/D/E. Never invents;
Screener/filing still outrank Yahoo. Gated on ``market.yahoo_enabled`` (or
explicit config ``yahoo_enabled``). Prefers open-book symbols when configured.

E2 / A9: daily ticks stay ``open_books_only``; IST Sunday early window expands
to the rest of the watchlist (weekly universe densify).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from atlas.workers.base import PersistentWorker, TickContext, TickResult

_IST = ZoneInfo("Asia/Kolkata")


def _in_universe_weekly_window(cfg: dict[str, Any], *, now: datetime | None = None) -> bool:
    """True during the configured IST Sunday (default) early-hour window."""
    weekly = cfg.get("universe_weekly")
    if weekly is False:
        return False
    if not isinstance(weekly, dict):
        weekly = {}
    if weekly.get("enabled") is False:
        return False
    wd = int(weekly.get("ist_weekday", 6))  # Sunday
    hour_start = int(weekly.get("hour_start", 3))
    hour_end = int(weekly.get("hour_end", 5))
    dt = now or datetime.now(_IST)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_IST)
    else:
        dt = dt.astimezone(_IST)
    return dt.weekday() == wd and hour_start <= dt.hour < hour_end


class FundamentalsEnrichWorker(PersistentWorker):
    type = "fundamentals_enrich"
    VERSION = 3
    journal_ticks = True

    def __init__(
        self,
        *,
        data_dir: str | None = None,
        yahoo_enabled: bool = False,
        portfolio: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._yahoo_enabled = bool(yahoo_enabled)
        self._portfolio = portfolio
        self._logger = logger or logging.getLogger("atlas.workers.fundamentals_enrich")

    def _sync_open_book_hermetic(
        self,
        data_dir: str,
        *,
        cfg: dict[str, Any],
        program_id: str,
    ) -> dict[str, Any]:
        """DP-FUND1 — sector-proxy / universe profiles when Yahoo is paused."""
        try:
            from atlas.investment.company_profiles import ensure_open_book_profiles
            from atlas.trading.company import CompanyDataService

            return ensure_open_book_profiles(
                data_dir=data_dir,
                company_data=CompanyDataService(),
                portfolio=self._portfolio,
                laboratory_id=str(
                    cfg.get("portfolio_key") or "india_equity_learner"
                ),
                program_id=program_id,
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("hermetic open-book sync skipped: %s", exc)
            return {"ok": 0, "count": 0, "reason": type(exc).__name__}

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        ticks = int(state.get("ticks", 0)) + 1
        state["ticks"] = ticks
        program_id = str(cfg.get("program_id") or "market_intelligence")
        limit = max(1, min(int(cfg.get("max_symbols") or 3), 10))
        batch_size = max(1, min(int(cfg.get("batch_size") or limit), 5))
        enabled = bool(cfg.get("yahoo_enabled", self._yahoo_enabled))
        data_dir = str(cfg.get("data_dir") or self._data_dir or "")

        if not data_dir:
            return TickResult(state=state, note="idle: data_dir not wired")

        from atlas.investment.fundamentals import enrich_watchlist_gaps
        from atlas.investment.yahoo_fundamentals import (
            get_yahoo_rate_gate,
            yahoo_background_should_yield_to_live,
        )

        try:
            if enabled and yahoo_background_should_yield_to_live():
                hermetic = self._sync_open_book_hermetic(
                    data_dir, cfg=cfg, program_id=program_id
                )
                state["last_enrich"] = {
                    "fetched": 0,
                    "reason": "yield_rth",
                    "mode": "yield_live_session",
                    "hermetic_sync": hermetic,
                }
                return TickResult(
                    state=state,
                    note=(
                        "idle: yield yahoo to live session (RTH); "
                        f"hermetic_ok={hermetic.get('ok')}/{hermetic.get('count')}"
                    ),
                )
        except Exception:  # noqa: BLE001
            pass

        # Hard-pause while Yahoo cooldown is armed (do not burn IP on fallbacks).
        # Still sync hermetic open-book profiles so holdings are not blank in store.
        gate = get_yahoo_rate_gate(data_dir)
        gate_st = gate.status()
        if not gate_st.get("ready") and float(gate_st.get("cooldown_remaining_s") or 0) > 0:
            cool = gate_st.get("cooldown_remaining_s")
            hermetic = self._sync_open_book_hermetic(
                data_dir, cfg=cfg, program_id=program_id
            )
            state["last_enrich"] = {
                "fetched": 0,
                "reason": "yahoo_cooldown",
                "rate_gate": gate_st,
                "mode": "hard_pause",
                "hermetic_sync": hermetic,
            }
            return TickResult(
                state=state,
                note=(
                    f"LQ.7 hard-pause cooldown {cool}s (no Yahoo probes); "
                    f"hermetic_ok={hermetic.get('ok')}/{hermetic.get('count')}"
                ),
            )

        priority: list[str] = []
        if bool(cfg.get("prefer_open_books", True)) and self._portfolio is not None:
            try:
                from atlas.investment.open_book_packs import resolve_open_symbols

                priority = resolve_open_symbols(
                    portfolio=self._portfolio,
                    portfolio_key=str(
                        cfg.get("portfolio_key") or "india_equity_learner"
                    ),
                    limit=20,
                )
            except Exception:  # noqa: BLE001
                priority = []

        open_books_only = bool(cfg.get("open_books_only", False))
        weekly_window = _in_universe_weekly_window(cfg)
        if open_books_only and weekly_window:
            open_books_only = False

        lab_id = str(cfg.get("portfolio_key") or "india_equity_learner")
        try:
            result = enrich_watchlist_gaps(
                data_dir,
                program_id=program_id,
                enabled=enabled,
                limit=limit,
                batch_size=batch_size,
                priority_symbols=priority or None,
                open_books_only=open_books_only,
                laboratory_id=lab_id,
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.exception("LQ.7 fundamentals enrich failed")
            state["last_error"] = str(exc)[:200]
            return TickResult(state=state, note=f"enrich error: {type(exc).__name__}")

        state["last_enrich"] = {
            "fetched": result.get("fetched"),
            "skipped": result.get("skipped_already_covered"),
            "reason": result.get("reason"),
            "gap_symbols": (result.get("gap_symbols") or [])[:12],
            "priority": priority[:8],
            "material_challengers": (result.get("material_challengers") or [])[:8],
            "remaining": result.get("remaining"),
            "errors": len(result.get("errors") or []),
            "mode": result.get("mode") or result.get("reason"),
            "open_books_only": open_books_only,
            "universe_weekly_window": weekly_window,
            "rate_gate": result.get("rate_gate"),
        }
        state.pop("last_error", None)

        fetched = int(result.get("fetched") or 0)
        reason = str(result.get("reason") or "")
        remaining = int(result.get("remaining") or 0)
        if reason == "yahoo_disabled":
            note = f"LQ.7 gated (yahoo_disabled); {len(result.get('gap_symbols') or [])} gaps remain"
        elif reason == "no_gaps":
            note = "LQ.7 no watchlist gaps"
        elif reason == "no_open_books":
            note = "LQ.7 idle: open_books_only and no holdings/challengers"
        elif reason == "no_watchlist_symbols":
            note = "LQ.7 idle: empty watchlist"
        elif reason == "yahoo_cooldown":
            cool = (result.get("rate_gate") or {}).get("cooldown_remaining_s")
            note = f"LQ.7 cooldown {cool}s; {remaining} gaps queued"
        elif fetched:
            syms = ", ".join(str(s) for s in (result.get("symbols") or [])[:5])
            tail = f"; {remaining} remain" if remaining else ""
            if open_books_only and priority:
                pbit = " (open books only)"
            elif open_books_only and (result.get("material_challengers") or []):
                pbit = " (material challengers)"
            elif weekly_window:
                pbit = " (weekly universe)"
            elif priority:
                pbit = " (open-book first)"
            else:
                pbit = ""
            note = f"LQ.7 enriched {fetched}{pbit}: {syms}{tail}"
        else:
            err_n = len(result.get("errors") or [])
            tail = f"; {remaining} remain" if remaining else ""
            note = f"LQ.7 fetched 0 (errors={err_n}){tail}"

        return TickResult(state=state, note=note)
