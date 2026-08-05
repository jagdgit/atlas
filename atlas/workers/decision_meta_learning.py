"""DecisionMetaLearningWorker — DI.6 weekly intelligence digest.

Builds Appendix B answers + playbook proposals from Decision Packets /
attributions / process proxies. Never silently rewrites strategy.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.workers.base import PersistentWorker, TickContext, TickResult


class DecisionMetaLearningWorker(PersistentWorker):
    type = "decision_meta_learning"
    VERSION = 1
    journal_ticks = True

    def __init__(
        self,
        *,
        data_dir: str | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._logger = logger or logging.getLogger(
            "atlas.workers.decision_meta_learning"
        )

    def do_tick(self, ctx: TickContext) -> TickResult:
        from atlas.investment.meta_learning import (
            collect_meta_learning_inputs,
            week_key,
        )

        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        ticks = int(state.get("ticks", 0)) + 1
        state["ticks"] = ticks
        portfolio_key = str(cfg.get("portfolio_key") or "india_equity_learner").strip()
        force = bool(cfg.get("force") or False)
        wk = week_key()

        # Once per ISO week unless force
        if not force and state.get("last_week") == wk and state.get("last_digest"):
            return TickResult(
                state=state,
                note=f"idle: meta-learning already ran for {wk}",
            )

        try:
            digest = collect_meta_learning_inputs(
                data_dir=self._data_dir or getattr(ctx, "data_dir", None),
                portfolio_key=portfolio_key,
                lookback_days=int(cfg.get("lookback_days") or 14),
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("meta-learning tick failed: %s", exc)
            return TickResult(state=state, note=f"error: {exc}")

        state["last_week"] = wk
        state["last_digest"] = {
            "week": digest.get("week"),
            "intelligence_score": digest.get("intelligence_score"),
            "proposal_count": len(digest.get("proposals") or []),
            "packets": (digest.get("sample") or {}).get("packets"),
            "attributions": (digest.get("sample") or {}).get("attributions"),
            "mirror_path": digest.get("mirror_path"),
        }
        return TickResult(
            state=state,
            note=(
                f"meta-learning {wk}: score={digest.get('intelligence_score')} "
                f"proposals={len(digest.get('proposals') or [])} "
                f"packets={(digest.get('sample') or {}).get('packets')}"
            ),
        )
