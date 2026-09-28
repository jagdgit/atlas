"""OI-LAB-LOOP0 Step 3 / TRADE-LOOP0 F — F&O object: index FUT + ATM CE/PE.

NIFTY/BANKNIFTY/FINNIFTY/MIDCPNIFTY are underliers, not tradable F&O contracts.
Resolve underlying → nearest unexpired NFO FUT → expiry → ATM CE/PE (never written).
Stock F&O is deferred (Phase 3b). No live orders. Do not persist the full chain.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "lab.loop0.fno.phase1.v1"
PHASE = "index_fut_nearest"
VERSION2 = "lab.loop0.fno.phase2.v1"
PHASE2 = "index_atm_ce_pe"
STRATEGY_TAG_ATM = "fno_atm_option"  # adapter id only — control stays sma_cross_rsi
CONTROL_STRATEGY_TAG = "sma_cross_rsi"
CONTROL_STRATEGY_VERSION = "sma_cross_rsi.v1"
ADAPTER_ID = "fno_atm_ce_pe.v1"
P2_EXPERIMENT_ID = "FNO-P2-001"
STRIKE_STEP = 50.0
STORE_REL = Path("investment") / "fno" / "contracts"
EXPERIMENT_REL = Path("investment") / "fno" / "experiments"
UNDERLYING = "NIFTY"
PHASE2_UNDERLYING = "NIFTY"
INDEX_UNIVERSE = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.fno_contract")

_FAMILIES: dict[str, dict[str, Any]] = {
    "NIFTY": {
        "aliases": frozenset({"NIFTY", "NIFTY50", "NIFTY-FUT", "^NSEI", "NSEI"}),
        "names": frozenset({"NIFTY", "NIFTY50", "NIFTY 50"}),
        "prefix": "NIFTY",
        "exclude_prefixes": (
            "BANKNIFTY",
            "FINNIFTY",
            "MIDCPNIFTY",
            "NIFTYNXT",
            "NIFTYIT",
        ),
        "strike_step": 50.0,
        "default_lot": 25,
    },
    "BANKNIFTY": {
        "aliases": frozenset({"BANKNIFTY", "BANKNIFTY-FUT", "^NSEBANK", "NSEBANK"}),
        "names": frozenset({"BANKNIFTY", "NIFTY BANK"}),
        "prefix": "BANKNIFTY",
        "exclude_prefixes": (),
        "strike_step": 100.0,
        "default_lot": 15,
    },
    "FINNIFTY": {
        "aliases": frozenset({"FINNIFTY", "FINNIFTY-FUT"}),
        "names": frozenset({"FINNIFTY", "NIFTY FIN SERVICE"}),
        "prefix": "FINNIFTY",
        "exclude_prefixes": (),
        "strike_step": 50.0,
        "default_lot": 25,
    },
    "MIDCPNIFTY": {
        "aliases": frozenset({"MIDCPNIFTY", "MIDCPNIFTY-FUT"}),
        "names": frozenset({"MIDCPNIFTY", "NIFTY MID SELECT"}),
        "prefix": "MIDCPNIFTY",
        "exclude_prefixes": (),
        "strike_step": 25.0,
        "default_lot": 75,
    },
}

_EXCLUDED_TSYM_PREFIXES = (
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "NIFTYNXT",
    "NIFTYIT",
)
_NIFTY_NAMES = frozenset({"NIFTY", "NIFTY50", "NIFTY 50"})


def ist_as_of(now: datetime | date | None = None) -> date:
    if isinstance(now, date) and not isinstance(now, datetime):
        return now
    clock = now if isinstance(now, datetime) else datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    return clock.astimezone(_IST).date()


def family_for_symbol(symbol: str) -> str | None:
    """Map an Atlas underlier or NFO tsym to an index family. Cash names → None."""
    key = str(symbol or "").strip().upper()
    if ":" in key:
        key = key.split(":", 1)[-1]
    if not key:
        return None
    for fam in ("MIDCPNIFTY", "BANKNIFTY", "FINNIFTY", "NIFTY"):
        spec = _FAMILIES[fam]
        if key in spec["aliases"]:
            return fam
        prefix = str(spec["prefix"])
        if key.startswith(prefix):
            if fam == "NIFTY" and any(
                key.startswith(ex) for ex in spec["exclude_prefixes"]
            ):
                continue
            return fam
    return None


def is_index_underlier(symbol: str) -> bool:
    """True for Phase-3a index underlier aliases (never cash, never CE/PE tsyms)."""
    key = str(symbol or "").strip().upper()
    if ":" in key:
        key = key.split(":", 1)[-1]
    if option_right(key) is not None:
        return False
    if key.endswith("FUT") and key not in {
        "NIFTY-FUT",
        "BANKNIFTY-FUT",
        "FINNIFTY-FUT",
        "MIDCPNIFTY-FUT",
    }:
        # tradingsymbols are contracts, not lab underliers
        return False
    fam = family_for_symbol(key)
    if fam is None:
        return False
    spec = _FAMILIES[fam]
    return key in spec["aliases"] or key == fam


def is_phase1_underlying(symbol: str) -> bool:
    """Back-compat: any Phase-3a index underlier (was NIFTY-only)."""
    return is_index_underlier(symbol)


def is_phase2_underlying(symbol: str) -> bool:
    """Phase 2 paper ATM CE/PE is NIFTY only. No BANKNIFTY/FINNIFTY/MIDCPNIFTY."""
    key = str(symbol or "").strip().upper()
    if ":" in key:
        key = key.split(":", 1)[-1]
    if family_for_symbol(key) != PHASE2_UNDERLYING:
        return False
    return is_index_underlier(key)


def equity_underlier_name(symbol: str | None) -> str | None:
    """Bare stock underlier for NFO (RELIANCE). None for indices / cash / contracts.

    Cash tape symbols (``RELIANCE.NS``) are rejected here — lab instruments use
    bare Kite names. Callers that accept ``.NS`` aliases should normalize first.
    """
    key = str(symbol or "").strip().upper()
    if ":" in key:
        key = key.split(":", 1)[-1]
    if not key:
        return None
    if key.endswith(".NS") or key.endswith(".BO"):
        return None
    if is_index_underlier(key) or family_for_symbol(key) is not None:
        return None
    if option_right(key) is not None:
        return None
    if key.endswith("FUT") and key not in {
        "NIFTY-FUT",
        "BANKNIFTY-FUT",
        "FINNIFTY-FUT",
        "MIDCPNIFTY-FUT",
    }:
        return None
    return key


def is_stock_fut_row(row: dict[str, Any] | None, name: str) -> bool:
    if not isinstance(row, dict):
        return False
    want = str(name or "").strip().upper()
    if not want:
        return False
    if str(row.get("instrument_type") or "").upper() != "FUT":
        return False
    # Never treat index FUT rows as stock.
    for fam in INDEX_UNIVERSE:
        if is_index_fut_row(row, fam):
            return False
    row_name = " ".join(str(row.get("name") or "").upper().split())
    tsym = str(row.get("tradingsymbol") or "").strip().upper()
    if row_name == want:
        return True
    return tsym.startswith(want) and tsym.endswith("FUT")


def is_stock_option_row(row: dict[str, Any] | None, name: str, right: str) -> bool:
    if not isinstance(row, dict):
        return False
    want = str(name or "").strip().upper()
    side = str(right or "").strip().upper()
    if not want or side not in {"CE", "PE"}:
        return False
    if str(row.get("instrument_type") or "").upper() != side:
        return False
    for fam in INDEX_UNIVERSE:
        if is_index_option_row(row, fam):
            return False
    row_name = " ".join(str(row.get("name") or "").upper().split())
    tsym = str(row.get("tradingsymbol") or "").strip().upper()
    if row_name == want and tsym.endswith(side):
        return True
    return tsym.startswith(want) and tsym.endswith(side)


def option_positions_for_underlier(
    positions: list[dict[str, Any]] | None,
    *,
    underlier: str,
) -> list[dict[str, Any]]:
    """Held CE/PE lots for an index family or stock underlier name."""
    fam = family_for_symbol(underlier)
    if fam is not None:
        return nifty_option_positions(positions, family=fam)
    name = equity_underlier_name(underlier) or str(underlier or "").strip().upper()
    out: list[dict[str, Any]] = []
    for pos in positions or []:
        if not isinstance(pos, dict):
            continue
        sym = str(pos.get("symbol") or "").strip().upper()
        right = option_right(sym)
        if right is None:
            continue
        if not (sym.startswith(name) and sym.endswith(right)):
            continue
        try:
            qty = float(pos.get("quantity") or pos.get("qty") or 0)
        except (TypeError, ValueError):
            continue
        if qty <= 1e-12:
            continue
        out.append({"symbol": sym, "right": right, "qty": qty, "position": pos})
    return out


def _expiry_date(raw: Any) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    try:
        if "T" in text:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def is_index_fut_row(row: dict[str, Any] | None, family: str) -> bool:
    """True for that index family's futures only — never CE/PE or other indices."""
    if not isinstance(row, dict):
        return False
    fam = str(family or "").strip().upper()
    spec = _FAMILIES.get(fam)
    if not spec:
        return False
    if str(row.get("instrument_type") or "").upper() != "FUT":
        return False
    tsym = str(row.get("tradingsymbol") or "").strip().upper()
    if not tsym.endswith("FUT"):
        return False
    for prefix in spec.get("exclude_prefixes") or ():
        if tsym.startswith(str(prefix)):
            return False
    name = " ".join(str(row.get("name") or "").upper().split())
    if name in spec["names"]:
        return True
    return tsym.startswith(str(spec["prefix"]))


def is_nifty50_fut_row(row: dict[str, Any] | None) -> bool:
    """True for NIFTY 50 index futures only — never CE/PE or other indices."""
    return is_index_fut_row(row, "NIFTY")


def kite_instrument(contract: dict[str, Any] | None) -> str | None:
    if not isinstance(contract, dict) or not contract.get("ok"):
        return None
    tsym = str(contract.get("tradingsymbol") or "").strip().upper()
    if not tsym:
        return None
    ex = str(contract.get("exchange") or "NFO").strip().upper() or "NFO"
    return f"{ex}:{tsym}"


def resolve_nearest_fut(
    rows: list[dict[str, Any]] | None,
    *,
    symbol: str = UNDERLYING,
    as_of: datetime | date | None = None,
) -> dict[str, Any]:
    """Pick the nearest unexpired FUT (index family or stock underlier)."""
    day = ist_as_of(as_of)
    atlas = str(symbol or UNDERLYING).strip().upper() or UNDERLYING
    if ":" in atlas:
        atlas = atlas.split(":", 1)[-1]
    if atlas.endswith(".NS") or atlas.endswith(".BO"):
        atlas = atlas.rsplit(".", 1)[0]
    fam = family_for_symbol(atlas)
    stock = None if fam else equity_underlier_name(atlas)
    if fam is None and stock:
        # Unknown cash names must not look like failed stock-F&O lookups.
        if not any(is_stock_fut_row(r, stock) for r in (rows or []) if isinstance(r, dict)):
            return {
                "ok": False,
                "version": VERSION,
                "phase": PHASE,
                "underlying": atlas,
                "atlas_symbol": atlas,
                "as_of": day.isoformat(),
                "reason": "not_index_underlier",
            }
    if fam is None and not stock:
        return {
            "ok": False,
            "version": VERSION,
            "phase": PHASE,
            "underlying": atlas,
            "atlas_symbol": atlas,
            "as_of": day.isoformat(),
            "reason": "not_index_underlier",
        }
    if fam is not None and not is_index_underlier(atlas):
        return {
            "ok": False,
            "version": VERSION,
            "phase": PHASE,
            "underlying": fam,
            "atlas_symbol": atlas,
            "as_of": day.isoformat(),
            "reason": "not_index_underlier",
        }
    underlying_key = fam or str(stock)
    candidates: list[tuple[date, str, dict[str, Any]]] = []
    for row in rows or []:
        if fam is not None:
            if not is_index_fut_row(row, fam):
                continue
        elif not is_stock_fut_row(row, str(stock)):
            continue
        exp = _expiry_date(row.get("expiry"))
        if exp is None or exp < day:
            continue
        tok = row.get("instrument_token")
        if tok is None:
            continue
        tsym = str(row.get("tradingsymbol") or "").strip().upper()
        candidates.append((exp, tsym, row))
    if not candidates:
        return {
            "ok": False,
            "version": VERSION,
            "phase": PHASE,
            "underlying": underlying_key,
            "atlas_symbol": atlas,
            "as_of": day.isoformat(),
            "reason": "no_unexpired_fut",
        }
    candidates.sort(key=lambda item: (item[0], item[1]))
    exp, tsym, row = candidates[0]
    try:
        lot = int(row.get("lot_size") or 0)
    except (TypeError, ValueError):
        lot = 0
    try:
        token = int(row.get("instrument_token"))
    except (TypeError, ValueError):
        return {
            "ok": False,
            "version": VERSION,
            "phase": PHASE,
            "underlying": underlying_key,
            "atlas_symbol": atlas,
            "as_of": day.isoformat(),
            "reason": "instrument_token_unresolved",
        }
    exchange = str(row.get("exchange") or "NFO").strip().upper() or "NFO"
    default_lot = 0
    if fam is not None:
        spec = _FAMILIES[fam]
        default_lot = int(spec.get("default_lot") or 0)
    return {
        "ok": True,
        "version": VERSION,
        "phase": PHASE,
        "underlying": underlying_key,
        "atlas_symbol": atlas,
        "underlying_type": "index" if fam else "stock",
        "tradingsymbol": tsym,
        "exchange": exchange,
        "segment": str(row.get("segment") or "NFO-FUT"),
        "instrument_type": "FUT",
        "instrument_token": token,
        "expiry": exp.isoformat(),
        "lot_size": lot if lot > 0 else (default_lot or None),
        "as_of": day.isoformat(),
        "reason": "ok",
    }


def contract_path(
    data_dir: str | Path | None,
    *,
    underlying: str = UNDERLYING,
    ist_date: str | None = None,
) -> Path | None:
    if not data_dir:
        return None
    name = str(underlying or UNDERLYING).strip().upper() or UNDERLYING
    if ist_date:
        return Path(data_dir) / STORE_REL / f"{name}_{ist_date}.json"
    return Path(data_dir) / STORE_REL / f"{name}.json"


def persist_resolved(
    data_dir: str | Path | None, contract: dict[str, Any] | None
) -> dict[str, Any]:
    """Write latest + dated snapshot so decide-time FUT is reconstructable."""
    if not isinstance(contract, dict):
        return {"ok": False, "reason": "no_contract"}
    path = contract_path(data_dir, underlying=str(contract.get("underlying") or UNDERLYING))
    if path is None:
        return {"ok": False, "reason": "no_data_dir"}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(contract)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        text = json.dumps(payload, indent=2, default=str) + "\n"
        path.write_text(text, encoding="utf-8")
        dated = contract_path(
            data_dir,
            underlying=str(contract.get("underlying") or UNDERLYING),
            ist_date=str(contract.get("as_of") or ""),
        )
        if dated is not None and contract.get("as_of"):
            dated.write_text(text, encoding="utf-8")
        return {"ok": True, "path": str(path)}
    except OSError as exc:
        _log.debug("fno contract persist failed: %s", exc, exc_info=True)
        return {"ok": False, "reason": "persist_error"}


def load_resolved(
    data_dir: str | Path | None,
    *,
    underlying: str = UNDERLYING,
    ist_date: str | None = None,
) -> dict[str, Any] | None:
    path = contract_path(data_dir, underlying=underlying, ist_date=ist_date)
    if path is None or not path.is_file():
        if ist_date:
            path = contract_path(data_dir, underlying=underlying)
        if path is None or not path.is_file():
            return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def stamp_phase1_contracts(
    instruments: list[dict[str, Any]] | None,
    *,
    rows: list[dict[str, Any]] | None = None,
    feed: Any | None = None,
    data_dir: str | Path | None = None,
    now: datetime | date | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Attach Phase-1 FUT metadata onto F&O lab instrument rows. Copies rows."""
    day = ist_as_of(now)
    dump = list(rows or [])
    if not dump and feed is not None:
        lister = getattr(feed, "list_nfo_futures", None)
        if callable(lister):
            try:
                dump = list(lister() or [])
            except Exception:  # noqa: BLE001
                _log.debug("nfo futures list failed", exc_info=True)
                dump = []
    out: list[dict[str, Any]] = []
    by_sym: dict[str, dict[str, Any]] = {}
    for inst in instruments or []:
        if not isinstance(inst, dict):
            continue
        row = dict(inst)
        sym = str(row.get("symbol") or "").strip()
        if not sym:
            continue
        if is_phase1_underlying(sym):
            contract = resolve_nearest_fut(dump, symbol=sym, as_of=day)
            if contract.get("ok"):
                persist_resolved(data_dir, contract)
                if contract.get("lot_size"):
                    row["lot_size"] = contract["lot_size"]
                if contract.get("expiry"):
                    row["expiry"] = contract["expiry"]
                row["nfo_tradingsymbol"] = contract.get("tradingsymbol")
            row["fno_contract"] = contract
            by_sym[sym.upper()] = contract
        else:
            fam = family_for_symbol(sym)
            if fam:
                contract = resolve_nearest_fut(dump, symbol=sym, as_of=day)
                row["fno_contract"] = contract
                by_sym[sym.upper()] = contract
        out.append(row)
    return out, by_sym


def option_right(symbol: str) -> str | None:
    key = str(symbol or "").strip().upper()
    if ":" in key:
        key = key.split(":", 1)[-1]
    # Digit before CE/PE — avoids false positives on names like RELIANCE / FORCE.
    if len(key) >= 3 and key[-2:] in {"CE", "PE"} and key[-3].isdigit():
        return key[-2:]
    return None


def is_index_option_row(row: dict[str, Any] | None, family: str) -> bool:
    """True for that family's CE/PE — never other indices or FUT."""
    if not isinstance(row, dict):
        return False
    fam = str(family or "").strip().upper()
    spec = _FAMILIES.get(fam)
    if not spec:
        return False
    right = str(row.get("instrument_type") or "").upper()
    if right not in {"CE", "PE"}:
        return False
    tsym = str(row.get("tradingsymbol") or "").strip().upper()
    if not tsym.endswith(right):
        return False
    for prefix in spec.get("exclude_prefixes") or ():
        if tsym.startswith(str(prefix)):
            return False
    name = " ".join(str(row.get("name") or "").upper().split())
    if name in spec["names"]:
        return True
    return tsym.startswith(str(spec["prefix"]))


def is_nifty50_option_row(row: dict[str, Any] | None) -> bool:
    """True for NIFTY 50 index CE/PE — never BANKNIFTY/FINNIFTY or FUT."""
    return is_index_option_row(row, "NIFTY")


def _strike_px(raw: Any) -> float | None:
    try:
        px = float(raw)
    except (TypeError, ValueError):
        return None
    if px <= 0:
        return None
    return px


def atm_strike(spot: float, *, step: float = STRIKE_STEP) -> float | None:
    try:
        px = float(spot)
        st = float(step) if step else STRIKE_STEP
    except (TypeError, ValueError):
        return None
    if px <= 0 or st <= 0:
        return None
    return round(px / st) * st


def sma_margin(indicators: dict[str, Any] | None) -> float:
    """(sma_fast - sma_slow) / sma_slow — same sign convention as StrategyDecisionRule."""
    ind = indicators if isinstance(indicators, dict) else {}
    try:
        fast = float(ind.get("sma_fast"))
        slow = float(ind.get("sma_slow"))
    except (TypeError, ValueError):
        return 0.0
    if slow == 0:
        return 0.0
    return (fast - slow) / slow


def _option_payload(
    row: dict[str, Any],
    *,
    right: str,
    exp: date,
    atlas: str,
    day: date,
    strike: float,
    underlying: str | None = None,
) -> dict[str, Any]:
    fam = str(underlying or family_for_symbol(atlas) or UNDERLYING).strip().upper()
    spec = _FAMILIES.get(fam) or _FAMILIES["NIFTY"]
    try:
        lot = int(row.get("lot_size") or 0)
    except (TypeError, ValueError):
        lot = 0
    try:
        token = int(row.get("instrument_token"))
    except (TypeError, ValueError):
        return {
            "ok": False,
            "version": VERSION2,
            "phase": PHASE2,
            "underlying": fam,
            "atlas_symbol": atlas,
            "instrument_type": right,
            "as_of": day.isoformat(),
            "reason": "instrument_token_unresolved",
        }
    tsym = str(row.get("tradingsymbol") or "").strip().upper()
    exchange = str(row.get("exchange") or "NFO").strip().upper() or "NFO"
    return {
        "ok": True,
        "version": VERSION2,
        "phase": PHASE2,
        "underlying": fam,
        "atlas_symbol": atlas,
        "tradingsymbol": tsym,
        "exchange": exchange,
        "segment": str(row.get("segment") or "NFO-OPT"),
        "instrument_type": right,
        "instrument_token": token,
        "expiry": exp.isoformat(),
        "strike": strike,
        "lot_size": lot if lot > 0 else int(spec.get("default_lot") or 25),
        "writing": False,
        "as_of": day.isoformat(),
        "reason": "ok",
    }


def resolve_atm_option(
    rows: list[dict[str, Any]] | None,
    *,
    right: str,
    spot: float,
    expiry: str | date | None,
    symbol: str = UNDERLYING,
    as_of: datetime | date | None = None,
) -> dict[str, Any]:
    """ATM CE or PE on the same expiry as the nearest FUT. Never writes."""
    day = ist_as_of(as_of)
    atlas = str(symbol or UNDERLYING).strip().upper() or UNDERLYING
    if ":" in atlas:
        atlas = atlas.split(":", 1)[-1]
    if atlas.endswith(".NS") or atlas.endswith(".BO"):
        atlas = atlas.rsplit(".", 1)[0]
    fam = family_for_symbol(atlas)
    stock = None if fam else equity_underlier_name(atlas)
    underlying_key = fam or stock or atlas
    spec = _FAMILIES.get(str(fam)) if fam else None
    want = str(right or "").strip().upper()
    if want not in {"CE", "PE"}:
        return {
            "ok": False,
            "version": VERSION2,
            "phase": PHASE2,
            "underlying": underlying_key,
            "atlas_symbol": atlas,
            "as_of": day.isoformat(),
            "reason": "right_must_be_ce_or_pe",
        }
    if fam is None and not stock:
        return {
            "ok": False,
            "version": VERSION2,
            "phase": PHASE2,
            "underlying": underlying_key,
            "atlas_symbol": atlas,
            "instrument_type": want,
            "as_of": day.isoformat(),
            "reason": "not_index_underlier",
        }
    if fam is not None and not is_index_underlier(atlas):
        return {
            "ok": False,
            "version": VERSION2,
            "phase": PHASE2,
            "underlying": underlying_key,
            "atlas_symbol": atlas,
            "instrument_type": want,
            "as_of": day.isoformat(),
            "reason": "not_index_underlier",
        }
    exp_want = _expiry_date(expiry)
    if exp_want is None:
        return {
            "ok": False,
            "version": VERSION2,
            "phase": PHASE2,
            "underlying": underlying_key,
            "atlas_symbol": atlas,
            "instrument_type": want,
            "as_of": day.isoformat(),
            "reason": "expiry_unresolved",
        }
    try:
        spot_f = float(spot)
    except (TypeError, ValueError):
        spot_f = 0.0
    if spot_f <= 0:
        return {
            "ok": False,
            "version": VERSION2,
            "phase": PHASE2,
            "underlying": underlying_key,
            "atlas_symbol": atlas,
            "instrument_type": want,
            "as_of": day.isoformat(),
            "reason": "no_spot",
        }
    # Index families use configured strike step; stocks pick closest listed strike.
    step = float((spec or {}).get("strike_step") or STRIKE_STEP) if fam else None
    target = atm_strike(spot_f, step=step) if step else None
    candidates: list[tuple[float, float, str, dict[str, Any]]] = []
    for row in rows or []:
        if fam is not None:
            if not is_index_option_row(row, str(fam)):
                continue
        elif not is_stock_option_row(row, str(stock), want):
            continue
        if str(row.get("instrument_type") or "").upper() != want:
            continue
        exp = _expiry_date(row.get("expiry"))
        if exp is None or exp != exp_want:
            continue
        strike = _strike_px(row.get("strike"))
        if strike is None:
            continue
        if row.get("instrument_token") is None:
            continue
        tsym = str(row.get("tradingsymbol") or "").strip().upper()
        aim = target if target is not None else spot_f
        candidates.append((abs(strike - aim), strike, tsym, row))
    if not candidates:
        return {
            "ok": False,
            "version": VERSION2,
            "phase": PHASE2,
            "underlying": underlying_key,
            "atlas_symbol": atlas,
            "instrument_type": want,
            "expiry": exp_want.isoformat(),
            "atm_strike": target,
            "as_of": day.isoformat(),
            "reason": "no_atm_option",
        }
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    _dist, strike, _tsym, row = candidates[0]
    return _option_payload(
        row,
        right=want,
        exp=exp_want,
        atlas=atlas,
        day=day,
        strike=strike,
        underlying=str(underlying_key),
    )


def resolve_phase2_bundle(
    rows: list[dict[str, Any]] | None,
    *,
    symbol: str = UNDERLYING,
    spot: float,
    as_of: datetime | date | None = None,
) -> dict[str, Any]:
    """Nearest FUT + ATM CE/PE at that expiry (index or stock underlier). No writes."""
    day = ist_as_of(as_of)
    atlas_raw = str(symbol or UNDERLYING).strip().upper() or UNDERLYING
    if ":" in atlas_raw:
        atlas_raw = atlas_raw.split(":", 1)[-1]
    if atlas_raw.endswith(".NS") or atlas_raw.endswith(".BO"):
        atlas_raw = atlas_raw.rsplit(".", 1)[0]
    fam = family_for_symbol(atlas_raw)
    stock = None if fam else equity_underlier_name(atlas_raw)
    underlying_key = fam or stock or atlas_raw
    fut = resolve_nearest_fut(rows, symbol=atlas_raw, as_of=day)
    base = {
        "ok": False,
        "version": VERSION2,
        "phase": PHASE2,
        "underlying": underlying_key,
        "atlas_symbol": atlas_raw,
        "underlying_type": "index" if fam else ("stock" if stock else "unknown"),
        "as_of": day.isoformat(),
        "writing": False,
        "fut": fut,
        "ce": None,
        "pe": None,
        "spot": None,
        "atm_strike": None,
    }
    try:
        spot_f = float(spot)
    except (TypeError, ValueError):
        base["reason"] = "no_spot"
        return base
    base["spot"] = spot_f
    if not fut.get("ok"):
        base["reason"] = str(fut.get("reason") or "fut_unresolved")
        return base
    if fam is not None:
        spec = _FAMILIES.get(fam) or _FAMILIES["NIFTY"]
        target = atm_strike(spot_f, step=float(spec.get("strike_step") or STRIKE_STEP))
    else:
        target = None  # stock: resolve_atm_option picks closest listed strike
    base["atm_strike"] = target
    ce = resolve_atm_option(
        rows, right="CE", spot=spot_f, expiry=fut.get("expiry"), symbol=atlas_raw, as_of=day
    )
    pe = resolve_atm_option(
        rows, right="PE", spot=spot_f, expiry=fut.get("expiry"), symbol=atlas_raw, as_of=day
    )
    if target is None:
        for side in (ce, pe):
            if isinstance(side, dict) and side.get("ok") and side.get("strike") is not None:
                base["atm_strike"] = side.get("strike")
                break
    base["ce"] = ce
    base["pe"] = pe
    if ce.get("ok") and pe.get("ok"):
        base["ok"] = True
        base["reason"] = "ok"
        return base
    if not ce.get("ok") and not pe.get("ok"):
        base["reason"] = str(ce.get("reason") or pe.get("reason") or "no_atm_option")
        return base
    base["ok"] = True
    base["reason"] = "partial_atm"
    return base


def persist_phase2_bundle(
    data_dir: str | Path | None, bundle: dict[str, Any] | None
) -> dict[str, Any]:
    """Dated ATM snapshot only — never the full options chain."""
    if not isinstance(bundle, dict):
        return {"ok": False, "reason": "no_bundle"}
    path = contract_path(
        data_dir, underlying=f"{bundle.get('underlying') or UNDERLYING}_ATM"
    )
    if path is None:
        return {"ok": False, "reason": "no_data_dir"}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(bundle)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        text = json.dumps(payload, indent=2, default=str) + "\n"
        path.write_text(text, encoding="utf-8")
        dated = contract_path(
            data_dir,
            underlying=f"{bundle.get('underlying') or UNDERLYING}_ATM",
            ist_date=str(bundle.get("as_of") or ""),
        )
        if dated is not None and bundle.get("as_of"):
            dated.write_text(text, encoding="utf-8")
        return {"ok": True, "path": str(path)}
    except OSError as exc:
        _log.debug("fno phase2 persist failed: %s", exc, exc_info=True)
        return {"ok": False, "reason": "persist_error"}


def nifty_option_positions(
    positions: list[dict[str, Any]] | None,
    *,
    family: str | None = None,
) -> list[dict[str, Any]]:
    want = str(family or "NIFTY").strip().upper() or "NIFTY"
    out: list[dict[str, Any]] = []
    for pos in positions or []:
        if not isinstance(pos, dict):
            continue
        sym = str(pos.get("symbol") or "").strip()
        right = option_right(sym)
        if right is None:
            continue
        if family_for_symbol(sym) != want:
            continue
        try:
            qty = float(pos.get("quantity") or pos.get("qty") or 0)
        except (TypeError, ValueError):
            continue
        if qty <= 1e-12:
            continue
        out.append({"symbol": sym, "right": right, "qty": qty, "position": pos})
    return out


def size_one_option_lot(
    *,
    lot_size: int,
    premium: float,
    cash: float,
) -> dict[str, Any]:
    """Long 1 lot: cash debit = premium × lot. Never a write."""
    try:
        lot = int(lot_size or 0)
        px = float(premium)
        cash_f = float(cash)
    except (TypeError, ValueError):
        return {"ok": False, "qty": 0.0, "reason": "bad_price_or_cash", "debit": 0.0}
    if lot <= 0:
        lot = 25
    if px <= 0:
        return {"ok": False, "qty": 0.0, "reason": "no_option_mark", "debit": 0.0}
    debit = float(lot) * px
    if cash_f + 1e-6 < debit:
        return {
            "ok": False,
            "qty": 0.0,
            "lot_size": lot,
            "debit": debit,
            "reason": f"insufficient cash for premium {debit:.2f}; cash={cash_f:.2f}",
        }
    return {
        "ok": True,
        "qty": float(lot),
        "lot_size": lot,
        "premium": px,
        "debit": debit,
        "reason": "",
        "strategy_tag": STRATEGY_TAG_ATM,
        "writing": False,
    }


def atm_tradingsymbols(bundle: dict[str, Any] | None) -> set[str]:
    out: set[str] = set()
    if not isinstance(bundle, dict):
        return out
    for key in ("ce", "pe"):
        row = bundle.get(key)
        if isinstance(row, dict) and row.get("ok") and row.get("tradingsymbol"):
            out.add(str(row["tradingsymbol"]).strip().upper())
    return out


def option_state_marks(
    *,
    right: str,
    contract: dict[str, Any] | None,
    option_ltp: float | None,
    underlying_price: float | None,
    future_price: float | None,
    lot_size: int | None = None,
) -> dict[str, Any]:
    """Decide-time option state. Index level is never the option mark."""
    row = contract if isinstance(contract, dict) else {}
    try:
        ltp = float(option_ltp) if option_ltp is not None else None
    except (TypeError, ValueError):
        ltp = None
    if ltp is not None and ltp <= 0:
        ltp = None
    try:
        lot = int(lot_size or row.get("lot_size") or 0) or None
    except (TypeError, ValueError):
        lot = None
    debit = None
    if ltp is not None and lot:
        debit = round(float(lot) * ltp, 4)
    try:
        under = float(underlying_price) if underlying_price is not None else None
    except (TypeError, ValueError):
        under = None
    try:
        fut = float(future_price) if future_price is not None else None
    except (TypeError, ValueError):
        fut = None
    return {
        "underlying_price": under,
        "future_price": fut,
        "option_ltp": ltp,
        "strike": row.get("strike"),
        "expiry": row.get("expiry"),
        "option_type": str(right or row.get("instrument_type") or "").upper() or None,
        "tradingsymbol": row.get("tradingsymbol"),
        "instrument_token": row.get("instrument_token"),
        "lot_size": lot,
        "cash_debit": debit,
        "honesty": "option fills use premium × lot, never index level",
    }


def _normalize_control_action(raw: str | None) -> str:
    act = str(raw or "hold").strip().lower()
    if act in {"buy", "sell"}:
        return act
    return "hold"


def experiment_path(data_dir: str | Path | None, experiment_id: str = P2_EXPERIMENT_ID) -> Path | None:
    if not data_dir:
        return None
    name = str(experiment_id or P2_EXPERIMENT_ID).strip() or P2_EXPERIMENT_ID
    return Path(data_dir) / EXPERIMENT_REL / f"{name}.json"


def load_phase2_experiment(
    data_dir: str | Path | None,
    experiment_id: str = P2_EXPERIMENT_ID,
) -> dict[str, Any] | None:
    path = experiment_path(data_dir, experiment_id)
    if path is None or not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def stamp_phase2_experiment(
    data_dir: str | Path | None,
    *,
    snapshot: dict[str, Any] | None,
    contract: dict[str, Any] | None = None,
    strategy_version: str = CONTROL_STRATEGY_VERSION,
    resolver_version: str = VERSION2,
    market_data_version: str = "zerodha.ltp",
    force: bool = False,
) -> dict[str, Any]:
    """FNO-P2-001 boundary. Leftover book is initial_state, not Phase-2 evidence."""
    existing = load_phase2_experiment(data_dir)
    if existing and not force:
        return {**existing, "already_stamped": True, "ok": True}
    path = experiment_path(data_dir)
    snap = snapshot if isinstance(snapshot, dict) else {}
    positions = []
    for pos in snap.get("positions") or []:
        if not isinstance(pos, dict):
            continue
        sym = str(pos.get("symbol") or "").strip()
        if not option_right(sym):
            continue
        try:
            qty = float(pos.get("quantity") or pos.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        if qty <= 1e-12:
            continue
        positions.append(
            {
                "symbol": sym,
                "qty": qty,
                "avg_price": pos.get("avg_price") or pos.get("avg_cost"),
            }
        )
    payload = {
        "ok": True,
        "already_stamped": False,
        "experiment_id": P2_EXPERIMENT_ID,
        "version": VERSION2,
        "phase": PHASE2,
        "underlying": PHASE2_UNDERLYING,
        "writing": False,
        "live_orders": False,
        "strategy_version": strategy_version,
        "adapter_id": ADAPTER_ID,
        "contract_resolver_version": resolver_version,
        "market_data_version": market_data_version,
        "control_strategy": CONTROL_STRATEGY_VERSION,
        "initial_cash": snap.get("cash"),
        "initial_equity": snap.get("equity"),
        "initial_position": positions,
        "initial_contract": contract if isinstance(contract, dict) else None,
        "stamped_at": datetime.now(timezone.utc).isoformat(),
        "honesty": (
            "Positions open at stamp are pre-Phase-2 leftover. "
            "They are not FNO-P2-001 evidence. New ATM CE/PE fills after flatten are."
        ),
    }
    if path is None:
        payload["ok"] = False
        payload["reason"] = "no_data_dir"
        return payload
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
        payload["path"] = str(path)
        return payload
    except OSError as exc:
        _log.debug("FNO-P2-001 stamp failed: %s", exc, exc_info=True)
        payload["ok"] = False
        payload["reason"] = "persist_error"
        return payload


def choose_atm_overlay(
    *,
    sma_margin: float,
    underlier_held: float,
    positions: list[dict[str, Any]] | None,
    bundle: dict[str, Any] | None,
    cash: float,
    ce_ltp: float | None,
    pe_ltp: float | None,
    control_action: str | None = None,
    underlying_price: float | None = None,
    future_price: float | None = None,
) -> dict[str, Any]:
    """Translate SMA/RSI V1 control onto ATM CE/PE (Lab v1 underliers). Not a new strategy.

    BUY underlier → bullish SMA → 1 lot ATM CE; bearish SMA → 1 lot ATM PE.
    SELL underlier → close the held ATM option. HOLD does not open or flip.
    Leftover non-ATM options are ignored here (FNO-P2-001 flatten).
    ``fallback_l4`` True only when ATM CE/PE are unresolved on an **index**
    underlier (legacy index-proxy). Stock underliers never fall back to L4.
    """
    def _idle(**extra: Any) -> dict[str, Any]:
        body = {
            "used": False,
            "fallback_l4": False,
            "reason": "idle",
            "strategy_tag": CONTROL_STRATEGY_TAG,
            "adapter_id": ADAPTER_ID,
            "writing": False,
            "control_action": _normalize_control_action(control_action),
        }
        body.update(extra)
        return body

    held_u = 0.0
    try:
        held_u = float(underlier_held or 0)
    except (TypeError, ValueError):
        held_u = 0.0
    if held_u > 1e-9:
        return _idle(fallback_l4=True, reason="legacy_index_proxy_open")
    if not isinstance(bundle, dict) or not bundle.get("ok"):
        return _idle(
            fallback_l4=True,
            reason=str((bundle or {}).get("reason") or "atm_unresolved"),
        )
    fam = str(bundle.get("underlying") or PHASE2_UNDERLYING).strip().upper()
    is_index = fam in INDEX_UNIVERSE or bool(family_for_symbol(fam))
    ce = bundle.get("ce") if isinstance(bundle.get("ce"), dict) else {}
    pe = bundle.get("pe") if isinstance(bundle.get("pe"), dict) else {}
    if not ce.get("ok") and not pe.get("ok"):
        return _idle(fallback_l4=is_index, reason="atm_unresolved")

    atm = atm_tradingsymbols(bundle)
    held_opts = option_positions_for_underlier(positions, underlier=fam)
    held_atm = [p for p in held_opts if str(p.get("symbol") or "").upper() in atm]
    leftover = [p for p in held_opts if str(p.get("symbol") or "").upper() not in atm]
    held_ce = [p for p in held_atm if p["right"] == "CE"]
    held_pe = [p for p in held_atm if p["right"] == "PE"]
    action = _normalize_control_action(control_action)
    try:
        margin = float(sma_margin)
    except (TypeError, ValueError):
        margin = 0.0
    bullish = margin > 0
    bearish = margin < 0
    spot = underlying_price if underlying_price is not None else bundle.get("spot")

    def _ltp_for(right: str) -> float | None:
        raw = ce_ltp if right == "CE" else pe_ltp
        try:
            px = float(raw) if raw is not None else 0.0
        except (TypeError, ValueError):
            return None
        return px if px > 0 else None

    def _filled(kind: str, *, right: str, pos: dict[str, Any] | None, px: float, qty: float, reason: str, contract: dict[str, Any], exit_code: str | None = None) -> dict[str, Any]:
        tsym = str((pos or {}).get("symbol") or contract.get("tradingsymbol") or "")
        lot = int(contract.get("lot_size") or (pos or {}).get("qty") or qty or 25)
        body = {
            "used": True,
            "fallback_l4": False,
            "kind": kind,
            "symbol": tsym,
            "qty": float(qty),
            "price": px,
            "right": right,
            "held": float((pos or {}).get("qty") or 0.0),
            "lot_size": lot,
            "expiry": contract.get("expiry"),
            "bundle": bundle,
            "reason": reason,
            "strategy_tag": CONTROL_STRATEGY_TAG,
            "adapter_id": ADAPTER_ID,
            "writing": False,
            "control_action": action,
            "marks": option_state_marks(
                right=right,
                contract=contract,
                option_ltp=px,
                underlying_price=spot,
                future_price=future_price,
                lot_size=lot,
            ),
            "legacy_positions": [p.get("symbol") for p in leftover],
        }
        if exit_code:
            body["exit_code"] = exit_code
        return body

    if leftover and not held_atm:
        idle = _idle(reason="legacy_non_atm_option")
        idle["legacy_positions"] = [p.get("symbol") for p in leftover]
        return idle

    if action == "sell":
        pos = (held_ce or held_pe or [None])[0]
        if not pos:
            return _idle(reason="sell_no_atm_option", legacy_positions=[p.get("symbol") for p in leftover])
        right = str(pos["right"])
        contract = ce if right == "CE" else pe
        px = _ltp_for(right)
        if px is None:
            return _idle(reason="no_option_mark")
        return _filled(
            "sell",
            right=right,
            pos=pos,
            px=px,
            qty=float(pos["qty"]),
            reason="v1_sell_close_atm_option",
            contract=contract,
            exit_code="sma_crossunder",
        )

    if held_ce or held_pe:
        return _idle(reason="hold_aligned_option")

    if action != "buy":
        return _idle(reason="control_hold")

    try:
        cash_f = float(cash)
    except (TypeError, ValueError):
        cash_f = 0.0

    if bullish:
        if not ce.get("ok"):
            return _idle(reason=str(ce.get("reason") or "no_ce"))
        px = _ltp_for("CE")
        if px is None:
            return _idle(reason="no_ce_mark")
        sized = size_one_option_lot(
            lot_size=int(ce.get("lot_size") or 25), premium=px, cash=cash_f
        )
        if not sized.get("ok"):
            return _idle(reason=str(sized.get("reason") or "insufficient_premium"))
        return _filled(
            "buy",
            right="CE",
            pos=None,
            px=px,
            qty=float(sized["qty"]),
            reason="v1_buy_atm_ce",
            contract=ce,
        )
    if bearish:
        if not pe.get("ok"):
            return _idle(reason=str(pe.get("reason") or "no_pe"))
        px = _ltp_for("PE")
        if px is None:
            return _idle(reason="no_pe_mark")
        sized = size_one_option_lot(
            lot_size=int(pe.get("lot_size") or 25), premium=px, cash=cash_f
        )
        if not sized.get("ok"):
            return _idle(reason=str(sized.get("reason") or "insufficient_premium"))
        return _filled(
            "buy",
            right="PE",
            pos=None,
            px=px,
            qty=float(sized["qty"]),
            reason="v1_buy_atm_pe",
            contract=pe,
        )
    return _idle(reason="underlier_neutral")
