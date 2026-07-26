"""India learner operator happy path (IL.9) — checklist + next actions.

Pure helpers (no DB). Surfaces what “₹10k India learner” already wires so the
operator does not need hand-built JSON instruments.
"""

from __future__ import annotations

from typing import Any

from atlas.missions.programs import india_equity_learner_overrides

VERSION = "il.9"
PRESET = "india_equity_learner"


def happy_path_guide(*, capital: float = 10_000.0) -> dict[str, Any]:
    """Static guide: how to start and what each surface does."""
    overrides = india_equity_learner_overrides()
    return {
        "kind": "india_learner_happy_path",
        "version": VERSION,
        "preset": PRESET,
        "capital": float(capital),
        "one_liner": (
            "Atlas chooses; you constrain — start the India learner, then ask "
            "learner status / daily plan. No hand-typed instruments required."
        ),
        "start": {
            "beginner_chat": "start India learner with 10000",
            "confirm_chat": "confirm India learner",
            "power_chat": "start India learner now",
            "api_plan": "POST /v1/programs/market_intelligence/plan",
            "api_start": (
                'POST /v1/programs/market_intelligence/start '
                '{"preset":"india_equity_learner"}'
            ),
        },
        "monitor": {
            "learner_status": "GET /v1/learner/status",
            "daily_plan": "GET /v1/market/daily-plan",
            "screener": "GET /v1/market/screener-signals",
            "goals": "GET /v1/goals",
            "chat": "learner status · how is my goal?",
        },
        "defaults": {
            "universe": "NIFTY50",
            "feed": "live Yahoo (.NS)",
            "broker_profile": overrides.get("decision_simulation", {}).get(
                "broker_profile", "zerodha"
            ),
            "instruments": "empty → M0 ranked watchlist",
            "session": "nse_equity",
            "yahoo_required": "market.yahoo_enabled: true",
        },
        "member_overrides": {
            k: {
                "keys": sorted(v.keys()),
            }
            for k, v in overrides.items()
        },
        "checklist": [
            {"id": "yahoo", "text": "Enable market.yahoo_enabled for live .NS bars"},
            {"id": "start", "text": "Start India learner (preview → confirm, or … now)"},
            {"id": "m0", "text": "Wait for M0 watchlist + daily plan in journal"},
            {"id": "status", "text": "Ask learner status / GET /v1/learner/status"},
            {
                "id": "constrain",
                "text": "Optional: pin symbols, POST screener-snapshot, set policy",
            },
            {"id": "p10", "text": "Remember: simulation only — no real broker orders"},
        ],
        "non_goals": [
            "Hand-building instruments JSON",
            "Broker trading login",
            "Screener website scrapes",
        ],
    }


def happy_path_status(
    *,
    goal: dict[str, Any] | None = None,
    watchlist: dict[str, Any] | None = None,
    book: dict[str, Any] | None = None,
    snapshot: dict[str, Any] | None = None,
    screener_count: int = 0,
) -> dict[str, Any]:
    """Runtime checklist against current learner state."""
    guide = happy_path_guide()
    wl = watchlist or {}
    extra = wl.get("extra") if isinstance(wl.get("extra"), dict) else {}
    ranked = list(wl.get("ranked") or wl.get("watchlist") or [])
    daily = extra.get("daily_plan") if isinstance(extra.get("daily_plan"), dict) else None
    checks: list[dict[str, Any]] = []

    def _row(cid: str, ok: bool, detail: str) -> None:
        checks.append({"id": cid, "ok": ok, "detail": detail})

    _row("goal", bool(goal and goal.get("id")), "Goal linked" if goal else "No active goal yet")
    _row(
        "portfolio",
        bool(book and book.get("portfolio_key")),
        f"book={book.get('portfolio_key')}" if book else "No portfolio registry row",
    )
    _row(
        "watchlist",
        bool(ranked),
        f"{len(ranked)} ranked symbols" if ranked else "M0 watchlist not published yet",
    )
    _row(
        "daily_plan",
        bool(daily and daily.get("candidates")),
        (daily or {}).get("summary") or "Daily plan not cached yet",
    )
    phase = str(extra.get("phase") or "")
    conf = str(extra.get("confidence") or "")
    learning = phase == "learning" or conf in {"very_low", "very-low"}
    _row(
        "cold_start",
        not learning if ranked else False,
        (
            "Ranking past cold-start"
            if ranked and not learning
            else ("Still learning / very_low confidence" if ranked else "No ranking yet")
        ),
    )
    _row(
        "sim_book",
        bool(snapshot and snapshot.get("equity") is not None),
        (
            f"equity={snapshot.get('equity')}"
            if snapshot
            else "No sim snapshot (Decision Simulation may not have ticked)"
        ),
    )
    _row(
        "screener",
        screener_count > 0,
        f"{screener_count} screener rows" if screener_count else "No screener snapshot (optional)",
    )

    ready = all(
        c["ok"]
        for c in checks
        if c["id"] in {"goal", "portfolio", "watchlist", "daily_plan"}
    )
    next_actions: list[str] = []
    if not goal:
        next_actions.append('Chat: "start India learner now" or create a goal')
    if not ranked:
        next_actions.append("Wait for Investment Universe (M0) tick / morning cron")
    if ranked and learning:
        next_actions.append("Allow live bars to accumulate — confidence stays honest while learning")
    if screener_count == 0:
        next_actions.append("Optional: POST /v1/market/screener-snapshot with PE/ROE rows")
    if not next_actions:
        next_actions.append("Ask learner status periodically; constrain with pins / policy as needed")

    return {
        "kind": "india_learner_status",
        "version": VERSION,
        "ready": ready,
        "checks": checks,
        "next_actions": next_actions,
        "guide": guide,
    }
