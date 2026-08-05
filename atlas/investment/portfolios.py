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
    """Require a complete persona; fill sensible India-learner defaults."""
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
    return {
        "objective": str(raw.get("objective") or "Learning").strip() or "Learning",
        "risk": risk,
        "time_horizon": str(raw.get("time_horizon") or "medium").strip() or "medium",
        "capital": float(cash),
        "allowed_assets": assets_out,
        "strategy": strategy,
        "currency": str(raw.get("currency") or "INR").strip().upper() or "INR",
    }


def slugify(label: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (label or "").strip().lower()).strip("_")
    return s[:64] or f"book_{uuid.uuid4().hex[:8]}"


def experience_tag(portfolio_key: str) -> str:
    return f"portfolio:{portfolio_key}"


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
    return {
        "portfolio_key": key,
        "portfolio_label": row.get("label") or key,
        "persona": person,
        "starting_cash": float(person.get("capital") or 10000.0),
        "program_id": row.get("program_id") or DEFAULT_PROGRAM,
        "universe_index": row.get("universe") or "NIFTY50",
        "broker_profile": row.get("broker_profile") or "paper_demo",
        "asset_class": row.get("asset_class") or "cash_equity",
        "instrument_pack": row.get("instrument_pack")
        or row.get("asset_class")
        or "cash_equity",
        "instruments": [],
        "feed_mode": "live",
        "live_provider": "yahoo",
        "market_session": "nse_equity",
        "respect_market_hours": True,
        "auto_max_instruments": 10,
    }


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
) -> dict[str, Any]:
    """Register a virtual portfolio; optionally spawn its Decision Simulation mission."""
    person = normalize_persona(persona, capital=capital)
    if capital is not None:
        person["capital"] = float(capital)
    row = register(
        label=label,
        persona=person,
        program_id=program_id,
        portfolio_key=portfolio_key,
        universe=universe,
        broker_profile=broker_profile,
        asset_class=asset_class or (person["allowed_assets"][0] if person["allowed_assets"] else "cash_equity"),
    )
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
            row = bound
    row = dict(row)
    row["mission"] = {
        "id": mid,
        "title": title,
        "status": getattr(mission, "status", None),
    }
    row["instantiated"] = True
    return row
