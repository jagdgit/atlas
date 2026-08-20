"""CAP.1 — Yahoo / durable symbol aliases (corporate renames + index ids).

Maps operator/universe symbols to the ticker Yahoo (and bar_store) actually serve.
Missing data stays missing — aliases never invent prices.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

VERSION = "cap1.symbol_aliases.v1"

# Operator / stale → Yahoo chart id (and preferred durable bar key)
_YAHOO_ALIASES: dict[str, str] = {
    "ZOMATO": "ETERNAL.NS",
    "ZOMATO.NS": "ETERNAL.NS",
    "TATAMOTORS": "TMPV.NS",
    "TATAMOTORS.NS": "TMPV.NS",
    "NIFTY": "^NSEI",
    "NIFTY.NS": "^NSEI",
    "NSEI": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "BANKNIFTY.NS": "^NSEBANK",
    "NSEBANK": "^NSEBANK",
    # HBL Power → HBL Engineering (A2 default probe target)
    "HBLPOWER": "HBLENGINE.NS",
    "HBLPOWER.NS": "HBLENGINE.NS",
    "HBLENGINEERING": "HBLENGINE.NS",
    "HBLENGINEERING.NS": "HBLENGINE.NS",
}


@dataclass(frozen=True)
class SymbolResolve:
    """Canonical Atlas key + Yahoo network id (may differ for indices)."""

    requested: str
    canonical: str  # preferred bar_store / WSO key
    yahoo: str  # chart API path segment
    aliased: bool
    identity_unknown: bool = False


def _norm_key(symbol: str) -> str:
    return (symbol or "").strip().upper()


def resolve_yahoo_symbol(symbol: str) -> SymbolResolve:
    """Resolve a requested symbol to Yahoo + durable canonical form."""
    raw = (symbol or "").strip()
    if not raw:
        return SymbolResolve(
            requested="",
            canonical="",
            yahoo="",
            aliased=False,
            identity_unknown=True,
        )
    key = _norm_key(raw)
    if key in _YAHOO_ALIASES:
        yahoo = _YAHOO_ALIASES[key]
        canonical = yahoo
        return SymbolResolve(
            requested=raw,
            canonical=canonical,
            yahoo=yahoo,
            aliased=True,
        )
    # Indices must not get a blind .NS suffix elsewhere
    if key.startswith("^"):
        return SymbolResolve(
            requested=raw,
            canonical=key,
            yahoo=key,
            aliased=False,
        )
    # Already .NS / .BO style — pass through
    if "." in raw:
        return SymbolResolve(
            requested=raw,
            canonical=raw.upper() if raw.endswith(".NS") else raw,
            yahoo=raw,
            aliased=False,
        )
    # Bare equity ticker — Yahoo India convention
    yahoo = f"{raw.upper()}.NS"
    return SymbolResolve(
        requested=raw,
        canonical=yahoo,
        yahoo=yahoo,
        aliased=False,
    )


def alias_map() -> dict[str, str]:
    """Copy of the static alias table (tests / ops)."""
    return dict(_YAHOO_ALIASES)


def is_seed_news_source(source: str | None) -> bool:
    """E0 — watchlist / open-book monitoring stubs are non-evidence."""
    s = str(source or "").strip().lower()
    return s in {
        "watchlist_seed",
        "open_book_seed",
        "seed",
        "monitoring_seed",
    }


def news_is_evidence(row: dict[str, Any] | None) -> bool:
    """False for seed / explicitly marked non-evidence rows."""
    if not isinstance(row, dict):
        return False
    if row.get("evidence_class") == "non_evidence" or row.get("seed") is True:
        return False
    pl = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    if pl.get("evidence_class") == "non_evidence" or pl.get("seed") is True:
        return False
    src = str(
        row.get("source") or pl.get("source") or row.get("provider") or ""
    )
    if is_seed_news_source(src):
        return False
    try:
        from atlas.investment.market_events import may_become_evidence

        if not may_become_evidence(row):
            return False
    except Exception:  # noqa: BLE001
        pass
    return True
