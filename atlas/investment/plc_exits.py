"""PLC.B — richer exits + labeled primary failure cause.

Keeps SMA crossunder as one exit lane. Adds deterministic sim exit reason
codes and maps loss exits → LI.0a.10 ``failure_cause`` (never invent on winners).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "plc.b.exits"
_IST = ZoneInfo("Asia/Kolkata")

EXIT_REASON_CODES: frozenset[str] = frozenset(
    {
        "sma_crossunder",
        "thesis_broken",
        "valuation_excessive",
        "better_opportunity",
        "concentration",
        "earnings_deterioration",
        "stop_loss",
        "trailing_stop",
        "time_stop",
    }
)

# Priority: higher wins when multiple fire. Hard risk exits beat SMA.
EXIT_PRIORITY: dict[str, int] = {
    "stop_loss": 90,
    "trailing_stop": 85,
    "thesis_broken": 80,
    "earnings_deterioration": 75,
    "concentration": 70,
    "valuation_excessive": 60,
    "time_stop": 55,
    "better_opportunity": 40,
    "sma_crossunder": 50,
}

# Map exit code → LQ.4 / LI.0a.10 primary root cause (losses only).
EXIT_TO_FAILURE_CAUSE: dict[str, str | None] = {
    "sma_crossunder": None,  # let LQ.4 infer; technical exit ≠ automatic research fail
    "thesis_broken": "research_failure",
    "valuation_excessive": "research_failure",
    "better_opportunity": "portfolio_failure",
    "concentration": "portfolio_failure",
    "earnings_deterioration": "research_failure",
    "stop_loss": "risk_failure",
    "trailing_stop": "risk_failure",
    "time_stop": "risk_failure",
}

DEFAULT_STOP_LOSS_PCT = 0.08
DEFAULT_TRAIL_PCT = 0.10
DEFAULT_TIME_STOP_DAYS = 90
DEFAULT_MAX_NAME_PCT = 0.40
DEFAULT_PE_EXCESSIVE = 55.0


def plc_b_enabled(cfg: dict[str, Any] | None, portfolio_key: str | None) -> bool:
    cfg = cfg or {}
    if cfg.get("plc_b_exits") is not None:
        return bool(cfg.get("plc_b_exits"))
    if cfg.get("plc_b_gates") is not None:
        return bool(cfg.get("plc_b_gates"))
    pk = (portfolio_key or "").lower()
    return "learner" in pk or "laboratory" in pk


def normalize_exit_code(raw: str | None) -> str | None:
    s = str(raw or "").strip().lower().replace(" ", "_")
    if s in EXIT_REASON_CODES:
        return s
    aliases = {
        "sma": "sma_crossunder",
        "sma_exit": "sma_crossunder",
        "crossunder": "sma_crossunder",
        "stop": "stop_loss",
        "trail": "trailing_stop",
        "time": "time_stop",
        "thesis": "thesis_broken",
        "falsified": "thesis_broken",
        "pe_rich": "valuation_excessive",
        "overweight": "concentration",
    }
    return aliases.get(s)


def failure_cause_for_exit(
    exit_code: str | None,
    *,
    pnl: float | None = None,
) -> str | None:
    """Primary failure cause for material sells. Never invent on winners / flat."""
    if pnl is not None and float(pnl) >= 0:
        return None
    code = normalize_exit_code(exit_code)
    if not code:
        return None
    return EXIT_TO_FAILURE_CAUSE.get(code)


def _f(val: Any) -> float | None:
    try:
        if val is None or val == "":
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


def _hold_days(entry_ist: str | None, *, as_of_ist: str | None = None) -> int | None:
    if not entry_ist:
        return None
    try:
        start = date.fromisoformat(str(entry_ist)[:10])
        if as_of_ist:
            end = date.fromisoformat(str(as_of_ist)[:10])
        else:
            end = datetime.now(_IST).date()
        return max(0, (end - start).days)
    except ValueError:
        return None


def evaluate_plc_b_exits(
    *,
    symbol: str,
    price: float,
    held: float,
    avg_price: float | None = None,
    peak_price: float | None = None,
    equity: float | None = None,
    entry_ist: str | None = None,
    as_of_ist: str | None = None,
    fundamentals: dict[str, Any] | None = None,
    awareness: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return the highest-priority non-SMA exit proposal, or None.

    Does not invent PE/thesis — only fires when fields are known and thresholds met.
    """
    cfg = cfg or {}
    if held <= 0 or price <= 0:
        return None

    proposals: list[dict[str, Any]] = []
    avg = _f(avg_price)
    peak = _f(peak_price) or (max(price, avg) if avg else price)
    eq = _f(equity)

    stop_pct = _f(cfg.get("plc_b_stop_loss_pct"))
    if stop_pct is None:
        stop_pct = DEFAULT_STOP_LOSS_PCT
    if avg and avg > 0:
        ret = (price - avg) / avg
        if ret <= -abs(stop_pct):
            proposals.append(
                {
                    "exit_code": "stop_loss",
                    "priority": EXIT_PRIORITY["stop_loss"],
                    "quantity": float(held),
                    "rationale": (
                        f"stop_loss: mark {price:.2f} is {ret:.1%} vs avg {avg:.2f} "
                        f"(threshold −{abs(stop_pct):.0%})"
                    ),
                    "detail": {"return_pct": round(100.0 * ret, 3), "avg_price": avg},
                }
            )

    trail_pct = _f(cfg.get("plc_b_trail_pct"))
    if trail_pct is None:
        trail_pct = DEFAULT_TRAIL_PCT
    if peak and peak > 0 and avg and price < peak:
        dd = (price - peak) / peak
        if peak >= avg * 1.02 and dd <= -abs(trail_pct):
            proposals.append(
                {
                    "exit_code": "trailing_stop",
                    "priority": EXIT_PRIORITY["trailing_stop"],
                    "quantity": float(held),
                    "rationale": (
                        f"trailing_stop: mark {price:.2f} is {dd:.1%} vs peak {peak:.2f}"
                    ),
                    "detail": {
                        "drawdown_pct": round(100.0 * dd, 3),
                        "peak_price": peak,
                    },
                }
            )

    time_days = int(cfg.get("plc_b_time_stop_days") or DEFAULT_TIME_STOP_DAYS)
    held_d = _hold_days(entry_ist, as_of_ist=as_of_ist)
    if held_d is not None and held_d >= max(1, time_days):
        proposals.append(
            {
                "exit_code": "time_stop",
                "priority": EXIT_PRIORITY["time_stop"],
                "quantity": float(held),
                "rationale": (
                    f"time_stop: held {held_d}d ≥ {time_days}d calendar stop"
                ),
                "detail": {"hold_days": held_d, "limit_days": time_days},
            }
        )

    max_name = _f(cfg.get("plc_b_max_name_pct"))
    if max_name is None:
        max_name = _f(cfg.get("max_name_pct"))
    if max_name is None:
        max_name = DEFAULT_MAX_NAME_PCT
    if max_name and max_name > 1.0:
        max_name = max_name / 100.0
    if eq and eq > 0 and max_name:
        weight = (held * price) / eq
        if weight > max_name + 1e-9:
            proposals.append(
                {
                    "exit_code": "concentration",
                    "priority": EXIT_PRIORITY["concentration"],
                    "quantity": float(held),
                    "rationale": (
                        f"concentration: name weight {weight:.1%} > cap {max_name:.0%}"
                    ),
                    "detail": {"weight": round(weight, 4), "cap": max_name},
                }
            )

    fund = fundamentals if isinstance(fundamentals, dict) else {}
    pe = _f(fund.get("pe"))
    pe_cap = _f(cfg.get("plc_b_pe_excessive")) or DEFAULT_PE_EXCESSIVE
    ind_pe = _f(fund.get("industry_pe") or fund.get("sector_pe_median"))
    if pe is not None:
        rich = pe >= pe_cap
        if ind_pe and ind_pe > 0 and pe >= ind_pe * 1.75:
            rich = True
        if rich:
            proposals.append(
                {
                    "exit_code": "valuation_excessive",
                    "priority": EXIT_PRIORITY["valuation_excessive"],
                    "quantity": float(held),
                    "rationale": (
                        f"valuation_excessive: PE {pe:.1f}"
                        + (
                            f" vs industry {ind_pe:.1f}"
                            if ind_pe
                            else f" ≥ {pe_cap:g}"
                        )
                    ),
                    "detail": {"pe": pe, "industry_pe": ind_pe},
                }
            )

    aw = awareness if isinstance(awareness, dict) else {}
    thesis = aw.get("thesis") if isinstance(aw.get("thesis"), dict) else {}
    status = str(
        thesis.get("status")
        or aw.get("thesis_status")
        or thesis.get("verdict")
        or ""
    ).lower()
    falsifiers = thesis.get("falsifiers") or aw.get("falsifiers") or []
    falsifier_hit = isinstance(falsifiers, list) and any(
        isinstance(f, dict)
        and str(f.get("status") or "").lower() in {"hit", "true", "triggered"}
        for f in falsifiers
    )
    if status in {"broken", "falsified", "invalidated", "rejected"} or falsifier_hit:
        proposals.append(
            {
                "exit_code": "thesis_broken",
                "priority": EXIT_PRIORITY["thesis_broken"],
                "quantity": float(held),
                "rationale": f"thesis_broken: thesis status={status or 'falsifier_hit'}",
                "detail": {"thesis_status": status},
            }
        )

    roe = _f(fund.get("roe"))
    buy_roe = None
    if isinstance(fund.get("extra"), dict):
        buy_roe = _f(fund["extra"].get("buy_roe"))
    if buy_roe is None:
        buy_roe = _f(cfg.get("buy_roe_snapshot"))
    if (
        roe is not None
        and buy_roe is not None
        and buy_roe > 0
        and roe < buy_roe * 0.55
    ):
        proposals.append(
            {
                "exit_code": "earnings_deterioration",
                "priority": EXIT_PRIORITY["earnings_deterioration"],
                "quantity": float(held),
                "rationale": (
                    f"earnings_deterioration: ROE {roe:.2f} vs buy-time {buy_roe:.2f}"
                ),
                "detail": {"roe": roe, "buy_roe": buy_roe},
            }
        )

    if not proposals:
        return None
    proposals.sort(key=lambda p: int(p.get("priority") or 0), reverse=True)
    best = dict(proposals[0])
    best["symbol"] = str(symbol).strip().upper()
    best["version"] = VERSION
    best["candidates"] = [p["exit_code"] for p in proposals]
    return best


def format_exit_rules_lines() -> list[str]:
    return [
        "  When Atlas sells (PLC.B + SMA control — P10 sim):",
        "    · Technical: SMA fast below SMA slow (RSI not oversold) — code sma_crossunder",
        "    · Risk: stop_loss (−8% vs avg), trailing_stop (−10% vs peak after profit),",
        "      time_stop (default 90d hold)",
        "    · Portfolio: concentration above name cap",
        "    · Research (when known): thesis_broken, valuation_excessive, earnings_deterioration",
        "    · Loss exits stamp one primary failure_cause (LQ.4); winners stay unlabeled",
    ]
