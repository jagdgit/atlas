"""CareerResearchWorker — CI.2.5 deepen companies (never apply / never recommend)."""

from __future__ import annotations

import logging
from typing import Any

from atlas.career import research as cr
from atlas.career import watchlist as wl
from atlas.workers.base import PersistentWorker, TickContext, TickResult


class CareerResearchWorker(PersistentWorker):
    type = "career_research"
    VERSION = 1
    journal_ticks = True

    def __init__(
        self,
        *,
        candidates: Any,
        company_data: Any | None = None,
        events: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._candidates = candidates
        self._companies = company_data
        self._events = events
        self._logger = logger or logging.getLogger("atlas.workers.career_research")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        ticks = int(state.get("ticks", 0)) + 1
        state["ticks"] = ticks

        names: list[str] = []
        for n in cfg.get("company_names") or []:
            if str(n).strip():
                names.append(str(n).strip())
        for cid in cfg.get("company_ids") or []:
            s = str(cid).strip()
            if s.startswith("company:"):
                names.append(s.split(":", 1)[-1].replace("-", " "))
            elif s:
                names.append(s)

        if bool(cfg.get("from_watchlist", True)):
            for row in (wl.list_items(kind="company").get("items") or []):
                label = str(row.get("label") or "").strip()
                if label and label not in names:
                    names.append(label)

        for inp in ctx.inputs or []:
            if inp.get("company"):
                names.append(str(inp["company"]).strip())

        # Dedup preserve order
        uniq: list[str] = []
        for n in names:
            if n and n not in uniq:
                uniq.append(n)
        limit = max(1, int(cfg.get("max_companies_per_tick") or 8))
        uniq = uniq[:limit]

        if not uniq:
            return TickResult(
                state=state,
                note=(
                    "idle: set company_names / company_ids or add Career Memory companies "
                    "(research only — never recommends)"
                ),
            )

        seen = set(state.get("researched") or [])
        emitted = 0
        packs = 0
        notes: list[str] = []
        for name in uniq:
            key = name.lower()
            if key in seen and not any(bool(i.get("force")) for i in (ctx.inputs or [])):
                continue
            pack = cr.research_pack_for_company(name, company_data=self._companies)
            packs += 1
            for payload in cr.research_candidates(pack, mission_id=ctx.mission_id):
                try:
                    self._candidates.emit(payload)
                    emitted += 1
                except Exception as exc:  # noqa: BLE001
                    self._logger.warning("research candidate emit failed: %s", exc)
            seen.add(key)
            notes.append(f"{name}:{pack.get('research_sufficiency')}")

        if emitted and hasattr(self._candidates, "consume_pending"):
            try:
                self._candidates.consume_pending(limit=max(emitted, 20))
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("research consolidate failed: %s", exc)

        state["researched"] = list(seen)[-200:]
        state["last_emitted"] = emitted
        state["last_packs"] = packs

        if self._events is not None and packs:
            try:
                self._events.emit(
                    "CareerResearchPacks",
                    {"mission_id": ctx.mission_id, "packs": packs, "emitted": emitted},
                    source=self.type,
                )
            except Exception:  # noqa: BLE001
                pass

        return TickResult(
            state=state,
            note=(
                f"career research: {packs} pack(s), {emitted} candidate(s)"
                + (f" ({', '.join(notes[:4])})" if notes else "")
                + " (research only — no recommend/apply)"
            ),
        )
