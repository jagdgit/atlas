"""Shared watchlist store (IL.2 / IL.4) — M0 publishes; M1–M5 consume when config is empty.

In-process registry keyed by Program id (default ``market_intelligence``).
Also persists JSON under ``data/market/watchlists/`` so Learner / Decision
Simulation survive process restarts until the next M0 tick.

IL.4 contract: if operator pins ``symbols`` / ``tickers`` / ``instruments`` /
``companies`` / ``headlines``, those win; otherwise pull from the ranked snapshot.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()
_STORE: dict[str, dict[str, Any]] = {}
_LOG = logging.getLogger("atlas.investment.watchlists")

DEFAULT_PROGRAM = "market_intelligence"


def _safe_id(program_id: str) -> str:
    raw = (program_id or DEFAULT_PROGRAM).strip() or DEFAULT_PROGRAM
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", raw)[:80]


def persist_dir() -> Path:
    env = (os.environ.get("ATLAS_WATCHLIST_DIR") or "").strip()
    if env:
        return Path(env)
    data = (os.environ.get("ATLAS_DATA_DIR") or "").strip()
    if data:
        return Path(data) / "market" / "watchlists"
    # Prefer configured data root (same as triage / fundamentals) over CWD.
    try:
        from atlas.config import get_config

        cfg_data = str(get_config().paths.data or "").strip()
        if cfg_data:
            return Path(cfg_data) / "market" / "watchlists"
    except Exception:  # noqa: BLE001
        pass
    return Path("data") / "market" / "watchlists"


def _persist_path(program_id: str) -> Path:
    return persist_dir() / f"{_safe_id(program_id)}.json"


def _write_disk(program_id: str, payload: dict[str, Any]) -> None:
    try:
        path = _persist_path(program_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, default=str), encoding="utf-8")
        tmp.replace(path)
    except Exception as exc:  # noqa: BLE001
        _LOG.debug("watchlist persist skipped: %s", exc)


def _read_disk(program_id: str) -> dict[str, Any] | None:
    try:
        path = _persist_path(program_id)
        if not path.is_file():
            if program_id != "default":
                alt = _persist_path("default")
                path = alt if alt.is_file() else path
            if not path.is_file():
                return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception as exc:  # noqa: BLE001
        _LOG.debug("watchlist load skipped: %s", exc)
        return None


def publish(
    *,
    program_id: str = DEFAULT_PROGRAM,
    index: str,
    watchlist: list[dict[str, Any]],
    ranked: list[dict[str, Any]] | None = None,
    mission_id: str | None = None,
    mode: str = "auto",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Publish the latest universe snapshot for consumers."""
    payload = {
        "program_id": program_id,
        "index": index,
        "watchlist": list(watchlist or []),
        "ranked": list(ranked or watchlist or []),
        "mission_id": mission_id,
        "mode": mode,
        "updated_at": time.time(),
        "extra": dict(extra or {}),
    }
    with _LOCK:
        _STORE[program_id] = payload
        _STORE["default"] = payload
    _write_disk(program_id, payload)
    if program_id != "default":
        _write_disk("default", payload)
    return dict(payload)


def latest(program_id: str = DEFAULT_PROGRAM) -> dict[str, Any] | None:
    """Return latest snapshot — memory first, then durable disk."""
    with _LOCK:
        row = _STORE.get(program_id) or _STORE.get("default")
        if row:
            return dict(row)
    disk = _read_disk(program_id)
    if disk is None and program_id != "default":
        disk = _read_disk("default")
    if disk:
        with _LOCK:
            _STORE[program_id] = disk
            _STORE.setdefault("default", disk)
        return dict(disk)
    return None


def clear(program_id: str | None = None, *, disk: bool = False) -> None:
    with _LOCK:
        if program_id is None:
            _STORE.clear()
        else:
            _STORE.pop(program_id, None)
    if not disk:
        return
    try:
        if program_id is None:
            d = persist_dir()
            if d.is_dir():
                for p in d.glob("*.json"):
                    p.unlink(missing_ok=True)
        else:
            _persist_path(program_id).unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        _LOG.debug("watchlist disk clear skipped: %s", exc)


def instruments_for(
    program_id: str = DEFAULT_PROGRAM,
    *,
    max_n: int = 10,
) -> list[dict[str, str]]:
    """Decision-Simulation-shaped instruments from the latest watchlist/ranks."""
    rows = ranked_rows(program_id, max_n=max_n)
    return [
        {"symbol": str(r["symbol"]), "asset": str(r.get("asset") or "").strip()}
        for r in rows
    ]


def ranked_rows(
    program_id: str = DEFAULT_PROGRAM,
    *,
    max_n: int = 15,
) -> list[dict[str, Any]]:
    """Top ranked/watchlist rows from the latest M0 snapshot."""
    snap = latest(program_id)
    if not snap:
        return []
    ranked = list(snap.get("ranked") or snap.get("watchlist") or [])
    out: list[dict[str, Any]] = []
    for row in ranked:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").strip()
        if not sym:
            continue
        out.append(dict(row))
        if len(out) >= max(1, int(max_n)):
            break
    return out


def program_id_from(cfg: dict[str, Any] | None) -> str:
    cfg = cfg or {}
    return str(cfg.get("program_id") or DEFAULT_PROGRAM).strip() or DEFAULT_PROGRAM


def _auto_max(cfg: dict[str, Any], default: int = 15) -> int:
    for key in ("auto_max_symbols", "auto_max_instruments", "auto_max_tickers", "max_watchlist"):
        if cfg.get(key) is not None:
            try:
                return max(1, int(cfg[key]))
            except (TypeError, ValueError):
                continue
    return max(1, int(default))


def pinned_symbols(cfg: dict[str, Any] | None) -> list[str]:
    """Operator-pinned symbols from common config fields (order preserved)."""
    cfg = cfg or {}
    out: list[str] = []
    seen: set[str] = set()

    def _add(raw: Any) -> None:
        sym = str(raw or "").strip()
        if sym and sym not in seen:
            seen.add(sym)
            out.append(sym)

    for s in cfg.get("symbols") or []:
        _add(s)
    for t in cfg.get("tickers") or []:
        _add(t)
    for inst in cfg.get("instruments") or []:
        if isinstance(inst, dict):
            _add(inst.get("symbol") or inst.get("asset"))
        else:
            _add(inst)
    for c in cfg.get("companies") or []:
        if isinstance(c, dict):
            _add(c.get("symbol"))
    return out


def resolve_symbols(
    cfg: dict[str, Any] | None = None,
    *,
    max_n: int | None = None,
) -> tuple[list[str], bool]:
    """Return ``(symbols, auto)``. Operator pins win; else ranked watchlist."""
    cfg = cfg or {}
    pinned = pinned_symbols(cfg)
    if pinned:
        limit = max_n if max_n is not None else len(pinned)
        return pinned[: max(1, int(limit))], False
    n = max_n if max_n is not None else _auto_max(cfg)
    rows = ranked_rows(program_id_from(cfg), max_n=n)
    return [str(r["symbol"]) for r in rows], bool(rows)


def resolve_instruments(
    cfg: dict[str, Any] | None = None,
    *,
    max_n: int | None = None,
) -> tuple[list[dict[str, str]], bool]:
    """Return ``(instruments, auto)`` for Market Observer / Decision Simulation."""
    cfg = cfg or {}
    instruments: list[dict[str, str]] = []
    seen: set[str] = set()
    for inst in cfg.get("instruments") or []:
        if not isinstance(inst, dict):
            continue
        sym = str(inst.get("symbol") or "").strip()
        asset = str(inst.get("asset") or "").strip()
        if not (sym or asset):
            continue
        key = sym or asset
        if key in seen:
            continue
        seen.add(key)
        instruments.append({"symbol": sym or asset, "asset": asset})
    for sym in cfg.get("symbols") or []:
        s = str(sym).strip()
        if s and s not in seen:
            seen.add(s)
            instruments.append({"symbol": s, "asset": ""})
    if instruments:
        limit = max_n if max_n is not None else len(instruments)
        return instruments[: max(1, int(limit))], False
    n = max_n if max_n is not None else _auto_max(cfg, default=10)
    got = instruments_for(program_id_from(cfg), max_n=n)
    return got, bool(got)


def resolve_company_targets(
    cfg: dict[str, Any] | None = None,
    *,
    max_n: int | None = None,
) -> tuple[list[str], list[dict[str, Any]], bool]:
    """Return ``(tickers, company_seed_profiles, auto)`` for Company Intelligence.

    When auto-loading from the watchlist, builds hermetic ``config_seed``
    profiles from membership name/sector plus IL.5 quality-seed ratios
    (sector proxies — not invented live filings).
    """
    cfg = cfg or {}
    companies = [c for c in (cfg.get("companies") or []) if isinstance(c, dict)]
    tickers = pinned_symbols(cfg)
    if companies and not tickers:
        for c in companies:
            sym = str(c.get("symbol") or "").strip()
            if sym and sym not in tickers:
                tickers.append(sym)
    if tickers or companies:
        limit = max_n if max_n is not None else max(len(tickers), 1)
        capped = tickers[: max(1, int(limit))] if tickers else tickers
        return capped, companies, False

    n = max_n if max_n is not None else _auto_max(cfg)
    pid = program_id_from(cfg)
    rows = ranked_rows(pid, max_n=n)
    if not rows:
        return [], [], False
    snap = latest(pid) or {}
    index = str(snap.get("index") or "universe")
    from atlas.investment.quality_seed import ratios_for_symbol

    seeds: list[dict[str, Any]] = []
    syms: list[str] = []
    for r in rows:
        sym = str(r.get("symbol") or "").strip()
        if not sym:
            continue
        syms.append(sym)
        name = str(r.get("name") or sym).strip()
        sector = str(r.get("sector") or "").strip()
        facts = [f"{name} is a constituent of {index}."]
        if sector:
            facts.append(f"{name} is classified in the {sector} sector.")
        ratios = ratios_for_symbol(sym)
        if ratios.get("roe") is not None:
            facts.append(
                f"Hermetic quality seed ROE≈{float(ratios['roe']) * 100:.0f}% "
                f"(sector proxy as_of {ratios.get('as_of')}; not live filings)."
            )
        # IL.8 — operator screener snapshot fields
        from atlas.investment.screener_signals import latest_snapshot, quality_enrichment_fact

        snap = latest_snapshot(pid)
        if snap and isinstance(snap.get("symbols"), dict):
            srow = snap["symbols"].get(sym)
            if isinstance(srow, dict):
                for fld in ("roe", "debt_to_equity", "pe", "promoter_holding"):
                    if fld in srow and srow[fld] is not None:
                        ratios[fld] = srow[fld]
                if srow.get("score") is not None:
                    ratios["screener_score"] = srow["score"]
                ratios["screener_source"] = srow.get("source") or snap.get("source")
                fact = quality_enrichment_fact(ratios)
                if fact:
                    facts.append(fact)
        # IL.5+ — hermetic / operator filing refs (metadata only)
        from atlas.investment.filings import enrichment_fact, filings_for_symbol

        filing_refs = filings_for_symbol(sym, program_id=pid, name=name)
        f_fact = enrichment_fact(filing_refs)
        if f_fact:
            facts.append(f_fact)
        seeds.append(
            {
                "symbol": sym,
                "name": name,
                "sector": sector or None,
                "exchange": str(r.get("exchange") or "NSE"),
                "facts": facts,
                "filings": filing_refs,
                "ratios": ratios,
            }
        )
    return syms, seeds, True


def resolve_news_items(
    cfg: dict[str, Any] | None = None,
    *,
    max_n: int | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Return ``(items, auto)`` for News Intelligence.

    Operator ``headlines`` / ``items`` win. Otherwise, when
    ``seed_from_watchlist`` is true (default), emit symbol-tagged monitoring
    seeds from the ranked watchlist (honest stubs — not fabricated market news).
    """
    cfg = cfg or {}
    items: list[dict[str, Any]] = []
    for raw in cfg.get("items") or []:
        if isinstance(raw, dict) and raw.get("text"):
            items.append(dict(raw))
    for headline in cfg.get("headlines") or []:
        text = str(headline).strip()
        if text:
            items.append({"text": text, "source": "headline"})
    if items:
        return items, False

    seed = cfg.get("seed_from_watchlist")
    if seed is None:
        seed = True
    if not seed:
        return [], False

    n = max_n if max_n is not None else _auto_max(cfg, default=10)
    rows = ranked_rows(program_id_from(cfg), max_n=n)
    out: list[dict[str, Any]] = []
    for r in rows:
        sym = str(r.get("symbol") or "").strip()
        if not sym:
            continue
        name = str(r.get("name") or sym).strip()
        out.append(
            {
                "text": (
                    f"{name} ({sym}) is on the Atlas Investment Universe watchlist — "
                    f"monitor material news and regulatory filings."
                ),
                "symbol": sym,
                "source": "watchlist_seed",
                "seed": True,
                "evidence_class": "non_evidence",
            }
        )
    return out, bool(out)
