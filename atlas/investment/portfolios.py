"""Virtual portfolio registry (IL.10) — one Decision Simulation book per portfolio.

In-process registry keyed by ``portfolio_key``, **persisted under**
``data/market/virtual_portfolios.json`` so books + mission binding survive
``atlas serve`` restarts. Cash/positions remain the source of truth in
``sim.portfolios`` (one row per mission + name=portfolio_key); the registry
stores persona + mission binding for the UI.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()
_STORE: dict[str, dict[str, Any]] = {}
_LOADED = False
_LOG = logging.getLogger("atlas.investment.portfolios")

DEFAULT_PROGRAM = "market_intelligence"

RISK_LEVELS = ("very_low", "low", "medium", "high", "very_high")
ASSET_CLASSES = (
    "cash_equity",
    "etf",
    "futures",
    "options",
    "commodity",
    "currency",
    "fx",
    "crypto",
    "mixed",
)


def normalize_persona(raw: dict[str, Any] | None = None, *, capital: float | None = None) -> dict[str, Any]:
    """Require a complete persona; fill sensible India-learner defaults.

    LI.1b optional personality fields (mentor, capital_policy, holding_philosophy,
    confidence_calibration, review_schedule) pass through when provided.
    """
    raw = dict(raw or {})
    cash = capital
    if cash is None:
        try:
            cash = float(raw.get("capital") or 10000.0)
        except (TypeError, ValueError):
            cash = 10000.0
    risk = str(raw.get("risk") or "medium").strip().lower().replace(" ", "_")
    if risk not in RISK_LEVELS:
        risk = "medium"
    assets = raw.get("allowed_assets")
    if isinstance(assets, str):
        assets = [assets]
    if not isinstance(assets, list) or not assets:
        assets = ["cash_equity"]
    assets_out = []
    for a in assets:
        s = str(a).strip().lower().replace(" ", "_")
        if s and s not in assets_out:
            assets_out.append(s if s in ASSET_CLASSES else s)
    strategy = raw.get("strategy")
    if strategy is None:
        strategy = {}
    elif not isinstance(strategy, dict):
        strategy = {"ref": str(strategy)}
    out: dict[str, Any] = {
        "objective": str(raw.get("objective") or "Learning").strip() or "Learning",
        "risk": risk,
        "time_horizon": str(raw.get("time_horizon") or "medium").strip() or "medium",
        "capital": float(cash),
        "allowed_assets": assets_out,
        "strategy": strategy,
        "currency": str(raw.get("currency") or "INR").strip().upper() or "INR",
    }
    # LI.1b laboratory personality (optional; defaults applied by apply_laboratory_personality)
    for key in (
        "mentor",
        "capital_policy",
        "holding_philosophy",
        "confidence_calibration",
        "review_schedule",
    ):
        if raw.get(key) is not None:
            out[key] = raw[key]
    return out


def laboratory_personality_preset(kind: str) -> dict[str, Any]:
    """LI.1b character defaults for swing / intraday / F&O laboratories."""
    k = str(kind or "swing").strip().lower().replace(" ", "_")
    presets = {
        "swing": {
            "mentor": "mos_patience",
            "risk": "medium",
            "time_horizon": "weeks",
            "capital_policy": "gradual_buffer",
            "holding_philosophy": "weeks_ignore_noise",
            "confidence_calibration": "research_depth",
            "review_schedule": ["D1", "D3", "W1", "D14", "M1", "Q"],
        },
        "equity_swing": {
            "mentor": "mos_patience",
            "risk": "medium",
            "time_horizon": "weeks",
            "capital_policy": "gradual_buffer",
            "holding_philosophy": "weeks_ignore_noise",
            "confidence_calibration": "research_depth",
            "review_schedule": ["D1", "D3", "W1", "D14", "M1", "Q"],
        },
        "intraday": {
            "mentor": "session_risk",
            "risk": "high",
            "time_horizon": "intraday",
            "capital_policy": "tight_day",
            "holding_philosophy": "flat_eod",
            "confidence_calibration": "liquidity_timing",
            "review_schedule": ["same_day", "next_open"],
        },
        "equity_intraday": {
            "mentor": "session_risk",
            "risk": "high",
            "time_horizon": "intraday",
            "capital_policy": "tight_day",
            "holding_philosophy": "flat_eod",
            "confidence_calibration": "liquidity_timing",
            "review_schedule": ["same_day", "next_open"],
        },
        "futures": {
            "mentor": "margin_lot_expiry",
            "risk": "very_high",
            "time_horizon": "intraday",
            "capital_policy": "margin_aware",
            "holding_philosophy": "contract_lifecycle",
            "confidence_calibration": "pack_readiness",
            "review_schedule": ["same_day", "expiry"],
        },
        "options": {
            "mentor": "margin_lot_expiry",
            "risk": "very_high",
            "time_horizon": "intraday",
            "capital_policy": "margin_aware",
            "holding_philosophy": "contract_lifecycle",
            "confidence_calibration": "pack_readiness",
            "review_schedule": ["same_day", "expiry"],
        },
        "f&o": {
            "mentor": "margin_lot_expiry",
            "risk": "very_high",
            "time_horizon": "intraday",
            "capital_policy": "margin_aware",
            "holding_philosophy": "contract_lifecycle",
            "confidence_calibration": "pack_readiness",
            "review_schedule": ["same_day", "expiry"],
        },
    }
    return dict(presets.get(k) or presets["swing"])


def apply_laboratory_personality(
    persona: dict[str, Any] | None,
    *,
    kind: str | None = None,
    capital: float | None = None,
) -> dict[str, Any]:
    """Merge LI.1b personality preset under explicit persona overrides."""
    base = laboratory_personality_preset(kind or "swing")
    merged = {**base, **dict(persona or {})}
    return normalize_persona(merged, capital=capital)


def slugify(label: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (label or "").strip().lower()).strip("_")
    return s[:64] or f"book_{uuid.uuid4().hex[:8]}"


def experience_tag(portfolio_key: str) -> str:
    return f"portfolio:{portfolio_key}"


def laboratory_id_for(portfolio_key: str | None) -> str:
    """LI.1a — laboratory_id is 1:1 with portfolio_key."""
    from atlas.investment.laboratory import laboratory_id_for as _lab

    return _lab(portfolio_key)


def create_laboratory(
    *,
    label: str,
    laboratory_id: str | None = None,
    capital: float | None = None,
    persona: dict[str, Any] | None = None,
    personality_kind: str | None = None,
    program_id: str = DEFAULT_PROGRAM,
    universe: str = "NIFTY50",
    broker_profile: str = "paper_demo",
    asset_class: str = "cash_equity",
    instantiate: bool = False,
    templates: Any = None,
    activate: bool = True,
) -> dict[str, Any]:
    """Register a Market Laboratory (IL.10 book + laboratory_id + LI.1b personality).

    Does not configure providers (LI.2). Mail lanes use laboratory_id in subjects.
    """
    kind = personality_kind
    if not kind:
        ac = str(asset_class or "").lower()
        if ac in {"futures", "options"}:
            kind = ac
        elif "intraday" in str(laboratory_id or label).lower():
            kind = "intraday"
        else:
            kind = "swing"
    person = apply_laboratory_personality(persona, kind=kind, capital=capital)
    row = create_book(
        label=label,
        persona=person,
        capital=capital if capital is not None else person.get("capital"),
        program_id=program_id,
        portfolio_key=laboratory_id,
        universe=universe,
        broker_profile=broker_profile,
        asset_class=asset_class,
        instantiate=instantiate,
        templates=templates,
        activate=activate,
    )
    out = stamp_laboratory_row(row)
    out["personality_kind"] = kind
    return out


def stamp_laboratory_row(row: dict[str, Any]) -> dict[str, Any]:
    """Ensure registry row exposes laboratory_id + lab experience tags."""
    from atlas.investment.laboratory import (
        laboratory_tag,
        lab_prior_tag,
        stamp_laboratory_identity,
    )

    out = stamp_laboratory_identity(dict(row))
    lid = str(out["laboratory_id"])
    out["experience_scope"] = experience_tag(lid)
    out["laboratory_tag"] = laboratory_tag(lid)
    out["lab_prior_tag"] = lab_prior_tag(lid)
    return out


def india_equity_learner_persona(*, capital: float = 10000.0) -> dict[str, Any]:
    return normalize_persona(
        {
            "objective": "Wealth",
            "risk": "medium",
            "time_horizon": "1y",
            "allowed_assets": ["cash_equity"],
            "strategy": {"ref": "india_equity_learner", "mode": "auto"},
            "currency": "INR",
        },
        capital=capital,
    )


def _data_root() -> Path | None:
    # Explicit registry file/dir wins; under pytest skip global data dir unless set.
    env = (os.environ.get("ATLAS_VIRTUAL_PORTFOLIOS") or "").strip()
    if env:
        p = Path(env)
        return p if p.suffix else p
    if os.environ.get("PYTEST_CURRENT_TEST") and not (
        os.environ.get("ATLAS_DATA_DIR") or ""
    ).strip():
        return None
    data = (os.environ.get("ATLAS_DATA_DIR") or "").strip()
    if data:
        return Path(data)
    try:
        from atlas.config import get_config

        return Path(get_config().paths.data)
    except Exception:  # noqa: BLE001
        return None

def persist_path() -> Path | None:
    """JSON file for the whole registry (or dir/file via ATLAS_VIRTUAL_PORTFOLIOS)."""
    env = (os.environ.get("ATLAS_VIRTUAL_PORTFOLIOS") or "").strip()
    if env:
        p = Path(env)
        if p.suffix:
            return p
        return p / "virtual_portfolios.json"
    root = _data_root()
    if root is None:
        return None
    return root / "market" / "virtual_portfolios.json"


def _write_disk() -> None:
    path = persist_path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": "il.10",
            "updated_at": time.time(),
            "portfolios": list(_STORE.values()),
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
        tmp.replace(path)
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("virtual portfolio persist skipped: %s", exc)


def _read_disk() -> dict[str, dict[str, Any]]:
    path = persist_path()
    if path is None or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data.get("portfolios") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return {}
        out: dict[str, dict[str, Any]] = {}
        for row in items:
            if not isinstance(row, dict):
                continue
            key = str(row.get("portfolio_key") or "").strip()
            if not key:
                continue
            out[key] = dict(row)
        return out
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("virtual portfolio load skipped: %s", exc)
        return {}


def _ensure_loaded() -> None:
    global _LOADED
    if _LOADED:
        return
    with _LOCK:
        if _LOADED:
            return
        disk = _read_disk()
        if disk:
            _STORE.update(disk)
            _LOG.info("loaded %d virtual portfolio(s) from disk", len(disk))
        _LOADED = True


def register(
    *,
    label: str,
    persona: dict[str, Any] | None = None,
    program_id: str = DEFAULT_PROGRAM,
    portfolio_key: str | None = None,
    universe: str = "NIFTY50",
    broker_profile: str = "paper_demo",
    asset_class: str = "cash_equity",
    instrument_pack: str | None = None,
    mission_id: str | None = None,
    ledger_mission_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create or update a virtual portfolio registry row (memory + disk)."""
    _ensure_loaded()
    key = (portfolio_key or slugify(label)).strip() or slugify(label)
    person = normalize_persona(persona, capital=(persona or {}).get("capital"))
    if persona and persona.get("capital") is None:
        person = normalize_persona(persona, capital=person["capital"])
    ac = str(asset_class or person["allowed_assets"][0]).strip()
    pack_id = str(instrument_pack or ac or "cash_equity").strip()
    now = time.time()
    with _LOCK:
        existing = _STORE.get(key)
        row = {
            "id": (existing or {}).get("id") or str(uuid.uuid4()),
            "portfolio_key": key,
            "label": (label or key).strip() or key,
            "program_id": program_id or DEFAULT_PROGRAM,
            "universe": universe or "NIFTY50",
            "broker_profile": broker_profile or "paper_demo",
            "asset_class": ac,
            "instrument_pack": pack_id,
            "persona": person,
            "mission_id": mission_id or (existing or {}).get("mission_id"),
            "ledger_mission_id": ledger_mission_id
            or (existing or {}).get("ledger_mission_id"),
            "experience_scope": experience_tag(key),
            "laboratory_id": key,  # LI.1a — Laboratory contains this ledger
            "laboratory_tag": f"laboratory:{key}",
            "lab_prior_tag": f"lab:{key}",
            "created_at": (existing or {}).get("created_at") or now,
            "updated_at": now,
            "extra": {**((existing or {}).get("extra") or {}), **(extra or {})},
        }
        _STORE[key] = row
        _write_disk()
        return dict(row)


def bind_mission(
    portfolio_key: str,
    *,
    mission_id: str,
    ledger_mission_id: str | None = None,
) -> dict[str, Any] | None:
    _ensure_loaded()
    with _LOCK:
        row = _STORE.get(portfolio_key)
        if row is None:
            return None
        row["mission_id"] = str(mission_id)
        if ledger_mission_id:
            row["ledger_mission_id"] = str(ledger_mission_id)
        row["updated_at"] = time.time()
        _write_disk()
        return dict(row)


def sync_live_cash(
    portfolio_key: str,
    cash: float,
    *,
    mission_id: str | None = None,
) -> dict[str, Any] | None:
    """Update registry persona.capital from live sim book cash (post deposit / tick)."""
    _ensure_loaded()
    key = str(portfolio_key or "").strip()
    if not key:
        return None
    try:
        cash_f = float(cash)
    except (TypeError, ValueError):
        return None
    with _LOCK:
        row = _STORE.get(key)
        if row is None:
            return None
        person = dict(row.get("persona") or {})
        person["capital"] = cash_f
        row["persona"] = person
        if mission_id:
            row["mission_id"] = str(mission_id)
        row["updated_at"] = time.time()
        _write_disk()
        return dict(row)


def get(portfolio_key: str) -> dict[str, Any] | None:
    _ensure_loaded()
    with _LOCK:
        row = _STORE.get(portfolio_key)
        return dict(row) if row else None


def get_by_id(portfolio_id: str) -> dict[str, Any] | None:
    _ensure_loaded()
    with _LOCK:
        for row in _STORE.values():
            if str(row.get("id")) == str(portfolio_id):
                return dict(row)
        return None


def list_portfolios(
    *,
    program_id: str | None = None,
) -> list[dict[str, Any]]:
    _ensure_loaded()
    with _LOCK:
        rows = [dict(r) for r in _STORE.values()]
    if program_id:
        rows = [r for r in rows if r.get("program_id") == program_id]
    rows.sort(key=lambda r: float(r.get("created_at") or 0))
    return rows


def clear(portfolio_key: str | None = None) -> None:
    """Clear memory (and matching disk). Used by tests; full clear drops the file."""
    global _LOADED
    with _LOCK:
        path = persist_path()
        if portfolio_key is None:
            _STORE.clear()
            _LOADED = True  # stay empty until next process (or re-register)
            if path is not None and path.is_file():
                try:
                    path.unlink()
                except OSError:
                    pass
        else:
            _ensure_loaded()
            _STORE.pop(portfolio_key, None)
            _LOADED = True
            _write_disk()


def ensure_from_config(
    cfg: dict[str, Any] | None,
    *,
    mission_id: str | None = None,
) -> dict[str, Any]:
    """Resolve/register a portfolio from Decision Simulation config.

    Does **not** reset deposited capital: if the registry (or disk) already has a
    higher ``persona.capital`` than config ``starting_cash``, the higher value wins.
    Live cash in ``sim.portfolios`` is still authoritative once a book exists.
    """
    _ensure_loaded()
    cfg = cfg or {}
    key = str(cfg.get("portfolio_key") or "").strip()
    label = str(cfg.get("portfolio_label") or cfg.get("label") or "").strip()
    if not key:
        key = slugify(label) if label else "default"
    if not label:
        label = key.replace("_", " ").title()
    persona_raw = dict(cfg.get("persona")) if isinstance(cfg.get("persona"), dict) else {}
    capital = cfg.get("starting_cash")
    if capital is not None:
        persona_raw = {**persona_raw, "capital": capital}
    existing = get(key)
    # Never clobber deposited capital with a lower mission starting_cash.
    if existing and isinstance(existing.get("persona"), dict):
        try:
            old_c = float((existing.get("persona") or {}).get("capital") or 0)
        except (TypeError, ValueError):
            old_c = 0.0
        try:
            new_c = float(persona_raw.get("capital") or capital or 0)
        except (TypeError, ValueError):
            new_c = 0.0
        if old_c > new_c:
            persona_raw = {
                **((existing.get("persona") if isinstance(existing.get("persona"), dict) else {}) or {}),
                **persona_raw,
                "capital": old_c,
            }
            # Keep richer existing persona fields when config omits them
            for k, v in (existing.get("persona") or {}).items():
                if k not in persona_raw or persona_raw.get(k) in (None, "", []):
                    persona_raw[k] = v
    if existing and not cfg.get("persona") and capital is None:
        if mission_id and not existing.get("mission_id"):
            return bind_mission(key, mission_id=mission_id) or existing
        if mission_id and existing.get("mission_id") != str(mission_id):
            return bind_mission(key, mission_id=mission_id) or existing
        return existing
    return register(
        label=label or (existing or {}).get("label") or key,
        portfolio_key=key,
        persona=persona_raw or (existing or {}).get("persona"),
        program_id=str(
            cfg.get("program_id")
            or (existing or {}).get("program_id")
            or DEFAULT_PROGRAM
        ),
        universe=str(
            cfg.get("universe_index")
            or cfg.get("universe")
            or (existing or {}).get("universe")
            or "NIFTY50"
        ),
        broker_profile=str(
            cfg.get("broker_profile")
            or (existing or {}).get("broker_profile")
            or "paper_demo"
        ),
        asset_class=str(
            cfg.get("asset_class")
            or (existing or {}).get("asset_class")
            or (persona_raw.get("allowed_assets") or ["cash_equity"])[0]
        ),
        instrument_pack=str(cfg.get("instrument_pack") or "") or (existing or {}).get(
            "instrument_pack"
        ),
        mission_id=mission_id or (existing or {}).get("mission_id"),
        ledger_mission_id=(existing or {}).get("ledger_mission_id"),
        extra=(existing or {}).get("extra") if isinstance((existing or {}).get("extra"), dict) else None,
    )


def asset_allowed(persona: dict[str, Any] | None, asset_class: str | None) -> bool:
    """True if persona permits this asset class (empty/mixed → allow)."""
    person = normalize_persona(persona)
    allowed = list(person.get("allowed_assets") or [])
    if not allowed or "mixed" in allowed:
        return True
    ac = (asset_class or "cash_equity").strip().lower().replace(" ", "_")
    return ac in allowed


def filter_journals_for_portfolio(
    journals: list[dict[str, Any]] | None,
    portfolio_key: str | None,
) -> list[dict[str, Any]]:
    """Keep journals tagged for this book; drop other books' tags.

    Untagged (legacy) journals are excluded when a portfolio_key is set so book A
    never soft-biases book B.
    """
    if not portfolio_key:
        return list(journals or [])
    want = experience_tag(portfolio_key)
    out: list[dict[str, Any]] = []
    for j in journals or []:
        if not isinstance(j, dict):
            continue
        tags = [str(t) for t in (j.get("tags") or [])]
        meta = j.get("metadata") if isinstance(j.get("metadata"), dict) else {}
        if not tags and isinstance(j.get("experience"), dict):
            exp = j["experience"]
            tags = [str(t) for t in (exp.get("tags") or [])]
            if not meta and isinstance(exp.get("metadata"), dict):
                meta = exp["metadata"]
        if str(meta.get("portfolio_key") or "") == portfolio_key:
            out.append(j)
            continue
        portfolio_tags = [t for t in tags if t.startswith("portfolio:")]
        if want in tags:
            out.append(j)
        elif not portfolio_tags:
            # Legacy unscoped — exclude when scoping to a book (honest isolation)
            continue
    return out


def default_decision_config(row: dict[str, Any]) -> dict[str, Any]:
    """Config overrides for a Decision Simulation mission bound to this book."""
    person = normalize_persona(row.get("persona"))
    key = str(row.get("portfolio_key") or "default")
    ac = str(row.get("asset_class") or "cash_equity").strip().lower().replace(" ", "_")
    if not ac:
        ac = str((person.get("allowed_assets") or ["cash_equity"])[0]).strip().lower()
    pack = str(
        row.get("instrument_pack") or ac or "cash_equity"
    ).strip().lower()
    instruments: list[dict[str, Any]] = list(row.get("instruments") or [])
    market_session = "nse_equity"
    auto_max = 10
    # F&O: never auto-pull cash equity universe — operator/demo instruments only
    if ac in {"futures", "options"} or pack in {"futures", "options", "fno"}:
        market_session = "nse_fno"
        auto_max = 0
        if not instruments:
            instruments = [
                {
                    "symbol": "NIFTY",
                    "asset_class": "futures",
                    "lot_size": 25,
                    "note": "plc.e_demo_seed — underlier ^NSEI via alias; replace with operator contracts",
                },
                {
                    "symbol": "BANKNIFTY",
                    "asset_class": "futures",
                    "lot_size": 15,
                    "note": "plc.e_demo_seed — optional second underlier",
                },
            ]
    elif "intraday" in key.lower():
        market_session = "nse_equity"
        auto_max = 15
    return {
        "portfolio_key": key,
        "portfolio_label": row.get("label") or key,
        "persona": person,
        "starting_cash": float(person.get("capital") or 10000.0),
        "program_id": row.get("program_id") or DEFAULT_PROGRAM,
        "universe_index": row.get("universe") or "NIFTY50",
        "broker_profile": row.get("broker_profile") or "paper_demo",
        "asset_class": ac,
        "instrument_pack": pack,
        "instruments": instruments,
        "feed_mode": "live",
        "live_provider": "yahoo",
        "market_session": market_session,
        "respect_market_hours": True,
        "auto_max_instruments": auto_max,
    }


def enrich_decision_config_from_book(
    cfg: dict[str, Any] | None,
    book: dict[str, Any] | None,
) -> dict[str, Any]:
    """PLC.E / lab wake — fill missing mission config so F&O/intraday can tick.

    Does not invent prices. Seeds demo F&O instruments when ``auto_max=0`` and
    instruments are empty. Safe to call every tick (idempotent merges).
    """
    out = dict(cfg or {})
    if not isinstance(book, dict):
        return out
    suggested = default_decision_config(book)
    ac = str(
        out.get("asset_class")
        or book.get("asset_class")
        or suggested.get("asset_class")
        or "cash_equity"
    ).strip().lower()
    key = str(book.get("portfolio_key") or out.get("portfolio_key") or "")

    for field in (
        "portfolio_key",
        "asset_class",
        "instrument_pack",
        "market_session",
        "feed_mode",
        "live_provider",
        "respect_market_hours",
        "auto_max_instruments",
        "broker_profile",
        "program_id",
        "universe_index",
    ):
        if out.get(field) in (None, "", []):
            if suggested.get(field) is not None:
                out[field] = suggested[field]

    if not out.get("persona") and suggested.get("persona"):
        out["persona"] = suggested["persona"]

    instruments = out.get("instruments")
    if not isinstance(instruments, list):
        instruments = []
    # F&O: never idle forever on empty instruments when pack is futures
    if ac in {"futures", "options"} or str(out.get("instrument_pack") or "").lower() in {
        "futures",
        "options",
        "fno",
    }:
        out["auto_max_instruments"] = 0
        out["market_session"] = str(out.get("market_session") or "nse_fno")
        if not instruments:
            instruments = list(suggested.get("instruments") or [])
            out["_lab_seeded_instruments"] = True
        # Ensure asset_class stamped on rows so persona filter keeps them
        fixed: list[dict[str, Any]] = []
        for inst in instruments:
            if not isinstance(inst, dict):
                continue
            row = dict(inst)
            row.setdefault("asset_class", ac or "futures")
            if not row.get("lot_size"):
                try:
                    from atlas.investment.packs.derivatives import default_lot_size

                    row["lot_size"] = default_lot_size(str(row.get("symbol") or ""))
                except Exception:  # noqa: BLE001
                    row["lot_size"] = 25
            fixed.append(row)
        out["instruments"] = fixed
    elif "intraday" in key.lower():
        out.setdefault("market_session", "nse_equity")
        out.setdefault("respect_market_hours", True)
        if not instruments:
            out["instruments"] = list(instruments)
        # Keep auto_max so M0 watchlist can load when empty
        if out.get("auto_max_instruments") is None:
            out["auto_max_instruments"] = int(suggested.get("auto_max_instruments") or 15)

    return out


def create_book(
    *,
    label: str,
    persona: dict[str, Any] | None = None,
    capital: float | None = None,
    program_id: str = DEFAULT_PROGRAM,
    portfolio_key: str | None = None,
    universe: str = "NIFTY50",
    broker_profile: str = "paper_demo",
    asset_class: str = "cash_equity",
    instantiate: bool = False,
    templates: Any = None,
    activate: bool = True,
    personality_kind: str | None = None,
) -> dict[str, Any]:
    """Register a virtual portfolio; optionally spawn its Decision Simulation mission."""
    ac = str(asset_class or "cash_equity").strip().lower().replace(" ", "_")
    kind = personality_kind
    if not kind:
        key_l = str(portfolio_key or label or "").lower()
        if ac in {"futures", "options"}:
            kind = ac
        elif "intraday" in key_l:
            kind = "intraday"
        elif "fno" in key_l or "futures" in key_l:
            kind = "futures"
        else:
            kind = None
    raw_person = dict(persona or {})
    # Align allowed_assets with asset_class (F&O must not stay cash_equity)
    if ac in {"futures", "options"}:
        allowed = raw_person.get("allowed_assets")
        if not allowed or allowed == ["cash_equity"] or allowed == "cash_equity":
            raw_person["allowed_assets"] = [ac]
    if kind:
        person = apply_laboratory_personality(raw_person, kind=kind, capital=capital)
    else:
        person = normalize_persona(raw_person, capital=capital)
    if capital is not None:
        person["capital"] = float(capital)
    row = register(
        label=label,
        persona=person,
        program_id=program_id,
        portfolio_key=portfolio_key,
        universe=universe,
        broker_profile=broker_profile,
        asset_class=ac or (person["allowed_assets"][0] if person["allowed_assets"] else "cash_equity"),
    )
    row = stamp_laboratory_row(row)
    if kind:
        row["personality_kind"] = kind
    if not instantiate or templates is None:
        return row
    cfg = default_decision_config(row)
    title = f"{row['label']} · Decision Simulation"
    result = templates.instantiate(
        "decision_simulation",
        title=title,
        config_overrides=cfg,
        labels=[
            f"program:{row['program_id']}",
            f"portfolio:{row['portfolio_key']}",
            f"role:decision_simulation",
        ],
        metadata={
            "program_id": row["program_id"],
            "portfolio_key": row["portfolio_key"],
            "template": "decision_simulation",
        },
        activate=activate,
    )
    mission = result.get("mission")
    mid = str(getattr(mission, "id", None) or (mission or {}).get("id") or "")
    if mid:
        bound = bind_mission(row["portfolio_key"], mission_id=mid)
        if bound:
            row = stamp_laboratory_row(bound)
            if kind:
                row["personality_kind"] = kind
    row = dict(row)
    row["mission"] = {
        "id": mid,
        "title": title,
        "status": getattr(mission, "status", None),
    }
    row["instantiated"] = True
    return row


def repair_laboratory_pack_alignment(portfolio_key: str) -> dict[str, Any] | None:
    """PLC.E — fix F&O/intraday registry rows created with cash defaults.

    Updates durable registry persona. Returns suggested decision_simulation config
    (mission config may still need a PATCH to pick up instruments/session).
    """
    row = get(portfolio_key)
    if not row:
        return None
    key = str(row.get("portfolio_key") or portfolio_key)
    ac = str(row.get("asset_class") or "cash_equity").strip().lower()
    person = dict(row.get("persona") or {})
    changed = False
    if ac in {"futures", "options"}:
        if list(person.get("allowed_assets") or []) != [ac]:
            person["allowed_assets"] = [ac]
            changed = True
        if not person.get("mentor"):
            person = apply_laboratory_personality(person, kind=ac)
            changed = True
    elif "intraday" in key.lower() and not person.get("mentor"):
        person = apply_laboratory_personality(person, kind="intraday")
        changed = True
    if changed:
        row = dict(row)
        row["persona"] = normalize_persona(person, capital=person.get("capital"))
        row = stamp_laboratory_row(row)
        with _LOCK:
            _ensure_loaded()
            _STORE[key] = row
            _write_disk()
    suggested = default_decision_config(row)
    return {"portfolio": row, "suggested_decision_config": suggested, "changed": changed}
