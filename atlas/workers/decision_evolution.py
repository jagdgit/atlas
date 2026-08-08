"""DecisionEvolutionWorker — DI.2 / LQ.2 denser timeline revisits.

Ensures open material books have Day1→Day3→Week1→Day14→Month1→Quarter
schedules, then drains due checkpoints with Host Guard thinning. Never
rewrites packets; never invents coverage when budget is zero.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.workers.base import PersistentWorker, TickContext, TickResult


class DecisionEvolutionWorker(PersistentWorker):
    type = "decision_evolution"
    VERSION = 3
    journal_ticks = True

    def __init__(
        self,
        *,
        timeline: Any | None = None,
        decision_packets: Any | None = None,
        investment_research: Any | None = None,
        market_reader: Any | None = None,
        attributions: Any | None = None,
        observations: Any | None = None,
        portfolio: Any | None = None,
        host_guard: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._timeline = timeline
        self._packets = decision_packets
        self._research = investment_research
        self._market = market_reader
        self._attributions = attributions
        self._observations = observations
        self._portfolio = portfolio
        self._host_guard = host_guard
        self._logger = logger or logging.getLogger("atlas.workers.decision_evolution")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        ticks = int(state.get("ticks", 0)) + 1
        state["ticks"] = ticks
        portfolio_key = str(cfg.get("portfolio_key") or "india_equity_learner").strip()
        program_id = str(cfg.get("program_id") or "market_intelligence")
        requested = max(1, min(int(cfg.get("max_revisits") or 20), 50))
        obs_hours = float(cfg.get("observation_lookback_hours") or 168.0)

        if self._timeline is None:
            return TickResult(state=state, note="idle: decision timeline not wired")

        from atlas.investment.observation_cadence import evolution_cadence_budget

        budget = evolution_cadence_budget(
            self._host_guard,
            worker_type="decision_evolution",
            requested=requested,
            reduced=max(1, min(5, requested)),
        )
        limit = int(budget.get("budget") or 0)
        state["evolution_cadence"] = budget

        open_symbols = self._open_symbols(cfg, portfolio_key=portfolio_key)
        personality_kind = str(cfg.get("personality_kind") or "swing")
        review_schedule = cfg.get("review_schedule")
        if isinstance(review_schedule, str):
            review_schedule = [s.strip() for s in review_schedule.split(",") if s.strip()]

        ensure_meta: dict[str, Any] = {}
        try:
            ensure_meta = self._timeline.ensure_open_book_schedules(
                portfolio_key=portfolio_key,
                open_symbols=open_symbols,
                personality_kind=personality_kind,
                review_schedule=review_schedule if isinstance(review_schedule, list) else None,
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("LQ.2 ensure schedules failed: %s", exc)
            ensure_meta = {"error": str(exc)[:120]}

        if limit <= 0:
            counts = {}
            try:
                counts = self._timeline.learning_counts(portfolio_key=portfolio_key)
                cov = self._timeline.open_book_timeline_coverage(
                    portfolio_key=portfolio_key,
                    open_symbols=open_symbols,
                    personality_kind=personality_kind,
                )
                counts.update(
                    {
                        "open_books": cov.get("open_books"),
                        "open_books_with_full_schedule": cov.get(
                            "open_books_with_full_schedule"
                        ),
                        "overdue_revisits": cov.get("overdue_revisits"),
                        "host_guard_reason": budget.get("reason"),
                        "host_guard_budget": 0,
                    }
                )
            except Exception:  # noqa: BLE001
                counts = {}
            state["last_evolution"] = {
                "completed": 0,
                "due": 0,
                "thinned": True,
                "ensure": ensure_meta,
                "counts": counts,
                "cadence": budget,
            }
            return TickResult(
                state=state,
                note=(
                    f"evolution: host_guard thinned to 0 "
                    f"({budget.get('reason')}); pending kept honest; "
                    f"ensured={ensure_meta.get('books_ensured', 0)}"
                ),
            )

        def mark_fn(symbol: str) -> float | None:
            if self._market is None:
                return None
            try:
                out = self._market.bars_for(symbol, provider="yahoo", limit=1)
                bars = list((out or {}).get("bars") or [])
                if bars and bars[-1].get("close") is not None:
                    return float(bars[-1]["close"])
            except Exception:  # noqa: BLE001
                return None
            return None

        def awareness_fn(symbol: str) -> dict[str, Any] | None:
            if self._research is None:
                return None
            try:
                return self._research.awareness(symbol, program_id=program_id)
            except Exception:  # noqa: BLE001
                return None

        def observations_fn(symbol: str) -> list[dict[str, Any]]:
            if self._observations is None:
                return []
            try:
                return list(
                    self._observations.list_symbol(
                        symbol=symbol, limit=20, since_hours=obs_hours
                    )
                    or []
                )
            except Exception:  # noqa: BLE001
                return []

        try:
            result = self._timeline.run_due_revisits(
                portfolio_key=portfolio_key,
                limit=limit,
                mark_fn=mark_fn,
                awareness_fn=awareness_fn,
                observations_fn=observations_fn,
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("decision evolution tick failed: %s", exc)
            return TickResult(state=state, note=f"error: {exc}")

        # DI.Attr — provisional attribution on each completed revisit
        attr_n = 0
        obs_hits = 0
        if self._attributions is not None:
            for item in result.get("items") or []:
                try:
                    wc = item.get("what_changed") or {}
                    if wc.get("new_observations"):
                        obs_hits += 1
                    self._attributions.record(
                        decision_id=item.get("decision_id"),
                        symbol=str(item.get("symbol") or ""),
                        portfolio_key=portfolio_key,
                        trigger="revisit",
                        checkpoint=str(item.get("checkpoint") or ""),
                        what_changed=wc,
                        what_changed_event_ids=[str(item.get("timeline_event_id"))]
                        if item.get("timeline_event_id")
                        else None,
                        price_change_pct=wc.get("price_change_pct"),
                    )
                    attr_n += 1
                except Exception:  # noqa: BLE001
                    self._logger.debug("DI.Attr revisit attribution skipped", exc_info=True)

        counts: dict[str, Any] = {}
        try:
            counts = self._timeline.learning_counts(portfolio_key=portfolio_key)
            cov = self._timeline.open_book_timeline_coverage(
                portfolio_key=portfolio_key,
                open_symbols=open_symbols,
                personality_kind=personality_kind,
            )
            counts.update(
                {
                    "open_books": cov.get("open_books"),
                    "open_books_with_full_schedule": cov.get(
                        "open_books_with_full_schedule"
                    ),
                    "overdue_revisits": cov.get("overdue_revisits"),
                    "host_guard_reason": budget.get("reason"),
                    "host_guard_budget": limit,
                }
            )
        except Exception:  # noqa: BLE001
            counts = {}
        state["last_evolution"] = {
            "completed": result.get("completed"),
            "due": result.get("due"),
            "as_of_ist": result.get("as_of_ist"),
            "ensure": ensure_meta,
            "counts": counts,
            "attributions": attr_n,
            "revisits_with_new_observations": obs_hits,
            "cadence": budget,
        }
        thinned = "" if budget.get("allowed") else f" thinned={budget.get('reason')}"
        return TickResult(
            state=state,
            note=(
                f"evolution: completed={result.get('completed')} due={result.get('due')} "
                f"pending={counts.get('pending_revisits', '?')} "
                f"done={counts.get('done_revisits', '?')} attr={attr_n} "
                f"new_obs={obs_hits} ensured={ensure_meta.get('books_ensured', 0)}"
                f"{thinned}"
            ),
        )

    def _open_symbols(
        self, cfg: dict[str, Any], *, portfolio_key: str
    ) -> list[str]:
        raw = cfg.get("open_symbols") or cfg.get("symbols") or []
        if isinstance(raw, str):
            raw = [s.strip() for s in raw.split(",") if s.strip()]
        out = [str(s).strip().upper() for s in raw if str(s).strip()]
        if out:
            return out[:40]
        if self._portfolio is None:
            return []
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
            self._logger.debug("LQ.2 open positions resolve failed", exc_info=True)
        return out
