"""MarketObserverWorker — Market Intelligence M1 (MI.3 / MI.4 / IL.4).

Observes configured symbols/instruments via MarketReader, scores interesting
events (price + volume), journals moves, emits ``MarketInterestingMove``, and
optionally spawns research Jobs when ``spawn_research`` is enabled (default off).

IL.4: empty symbols/instruments → ranked Investment Universe watchlist.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.decision.rules import CapabilityGap
from atlas.investment import watchlists as wl
from atlas.trading.interesting_events import score_observation
from atlas.workers.base import PersistentWorker, TickContext, TickResult


class MarketObserverWorker(PersistentWorker):
    type = "market_observer"
    VERSION = 4
    journal_ticks = True

    def __init__(
        self,
        *,
        market_reader: Any,
        events: Any | None = None,
        jobs: Any | None = None,
        capabilities: Any | None = None,
        observations: Any | None = None,
        host_guard: Any | None = None,
        portfolio: Any | None = None,
        data_dir: str | None = None,
        decision_packets: Any | None = None,
        investment_research: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._reader = market_reader
        self._events = events
        self._jobs = jobs
        self._capabilities = capabilities
        self._observations = observations
        self._host_guard = host_guard
        self._portfolio = portfolio
        self._data_dir = data_dir
        self._packets = decision_packets
        self._investment_research = investment_research
        self._logger = logger or logging.getLogger("atlas.workers.market_observer")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        ticks = int(state.get("ticks", 0)) + 1
        state["ticks"] = ticks

        if self._capabilities is not None:
            from atlas.capabilities.needs import needs_for_mission

            report = self._capabilities.check_needs(needs_for_mission(self.type))
            if not report.get("ok"):
                missing = report.get("missing") or report.get("disabled") or []
                state["capability_gap"] = report
                return TickResult(
                    state=state,
                    note=(
                        f"capability_gap: need {', '.join(missing) or 'unknown'} "
                        f"(declare via Capability Registry, not imports)"
                    ),
                )

        from atlas.investment.observation_cadence import observation_cadence_budget

        cadence = observation_cadence_budget(
            self._host_guard,
            worker_type=self.type,
            requested=int(cfg.get("mark_snapshot_budget") or 20),
            reduced=int(cfg.get("mark_snapshot_budget_reduced") or 5),
        )
        state["observation_cadence"] = cadence
        mark_budget = int(cadence.get("budget") or 0)
        record_marks = bool(cfg.get("record_mark_snapshots", True))

        # PLC.C — open-book daily packs first (prefer holdings over vanity watchlist)
        open_book_note = ""
        if (
            self._observations is not None
            and bool(cfg.get("open_book_daily_packs", True))
            and self._portfolio is not None
        ):
            pack_cadence = observation_cadence_budget(
                self._host_guard,
                worker_type=self.type,
                requested=int(cfg.get("open_book_pack_budget") or 5),
                reduced=int(cfg.get("open_book_pack_budget_reduced") or 2),
            )
            pack_budget = int(pack_cadence.get("budget") or 0)
            state["open_book_pack_cadence"] = pack_cadence
            if pack_budget > 0:
                try:
                    from atlas.investment.open_book_packs import (
                        record_open_book_daily_packs,
                    )

                    pack_out = record_open_book_daily_packs(
                        observations=self._observations,
                        portfolio=self._portfolio,
                        market_reader=self._reader,
                        data_dir=self._data_dir
                        or str(cfg.get("data_dir") or "")
                        or None,
                        packets=self._packets,
                        investment_research=self._investment_research,
                        portfolio_key=str(
                            cfg.get("portfolio_key") or "india_equity_learner"
                        ),
                        program_id=str(
                            cfg.get("program_id") or "market_intelligence"
                        ),
                        budget=pack_budget,
                        provider=str(cfg.get("provider") or "yahoo") or "yahoo",
                    )
                    state["last_open_book_packs"] = {
                        "recorded": pack_out.get("recorded"),
                        "skipped": pack_out.get("skipped"),
                        "session_day": pack_out.get("session_day"),
                        "symbols": (pack_out.get("symbols") or [])[:12],
                    }
                    rec = int(pack_out.get("recorded") or 0)
                    sk = int(pack_out.get("skipped") or 0)
                    if rec or sk:
                        open_book_note = f"open_book_packs={rec} (skip={sk}); "
                except Exception as exc:  # noqa: BLE001
                    self._logger.debug("PLC.C open_book packs skipped: %s", exc)

        targets, auto = wl.resolve_instruments(cfg)
        state["auto_watchlist"] = auto
        if auto:
            state["auto_symbols"] = [t["symbol"] for t in targets]

        provider = str(cfg.get("provider") or "").strip() or None
        limit = max(2, int(cfg.get("bars_limit", 60)))
        alert_pct = float(cfg.get("move_alert_pct", 5.0) or 5.0)
        volume_min = float(cfg.get("volume_min_ratio", 2.5) or 2.5)
        spawn_research = bool(cfg.get("spawn_research") or False)
        score_threshold = float(cfg.get("score_threshold") or 0.7)

        if not targets:
            return TickResult(
                state=state,
                note=(
                    "idle: no symbols/instruments — set symbols=['RELIANCE.NS'] "
                    "or instruments=[{symbol, asset}], or start M0 / India learner "
                    "so the ranked watchlist auto-loads"
                ),
            )

        notes: list[str] = []
        interesting: list[dict[str, Any]] = []
        gaps = 0
        ok = 0
        spawned = 0
        mark_snaps = 0
        spawned_keys = set(state.get("spawned_keys") or [])

        for target in targets:
            try:
                result = self._reader.bars_for(
                    target["symbol"],
                    provider=provider,
                    asset=target["asset"] or None,
                    limit=limit,
                )
            except CapabilityGap as gap:
                gaps += 1
                notes.append(f"{target['symbol']}: gap {gap.capability}")
                continue
            except Exception as exc:  # noqa: BLE001
                gaps += 1
                notes.append(f"{target['symbol']}: error {exc}")
                self._logger.warning("observe failed for %s: %s", target["symbol"], exc)
                continue
            ok += 1
            move = result.get("pct_move")
            count = int(result.get("count") or 0)
            prov = result.get("provider")
            move_s = f"{move:+.2f}%" if isinstance(move, (int, float)) else "n/a"
            notes.append(f"{target['symbol']}@{prov}: {count} bars, move {move_s}")

            event = score_observation(
                target["symbol"],
                pct_move=move if isinstance(move, (int, float)) else None,
                bars=list(result.get("bars") or []),
                alert_pct=alert_pct,
                volume_min_ratio=volume_min,
                provider=str(prov) if prov else None,
            )
            if event is not None:
                interesting.append(event.as_dict())
                if self._observations is not None:
                    try:
                        self._observations.record_market_event(
                            symbol=target["symbol"],
                            event=event.as_dict(),
                        )
                    except Exception:  # noqa: BLE001
                        self._logger.debug("DI.Obs market_event skipped", exc_info=True)
            elif (
                record_marks
                and mark_snaps < mark_budget
                and self._observations is not None
                and count > 0
            ):
                # LI.3a — quiet books still get a mark observation (resource-gated)
                try:
                    self._observations.record_mark_snapshot(
                        symbol=target["symbol"],
                        pct_move=move if isinstance(move, (int, float)) else None,
                        provider=str(prov) if prov else None,
                        bar_count=count,
                    )
                    mark_snaps += 1
                except Exception:  # noqa: BLE001
                    self._logger.debug("DI.Obs mark_snapshot skipped", exc_info=True)

            if (
                event is not None
                and spawn_research
                and self._jobs is not None
                and event.score >= score_threshold
            ):
                key = f"{event.symbol}:{event.kind}:{round(event.pct_move or 0, 1)}"
                if key not in spawned_keys:
                    try:
                        self._jobs.create_job(
                            event.research_objective(),
                            mission_id=ctx.mission_id,
                        )
                        spawned_keys.add(key)
                        spawned += 1
                    except Exception as exc:  # noqa: BLE001
                        self._logger.warning("spawn research failed: %s", exc)

        state["last_interesting"] = interesting
        state["last_ok"] = ok
        state["last_gaps"] = gaps
        state["last_mark_snapshots"] = mark_snaps
        state["spawned_keys"] = list(spawned_keys)[-50:]
        if interesting and self._events is not None:
            try:
                self._events.emit(
                    "MarketInterestingMove",
                    {
                        "mission_id": ctx.mission_id,
                        "events": interesting,
                    },
                    source=self.type,
                )
            except Exception:  # noqa: BLE001
                pass

        auto_note = f"auto watchlist ({len(targets)}); " if auto else ""
        head = f"{open_book_note}{auto_note}observe: {ok} ok, {gaps} gap(s)"
        if interesting:
            head += f", {len(interesting)} interesting"
        if mark_snaps:
            head += f", {mark_snaps} mark_snapshot(s)"
        if not cadence.get("allowed"):
            head += f" [cadence reduced: {cadence.get('reason')}]"
        if spawned:
            head += f", spawned {spawned} research job(s)"
        detail = "; ".join(notes[:6])
        return TickResult(state=state, note=f"{head} | {detail}" if detail else head)
