"""IIP.7 — Portfolio Optimizer (pre-trade gates + sizing).

Buys must pass score path + research gate + portfolio gate (logged reasons).
Sizing from MoS + persona risk + horizon. Simulation-only (P10).
"""

from __future__ import annotations

from typing import Any

VERSION = "iip.7.portfolio_optimizer"

# Persona risk → max single-name equity fraction / max names / min cash buffer
RISK_LIMITS: dict[str, dict[str, float]] = {
    "very_low": {"max_name_pct": 0.08, "max_names": 8, "min_cash_pct": 0.35, "sector_cap_pct": 0.25},
    "low": {"max_name_pct": 0.12, "max_names": 10, "min_cash_pct": 0.25, "sector_cap_pct": 0.30},
    "medium": {"max_name_pct": 0.18, "max_names": 12, "min_cash_pct": 0.15, "sector_cap_pct": 0.35},
    "high": {"max_name_pct": 0.25, "max_names": 15, "min_cash_pct": 0.08, "sector_cap_pct": 0.45},
    "very_high": {"max_name_pct": 0.35, "max_names": 20, "min_cash_pct": 0.05, "sector_cap_pct": 0.55},
}

# Investment confidence label → floor for buys (soft gate)
CONF_FLOOR_RANK = {"very_low": 0, "low": 1, "medium": 2, "high": 3}

HORIZON_SIZE_MULT: dict[str, float] = {
    "swing": 0.70,
    "position": 0.90,
    "long_term": 1.00,
    "structural": 1.05,
    "speculative": 0.55,
    "medium": 1.00,
    "1y": 1.00,
    "short": 0.75,
}


def _f(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _limits_for_persona(persona: dict[str, Any] | None) -> dict[str, float]:
    risk = str((persona or {}).get("risk") or "medium").strip().lower()
    return dict(RISK_LIMITS.get(risk) or RISK_LIMITS["medium"])


def _as_pct_fraction(raw: Any) -> float | None:
    """Parse a name-cap. Values > 1 are treated as 0–100 percent."""
    if raw is None or raw == "":
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v > 1.0:
        v = v / 100.0
    return v


def name_cap_override_fraction(cfg: dict[str, Any] | None) -> float | None:
    """LOOP0 L0 — explicit name-cap fraction, or None to use persona default.

    Semantics (do **not** treat every 0 as unset):

    * ``max_name_pct`` present → honor it (including **0** as a hard 0% cap).
    * ``max_exposure_pct`` **missing / 0** → template unset (schema: 0 = no
      override). Paper-trading builtins ship 0; that is **not** a 0% cap.
    * ``max_exposure_pct`` **> 0** → explicit hard cap (0–100 or 0–1).
    """
    cfg = cfg or {}
    if cfg.get("max_name_pct") is not None:
        return _as_pct_fraction(cfg.get("max_name_pct"))
    exp = cfg.get("max_exposure_pct")
    if exp is None or exp == "":
        return None
    try:
        exp_f = float(exp)
    except (TypeError, ValueError):
        return None
    # Template / schema: 0 means unbounded override — use persona default.
    if exp_f <= 0:
        return None
    return _as_pct_fraction(exp_f)


def resolve_limits(
    persona: dict[str, Any] | None, cfg: dict[str, Any] | None = None
) -> dict[str, float]:
    """Persona limits with operator overrides, kept internally consistent.

    A sector cap below the single-name cap is contradictory: the first buy of a
    name would breach its own sector before any second name exists. Raising
    ``max_name_pct`` (e.g. via ``max_exposure_pct``) therefore lifts the sector
    floor to match instead of silently blocking every buy.
    """
    cfg = cfg or {}
    limits = _limits_for_persona(persona)
    cap = name_cap_override_fraction(cfg)
    if cap is not None:
        limits["max_name_pct"] = float(cap)
    for key in ("max_names", "sector_cap_pct", "min_cash_pct"):
        if cfg.get(key) is not None:
            try:
                limits[key] = float(cfg[key])
            except (TypeError, ValueError):
                continue
    if cfg.get("sector_cap_pct") is None:
        limits["sector_cap_pct"] = max(
            float(limits["sector_cap_pct"]), float(limits["max_name_pct"])
        )
    return limits


def target_name_pct(
    persona: dict[str, Any] | None = None, cfg: dict[str, Any] | None = None
) -> float:
    """Per-name sizing *target* (not the ceiling).

    Operator caps like ``max_exposure_pct`` are the most a single name may ever
    reach; sizing every buy at that ceiling fills the book with one or two names
    and starves the rest of the day's candidates. Target the persona risk budget
    instead, clamped by whatever ceiling is configured.
    """
    base = float(_limits_for_persona(persona)["max_name_pct"])
    ceiling = float(resolve_limits(persona, cfg)["max_name_pct"])
    return max(0.0, min(base, ceiling))


# Gate failures that a smaller order can satisfy (vs. hard vetoes like research).
TRIMMABLE_REASONS = (
    "insufficient_cash",
    "cash_buffer",
    "concentration_name",
    "concentration_sector",
)


def max_allowed_quantity(
    *,
    symbol: str,
    price: float,
    snapshot: dict[str, Any] | None = None,
    persona: dict[str, Any] | None = None,
    index: str = "NIFTY50",
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Largest whole-share buy that satisfies cash buffer + name + sector caps."""
    limits = resolve_limits(persona, cfg)
    snap = snapshot if isinstance(snapshot, dict) else {}
    px = _f(price)
    cash = _f(snap.get("cash"))
    equity = _f(snap.get("equity")) or cash
    sym = (symbol or "").strip().upper()
    if sym and not sym.endswith(".NS") and "." not in sym:
        sym = f"{sym}.NS"
    if px <= 0:
        return {"quantity": 0, "notional": 0.0, "binding": "invalid_price", "limits": limits}

    positions = open_positions(snap)
    existing_name = 0.0
    for p in positions:
        if p["symbol"] == sym:
            existing_name = _f(p.get("qty")) * _f(
                p.get("price") or p.get("mark") or p.get("avg_price") or px
            )
            break

    sector = sector_for_symbol(sym, index=index)
    existing_sector = 0.0
    if sector != "Unknown":
        for p in positions:
            if sector_for_symbol(str(p.get("symbol")), index=index) == sector:
                existing_sector += _f(p.get("qty")) * _f(
                    p.get("price") or p.get("mark") or p.get("avg_price") or 0
                )

    rooms: dict[str, float] = {
        "cash_buffer": max(0.0, cash - equity * float(limits["min_cash_pct"])),
        "concentration_name": max(
            0.0, equity * float(limits["max_name_pct"]) - existing_name
        ),
    }
    if equity > 0 and sector != "Unknown":
        rooms["concentration_sector"] = max(
            0.0, equity * float(limits["sector_cap_pct"]) - existing_sector
        )
    binding = min(rooms, key=lambda k: rooms[k])
    qty = int(rooms[binding] // px)
    return {
        "quantity": max(0, qty),
        "notional": round(max(0, qty) * px, 2),
        "binding": binding,
        "rooms": {k: round(v, 2) for k, v in rooms.items()},
        "sector": sector,
        "limits": limits,
    }


def sector_for_symbol(symbol: str, *, index: str = "NIFTY50") -> str:
    """Best-effort sector from universe membership."""
    try:
        from atlas.investment.universe import membership

        sym = (symbol or "").strip().upper()
        if sym and not sym.endswith(".NS") and "." not in sym:
            sym = f"{sym}.NS"
        for row in membership(index):
            if str(row.get("symbol") or "").upper() == sym:
                return str(row.get("sector") or "Unknown") or "Unknown"
    except Exception:  # noqa: BLE001
        pass
    return "Unknown"


def open_positions(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    snap = snapshot if isinstance(snapshot, dict) else {}
    raw = snap.get("positions") or snap.get("holdings") or []
    out: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        for sym, row in raw.items():
            if isinstance(row, dict):
                qty = _f(row.get("qty") or row.get("quantity") or row.get("shares"))
                if qty > 0:
                    out.append({"symbol": str(sym).upper(), "qty": qty, **row})
            elif _f(row) > 0:
                out.append({"symbol": str(sym).upper(), "qty": _f(row)})
    elif isinstance(raw, list):
        for row in raw:
            if not isinstance(row, dict):
                continue
            qty = _f(row.get("qty") or row.get("quantity") or row.get("shares"))
            if qty <= 0:
                continue
            out.append({**row, "symbol": str(row.get("symbol") or "").upper(), "qty": qty})
    return out


def suggest_notional(
    *,
    equity: float,
    cash: float,
    persona: dict[str, Any] | None = None,
    mos_pct: float | None = None,
    horizon: str = "long_term",
    investment_confidence_score: float | None = None,
    price: float | None = None,
) -> dict[str, Any]:
    """Size a buy notional from MoS + risk + horizon (capped by cash/limits)."""
    limits = _limits_for_persona(persona)
    eq = max(0.0, _f(equity))
    cash_f = max(0.0, _f(cash))
    base_pct = float(limits["max_name_pct"])
    # MoS tilt: negative MoS shrinks; strong MoS expands modestly
    mos = mos_pct
    mos_mult = 1.0
    if mos is not None:
        if mos < 0:
            mos_mult = max(0.25, 1.0 + mos / 50.0)
        else:
            mos_mult = min(1.25, 1.0 + mos / 80.0)
    hz = (horizon or "long_term").strip().lower().replace("-", "_")
    hz_mult = HORIZON_SIZE_MULT.get(hz, 1.0)
    inv = investment_confidence_score
    inv_mult = 1.0
    if inv is not None:
        inv_mult = max(0.35, min(1.15, 0.5 + _f(inv)))

    target_pct = base_pct * mos_mult * hz_mult * inv_mult
    target_pct = min(target_pct, float(limits["max_name_pct"]) * 1.15)
    notional = eq * target_pct if eq > 0 else 0.0
    # Respect cash after min buffer
    min_cash = eq * float(limits["min_cash_pct"]) if eq > 0 else 0.0
    spendable = max(0.0, cash_f - min_cash)
    notional = min(notional, spendable)
    qty = 0.0
    if price and price > 0 and notional > 0:
        qty = int(notional // price)
        notional = qty * price
    return {
        "notional": round(notional, 2),
        "quantity": int(qty),
        "target_pct": round(target_pct, 4),
        "mos_mult": round(mos_mult, 3),
        "horizon_mult": round(hz_mult, 3),
        "inv_mult": round(inv_mult, 3),
        "spendable_cash": round(spendable, 2),
        "limits": limits,
    }


def pre_trade_check(
    *,
    side: str,
    symbol: str,
    quantity: float,
    price: float,
    snapshot: dict[str, Any] | None = None,
    persona: dict[str, Any] | None = None,
    investment_score: dict[str, Any] | None = None,
    research_gate: dict[str, Any] | None = None,
    asset_class: str = "cash_equity",
    index: str = "NIFTY50",
    require_research: bool = True,
    require_score: bool = True,
    min_investment_confidence: str = "low",
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Explicit pass/fail portfolio gate. Sells are lightly checked (cash/qty)."""
    cfg = cfg or {}
    side_n = (side or "").strip().lower()
    sym = (symbol or "").strip().upper()
    if sym and not sym.endswith(".NS") and "." not in sym:
        sym = f"{sym}.NS"
    qty = _f(quantity)
    px = _f(price)
    snap = snapshot if isinstance(snapshot, dict) else {}
    cash = _f(snap.get("cash"))
    equity = _f(snap.get("equity") or (cash + sum(
        _f(p.get("qty")) * _f(p.get("price") or p.get("mark") or p.get("avg_price") or 0)
        for p in open_positions(snap)
    )))
    if equity <= 0:
        equity = cash
    persona = persona if isinstance(persona, dict) else {}
    limits = resolve_limits(persona, cfg)

    reasons: list[str] = []
    checks: list[dict[str, Any]] = []
    score = investment_score if isinstance(investment_score, dict) else {}
    rgate = research_gate if isinstance(research_gate, dict) else {}

    def _fail(code: str, detail: str = "") -> None:
        reasons.append(code if not detail else f"{code}:{detail}")
        checks.append({"id": code, "ok": False, "detail": detail})

    def _ok(code: str, detail: str = "") -> None:
        checks.append({"id": code, "ok": True, "detail": detail})

    if side_n not in {"buy", "sell"}:
        _fail("invalid_side", side_n)
        return _result(False, "hold", reasons, checks, None, limits)

    if qty <= 0 or px <= 0:
        _fail("invalid_qty_or_price")
        return _result(False, "hold", reasons, checks, None, limits)

    # --- sells: only position check ---
    if side_n == "sell":
        held = 0.0
        for p in open_positions(snap):
            if p.get("symbol") == sym:
                held = _f(p.get("qty"))
                break
        if qty > held + 1e-9:
            _fail("insufficient_position", f"have={held}")
        else:
            _ok("position", f"qty={held}")
        allowed = not reasons
        return _result(allowed, "sell_ok" if allowed else "hold", reasons, checks, None, limits)

    # --- buys ---
    # 1) Research gate
    if require_research and rgate:
        if rgate.get("allowed") is False:
            _fail("research_gate", ",".join(rgate.get("reasons") or []) or rgate.get("action") or "blocked")
        else:
            _ok("research_gate", str(rgate.get("action") or "buy_ok"))
    elif require_research and not rgate:
        _ok("research_gate", "not_supplied")

    # 2) Score / investment confidence
    if require_score:
        # Empty score must not invent "very_low" — that blocked every hermetic /
        # pre-research buy. Missing score = not_supplied (research gate still applies).
        has_score = bool(score) and any(
            score.get(k) is not None
            for k in (
                "path",
                "investment_confidence",
                "investment_confidence_score",
                "horizon",
            )
        )
        if not has_score:
            _ok("score_path", "not_supplied")
            _ok("investment_confidence", "not_supplied")
        else:
            path = str(score.get("path") or "")
            if path == "avoid":
                _fail("score_path_avoid", str(score.get("path_reason") or ""))
            elif path == "watch" and score.get("path_reason") == "high_research_low_investment":
                _fail("score_watch", "high_research_low_investment")
            else:
                _ok("score_path", path or "n/a")
            inv_label = str(score.get("investment_confidence") or "very_low")
            floor = str(
                min_investment_confidence or cfg.get("min_investment_confidence") or "low"
            )
            if CONF_FLOOR_RANK.get(inv_label, 0) < CONF_FLOOR_RANK.get(floor, 1):
                _fail("investment_confidence_floor", f"{inv_label}<{floor}")
            else:
                _ok("investment_confidence", inv_label)

    # 3) Persona asset class
    allowed_assets = persona.get("allowed_assets") or ["cash_equity"]
    ac = (asset_class or "cash_equity").strip().lower()
    if allowed_assets and ac not in {str(a).lower() for a in allowed_assets} and "mixed" not in {
        str(a).lower() for a in allowed_assets
    }:
        _fail("persona_asset", f"{ac} not in {allowed_assets}")
    else:
        _ok("persona_asset", ac)

    # 4) Cash + min buffer
    notional = qty * px
    min_cash = equity * float(limits["min_cash_pct"]) if equity > 0 else 0.0
    if cash < notional:
        _fail("insufficient_cash", f"need={notional:.2f} have={cash:.2f}")
    elif cash - notional < min_cash - 1e-6 and equity > 0:
        _fail("cash_buffer", f"min_cash_pct={limits['min_cash_pct']}")
    else:
        _ok("cash", f"spend={notional:.2f}")

    # 5) Max names
    positions = open_positions(snap)
    open_syms = {p["symbol"] for p in positions}
    already = sym in open_syms
    if not already and len(open_syms) >= int(limits["max_names"]):
        _fail("max_names", f"{len(open_syms)}>={int(limits['max_names'])}")
    else:
        _ok("max_names", f"open={len(open_syms)}")

    # 6) Single-name concentration
    if equity > 0:
        # Existing mark for symbol if any
        existing_val = 0.0
        for p in positions:
            if p["symbol"] == sym:
                existing_val = _f(p.get("qty")) * _f(p.get("price") or p.get("mark") or px)
                break
        new_val = existing_val + notional
        name_pct = new_val / equity
        if name_pct > float(limits["max_name_pct"]) + 1e-9:
            _fail("concentration_name", f"{name_pct:.1%}>{limits['max_name_pct']:.0%}")
        else:
            _ok("concentration_name", f"{name_pct:.1%}")

    # 7) Sector concentration
    sector = sector_for_symbol(sym, index=index)
    if equity > 0 and sector != "Unknown":
        sector_val = notional
        for p in positions:
            ps = sector_for_symbol(str(p.get("symbol")), index=index)
            if ps == sector:
                sector_val += _f(p.get("qty")) * _f(p.get("price") or p.get("mark") or 0)
        sector_pct = sector_val / equity
        if sector_pct > float(limits["sector_cap_pct"]) + 1e-9:
            _fail("concentration_sector", f"{sector} {sector_pct:.1%}>{limits['sector_cap_pct']:.0%}")
        else:
            _ok("concentration_sector", f"{sector} {sector_pct:.1%}")
    else:
        _ok("concentration_sector", sector)

    sizing = suggest_notional(
        equity=equity,
        cash=cash,
        persona=persona,
        mos_pct=_f(cfg.get("mos_pct")) if cfg.get("mos_pct") is not None else None,
        horizon=str(
            score.get("horizon")
            or persona.get("time_horizon")
            or "long_term"
        ),
        investment_confidence_score=(
            _f(score.get("investment_confidence_score"))
            if score.get("investment_confidence_score") is not None
            else None
        ),
        price=px,
    )

    allowed = not reasons
    action = "buy_ok" if allowed else "hold_portfolio"
    trim = max_allowed_quantity(
        symbol=sym,
        price=px,
        snapshot=snap,
        persona=persona,
        index=index,
        cfg=cfg,
    )
    return _result(
        allowed,
        action,
        reasons,
        checks,
        sizing,
        limits,
        sector=sector,
        max_quantity=int(trim.get("quantity") or 0),
        trim=trim,
    )


def _result(
    allowed: bool,
    action: str,
    reasons: list[str],
    checks: list[dict[str, Any]],
    sizing: dict[str, Any] | None,
    limits: dict[str, float],
    *,
    sector: str = "",
    max_quantity: int | None = None,
    trim: dict[str, Any] | None = None,
) -> dict[str, Any]:
    codes = {str(r).split(":", 1)[0] for r in reasons}
    return {
        "version": VERSION,
        "allowed": allowed,
        "action": action,
        "reasons": reasons,
        "checks": checks,
        "sizing": sizing,
        "limits": limits,
        "sector": sector,
        "max_quantity": max_quantity,
        "trim": trim,
        # True when every failure is a size problem a smaller order can fix.
        "trimmable": bool(codes) and codes.issubset(set(TRIMMABLE_REASONS)),
        "note": (
            "Portfolio gate (IIP.7): concentration · cash · persona · max names · "
            "investment confidence. Score + research gates also required for buys."
        ),
    }


def optimize_candidate(
    *,
    symbol: str,
    price: float,
    snapshot: dict[str, Any] | None,
    persona: dict[str, Any] | None,
    investment_score: dict[str, Any] | None = None,
    research_gate: dict[str, Any] | None = None,
    mos_pct: float | None = None,
    horizon: str | None = None,
    asset_class: str = "cash_equity",
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Suggest size then run pre-trade check for that size."""
    snap = snapshot or {}
    cash = _f(snap.get("cash"))
    equity = _f(snap.get("equity") or cash)
    score = investment_score or {}
    size = suggest_notional(
        equity=equity,
        cash=cash,
        persona=persona,
        mos_pct=mos_pct,
        horizon=horizon or str(score.get("horizon") or (persona or {}).get("time_horizon") or "long_term"),
        investment_confidence_score=(
            _f(score.get("investment_confidence_score"))
            if score.get("investment_confidence_score") is not None
            else None
        ),
        price=price,
    )
    qty = float(size.get("quantity") or 0)
    check = pre_trade_check(
        side="buy",
        symbol=symbol,
        quantity=qty if qty > 0 else 1.0,
        price=price,
        snapshot=snap,
        persona=persona,
        investment_score=score,
        research_gate=research_gate,
        asset_class=asset_class,
        cfg={**(cfg or {}), "mos_pct": mos_pct},
    )
    if qty <= 0:
        check = dict(check)
        check["allowed"] = False
        check["action"] = "hold_portfolio"
        check["reasons"] = list(check.get("reasons") or []) + ["zero_size"]
    return {"sizing": size, "pre_trade": check, "symbol": symbol, "version": VERSION}
