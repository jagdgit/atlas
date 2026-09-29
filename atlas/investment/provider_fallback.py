"""MDPH live-provider fallback — labeled substitutes, never silent Zerodha.

LOCKED honesty:
  - Live-required labs must not pretend Yahoo/Groww marks are Zerodha.
  - F&O stays paused without broker LTP (Yahoo cannot price ATM options).
  - Intraday may continue on Yahoo when Zerodha is LOGIN_REQUIRED/EXPIRED,
    with an explicit ``provider_fallback`` stamp (not silent).
  - Swing / non-live already uses Yahoo / bar_store.

Env ``ATLAS_MDPH_LIVE_FALLBACK``:
  off   — live-required pause when Zerodha not READY (classic MDPH)
  auto  — intraday→yahoo labeled; fno→pause; default when unset
  yahoo — force yahoo for live-required cash (still pause F&O)
  groww — try Groww when configured; else behave as auto
"""

from __future__ import annotations

import os
from typing import Any

VERSION = "mdph.provider_fallback.v1"

FALLBACK_OFF = "off"
FALLBACK_AUTO = "auto"
FALLBACK_YAHOO = "yahoo"
FALLBACK_GROWW = "groww"


def live_fallback_mode() -> str:
    raw = (os.environ.get("ATLAS_MDPH_LIVE_FALLBACK") or FALLBACK_AUTO).strip().lower()
    if raw in {FALLBACK_OFF, "0", "false", "no", "pause"}:
        return FALLBACK_OFF
    if raw in {FALLBACK_YAHOO, "yfinance"}:
        return FALLBACK_YAHOO
    if raw in {FALLBACK_GROWW}:
        return FALLBACK_GROWW
    return FALLBACK_AUTO


def groww_available() -> bool:
    """True when Groww credentials look real (not stub).

    MarketReader still has no Groww bars adapter — ``groww_bars_usable``
    gates actual tick substitution. Credentials alone do not unlock F&O.
    """
    try:
        from atlas.investment.groww_feed import GrowwMarketFeed

        tok = (os.environ.get("GROWW_AUTH_TOKEN") or "").strip()
        key = (os.environ.get("GROWW_API_KEY") or "").strip()
        secret = (os.environ.get("GROWW_API_SECRET") or "").strip()
        # Stub / placeholder tokens are not a live feed.
        if tok and len(tok) >= 20:
            feed = GrowwMarketFeed(auth_token=tok)
            return bool(feed.is_configured)
        if key and secret:
            feed = GrowwMarketFeed(api_key=key, api_secret=secret)
            return bool(feed.is_configured)
    except Exception:  # noqa: BLE001
        return False
    return False


def groww_bars_usable() -> bool:
    """Groww may supply LTP later; bars path is not wired into MarketReader yet."""
    return False


def _is_fno_lab(portfolio_key: str, cfg: dict[str, Any] | None) -> bool:
    pk = (portfolio_key or "").strip().lower()
    c = cfg if isinstance(cfg, dict) else {}
    ac = str(c.get("asset_class") or "").strip().lower()
    pack = str(c.get("instrument_pack") or "").strip().lower()
    if "fno" in pk or pk.endswith("_fno") or "fno_learner" in pk:
        return True
    return ac in {"futures", "options", "fno"} or pack in {"futures", "options", "fno"}


def _is_intraday_lab(portfolio_key: str, cfg: dict[str, Any] | None) -> bool:
    try:
        from atlas.investment.intraday_bars import is_intraday_lab

        return bool(is_intraday_lab(cfg if isinstance(cfg, dict) else {}, portfolio_key))
    except Exception:  # noqa: BLE001
        return "intraday" in (portfolio_key or "").lower()


def resolve_live_provider_plan(
    *,
    portfolio_key: str,
    cfg: dict[str, Any] | None = None,
    zerodha_health: dict[str, Any] | None = None,
    live_required: bool | None = None,
) -> dict[str, Any]:
    """Decide provider / pause for one lab tick.

    Returns keys: provider, paused, reason, fallback, zerodha_status, honesty
    """
    cfg = cfg if isinstance(cfg, dict) else {}
    pk = str(portfolio_key or cfg.get("portfolio_key") or "").strip()
    health = zerodha_health if isinstance(zerodha_health, dict) else {}
    z_status = str(health.get("status") or "")
    z_ready = bool(health.get("live_trading_allowed")) or z_status == "READY"
    configured = str(cfg.get("live_provider") or "yahoo").strip().lower() or "yahoo"

    if live_required is None:
        try:
            from atlas.investment.lab_contracts import live_required as _lr

            live_required = bool(_lr(pk, cfg=cfg))
        except Exception:  # noqa: BLE001
            live_required = False

    # Non-live: never pause for Zerodha — Yahoo / durable bars OK.
    if not live_required:
        if configured == "zerodha" and not z_ready:
            return {
                "version": VERSION,
                "provider": "yahoo",
                "paused": False,
                "reason": "non_live_zerodha_down_yahoo",
                "fallback": "yahoo",
                "zerodha_status": z_status or None,
                "honesty": (
                    "Non-live lab — Zerodha unavailable; using labeled Yahoo "
                    "(not a silent Zerodha substitute)."
                ),
            }
        return {
            "version": VERSION,
            "provider": configured if configured != "zerodha" or z_ready else "yahoo",
            "paused": False,
            "reason": "non_live",
            "fallback": None,
            "zerodha_status": z_status or None,
            "honesty": "Non-live lab continues on configured / Yahoo path.",
        }

    # Live-required + Zerodha READY → Zerodha only.
    if z_ready:
        return {
            "version": VERSION,
            "provider": "zerodha",
            "paused": False,
            "reason": "zerodha_ready",
            "fallback": None,
            "zerodha_status": z_status or "READY",
            "honesty": "Broker-authorized Zerodha session READY.",
        }

    mode = live_fallback_mode()
    fno = _is_fno_lab(pk, cfg)
    intraday = _is_intraday_lab(pk, cfg)

    # F&O: never Yahoo ATM — pause unless Groww bars are actually usable.
    if fno:
        if (
            mode in {FALLBACK_GROWW, FALLBACK_AUTO}
            and groww_available()
            and groww_bars_usable()
        ):
            return {
                "version": VERSION,
                "provider": "groww",
                "paused": False,
                "reason": "fno_zerodha_down_groww",
                "fallback": "groww",
                "zerodha_status": z_status or None,
                "honesty": (
                    "F&O Zerodha unavailable; using labeled Groww feed "
                    "(not silent Zerodha)."
                ),
            }
        return {
            "version": VERSION,
            "provider": None,
            "paused": True,
            "reason": "fno_paused_no_broker_ltp",
            "fallback": None,
            "zerodha_status": z_status or None,
            "honesty": (
                "F&O live-required — paused until Zerodha READY. "
                "Yahoo cannot supply ATM option LTP."
            ),
        }

    if mode == FALLBACK_OFF:
        return {
            "version": VERSION,
            "provider": None,
            "paused": True,
            "reason": "live_paused_fallback_off",
            "fallback": None,
            "zerodha_status": z_status or None,
            "honesty": "ATLAS_MDPH_LIVE_FALLBACK=off — live lab paused without Zerodha.",
        }

    if (
        (mode == FALLBACK_GROWW or mode == FALLBACK_AUTO)
        and groww_available()
        and groww_bars_usable()
    ):
        return {
            "version": VERSION,
            "provider": "groww",
            "paused": False,
            "reason": "live_zerodha_down_groww",
            "fallback": "groww",
            "zerodha_status": z_status or None,
            "honesty": "Live lab Zerodha down; labeled Groww fallback.",
        }

    # Intraday / other live cash: labeled Yahoo when auto/yahoo/groww-without-bars.
    if mode in {FALLBACK_AUTO, FALLBACK_YAHOO, FALLBACK_GROWW} and (
        intraday or not fno
    ):
        honesty = (
            "Live cash lab Zerodha unavailable; continuing on labeled Yahoo "
            f"({'intraday 5m' if intraday else 'daily'}). Not Zerodha."
        )
        if mode == FALLBACK_GROWW and groww_available() and not groww_bars_usable():
            honesty = (
                "Groww credentials present but bars adapter not wired; "
                "using labeled Yahoo (not Zerodha, not Groww)."
            )
        return {
            "version": VERSION,
            "provider": "yahoo",
            "paused": False,
            "reason": "live_zerodha_down_yahoo_labeled",
            "fallback": "yahoo",
            "zerodha_status": z_status or None,
            "honesty": honesty,
        }

    return {
        "version": VERSION,
        "provider": None,
        "paused": True,
        "reason": "live_paused",
        "fallback": None,
        "zerodha_status": z_status or None,
        "honesty": "Live-required lab paused — no allowable fallback.",
    }
