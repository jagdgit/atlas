"""Indian markets World Model pack (Market Program content on platform framework)."""

from __future__ import annotations

from atlas.world_models.framework import StaticWorldModelPack, WorldFact


def indian_markets_pack() -> StaticWorldModelPack:
    facts = [
        WorldFact(
            id="ex.nse",
            kind="exchange",
            label="National Stock Exchange of India (NSE)",
            attributes={"country": "IN", "currency": "INR", "timezone": "Asia/Kolkata"},
            tags=("nse", "india", "equity"),
        ),
        WorldFact(
            id="ex.bse",
            kind="exchange",
            label="BSE Limited (Bombay Stock Exchange)",
            attributes={"country": "IN", "currency": "INR", "timezone": "Asia/Kolkata"},
            tags=("bse", "india", "equity"),
        ),
        WorldFact(
            id="idx.nifty50",
            kind="index",
            label="NIFTY 50",
            attributes={
                "exchange": "NSE",
                "currency": "INR",
                "constituents_ref": "atlas.investment.universe.NIFTY50",
                "size": 50,
                "note": "Static snapshot for IL.1; lags NSE reconstitutions",
            },
            tags=("nifty", "india", "universe", "equity"),
        ),
        WorldFact(
            id="session.equity.regular",
            kind="session",
            label="Equity regular session",
            attributes={
                "open": "09:15",
                "close": "15:30",
                "timezone": "Asia/Kolkata",
                "preopen": "09:00-09:15",
            },
            tags=("nse", "bse", "hours"),
        ),
        WorldFact(
            id="settlement.equity.t1",
            kind="settlement",
            label="Equity settlement T+1",
            attributes={"cycle": "T+1", "asset_class": "equity", "note": "sim approx"},
            tags=("settlement", "equity"),
        ),
        WorldFact(
            id="sector.energy",
            kind="sector",
            label="Energy",
            attributes={"examples": ["RELIANCE.NS", "ONGC.NS"]},
            tags=("sector",),
        ),
        WorldFact(
            id="sector.it",
            kind="sector",
            label="Information Technology",
            attributes={"examples": ["TCS.NS", "INFY.NS"]},
            tags=("sector", "it"),
        ),
        WorldFact(
            id="sector.banking",
            kind="sector",
            label="Banking / Financials",
            attributes={"examples": ["HDFCBANK.NS", "ICICIBANK.NS"]},
            tags=("sector", "banks"),
        ),
        WorldFact(
            id="sector.pharma",
            kind="sector",
            label="Pharmaceuticals",
            attributes={"examples": ["SUNPHARMA.NS"]},
            tags=("sector",),
        ),
        WorldFact(
            id="ca.dividend",
            kind="corporate_action",
            label="Dividend",
            attributes={"affects": ["cash", "ex_date"]},
            tags=("corporate_action",),
        ),
        WorldFact(
            id="ca.split",
            kind="corporate_action",
            label="Stock split",
            attributes={"affects": ["quantity", "price"]},
            tags=("corporate_action",),
        ),
        WorldFact(
            id="risk.circuit",
            kind="risk_structure",
            label="Circuit filter / price band",
            attributes={"note": "exchange-imposed move limits; sim may approximate"},
            tags=("circuit", "risk"),
        ),
    ]
    return StaticWorldModelPack(
        id="indian_markets",
        name="Indian Markets",
        program_hint="market",
        version="wm.1",
        _facts=facts,
        description=(
            "Exchanges, sessions, T+1 settlement, sectors, corporate-action kinds "
            "for the Market Intelligence Program (structure ≠ Knowledge claims)."
        ),
    )
