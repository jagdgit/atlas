"""OI-CU0 CU.C — overnight densify worker (18:30–07:30 IST ticks)."""

from __future__ import annotations

import logging
from typing import Any

from atlas.workers.base import PersistentWorker, TickContext, TickResult


class OvernightDensifyWorker(PersistentWorker):
    type = "overnight_densify"
    VERSION = 1
    journal_ticks = True

    def __init__(
        self,
        *,
        data_dir: str | None = None,
        portfolio: Any | None = None,
        llm: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._portfolio = portfolio
        self._llm = llm
        self._logger = logger or logging.getLogger("atlas.workers.overnight_densify")

    def do_tick(self, ctx: TickContext) -> TickResult:
        from atlas.investment.overnight_densify import run_overnight_densify

        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        data_dir = str(cfg.get("data_dir") or self._data_dir or "") or None
        open_syms = cfg.get("open_symbols")
        if isinstance(open_syms, str):
            open_syms = [open_syms]
        doc = run_overnight_densify(
            data_dir,
            portfolio=self._portfolio,
            open_symbols=list(open_syms) if isinstance(open_syms, list) else None,
            rss_enable=list(cfg.get("rss_enable") or ["pib_press"]),
            allow_llm=bool(
                cfg.get("allow_llm")
                if cfg.get("allow_llm") is not None
                else True
            ),
            llm=self._llm,
            force=bool(cfg.get("force", False)),
            icr5_drain_passes=int(cfg.get("icr5_drain_passes") or 3),
            bre3_drain_passes=int(cfg.get("bre3_drain_passes") or 2),
        )
        state["last"] = {
            "skipped": doc.get("skipped"),
            "reason": doc.get("reason"),
            "intake": doc.get("intake"),
            "rss": doc.get("rss"),
            "as_of_ist": doc.get("as_of_ist"),
        }
        if doc.get("skipped"):
            return TickResult(
                state=state,
                note=f"overnight densify skipped: {doc.get('reason')}",
            )
        intake = doc.get("intake") if isinstance(doc.get("intake"), dict) else {}
        rss = doc.get("rss") if isinstance(doc.get("rss"), dict) else {}
        return TickResult(
            state=state,
            note=(
                f"overnight densify status={intake.get('status')} "
                f"rss_items={rss.get('item_count')} "
                f"obs={doc.get('observations_recorded', 0)}"
            ),
        )
