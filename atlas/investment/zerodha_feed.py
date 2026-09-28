"""Zerodha Kite Connect live market data (OI-ZERODHA0).

Read-only quotes / LTP / OHLC for Indian equities (.NS / .BO). Does **not**
place orders (Atlas P10 — simulation only).

Auth model (Kite Connect):
  1. ``login_url()`` → operator logs in on Zerodha
  2. Redirect returns ``request_token``
  3. ``complete_login(request_token)`` → daily ``access_token`` (until ~midnight IST)
  4. Subsequent ``get_ltp`` / ``get_quote`` use the stored session

Credentials come from env (never YAML secrets):
  ``ZERODHA_API_KEY``, ``ZERODHA_API_SECRET``, optional ``ZERODHA_ACCESS_TOKEN``,
  optional ``ZERODHA_REDIRECT_URL``.

Requires optional package: ``pip install kiteconnect``.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo

_log = logging.getLogger("atlas.investment.zerodha_feed")
_IST = ZoneInfo("Asia/Kolkata")
VERSION = "zerodha.feed.v1"
STORE_REL = Path("investment") / "zerodha"


def _ist_today() -> date:
    return datetime.now(_IST).date()


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip().strip("'").strip('"')


class ZerodhaMarketFeed:
    """Market feed adapter for Zerodha Kite Connect (quotes only)."""

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        *,
        access_token: str | None = None,
        redirect_url: str | None = None,
        data_dir: str | Path | None = None,
        client: Any | None = None,
    ) -> None:
        self._api_key = (api_key if api_key is not None else _env("ZERODHA_API_KEY")).strip()
        self._api_secret = (
            api_secret if api_secret is not None else _env("ZERODHA_API_SECRET")
        ).strip()
        self._access_token = (
            access_token if access_token is not None else _env("ZERODHA_ACCESS_TOKEN")
        ).strip()
        self._redirect_url = (
            redirect_url if redirect_url is not None else _env("ZERODHA_REDIRECT_URL")
        ).strip() or "http://127.0.0.1:8000"
        self._data_dir = Path(data_dir) if data_dir else None
        self._client = client
        self._initialized = client is not None
        self._nfo_futs: list[dict[str, Any]] | None = None
        self._nfo_futs_ist_day: str | None = None
        self._nfo_opts: list[dict[str, Any]] | None = None
        self._nfo_opts_ist_day: str | None = None

    @classmethod
    def from_env(cls, *, data_dir: str | Path | None = None) -> "ZerodhaMarketFeed":
        return cls(data_dir=data_dir)

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key and self._api_secret)

    @property
    def has_session(self) -> bool:
        if self._access_token:
            return True
        doc = self._load_session()
        return bool(doc.get("access_token") and doc.get("ist_day") == _ist_today().isoformat())

    def status(self) -> dict[str, Any]:
        sess = self._load_session()
        return {
            "version": VERSION,
            "configured": self.is_configured,
            "has_session": self.has_session,
            "api_key_set": bool(self._api_key),
            "redirect_url": self._redirect_url,
            "session_ist_day": sess.get("ist_day"),
            "session_user_id": sess.get("user_id"),
            "kiteconnect_importable": self._kite_importable(),
        }

    @staticmethod
    def _kite_importable() -> bool:
        try:
            import kiteconnect  # noqa: F401

            return True
        except ImportError:
            return False

    def _session_path(self) -> Path | None:
        if not self._data_dir:
            return None
        return Path(self._data_dir) / STORE_REL / "session.json"

    def _load_session(self) -> dict[str, Any]:
        path = self._session_path()
        if not path or not path.is_file():
            return {}
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            return doc if isinstance(doc, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_session(self, doc: dict[str, Any]) -> None:
        path = self._session_path()
        if not path:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        except OSError:
            _log.debug("zerodha session write failed", exc_info=True)

    def clear_session(self) -> dict[str, Any]:
        """Drop today's stored access_token so the operator can force a fresh login.

        Zerodha access tokens are day-scoped and cannot be refreshed without human
        2FA — clearing is the only honest recovery when a morning login was missed
        or the token later fails mid-session.
        """
        path = self._session_path()
        removed = False
        if path and path.is_file():
            try:
                path.unlink()
                removed = True
            except OSError as exc:
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        self._access_token = None
        self._client = None
        self._initialized = False
        return {
            "ok": True,
            "cleared": removed,
            "login_path": "/zerodha/login",
            "force_login_path": "/zerodha/force-login",
            "hint": "Open /zerodha/force-login (or /zerodha/login) to obtain a new daily access_token.",
        }

    def _resolve_access_token(self) -> str | None:
        if self._access_token:
            return self._access_token
        doc = self._load_session()
        if doc.get("ist_day") == _ist_today().isoformat() and doc.get("access_token"):
            return str(doc["access_token"])
        return None

    def _init_client(self, *, require_session: bool = True) -> bool:
        token = self._resolve_access_token()
        if require_session and not token and self._client is None:
            return False
        if self._client is not None:
            if require_session:
                if not token:
                    return False
                try:
                    self._client.set_access_token(token)
                except Exception:  # noqa: BLE001
                    pass
            return True
        if not self.is_configured:
            return False
        try:
            from kiteconnect import KiteConnect
        except ImportError:
            _log.debug("kiteconnect not installed (`pip install kiteconnect`)")
            return False
        try:
            kite = KiteConnect(api_key=self._api_key)
            if require_session:
                if not token:
                    return False
                kite.set_access_token(token)
            elif token:
                kite.set_access_token(token)
            self._client = kite
            self._initialized = True
            return True
        except Exception as exc:  # noqa: BLE001
            _log.warning("failed to initialize KiteConnect: %s", exc)
            return False

    def login_url(self) -> dict[str, Any]:
        """Return the Zerodha login URL the operator must open once per day."""
        if not self.is_configured:
            return {"ok": False, "error": "zerodha_not_configured"}
        if not self._init_client(require_session=False) or self._client is None:
            return {
                "ok": False,
                "error": "kiteconnect_unavailable",
                "hint": "pip install kiteconnect",
            }
        try:
            url = self._client.login_url()
            return {
                "ok": True,
                "login_url": url,
                "redirect_url": self._redirect_url,
                "hint": (
                    "Open login_url, complete Zerodha login, then call "
                    "complete_login(request_token) with the request_token from the redirect."
                ),
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def complete_login(self, request_token: str) -> dict[str, Any]:
        """Exchange request_token for a daily access_token and persist it."""
        token = (request_token or "").strip()
        if not token:
            return {"ok": False, "error": "missing_request_token"}
        if not self.is_configured:
            return {"ok": False, "error": "zerodha_not_configured"}
        if not self._init_client(require_session=False) or self._client is None:
            return {"ok": False, "error": "kiteconnect_unavailable"}
        try:
            data = self._client.generate_session(token, api_secret=self._api_secret)
            access = str(data.get("access_token") or "")
            if not access:
                return {"ok": False, "error": "no_access_token_in_response", "raw": data}
            self._client.set_access_token(access)
            self._access_token = access
            sess = {
                "version": VERSION,
                "ist_day": _ist_today().isoformat(),
                "access_token": access,
                "user_id": data.get("user_id"),
                "login_time": datetime.now(timezone.utc).isoformat(),
            }
            self._save_session(sess)
            return {
                "ok": True,
                "user_id": data.get("user_id"),
                "ist_day": sess["ist_day"],
                "session_persisted": self._session_path() is not None,
            }
        except Exception as exc:  # noqa: BLE001
            _log.warning("Zerodha complete_login failed: %s", exc)
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    @staticmethod
    def format_symbol(symbol: str) -> str:
        """Atlas ``RELIANCE.NS`` / ``TCS`` → Zerodha trading symbol ``RELIANCE``."""
        sym = (symbol or "").strip().upper()
        if sym.endswith(".NS") or sym.endswith(".BO"):
            return sym[:-3]
        return sym

    @staticmethod
    def format_instrument(symbol: str, exchange: str = "NSE") -> str:
        """Atlas symbol → Kite instrument ``NSE:RELIANCE``."""
        clean = ZerodhaMarketFeed.format_symbol(symbol)
        ex = "BSE" if (symbol or "").upper().endswith(".BO") else exchange
        return f"{ex}:{clean}"

    def _nfo_fut_cache_path(self) -> Path | None:
        if not self._data_dir:
            return None
        return Path(self._data_dir) / STORE_REL / "nfo_fut.json"

    def list_nfo_futures(self, *, force: bool = False) -> list[dict[str, Any]]:
        """NFO futures only (never persist the options chain)."""
        day = _ist_today().isoformat()
        if (
            not force
            and self._nfo_futs is not None
            and self._nfo_futs_ist_day == day
        ):
            return self._nfo_futs
        path = self._nfo_fut_cache_path()
        if not force and path is not None and path.is_file():
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
                if (
                    isinstance(doc, dict)
                    and doc.get("ist_day") == day
                    and isinstance(doc.get("rows"), list)
                ):
                    self._nfo_futs = [r for r in doc["rows"] if isinstance(r, dict)]
                    self._nfo_futs_ist_day = day
                    return self._nfo_futs
            except (OSError, json.JSONDecodeError):
                pass
        rows: list[dict[str, Any]] = []
        opt_rows: list[dict[str, Any]] = []
        if self.has_session and self._init_client(require_session=True) and self._client is not None:
            try:
                raw = self._client.instruments("NFO")
            except Exception as exc:  # noqa: BLE001
                _log.warning("Zerodha NFO instruments() failed: %s", exc)
                raw = None
            if isinstance(raw, list):
                from atlas.investment.fno_contract import INDEX_UNIVERSE, is_index_option_row
                from atlas.investment.fno_lab_v1 import load_stock_seed

                seed_names = set(load_stock_seed(self._data_dir))
                for row in raw:
                    if not isinstance(row, dict):
                        continue
                    itype = str(row.get("instrument_type") or "").upper()
                    slim = {
                        "tradingsymbol": row.get("tradingsymbol"),
                        "name": row.get("name"),
                        "instrument_type": row.get("instrument_type"),
                        "instrument_token": row.get("instrument_token"),
                        "expiry": row.get("expiry"),
                        "lot_size": row.get("lot_size"),
                        "exchange": row.get("exchange") or "NFO",
                        "segment": row.get("segment") or "NFO-FUT",
                    }
                    if itype == "FUT":
                        rows.append(slim)
                    elif itype in {"CE", "PE"}:
                        keep_index = any(
                            is_index_option_row(row, fam) for fam in INDEX_UNIVERSE
                        )
                        row_name = " ".join(str(row.get("name") or "").upper().split())
                        keep_stock = row_name in seed_names
                        if keep_index or keep_stock:
                            slim["segment"] = row.get("segment") or "NFO-OPT"
                            slim["strike"] = row.get("strike")
                            opt_rows.append(slim)
        self._nfo_futs = rows
        self._nfo_futs_ist_day = day
        if opt_rows or self._nfo_opts is None:
            self._nfo_opts = opt_rows
            self._nfo_opts_ist_day = day
        if path is not None and rows:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(
                        {"ist_day": day, "count": len(rows), "rows": rows},
                        indent=2,
                        default=str,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            except OSError:
                _log.debug("nfo_fut cache write failed", exc_info=True)
        return rows

    def list_nfo_options(
        self, *, expiry: str | date | datetime | None = None, force: bool = False
    ) -> list[dict[str, Any]]:
        """Index-family CE/PE (NIFTY/BANKNIFTY/FINNIFTY/MIDCPNIFTY) — memory, never persist the chain."""
        day = _ist_today().isoformat()
        if (
            not force
            and self._nfo_opts is not None
            and self._nfo_opts_ist_day == day
        ):
            rows = list(self._nfo_opts)
        else:
            # Reuse the FUT fetch when it already parsed options from instruments().
            self.list_nfo_futures(force=force)
            rows = list(self._nfo_opts or [])
            if not rows and self.has_session and self._init_client(require_session=True) and self._client is not None:
                try:
                    raw = self._client.instruments("NFO")
                except Exception as exc:  # noqa: BLE001
                    _log.warning("Zerodha NFO options instruments() failed: %s", exc)
                    raw = None
                parsed: list[dict[str, Any]] = []
                if isinstance(raw, list):
                    from atlas.investment.fno_contract import INDEX_UNIVERSE, is_index_option_row
                    from atlas.investment.fno_lab_v1 import load_stock_seed

                    seed_names = set(load_stock_seed(self._data_dir))
                    for row in raw:
                        if not isinstance(row, dict):
                            continue
                        itype = str(row.get("instrument_type") or "").upper()
                        if itype not in {"CE", "PE"}:
                            continue
                        keep_index = any(
                            is_index_option_row(row, fam) for fam in INDEX_UNIVERSE
                        )
                        row_name = " ".join(str(row.get("name") or "").upper().split())
                        if not (keep_index or row_name in seed_names):
                            continue
                        parsed.append(
                            {
                                "tradingsymbol": row.get("tradingsymbol"),
                                "name": row.get("name"),
                                "instrument_type": row.get("instrument_type"),
                                "instrument_token": row.get("instrument_token"),
                                "expiry": row.get("expiry"),
                                "lot_size": row.get("lot_size"),
                                "strike": row.get("strike"),
                                "exchange": row.get("exchange") or "NFO",
                                "segment": row.get("segment") or "NFO-OPT",
                            }
                        )
                self._nfo_opts = parsed
                self._nfo_opts_ist_day = day
                rows = parsed
        if expiry is None:
            return rows
        from atlas.investment.fno_contract import _expiry_date

        want = _expiry_date(expiry)
        if want is None:
            return rows
        return [r for r in rows if _expiry_date(r.get("expiry")) == want]

    def resolve_phase1_fut(
        self, symbol: str, *, as_of: date | datetime | None = None
    ) -> dict[str, Any]:
        from atlas.investment.fno_contract import resolve_nearest_fut

        return resolve_nearest_fut(
            self.list_nfo_futures(), symbol=symbol, as_of=as_of
        )

    def kite_quote_instrument(self, symbol: str, *, exchange: str = "NSE") -> str:
        """Kite ``EXCH:SYM`` for LTP/quote.

        Bare ``NIFTY`` uses the nearest NFO FUT. CE/PE/FUT tradingsymbols stay
        on NFO — never remap an option onto the index future.
        """
        from atlas.investment.fno_contract import (
            is_phase1_underlying,
            kite_instrument,
            option_right,
        )

        raw = (symbol or "").strip().upper()
        if raw.startswith("NFO:"):
            return raw
        if option_right(raw) or (
            raw.endswith("FUT") and not is_phase1_underlying(raw)
        ):
            return f"NFO:{self.format_symbol(raw)}"
        if is_phase1_underlying(symbol):
            labeled = kite_instrument(self.resolve_phase1_fut(symbol))
            if labeled:
                return labeled
        return self.format_instrument(symbol, exchange=exchange)

    def get_ltp(self, symbols: str | Sequence[str]) -> dict[str, Any]:
        """Fetch last traded price for one or more Atlas symbols."""
        if not self.is_configured:
            return {"ok": False, "error": "zerodha_not_configured"}
        if not self.has_session:
            return {
                "ok": False,
                "error": "zerodha_session_required",
                "hint": "Call login_url() then complete_login(request_token)",
            }
        if not self._init_client(require_session=True) or self._client is None:
            return {"ok": False, "error": "kiteconnect_unavailable"}

        sym_list = [symbols] if isinstance(symbols, str) else list(symbols)
        if not sym_list:
            return {"ok": True, "prices": {}}

        instruments = [self.kite_quote_instrument(s) for s in sym_list]
        try:
            resp = self._client.ltp(instruments)
            now_iso = datetime.now(timezone.utc).isoformat()
            prices: dict[str, dict[str, Any]] = {}
            if isinstance(resp, dict):
                for inst, orig in zip(instruments, sym_list):
                    row = resp.get(inst) or {}
                    last = row.get("last_price") if isinstance(row, dict) else None
                    if last is None and isinstance(row, (int, float)):
                        last = row
                    if last is not None:
                        prices[orig] = {
                            "last": float(last),
                            "as_of": now_iso,
                            "source": "zerodha",
                            "instrument": inst,
                            "instrument_token": (
                                row.get("instrument_token") if isinstance(row, dict) else None
                            ),
                        }
            return {"ok": True, "prices": prices, "raw": resp}
        except Exception as exc:  # noqa: BLE001
            _log.warning("Zerodha get_ltp error: %s", exc)
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def get_quote(self, symbol: str, *, exchange: str = "NSE") -> dict[str, Any]:
        """Fetch a fuller quote for one Atlas symbol."""
        if not self.is_configured:
            return {"ok": False, "error": "zerodha_not_configured"}
        if not self.has_session:
            return {
                "ok": False,
                "error": "zerodha_session_required",
                "hint": "Call login_url() then complete_login(request_token)",
            }
        if not self._init_client(require_session=True) or self._client is None:
            return {"ok": False, "error": "kiteconnect_unavailable"}

        inst = self.kite_quote_instrument(symbol, exchange=exchange)
        try:
            resp = self._client.quote([inst])
            row = (resp or {}).get(inst) or {}
            ohlc = row.get("ohlc") if isinstance(row.get("ohlc"), dict) else {}
            now_iso = datetime.now(timezone.utc).isoformat()
            mark = {
                "last": row.get("last_price"),
                "open": ohlc.get("open"),
                "high": ohlc.get("high"),
                "low": ohlc.get("low"),
                "close": ohlc.get("close"),
                "volume": row.get("volume"),
                "as_of": now_iso,
                "source": "zerodha",
                "instrument": inst,
            }
            return {"ok": True, "symbol": symbol, "mark": mark, "raw": row}
        except Exception as exc:  # noqa: BLE001
            _log.warning("Zerodha get_quote error for %s: %s", symbol, exc)
            return {"ok": False, "symbol": symbol, "error": f"{type(exc).__name__}: {exc}"}

    def resolve_instrument_token(self, symbol: str, *, exchange: str = "NSE") -> int | None:
        """Resolve instrument_token for historical candles.

        Equities: NSE/BSE EQ. F&O underlier ``NIFTY``: nearest NFO FUT
        (INDEX rows are skipped — ``NIFTY`` is not a tradable F&O object).
        Option CE/PE tradingsymbols resolve on NFO when passed explicitly.
        """
        clean = self.format_symbol(symbol)
        live_tok: int | None = None
        if self._init_client(require_session=True) and self._client is not None:
            try:
                rows = self._client.instruments(exchange)
            except Exception:  # noqa: BLE001
                rows = None
            if isinstance(rows, list):
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    if str(row.get("tradingsymbol") or "").upper() != clean:
                        continue
                    itype = str(row.get("instrument_type") or "").upper()
                    if itype and itype not in {"EQ", "FUT"}:
                        continue
                    if itype == "FUT" and exchange.upper() not in {"NFO", "MCX"}:
                        continue
                    tok = row.get("instrument_token")
                    if tok is not None:
                        live_tok = int(tok)
                        break
        if live_tok is not None:
            return live_tok

        # Exact NFO FUT tradingsymbol (already-resolved contract name).
        if clean.endswith("FUT"):
            for row in self.list_nfo_futures():
                if str(row.get("tradingsymbol") or "").upper() != clean:
                    continue
                tok = row.get("instrument_token")
                if tok is not None:
                    return int(tok)

        # Phase 1 — nearest NIFTY FUT (never CE/PE, never INDEX).
        try:
            from atlas.investment.fno_contract import is_phase1_underlying

            if is_phase1_underlying(symbol) or is_phase1_underlying(clean):
                fut = self.resolve_phase1_fut(symbol)
                if fut.get("ok") and fut.get("instrument_token") is not None:
                    return int(fut["instrument_token"])
        except Exception:  # noqa: BLE001
            _log.debug("phase1 nifty fut resolve failed for %s", symbol, exc_info=True)

        # Fallback: MDPH instrument meta (must look like a real dump)
        try:
            from atlas.investment.market_data_provider_health import load_instrument_meta

            meta = load_instrument_meta(self._data_dir) if self._data_dir else {}
            if int(meta.get("count") or 0) < 1000:
                return None
            mappings = meta.get("mappings") if isinstance(meta, dict) else None
            if isinstance(mappings, dict):
                for key in (symbol, clean, f"{clean}.NS", str(symbol).upper(), clean.upper()):
                    row = mappings.get(key)
                    if isinstance(row, dict) and row.get("instrument_token") is not None:
                        return int(row["instrument_token"])
        except Exception:  # noqa: BLE001
            pass
        return None

    @staticmethod
    def _kite_interval(interval: str) -> str:
        raw = (interval or "day").strip().lower()
        mapping = {
            "1m": "minute",
            "1min": "minute",
            "minute": "minute",
            "3m": "3minute",
            "5m": "5minute",
            "5min": "5minute",
            "5minute": "5minute",
            "10m": "10minute",
            "15m": "15minute",
            "30m": "30minute",
            "60m": "60minute",
            "1h": "60minute",
            "1d": "day",
            "day": "day",
            "daily": "day",
            "d": "day",
        }
        return mapping.get(raw, raw if "minute" in raw or raw == "day" else "day")

    def get_historical_bars(
        self,
        symbol: str,
        *,
        interval: str = "5minute",
        limit: int = 100,
        exchange: str = "NSE",
    ) -> dict[str, Any]:
        """OHLCV candles via Kite historical_data (quotes only — no orders)."""
        if not self.is_configured:
            return {"ok": False, "error": "zerodha_not_configured", "bars": []}
        if not self.has_session:
            return {
                "ok": False,
                "error": "zerodha_session_required",
                "bars": [],
                "hint": "Call login_url() then complete_login(request_token)",
            }
        if not self._init_client(require_session=True) or self._client is None:
            return {"ok": False, "error": "kiteconnect_unavailable", "bars": []}

        token = self.resolve_instrument_token(symbol, exchange=exchange)
        if token is None:
            return {
                "ok": False,
                "error": "instrument_token_unresolved",
                "bars": [],
                "symbol": symbol,
            }

        kite_iv = self._kite_interval(interval)
        from datetime import timedelta

        to_dt = datetime.now(_IST)
        if "minute" in kite_iv:
            days = max(2, min(30, int(limit / 50) + 2))
        else:
            days = max(40, min(400, int(limit) + 5))
        from_dt = to_dt - timedelta(days=days)
        try:
            raw = self._client.historical_data(
                token,
                from_dt,
                to_dt,
                kite_iv,
                continuous=False,
                oi=False,
            )
        except Exception as exc:  # noqa: BLE001
            _log.warning("Zerodha historical_data error for %s: %s", symbol, exc)
            return {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "bars": [],
                "symbol": symbol,
            }

        bars: list[dict[str, Any]] = []
        if isinstance(raw, list):
            for row in raw:
                if not isinstance(row, dict):
                    continue
                ts = row.get("date")
                if hasattr(ts, "isoformat"):
                    t_s = ts.isoformat()
                else:
                    t_s = str(ts) if ts is not None else None
                try:
                    bars.append(
                        {
                            "t": t_s,
                            "date": t_s,
                            "open": float(row["open"]),
                            "high": float(row["high"]),
                            "low": float(row["low"]),
                            "close": float(row["close"]),
                            "volume": float(row.get("volume") or 0),
                            "source": "zerodha",
                        }
                    )
                except (KeyError, TypeError, ValueError):
                    continue
        if limit and len(bars) > int(limit):
            bars = bars[-int(limit) :]
        return {
            "ok": True,
            "symbol": symbol,
            "interval": kite_iv,
            "instrument_token": token,
            "bars": bars,
            "count": len(bars),
            "source": "zerodha",
        }
