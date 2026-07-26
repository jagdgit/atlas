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
    VERSION = 3
    journal_ticks = True

    def __init__(
        self,
        *,
        market_reader: Any,
        events: Any | None = None,
        jobs: Any | None = None,
        capabilities: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._reader = market_reader
        self._events = events
        self._jobs = jobs
        self._capabilities = capabilities
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
            if event is None:
                continue
            interesting.append(event.as_dict())
            if (
                spawn_research
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
        head = f"{auto_note}observe: {ok} ok, {gaps} gap(s)"
        if interesting:
            head += f", {len(interesting)} interesting"
        if spawned:
            head += f", spawned {spawned} research job(s)"
        detail = "; ".join(notes[:6])
        return TickResult(state=state, note=f"{head} | {detail}" if detail else head)
