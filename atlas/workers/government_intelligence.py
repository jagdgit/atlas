"""GovernmentIntelligenceWorker — India budget/policy → ranking nudges.

Keeps a durable policy snapshot (hermetic catalog + operator inputs) and merges
sector deltas into Investment Universe ranking. Not a scrape OS.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.investment.government_policy import (
    ensure_defaults,
    format_policy_brief,
    refresh_catalog,
)
from atlas.workers.base import PersistentWorker, TickContext, TickResult

EVENT_GOV_POLICY = "GovernmentPolicyUpdated"


class GovernmentIntelligenceWorker(PersistentWorker):
    type = "government_intelligence"
    VERSION = 1
    journal_ticks = True

    def __init__(
        self,
        *,
        data_dir: str,
        events: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._events = events
        self._logger = logger or logging.getLogger("atlas.workers.government_intelligence")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        ticks = int(state.get("ticks", 0)) + 1
        state["ticks"] = ticks

        operator_items: list[dict[str, Any]] = []
        for raw in cfg.get("items") or cfg.get("policies") or []:
            if isinstance(raw, dict):
                operator_items.append(raw)
        for inp in ctx.inputs or []:
            if isinstance(inp, dict) and (inp.get("title") or inp.get("text") or inp.get("summary")):
                operator_items.append(inp)

        # IIP.9 — optional policy RSS allow-list → catalog items
        rss_note = ""
        if cfg.get("policy_rss") or cfg.get("fetch_policy_rss") or cfg.get("rss_feeds"):
            try:
                from atlas.investment import rss_feeds as rss

                feeds = rss.merge_allowlist(
                    cfg.get("rss_feeds") if isinstance(cfg.get("rss_feeds"), list) else None,
                    include_defaults=bool(cfg.get("rss_include_defaults", True)),
                )
                enable_ids = {
                    str(x).strip()
                    for x in (cfg.get("rss_enable") or cfg.get("policy_rss_enable") or [])
                    if str(x).strip()
                }
                if enable_ids:
                    for row in feeds:
                        if row.get("id") in enable_ids:
                            row["enabled"] = True
                if isinstance(cfg.get("policy_rss"), list):
                    feeds = rss.merge_allowlist(cfg["policy_rss"], include_defaults=True)
                    for row in feeds:
                        for r in cfg["policy_rss"]:
                            if isinstance(r, dict) and str(r.get("id")) == str(row.get("id")):
                                row["enabled"] = bool(r.get("enabled", True))
                                if r.get("url"):
                                    row["url"] = r["url"]
                result = rss.fetch_allowlist(feeds, kinds=["policy", "gov", "budget"])
                rss.save_last_fetch(self._data_dir, result)
                policy_items = rss.items_as_policy(result)
                operator_items.extend(policy_items)
                rss_note = (
                    f"; rss_policy={len(policy_items)} "
                    f"from {result.get('ok_feeds') or 0} feeds"
                )
                state["rss_policy"] = {
                    "ok_feeds": result.get("ok_feeds"),
                    "item_count": len(policy_items),
                }
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("policy rss skipped: %s", exc)
                rss_note = f"; rss_policy skipped ({exc})"

        include_defaults = cfg.get("include_defaults")
        if include_defaults is None:
            include_defaults = True

        if operator_items or not state.get("seeded"):
            snap = refresh_catalog(
                self._data_dir,
                operator_items=operator_items or None,
                include_defaults=bool(include_defaults),
            )
            state["seeded"] = True
        else:
            snap = ensure_defaults(self._data_dir, logger=self._logger)

        state["item_count"] = len(snap.get("items") or [])
        state["sector_deltas"] = dict(snap.get("sector_deltas") or {})
        state["updated_at"] = snap.get("updated_at")
        state["brief"] = format_policy_brief(snap, limit=5)

        if self._events is not None:
            try:
                self._events.emit(
                    EVENT_GOV_POLICY,
                    {
                        "mission_id": str(ctx.mission_id) if ctx.mission_id else None,
                        "item_count": state["item_count"],
                        "sectors": list(state["sector_deltas"]),
                    },
                    source=self.type,
                )
            except Exception:  # noqa: BLE001
                self._logger.debug("gov policy event failed", exc_info=True)

        top = ", ".join(list(state["sector_deltas"])[:5]) or "(none)"
        return TickResult(
            state=state,
            note=f"government policy items={state['item_count']}; sectors={top}{rss_note}",
        )
