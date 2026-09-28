"""BATCH FEL experiment runner — one queued experiment per tick.

Not on the decide tick. Yields during NSE RTH unless the next item is a
cheap skip-complete (load existing result, no Yahoo). Host-guard pause respected.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.workers.base import PersistentWorker, TickContext, TickResult

_E001_ID = "E001-buy_name-vol-accel"


class FelExperimentWorker(PersistentWorker):
    type = "fel_experiment_runner"
    VERSION = 1
    journal_ticks = True

    def __init__(
        self,
        *,
        data_dir: str | None = None,
        host_guard: Any | None = None,
        logger: logging.Logger | None = None,
        allow_rth: bool = False,
        seed_e001: bool = True,
    ) -> None:
        self._data_dir = data_dir
        self._host_guard = host_guard
        self._allow_rth = bool(allow_rth)
        self._seed_e001 = bool(seed_e001)
        self._logger = logger or logging.getLogger("atlas.workers.fel_experiment_runner")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = dict(ctx.config or {})
        state = dict(ctx.state or {})
        data_dir = str(cfg.get("data_dir") or self._data_dir or "") or None
        allow_rth = bool(cfg.get("allow_rth") if cfg.get("allow_rth") is not None else self._allow_rth)
        seed_e001 = bool(cfg.get("seed_e001") if cfg.get("seed_e001") is not None else self._seed_e001)

        if self._host_guard is not None:
            try:
                if hasattr(self._host_guard, "should_pause") and self._host_guard.should_pause():
                    return TickResult(state=state, note="idle: host_guard pause")
            except Exception:  # noqa: BLE001
                pass

        if not data_dir:
            return TickResult(state=state, note="idle: no data_dir")

        from atlas.investment.fel.experiments.dispatch import (
            item_is_cheap_skip,
            process_one,
        )
        from atlas.investment.fel.queue import enqueue, ensure_queue_dir, peek_next

        try:
            ensure_queue_dir(data_dir)
        except OSError as exc:
            return TickResult(state=state, note=f"fel queue not writable: {exc}")

        if seed_e001:
            enqueue(
                data_dir,
                kind="e001",
                experiment_id=_E001_ID,
                skip_if_complete=True,
            )
        try:
            from atlas.investment.fel.experiments.paper_round_trip import enqueue_mail_labs

            enqueue_mail_labs(data_dir)
        except Exception:  # noqa: BLE001
            self._logger.debug("paper round-trip FEL enqueue skipped", exc_info=True)

        if not allow_rth:
            try:
                from atlas.investment.yahoo_fundamentals import yahoo_background_should_yield_to_live

                if yahoo_background_should_yield_to_live():
                    nxt = peek_next(data_dir)
                    if nxt is None:
                        return TickResult(state=state, note="fel queue idle: empty_queue")
                    if not item_is_cheap_skip(nxt, data_dir):
                        return TickResult(
                            state=state,
                            note="idle: yield FEL BATCH to live session (RTH)",
                        )
            except Exception:  # noqa: BLE001
                pass

        out = process_one(data_dir)
        state["last"] = {
            "idle": out.get("idle"),
            "status": out.get("status"),
            "reason": out.get("reason"),
            "queue_id": out.get("queue_id"),
            "summary": out.get("summary"),
        }
        if out.get("idle"):
            return TickResult(state=state, note=f"fel queue idle: {out.get('reason')}")
        summary = out.get("summary") if isinstance(out.get("summary"), dict) else {}
        belief = summary.get("belief_status") or summary.get("result") or out.get("status")
        skipped = " skip" if summary.get("skipped") else ""
        return TickResult(
            state=state,
            note=(
                f"fel {out.get('status')} {summary.get('experiment_id') or out.get('queue_id')} "
                f"result={belief}{skipped}"
            ),
        )
