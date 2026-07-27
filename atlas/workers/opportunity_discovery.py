"""OpportunityDiscoveryWorker — IIP.2 discovery (screen + theme hypotheses).

Evening / periodic funnel: enabled universes → interesting ≤40 → research queue ≤10.
Does not place trades.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.investment.discovery import load_latest_discovery, run_discovery, save_discovery
from atlas.investment.quality_seed import resolve_quality_seed
from atlas.investment.universe_manager import resolve_members
from atlas.workers.base import PersistentWorker, TickContext, TickResult

EVENT_DISCOVERY = "OpportunityDiscoveryUpdated"


class OpportunityDiscoveryWorker(PersistentWorker):
    type = "opportunity_discovery"
    VERSION = 1
    journal_ticks = True

    def __init__(
        self,
        *,
        market_reader: Any | None = None,
        events: Any | None = None,
        data_dir: str | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._reader = market_reader
        self._events = events
        self._data_dir = data_dir
        self._logger = logger or logging.getLogger("atlas.workers.opportunity_discovery")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        ticks = int(state.get("ticks", 0)) + 1
        state["ticks"] = ticks

        max_interesting = max(5, int(cfg.get("max_interesting") or 40))
        max_research = max(0, int(cfg.get("max_enqueue_research") or 10))
        max_scan = max(20, int(cfg.get("max_scan") or 200))
        lookback = max(20, int(cfg.get("lookback_bars") or 60))
        provider = str(cfg.get("provider") or "yahoo").strip() or "yahoo"
        include_themes = cfg.get("include_themes")
        if include_themes is None:
            include_themes = True
        themes = cfg.get("themes") if isinstance(cfg.get("themes"), list) else None

        universes_cfg = cfg.get("universes")
        if isinstance(universes_cfg, str):
            universes_cfg = [u.strip() for u in universes_cfg.split(",") if u.strip()]

        resolved = resolve_members(
            universes=list(universes_cfg) if universes_cfg else None,
            data_dir=self._data_dir,
            max_members=max_scan,
        )
        members = list(resolved.get("members") or [])
        if not members:
            return TickResult(
                state=state,
                note="idle: no universe members — enable universes on Invest intel page",
            )

        # Collect bars (bounded — host-first)
        bars_by_symbol: dict[str, list[dict[str, Any]]] = {}
        feed_fails = 0
        if self._reader is not None:
            from atlas.decision.rules import CapabilityGap
            from atlas.investment.feed_failures import record_failure

            for m in members:
                sym = str(m.get("symbol") or "")
                if not sym:
                    continue
                try:
                    result = self._reader.bars_for(sym, provider=provider, limit=lookback)
                    bars = list((result or {}).get("bars") or [])
                    if bars:
                        bars_by_symbol[sym] = bars
                    else:
                        feed_fails += 1
                        record_failure(
                            self._data_dir,
                            provider=provider,
                            symbol=sym,
                            reason="empty_live_feed",
                            source="opportunity_discovery",
                        )
                except CapabilityGap as exc:
                    feed_fails += 1
                    record_failure(
                        self._data_dir,
                        provider=provider,
                        symbol=sym,
                        reason=str(exc)[:400],
                        capability=exc.capability,
                        source="opportunity_discovery",
                    )
                except Exception as exc:  # noqa: BLE001
                    feed_fails += 1
                    record_failure(
                        self._data_dir,
                        provider=provider,
                        symbol=sym,
                        reason=f"fetch_error: {exc}"[:400],
                        source="opportunity_discovery",
                    )

        quality = resolve_quality_seed(
            cfg.get("quality_seed"),
            index="NIFTY50",
            use_default=bool(cfg.get("use_quality_seed", True)),
        )
        # IIP.3 — overlay durable fundamentals (percent ROCE kept for discovery gates)
        if self._data_dir:
            try:
                from atlas.investment.fundamentals import as_quality_map, load_store

                fund_doc = load_store(self._data_dir)
                for sym, row in (fund_doc.get("symbols") or {}).items():
                    if not isinstance(row, dict):
                        continue
                    cur = dict(quality.get(sym) or {})
                    for fld, val in row.items():
                        if val is not None and fld not in {"fields_present", "strengthens_sections"}:
                            cur[fld] = val
                    quality[sym] = cur
                # also ensure as_quality_map fractions available if needed later
                _ = as_quality_map(self._data_dir)
            except Exception:  # noqa: BLE001
                self._logger.debug("fundamentals overlay skipped", exc_info=True)

        doc = run_discovery(
            members=members,
            bars_by_symbol=bars_by_symbol,
            quality_by_symbol=quality if isinstance(quality, dict) else {},
            themes=themes,
            max_interesting=max_interesting,
            max_enqueue_research=max_research,
            include_themes=bool(include_themes),
        )
        doc["universes"] = resolved.get("universes")
        doc["bars_symbols"] = len(bars_by_symbol)
        doc["feed_failures"] = feed_fails
        doc["provider"] = provider

        path = save_discovery(self._data_dir, doc)
        state["ist_date"] = doc.get("ist_date")
        state["interesting_count"] = doc.get("interesting_count")
        state["research_queue"] = doc.get("research_queue")
        state["top"] = [
            {"symbol": r.get("symbol"), "mode": r.get("mode"), "why": (r.get("why") or "")[:120]}
            for r in (doc.get("interesting") or [])[:8]
        ]
        state["path"] = str(path) if path else None
        state["feed_failures"] = feed_fails

        if self._events is not None:
            try:
                self._events.emit(
                    EVENT_DISCOVERY,
                    {
                        "mission_id": str(ctx.mission_id) if ctx.mission_id else None,
                        "interesting_count": doc.get("interesting_count"),
                        "ist_date": doc.get("ist_date"),
                    },
                    source=self.type,
                )
            except Exception:  # noqa: BLE001
                self._logger.debug("discovery event emit failed", exc_info=True)

        top = ", ".join(
            f"{r.get('symbol')}({r.get('mode')})" for r in (doc.get("interesting") or [])[:5]
        ) or "(none)"
        return TickResult(
            state=state,
            note=(
                f"discovery {doc.get('ist_date')}: scanned {doc.get('scanned')} → "
                f"interesting {doc.get('interesting_count')} "
                f"(bars={len(bars_by_symbol)}, feed_failures={feed_fails}); top={top}"
            ),
        )

    def latest(self) -> dict[str, Any]:
        return load_latest_discovery(self._data_dir)
