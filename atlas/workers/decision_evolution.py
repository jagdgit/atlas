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
    VERSION = 6
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
        llm: Any | None = None,
        experience_os: Any | None = None,
        reasoning: Any | None = None,
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
        self._llm = llm
        self._experience_os = experience_os
        self._reasoning = reasoning
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

        try:
            open_book = self._timeline.record_open_book_outcomes(
                portfolio_key=portfolio_key,
                open_symbols=open_symbols,
                mark_fn=mark_fn,
            )
            extra_items = list(open_book.get("items") or [])
            if extra_items:
                merged = list(result.get("items") or [])
                merged.extend(extra_items)
                result = dict(result)
                result["items"] = merged
                result["open_book_outcomes"] = int(open_book.get("wrote") or 0)
        except Exception:  # noqa: BLE001
            self._logger.debug("LOOP0 L3 open-book outcomes skipped", exc_info=True)

        # DI.Attr — provisional attribution on each completed revisit
        attr_n = 0
        obs_hits = 0
        l3_checks = 0
        l3_candidates = 0
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

        # LOOP0 L3 — genealogical belief candidates (advice-only; never auto-active)
        try:
            from atlas.reasoning.outcome_revision import record_belief_candidate

            for item in result.get("items") or []:
                oc = item.get("outcome_check")
                if not isinstance(oc, dict):
                    continue
                l3_checks += 1
                recorded = record_belief_candidate(
                    self._reasoning,
                    oc,
                    actor="outcome_loop",
                )
                item["belief_candidate"] = recorded.get("belief_candidate")
                item["belief_candidate_skip"] = recorded.get("skip_reason")
                if recorded.get("wrote"):
                    l3_candidates += 1
                try:
                    from atlas.config import get_config
                    from atlas.investment.learning_objects import record_from_outcome_check

                    data_dir = str(get_config().paths.data)
                    pkt = item.get("packet") if isinstance(item.get("packet"), dict) else {}
                    if not pkt and item.get("decision_id"):
                        pkt = {"decision_id": item.get("decision_id"), "symbol": item.get("symbol")}
                    record_from_outcome_check(
                        data_dir,
                        laboratory_id=portfolio_key,
                        packet=pkt,
                        outcome_check=oc,
                    )
                except Exception:  # noqa: BLE001
                    self._logger.debug("Phase 4 outcome experience skipped", exc_info=True)
        except Exception:  # noqa: BLE001
            self._logger.debug("LOOP0 L3 belief candidate skipped", exc_info=True)

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
            "outcome_checks": l3_checks,
            "belief_candidates": l3_candidates,
            "cadence": budget,
        }

        # PLC.D — drain due 7d/30d/90d hypothesis checks
        hyp_meta: dict[str, Any] = {}
        try:
            from atlas.investment.plc_hypothesis import (
                plc_d_enabled,
                run_due_hypothesis_checks,
            )

            if plc_d_enabled(cfg, portfolio_key):
                data_dir = None
                if self._packets is not None:
                    data_dir = getattr(self._packets, "data_dir", None)
                if not data_dir:
                    try:
                        from atlas.config import get_config

                        data_dir = str(get_config().paths.data)
                    except Exception:  # noqa: BLE001
                        data_dir = None
                hyp_meta = run_due_hypothesis_checks(
                    data_dir,
                    laboratory_id=portfolio_key,
                    portfolio_key=portfolio_key,
                    as_of_ist=result.get("as_of_ist"),
                    limit=max(1, min(10, limit or 5)),
                    observations=self._observations,
                )
                state["last_evolution"]["hypothesis_checks"] = {
                    "due": hyp_meta.get("due"),
                    "completed": hyp_meta.get("completed"),
                }
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("PLC.D hypothesis checks skipped: %s", exc)

        # UTS.E — drain due switch counterfactual horizons (1/5/20/60d)
        switch_meta: dict[str, Any] = {}
        try:
            from atlas.investment.opportunity_switch import opportunity_switch_enabled
            from atlas.investment.switch_learning import (
                list_switch_decisions,
                propose_threshold_adjustments,
                run_due_switch_horizons,
            )

            if opportunity_switch_enabled(cfg, portfolio_key):
                data_dir = None
                if self._packets is not None:
                    data_dir = getattr(self._packets, "data_dir", None)
                if not data_dir:
                    try:
                        from atlas.config import get_config

                        data_dir = str(get_config().paths.data)
                    except Exception:  # noqa: BLE001
                        data_dir = None
                price_fn = None
                if self._market is not None:

                    def _px(symbol: str, ist_day: str) -> float | None:
                        try:
                            # Best-effort mark; adapters vary — missing → None.
                            if hasattr(self._market, "price_on"):
                                return self._market.price_on(symbol, ist_day)
                            if hasattr(self._market, "last_price"):
                                # Only valid for as-of≈today; else leave missing.
                                from atlas.investment.switch_learning import ist_today

                                if str(ist_day)[:10] == ist_today():
                                    return float(self._market.last_price(symbol))
                        except Exception:  # noqa: BLE001
                            return None
                        return None

                    price_fn = _px
                switch_meta = run_due_switch_horizons(
                    data_dir,
                    laboratory_id=portfolio_key,
                    as_of_ist=result.get("as_of_ist"),
                    price_fn=price_fn,
                    limit=max(1, min(20, limit or 5)),
                )
                try:
                    thr = float(cfg.get("switching_threshold") or 0.02)
                except (TypeError, ValueError):
                    thr = 0.02
                props = propose_threshold_adjustments(
                    list_switch_decisions(
                        data_dir, laboratory_id=portfolio_key, limit=80
                    ),
                    current_threshold=thr,
                )
                state["last_evolution"]["switch_horizons"] = {
                    "completed": switch_meta.get("completed"),
                    "missing_prices": switch_meta.get("missing_prices"),
                    "threshold_proposals": props[:2],
                }
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("UTS.E switch horizons skipped: %s", exc)

        # CF.1 — drain due counterfactual horizons (+30d)
        try:
            from atlas.investment.counterfactual_learning import evaluate_due_cfs

            data_dir = None
            if self._packets is not None:
                data_dir = getattr(self._packets, "data_dir", None)
            if not data_dir:
                try:
                    from atlas.config import get_config

                    data_dir = str(get_config().paths.data)
                except Exception:  # noqa: BLE001
                    data_dir = None
            price_fn = None
            try:
                from atlas.investment.counterfactual_learning import default_price_fn

                price_fn = default_price_fn(data_dir)
            except Exception:  # noqa: BLE001
                price_fn = None
            cf_meta = evaluate_due_cfs(
                data_dir,
                laboratory_id=portfolio_key,
                as_of_ist=result.get("as_of_ist"),
                price_fn=price_fn,
                limit=max(1, min(20, limit or 5)),
            )
            if isinstance(state.get("last_evolution"), dict):
                state["last_evolution"]["counterfactuals"] = {
                    "completed": cf_meta.get("completed"),
                    "missing_prices": cf_meta.get("missing_prices"),
                }
            # OI-SELF-EXP — close learning loops for completed CF horizons (advice-only).
            if (
                int(cf_meta.get("completed") or 0) > 0
                and self._reasoning is not None
                and self._experience_os is not None
            ):
                loops = 0
                for row in list(cf_meta.get("rows") or [])[:5]:
                    if not isinstance(row, dict):
                        continue
                    done_h = [
                        h
                        for h in (row.get("horizons") or [])
                        if isinstance(h, dict) and h.get("status") == "done"
                    ]
                    if not done_h:
                        continue
                    h = done_h[-1]
                    packet = {
                        "symbol": row.get("symbol"),
                        "action": "buy",
                        "decision_id": row.get("decision_id") or row.get("cf_id"),
                        "expected": {
                            "vs_index": "outperform",
                            "entry_price": row.get("entry_price"),
                        },
                    }
                    outcome = {
                        "actual_return": h.get("actual_return"),
                        "index_return": h.get("index_return"),
                        "verdict": h.get("verdict"),
                    }
                    try:
                        closed = self._reasoning.close_packet_outcome(
                            self._experience_os,
                            packet,
                            outcome,
                            no_belief_link_reason=(
                                "CF horizon closed; belief mapping deferred until "
                                "packet↔belief links densify"
                            ),
                            lesson=(
                                f"CF {row.get('symbol')}: verdict={h.get('verdict')} "
                                f"actual={h.get('actual_return')} vs index="
                                f"{h.get('index_return')}"
                            ),
                        )
                        if closed.get("ok"):
                            loops += 1
                    except Exception:  # noqa: BLE001
                        self._logger.debug("CF learning loop skipped", exc_info=True)
                if isinstance(state.get("last_evolution"), dict):
                    state["last_evolution"]["learning_loops"] = loops
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("CF.1 evaluate skipped: %s", exc)

        # BRE.3 — drain async decide-time LLM rationales (never on fill path)
        try:
            from atlas.investment.decide_rationale import (
                DEFAULT_DECIDE_LLM_PASSES,
                drain_pending_rationales,
            )

            data_dir = None
            if self._packets is not None:
                data_dir = getattr(self._packets, "data_dir", None)
            if not data_dir:
                try:
                    from atlas.config import get_config

                    data_dir = str(get_config().paths.data)
                except Exception:  # noqa: BLE001
                    data_dir = None
            max_passes = max(
                1, min(int(cfg.get("decide_rationale_passes") or DEFAULT_DECIDE_LLM_PASSES), 5)
            )
            bre3 = drain_pending_rationales(
                data_dir,
                laboratory_id=portfolio_key,
                llm=self._llm,
                max_passes=max_passes,
                limit=max(1, min(20, limit or 5)),
            )
            if isinstance(state.get("last_evolution"), dict):
                state["last_evolution"]["decide_rationale"] = {
                    "done": bre3.get("done"),
                    "deferred": bre3.get("deferred"),
                    "skipped": bre3.get("skipped"),
                    "pending": bre3.get("pending"),
                }
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("BRE.3 drain skipped: %s", exc)

        # OI-LINT0 Phase 3 — drain event-triggered research scientist (advice-only)
        try:
            from atlas.reasoning.research_scientist import (
                DEFAULT_EVENT_PASSES,
                drain_scientist_queue,
            )

            data_dir = None
            if self._packets is not None:
                data_dir = getattr(self._packets, "data_dir", None)
            if not data_dir:
                try:
                    from atlas.config import get_config

                    data_dir = str(get_config().paths.data)
                except Exception:  # noqa: BLE001
                    data_dir = None
            sci = drain_scientist_queue(
                data_dir,
                laboratory_id=portfolio_key,
                llm=self._llm,
                max_n=max(1, min(int(cfg.get("scientist_passes") or DEFAULT_EVENT_PASSES), 5)),
            )
            if isinstance(state.get("last_evolution"), dict):
                state["last_evolution"]["research_scientist"] = sci
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("research scientist drain skipped: %s", exc)

        # UTS.F — Missed Opportunity Ledger (T+20)
        missed_meta: dict[str, Any] = {}
        try:
            miss_cfg = cfg.get("missed_opportunity_ledger")
            miss_enabled = (
                bool(miss_cfg)
                if miss_cfg is not None
                else ("learner" in portfolio_key.lower())
            )
            if miss_enabled:
                from atlas.investment.missed_opportunity import run_missed_opportunity_job

                data_dir = None
                if self._packets is not None:
                    data_dir = getattr(self._packets, "data_dir", None)
                if not data_dir:
                    try:
                        from atlas.config import get_config

                        data_dir = str(get_config().paths.data)
                    except Exception:  # noqa: BLE001
                        data_dir = None
                price_fn = None
                if self._market is not None:

                    def _px_m(symbol: str, ist_day: str) -> float | None:
                        try:
                            if hasattr(self._market, "price_on"):
                                return self._market.price_on(symbol, ist_day)
                        except Exception:  # noqa: BLE001
                            return None
                        return None

                    price_fn = _px_m
                # Book return: optional from cfg/state; fail-closed if absent.
                book_ret = cfg.get("missed_opportunity_book_return_20d")
                if book_ret is None:
                    book_ret = state.get("book_return_20d")
                try:
                    book_ret_f = float(book_ret) if book_ret is not None else None
                except (TypeError, ValueError):
                    book_ret_f = None
                held = set(open_symbols or [])
                # Prefer holdings as-of T if stored; else current open (honesty gap).
                missed_meta = run_missed_opportunity_job(
                    data_dir,
                    laboratory_id=portfolio_key,
                    program_id=program_id,
                    as_of_ist=result.get("as_of_ist"),
                    horizon_d=int(cfg.get("missed_opportunity_horizon_d") or 20),
                    top_n=int(cfg.get("missed_opportunity_top_n") or 5),
                    max_watchlist=int(cfg.get("max_watchlist") or 15),
                    price_fn=price_fn,
                    held_on_t=held,
                    book_return_20d=book_ret_f,
                    persist=True,
                )
                state["last_evolution"]["missed_opportunities"] = {
                    "ok": missed_meta.get("ok"),
                    "n": len(missed_meta.get("rows") or []),
                    "honesty": missed_meta.get("honesty"),
                    "decision_ist": missed_meta.get("decision_ist"),
                }
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("UTS.F missed opportunities skipped: %s", exc)

        thinned = "" if budget.get("allowed") else f" thinned={budget.get('reason')}"
        hyp_note = ""
        if hyp_meta.get("completed"):
            hyp_note = f"; hyp_checks={hyp_meta.get('completed')}"
        sw_note = ""
        if switch_meta.get("completed") or switch_meta.get("missing_prices"):
            sw_note = (
                f"; switch_cf={switch_meta.get('completed') or 0}"
                f"/{switch_meta.get('missing_prices') or 0}miss"
            )
        miss_note = ""
        if missed_meta.get("ok") and missed_meta.get("rows"):
            miss_note = f"; missed_opp={len(missed_meta.get('rows') or [])}"
        return TickResult(
            state=state,
            note=(
                f"evolution: completed={result.get('completed')} due={result.get('due')} "
                f"pending={counts.get('pending_revisits', '?')} "
                f"done={counts.get('done_revisits', '?')} attr={attr_n} "
                f"new_obs={obs_hits} ensured={ensure_meta.get('books_ensured', 0)}"
                f"{thinned}{hyp_note}{sw_note}{miss_note}"
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
