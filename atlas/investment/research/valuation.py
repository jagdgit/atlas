"""ValuationCase helpers — multiples + conservative DCF stub (IRA.11).

Hermetic / operator inputs only. Never invents line items. MoS is computed when
enough inputs exist; otherwise left explicit Null with gaps.
"""

from __future__ import annotations

from typing import Any

from atlas.investment.research.models import utc_now_iso

# Conservative defaults for India cash-equity simulation (not advice).
DEFAULT_FAIR_PE = 18.0
DEFAULT_DISCOUNT_RATE = 0.12
DEFAULT_GROWTH = 0.04
DEFAULT_TERMINAL_GROWTH = 0.03
MIN_MOS_BUY_PCT = 15.0


def _f(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def fair_pe_from_quality(*, roe: float | None = None, sector: str | None = None) -> float:
    """Soft fair PE band from quality proxies (illustrative, not a model)."""
    base = DEFAULT_FAIR_PE
    if roe is not None:
        # Higher ROE → slightly higher fair multiple (capped).
        roe_pct = roe * 100.0 if abs(roe) <= 1.5 else roe
        base = 12.0 + min(18.0, max(0.0, roe_pct) * 0.4)
    sec = (sector or "").lower()
    if "bank" in sec or "financial" in sec:
        base = min(base, 16.0)
    if "information technology" in sec or sec == "it":
        base = max(base, 20.0)
    return round(base, 2)


def dcf_value(
    fcf: float,
    *,
    growth: float = DEFAULT_GROWTH,
    discount_rate: float = DEFAULT_DISCOUNT_RATE,
    years: int = 5,
    terminal_growth: float = DEFAULT_TERMINAL_GROWTH,
) -> dict[str, Any]:
    """Simple multi-year FCF DCF → terminal Gordon. Units = FCF currency units."""
    r = max(0.05, float(discount_rate))
    g = min(float(growth), r - 0.01)
    tg = min(float(terminal_growth), r - 0.01)
    n = max(1, int(years))
    cashflows: list[dict[str, float]] = []
    pv = 0.0
    cf = float(fcf)
    for t in range(1, n + 1):
        cf = cf * (1.0 + g)
        disc = cf / ((1.0 + r) ** t)
        cashflows.append({"year": float(t), "fcf": round(cf, 4), "pv": round(disc, 4)})
        pv += disc
    terminal = (cf * (1.0 + tg)) / (r - tg)
    terminal_pv = terminal / ((1.0 + r) ** n)
    total = pv + terminal_pv
    return {
        "method": "dcf_fcf_stub",
        "years": n,
        "growth": g,
        "discount_rate": r,
        "terminal_growth": tg,
        "cashflows": cashflows,
        "terminal_value": round(terminal, 4),
        "terminal_pv": round(terminal_pv, 4),
        "enterprise_value_stub": round(total, 4),
        "note": (
            "EV stub in FCF currency units — not per-share IV unless shares/price supplied"
        ),
    }


def margin_of_safety_pct(
    *,
    intrinsic: float | None,
    price: float | None = None,
    pe: float | None = None,
    fair_pe: float | None = None,
) -> tuple[float | None, str]:
    """Return (MoS %, method). Positive = cheap vs estimate."""
    if intrinsic is not None and price is not None and price > 0:
        return round(100.0 * (float(intrinsic) - float(price)) / float(price), 2), "price_vs_iv"
    if pe is not None and pe > 0 and fair_pe is not None and fair_pe > 0:
        # Trading below fair multiple → positive MoS
        return round(100.0 * (float(fair_pe) - float(pe)) / float(pe), 2), "pe_vs_fair"
    return None, "unavailable"


def build_valuation_case(
    *,
    symbol: str,
    ratios: dict[str, Any] | None = None,
    price: float | None = None,
    shares: float | None = None,
    valuation_id: str | None = None,
) -> dict[str, Any]:
    """Build ValuationCase v1: multiples-first, DCF when FCF present."""
    ratios = dict(ratios or {})
    pe = _f(ratios.get("pe"))
    roe = _f(ratios.get("roe"))
    roic = _f(ratios.get("roic"))
    de = _f(ratios.get("debt_to_equity"))
    fcf = _f(ratios.get("fcf"))
    sector = ratios.get("sector")
    industry_pe = _f(ratios.get("industry_pe_median"))
    industry_pb = _f(ratios.get("industry_pb_median"))
    fair_pe = fair_pe_from_quality(roe=roe, sector=str(sector) if sector else None)
    fair_pe_source = "quality_heuristic"
    price_f = _f(price)
    shares_f = _f(shares)

    gaps: list[str] = []
    scenarios: dict[str, Any] = {}
    method = "multiples"
    intrinsic: float | None = None
    dcf: dict[str, Any] | None = None

    pe_vs_industry: float | None = None
    if pe is not None and industry_pe is not None and industry_pe > 0:
        pe_vs_industry = round(100.0 * (industry_pe - pe) / pe, 2)

    if pe is None and fcf is None:
        gaps.append("valuation: PE/FCF unavailable — MoS unknown")
        method = "insufficient"
        scenarios["base"] = "No PE or FCF — cannot form intrinsic estimate"
    else:
        scenarios["multiples"] = {
            "pe": pe,
            "fair_pe": fair_pe,
            "fair_pe_source": fair_pe_source,
            "industry_pe_median": industry_pe,
            "note": (
                "Fair PE is a hermetic quality band, not a sell-side target "
                "and not an industry average unless industry_pe_median was imported."
            ),
        }
        if industry_pe is None and pe is not None:
            gaps.append(
                "valuation: industry_pe_median not imported — "
                "cannot claim PE vs industry average"
            )

    if fcf is not None and fcf > 0:
        dcf = dcf_value(fcf)
        scenarios["dcf_base"] = {
            "fcf": fcf,
            "enterprise_value_stub": dcf["enterprise_value_stub"],
            "assumptions": {
                "growth": dcf["growth"],
                "discount_rate": dcf["discount_rate"],
                "terminal_growth": dcf["terminal_growth"],
            },
        }
        # Bear / bull growth bands
        bear = dcf_value(fcf, growth=max(0.0, DEFAULT_GROWTH - 0.02))
        bull = dcf_value(fcf, growth=DEFAULT_GROWTH + 0.02)
        scenarios["dcf_bear"] = {"enterprise_value_stub": bear["enterprise_value_stub"]}
        scenarios["dcf_bull"] = {"enterprise_value_stub": bull["enterprise_value_stub"]}
        method = "multiples+dcf"
        if shares_f is not None and shares_f > 0:
            intrinsic = dcf["enterprise_value_stub"] / shares_f
            scenarios["per_share"] = {"shares": shares_f, "iv": round(intrinsic, 4)}
        elif price_f is not None and price_f > 0:
            # Without shares: treat EV stub as not comparable to price — keep PE MoS
            gaps.append("dcf: shares outstanding unknown — MoS uses PE band when available")
        else:
            gaps.append("dcf: no price/shares — EV stub only; MoS from PE if available")
    elif fcf is not None and fcf <= 0:
        gaps.append("dcf: FCF non-positive — DCF skipped")
        scenarios["dcf_base"] = "FCF ≤ 0 — no DCF"

    mos, mos_method = margin_of_safety_pct(
        intrinsic=intrinsic,
        price=price_f,
        pe=pe,
        fair_pe=fair_pe if pe is not None else None,
    )
    if mos is None and "MoS unknown" not in " ".join(gaps):
        gaps.append("valuation: MoS unknown without IV/price or PE")

    missing_inputs = valuation_missing_inputs(
        pe=pe,
        fcf=fcf,
        price=price_f,
        shares=shares_f,
        method=method,
        ratios=ratios,
    )
    # Display method: simple_multiple when PE MoS only
    display_method = method
    if method == "multiples" and pe is not None:
        display_method = "simple_multiple"
    elif method == "multiples+dcf":
        display_method = "multiples+dcf"

    case = {
        "id": valuation_id or f"val-{symbol}",
        "as_of": utc_now_iso(),
        "method": display_method if display_method != "multiples" else method,
        "pe": pe,
        "fair_pe": fair_pe if pe is not None else None,
        "fair_pe_source": fair_pe_source if pe is not None else None,
        "industry_pe_median": industry_pe,
        "industry_pb_median": industry_pb,
        "pe_vs_industry_median_pct": pe_vs_industry,
        "may_claim_below_industry_pe": bool(
            pe is not None and industry_pe is not None and pe < industry_pe
        ),
        "roe": roe,
        "roic": roic,
        "debt_to_equity": de,
        "fcf": fcf,
        "price": price_f,
        "intrinsic_value": round(intrinsic, 4) if intrinsic is not None else None,
        "margin_of_safety_pct": mos,
        "mos_method": mos_method,
        "dcf": dcf,
        "scenarios": scenarios,
        "gaps": gaps,
        "missing_inputs": missing_inputs,
        "min_mos_buy_pct": MIN_MOS_BUY_PCT,
        "evidence_confidence": ratios.get("evidence_confidence") or ratios.get("confidence"),
        "source": ratios.get("source"),
    }
    case.update(valuation_method_meta(case))
    return case



def valuation_missing_inputs(
    *,
    pe: float | None,
    fcf: float | None,
    price: float | None,
    shares: float | None,
    method: str,
    ratios: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Operator-facing checklist: why DCF / MoS failed (never invent values)."""
    ratios = ratios or {}
    items: list[dict[str, Any]] = [
        {
            "id": "trailing_or_5y_fcf",
            "label": "Trailing or 5-year free cash flow",
            "present": fcf is not None and fcf > 0,
            "priority": "critical",
        },
        {
            "id": "current_price",
            "label": "Current price (price vs IV MoS)",
            "present": price is not None and price > 0,
            "priority": "critical",
        },
        {
            "id": "shares_outstanding",
            "label": "Shares outstanding (per-share intrinsic value)",
            "present": shares is not None and shares > 0,
            "priority": "critical",
        },
        {
            "id": "trading_pe",
            "label": "Trading PE (for multiples MoS)",
            "present": pe is not None and pe > 0,
            "priority": "critical",
        },
        {
            "id": "capex",
            "label": "Capital expenditure (growth vs maintenance)",
            "present": _f(ratios.get("capex")) is not None,
            "priority": "important",
        },
        {
            "id": "growth_assumptions",
            "label": "Explicit growth assumptions (operator)",
            "present": _f(ratios.get("fcf_growth")) is not None
            or _f(ratios.get("revenue_cagr")) is not None,
            "priority": "important",
        },
        {
            "id": "discount_rate",
            "label": "Discount rate (operator override; stub default exists)",
            "present": _f(ratios.get("discount_rate")) is not None,
            "priority": "important",
            "note": "Default 12% only used when FCF exists — not a substitute for judgment",
        },
        {
            "id": "roic",
            "label": "ROIC / return on capital",
            "present": _f(ratios.get("roic")) is not None,
            "priority": "important",
        },
        {
            "id": "debt_to_equity",
            "label": "Debt / equity",
            "present": _f(ratios.get("debt_to_equity")) is not None,
            "priority": "important",
        },
        {
            "id": "insider_or_promoter",
            "label": "Insider / promoter holding trend",
            "present": _f(ratios.get("promoter_holding")) is not None,
            "priority": "optional",
        },
        {
            "id": "dividend_history",
            "label": "Dividend history",
            "present": _f(ratios.get("dividend_yield")) is not None,
            "priority": "optional",
        },
    ]
    # Multiples MoS can work with PE alone; DCF needs FCF+price+shares.
    # Keep PE critical for MoS path; FCF/price/shares critical for DCF path.
    if method == "insufficient":
        for row in items:
            if not row["present"]:
                row["blocks"] = "dcf_and_mos"
    return items


def valuation_method_meta(valuation: dict[str, Any] | None) -> dict[str, Any]:
    """Label method + confidence for operator (locked MoS v1)."""
    if not isinstance(valuation, dict):
        return {
            "method": "insufficient",
            "method_label": "Insufficient",
            "method_confidence": "very_low",
        }
    method = str(valuation.get("method") or "insufficient")
    mos = valuation.get("margin_of_safety_pct")
    pe = valuation.get("pe")
    fcf = valuation.get("fcf")
    dcf = valuation.get("dcf")
    if method == "insufficient":
        label, conf = "Insufficient", "very_low"
    elif method == "multiples+dcf" and dcf:
        label, conf = "Hybrid (multiples + DCF stub)", "medium" if mos is not None else "low"
    elif method == "multiples" or (pe is not None and mos is not None):
        label, conf = "Simple multiple (PE vs fair)", "low"
    elif fcf is not None and dcf:
        label, conf = "DCF stub (trailing FCF)", "low"
    else:
        label, conf = method.replace("_", " ").title(), "low"
    # Estimated operator inputs pull confidence down
    ev_conf = str(valuation.get("evidence_confidence") or "").lower()
    if ev_conf == "estimated" and conf == "medium":
        conf = "low"
    return {
        "method": method,
        "method_label": label,
        "method_confidence": conf,
    }


def thesis_stance_from_valuation(valuation: dict[str, Any] | None) -> str:
    """Map MoS → stance. Unknown MoS → watch (force Watch without MoS)."""
    if not isinstance(valuation, dict):
        return "watch"
    mos = valuation.get("margin_of_safety_pct")
    if mos is None:
        return "watch"
    try:
        m = float(mos)
    except (TypeError, ValueError):
        return "watch"
    if m >= MIN_MOS_BUY_PCT:
        return "buy_candidate"
    if m >= 0:
        return "watch_positive"
    if m >= -15:
        return "watch"
    return "avoid"
