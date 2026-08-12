"""UTS.A — Universe triage memory: persist the full daily rank ladder.

M0 scores the entire membership pool; the deep watchlist truncates to top-N.
This module persists **all** scored rows so Atlas can remember #16–#190,
compute acceleration later (UTS.B), and report hard coverage KPIs.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_log = logging.getLogger("atlas.investment.triage_memory")

VERSION = "uts.b.triage_memory"
STORE_REL = Path("investment") / "triage"
_IST = ZoneInfo("Asia/Kolkata")

# Compact fields written per symbol (omit bulky explanation lists by default).
_ROW_KEYS = (
    "symbol",
    "name",
    "sector",
    "nse_symbol",
    "exchange",
    "asset_class",
    "rank",
    "score",
    "components",
    "confidence",
    "phase",
    "reason",
    "last_price",
    "rank_delta_1d",
    "rank_delta_3d",
    "rank_delta_5d",
    "acceleration_3d",
    "accel_score",
)


def ist_today() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def _safe_id(raw: str) -> str:
    s = (raw or "market_intelligence").strip() or "market_intelligence"
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", s)[:80]


def triage_root(data_dir: str | Path | None) -> Path | None:
    if not data_dir:
        return None
    return Path(data_dir) / STORE_REL


def triage_program_dir(data_dir: str | Path | None, program_id: str) -> Path | None:
    root = triage_root(data_dir)
    if root is None:
        return None
    return root / _safe_id(program_id)


def triage_day_path(
    data_dir: str | Path | None,
    program_id: str,
    as_of_ist: str | None = None,
) -> Path | None:
    base = triage_program_dir(data_dir, program_id)
    if base is None:
        return None
    day = (as_of_ist or ist_today()).strip()
    return base / f"{day}.jsonl"


def coverage_from_rows(
    rows: list[dict[str, Any]],
    *,
    membership: int | None = None,
    persisted: bool = False,
    as_of_ist: str | None = None,
    acceleration_ready: bool | None = None,
) -> dict[str, Any]:
    """Coverage KPI stub (UTS.A/B hard OS fields as data allows)."""
    n = len(rows)
    mem = int(membership) if membership is not None else n
    with_price = sum(
        1
        for r in rows
        if isinstance(r, dict) and r.get("last_price") is not None
    )
    price_pct = round(100.0 * with_price / max(1, mem), 1) if mem else 0.0
    with_accel = sum(
        1
        for r in rows
        if isinstance(r, dict) and r.get("acceleration_3d") is not None
    )
    if acceleration_ready is None:
        acceleration_ready = with_accel > 0
    return {
        "version": VERSION,
        "as_of_ist": as_of_ist or ist_today(),
        "universe_scanned": f"{n}/{mem}",
        "scanned": n,
        "membership": mem,
        "price_coverage_pct": price_pct,
        "price_with_last": with_price,
        "rank_ladder_persisted": bool(persisted),
        "acceleration_computed": bool(acceleration_ready),
        "acceleration_symbols": with_accel,
        "acceleration_status": (
            "ready" if acceleration_ready else "pending_history"
        ),
        "honesty": (
            "Triage coverage is deterministic. "
            "Acceleration needs ≥3 persisted triage days for a symbol (UTS.B)."
            if not acceleration_ready
            else "Acceleration computed where history allows (UTS.B)."
        ),
    }


def _parse_rank(row: dict[str, Any] | None) -> int | None:
    if not isinstance(row, dict):
        return None
    try:
        r = int(row.get("rank"))
    except (TypeError, ValueError):
        return None
    return r if r > 0 else None


def load_prior_rank_maps(
    data_dir: str | Path | None,
    program_id: str,
    *,
    before_day: str,
    lookback_days: int = 5,
) -> list[tuple[str, dict[str, int]]]:
    """Return ``[(day, {symbol: rank}), ...]`` oldest→newest strictly before ``before_day``."""
    days = [d for d in list_triage_days(data_dir, program_id) if d < before_day]
    if lookback_days > 0:
        days = days[-int(lookback_days) :]
    out: list[tuple[str, dict[str, int]]] = []
    for day in days:
        packed = load_triage_day(data_dir, program_id, day)
        m: dict[str, int] = {}
        for row in packed.get("rows") or []:
            sym = str(row.get("symbol") or "").strip().upper()
            rk = _parse_rank(row)
            if sym and rk is not None:
                m[sym] = rk
        if m:
            out.append((day, m))
    return out


def enrich_rows_with_acceleration(
    rows: list[dict[str, Any]],
    *,
    data_dir: str | Path | None,
    program_id: str,
    as_of_ist: str | None = None,
    lookback_days: int = 5,
) -> dict[str, Any]:
    """Attach rank_delta_* and acceleration_3d onto scored rows (in place).

    ``acceleration_3d = rank(t-3) - rank(t)`` (positive = improved toward #1).
    Deltas null when history is short — never invented.
    """
    day = (as_of_ist or ist_today()).strip()
    priors = load_prior_rank_maps(
        data_dir, program_id, before_day=day, lookback_days=lookback_days
    )
    # priors oldest→newest; index from end: -1 = t-1, -3 = t-3, -5 = t-5
    enriched = 0
    membership = max(len(rows), 1)
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        sym = str(raw.get("symbol") or "").strip().upper()
        cur = _parse_rank(raw)
        raw["rank_delta_1d"] = None
        raw["rank_delta_3d"] = None
        raw["rank_delta_5d"] = None
        raw["acceleration_3d"] = None
        raw["accel_score"] = None
        if not sym or cur is None:
            continue

        def _delta_at(offset: int) -> int | None:
            # offset 1 => yesterday
            if len(priors) < offset:
                return None
            prev = priors[-offset][1].get(sym)
            if prev is None:
                return None
            return int(prev) - int(cur)

        d1 = _delta_at(1)
        d3 = _delta_at(3)
        d5 = _delta_at(5)
        raw["rank_delta_1d"] = d1
        raw["rank_delta_3d"] = d3
        raw["rank_delta_5d"] = d5
        # Prefer explicit 3-day-ago rank for acceleration when present
        if len(priors) >= 3 and sym in priors[-3][1]:
            accel = int(priors[-3][1][sym]) - int(cur)
            raw["acceleration_3d"] = accel
            raw["accel_score"] = round(
                max(0.0, min(1.0, float(accel) / float(membership))), 4
            )
            enriched += 1
        elif d3 is not None:
            raw["acceleration_3d"] = d3
            raw["accel_score"] = round(
                max(0.0, min(1.0, float(d3) / float(membership))), 4
            )
            enriched += 1
    return {
        "as_of_ist": day,
        "prior_days": [d for d, _ in priors],
        "acceleration_symbols": enriched,
        "acceleration_ready": enriched > 0,
    }


def build_opportunity_queue(
    rows: list[dict[str, Any]],
    *,
    max_watchlist: int = 15,
    near_miss_end: int = 25,
    min_acceleration: int = 1,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """UTS.B attention queue: accelerators outside top-N + near-misses (#N+1..near_miss_end)."""
    max_n = max(1, int(max_watchlist))
    near_end = max(max_n + 1, int(near_miss_end))
    min_accel = int(min_acceleration)
    queue: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(row: dict[str, Any], reason: str, *, priority: float) -> None:
        sym = str(row.get("symbol") or "").strip()
        if not sym or sym in seen:
            return
        seen.add(sym)
        queue.append(
            {
                "symbol": sym,
                "name": row.get("name") or "",
                "sector": row.get("sector") or "",
                "rank": row.get("rank"),
                "score": row.get("score"),
                "acceleration_3d": row.get("acceleration_3d"),
                "rank_delta_1d": row.get("rank_delta_1d"),
                "reason": reason,
                "priority": round(float(priority), 4),
            }
        )

    # Accelerators outside deep watchlist
    accel_rows = [
        r
        for r in rows
        if isinstance(r, dict)
        and _parse_rank(r) is not None
        and int(r["rank"]) > max_n
        and r.get("acceleration_3d") is not None
        and int(r["acceleration_3d"]) >= min_accel
    ]
    accel_rows.sort(
        key=lambda r: (-int(r.get("acceleration_3d") or 0), int(r.get("rank") or 9999))
    )
    for r in accel_rows:
        _add(
            r,
            "acceleration_outside_watchlist",
            priority=1000.0 + float(r.get("acceleration_3d") or 0),
        )

    # Near misses: ranks max_n+1 .. near_end (esp. with positive 1d delta)
    near = [
        r
        for r in rows
        if isinstance(r, dict)
        and _parse_rank(r) is not None
        and max_n < int(r["rank"]) <= near_end
    ]
    near.sort(
        key=lambda r: (
            -(int(r.get("rank_delta_1d") or 0) if r.get("rank_delta_1d") is not None else -999),
            int(r.get("rank") or 9999),
        )
    )
    for r in near:
        reason = "near_miss"
        if r.get("acceleration_3d") is not None and int(r["acceleration_3d"]) >= min_accel:
            reason = "near_miss_accelerating"
        _add(
            r,
            reason,
            priority=500.0 - float(r.get("rank") or 0) + float(r.get("rank_delta_1d") or 0),
        )

    queue.sort(key=lambda q: -float(q.get("priority") or 0))
    return queue[: max(1, int(limit))]


def evening_triage_snapshot(
    rows: list[dict[str, Any]],
    *,
    max_watchlist: int = 15,
    near_miss_end: int = 25,
    limit: int = 8,
) -> dict[str, Any]:
    """Compact blocks for evening honesty: accelerating + near-misses."""
    max_n = max(1, int(max_watchlist))
    near_end = max(max_n + 1, int(near_miss_end))

    accelerating = [
        r
        for r in rows
        if isinstance(r, dict)
        and r.get("acceleration_3d") is not None
        and int(r["acceleration_3d"]) >= 1
        and _parse_rank(r) is not None
        and int(r["rank"]) <= near_end
    ]
    accelerating.sort(
        key=lambda r: (-int(r.get("acceleration_3d") or 0), int(r.get("rank") or 9999))
    )

    near_misses = [
        r
        for r in rows
        if isinstance(r, dict)
        and _parse_rank(r) is not None
        and max_n < int(r["rank"]) <= near_end
    ]
    near_misses.sort(key=lambda r: int(r.get("rank") or 9999))

    def _brief(r: dict[str, Any]) -> dict[str, Any]:
        return {
            "symbol": r.get("symbol"),
            "rank": r.get("rank"),
            "acceleration_3d": r.get("acceleration_3d"),
            "rank_delta_1d": r.get("rank_delta_1d"),
            "score": r.get("score"),
        }

    return {
        "accelerating": [_brief(r) for r in accelerating[:limit]],
        "near_misses": [_brief(r) for r in near_misses[:limit]],
        "max_watchlist": max_n,
        "near_miss_band": [max_n + 1, near_end],
    }


def persist_triage_day(
    data_dir: str | Path | None,
    program_id: str,
    rows: list[dict[str, Any]],
    *,
    as_of_ist: str | None = None,
    membership: int | None = None,
    include_explanations: bool = False,
    extra: dict[str, Any] | None = None,
    enrich_acceleration: bool = True,
    max_watchlist: int = 15,
    opportunity_queue_enabled: bool = True,
) -> dict[str, Any]:
    """Write one JSONL line per scored member for the IST day (overwrite).

    When ``enrich_acceleration`` is true, attaches rank deltas / acceleration from
    prior triage days (UTS.B) before writing.
    """
    day = (as_of_ist or ist_today()).strip()
    path = triage_day_path(data_dir, program_id, day)
    working = [dict(r) for r in rows if isinstance(r, dict)]
    accel_meta: dict[str, Any] = {}
    if enrich_acceleration and data_dir:
        accel_meta = enrich_rows_with_acceleration(
            working,
            data_dir=data_dir,
            program_id=program_id,
            as_of_ist=day,
        )
    queue: list[dict[str, Any]] = []
    if opportunity_queue_enabled:
        queue = build_opportunity_queue(working, max_watchlist=max_watchlist)
    evening = evening_triage_snapshot(working, max_watchlist=max_watchlist)

    if path is None:
        return {
            "ok": False,
            "reason": "no_data_dir",
            "opportunity_queue": queue,
            "evening": evening,
            "coverage": coverage_from_rows(
                working,
                membership=membership,
                persisted=False,
                as_of_ist=day,
                acceleration_ready=bool(accel_meta.get("acceleration_ready")),
            ),
        }

    path.parent.mkdir(parents=True, exist_ok=True)
    compact: list[dict[str, Any]] = []
    for raw in working:
        sym = str(raw.get("symbol") or "").strip()
        if not sym:
            continue
        row = {k: raw.get(k) for k in _ROW_KEYS if k in raw or k in ("symbol", "rank", "score")}
        row["symbol"] = sym
        row["as_of_ist"] = day
        if include_explanations and raw.get("explanations") is not None:
            row["explanations"] = raw.get("explanations")
        compact.append(row)

    extra_doc = dict(extra or {})
    extra_doc["opportunity_queue"] = queue
    extra_doc["evening"] = evening
    extra_doc["acceleration"] = {
        "prior_days": accel_meta.get("prior_days") or [],
        "acceleration_symbols": accel_meta.get("acceleration_symbols") or 0,
        "ready": bool(accel_meta.get("acceleration_ready")),
    }

    meta = {
        "version": VERSION,
        "kind": "triage_day_meta",
        "as_of_ist": day,
        "program_id": program_id,
        "count": len(compact),
        "membership": int(membership) if membership is not None else len(compact),
        "extra": extra_doc,
    }
    try:
        with path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(meta, ensure_ascii=False) + "\n")
            for row in compact:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        # Durable latest queue snapshot for evening / status chat
        qpath = path.with_suffix(".queue.json")
        qpath.write_text(
            json.dumps(
                {
                    "version": VERSION,
                    "as_of_ist": day,
                    "program_id": program_id,
                    "queue": queue,
                    "evening": evening,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        _log.warning("triage persist failed: %s", exc)
        return {
            "ok": False,
            "reason": f"write_failed:{type(exc).__name__}",
            "path": str(path),
            "opportunity_queue": queue,
            "evening": evening,
            "coverage": coverage_from_rows(
                compact,
                membership=membership,
                persisted=False,
                as_of_ist=day,
                acceleration_ready=bool(accel_meta.get("acceleration_ready")),
            ),
        }

    cov = coverage_from_rows(
        compact,
        membership=membership,
        persisted=True,
        as_of_ist=day,
        acceleration_ready=bool(accel_meta.get("acceleration_ready")),
    )
    return {
        "ok": True,
        "path": str(path),
        "as_of_ist": day,
        "count": len(compact),
        "coverage": cov,
        "opportunity_queue": queue,
        "evening": evening,
        "acceleration": accel_meta,
        "version": VERSION,
    }


def load_triage_day(
    data_dir: str | Path | None,
    program_id: str,
    as_of_ist: str | None = None,
) -> dict[str, Any]:
    """Load a persisted triage day: ``{meta, rows, coverage}``."""
    day = (as_of_ist or ist_today()).strip()
    path = triage_day_path(data_dir, program_id, day)
    empty = {
        "ok": False,
        "as_of_ist": day,
        "meta": None,
        "rows": [],
        "coverage": coverage_from_rows([], persisted=False, as_of_ist=day),
        "path": str(path) if path else None,
    }
    if path is None or not path.is_file():
        empty["reason"] = "missing"
        return empty

    meta: dict[str, Any] | None = None
    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                doc = json.loads(line)
                if not isinstance(doc, dict):
                    continue
                if doc.get("kind") == "triage_day_meta":
                    meta = doc
                    continue
                if doc.get("symbol"):
                    rows.append(doc)
    except Exception as exc:  # noqa: BLE001
        empty["reason"] = f"read_failed:{type(exc).__name__}"
        return empty

    mem = None
    if isinstance(meta, dict) and meta.get("membership") is not None:
        try:
            mem = int(meta["membership"])
        except (TypeError, ValueError):
            mem = None
    cov = coverage_from_rows(rows, membership=mem, persisted=True, as_of_ist=day)
    extra = (meta or {}).get("extra") if isinstance(meta, dict) else {}
    queue = []
    evening = {}
    if isinstance(extra, dict):
        queue = list(extra.get("opportunity_queue") or [])
        evening = dict(extra.get("evening") or {})
    return {
        "ok": True,
        "as_of_ist": day,
        "meta": meta,
        "rows": rows,
        "coverage": cov,
        "opportunity_queue": queue,
        "evening": evening,
        "path": str(path),
        "version": VERSION,
    }


def list_triage_days(data_dir: str | Path | None, program_id: str) -> list[str]:
    base = triage_program_dir(data_dir, program_id)
    if base is None or not base.is_dir():
        return []
    days: list[str] = []
    for p in sorted(base.glob("*.jsonl")):
        stem = p.stem
        if len(stem) == 10 and stem[4] == "-" and stem[7] == "-":
            days.append(stem)
    return days


def latest_triage_day(
    data_dir: str | Path | None, program_id: str
) -> dict[str, Any]:
    days = list_triage_days(data_dir, program_id)
    if not days:
        return {
            "ok": False,
            "reason": "none",
            "rows": [],
            "coverage": coverage_from_rows([], persisted=False),
        }
    return load_triage_day(data_dir, program_id, days[-1])


def symbol_history(
    data_dir: str | Path | None,
    program_id: str,
    symbol: str,
    *,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Recent triage rows for one symbol (oldest→newest), up to ``limit`` days."""
    sym = str(symbol or "").strip().upper()
    if not sym:
        return []
    if not sym.endswith(".NS") and "." not in sym:
        # accept bare NSE codes matching stored .NS
        candidates = {sym, f"{sym}.NS"}
    else:
        candidates = {sym}

    days = list_triage_days(data_dir, program_id)
    if limit > 0:
        days = days[-int(limit) :]
    out: list[dict[str, Any]] = []
    for day in days:
        packed = load_triage_day(data_dir, program_id, day)
        for row in packed.get("rows") or []:
            if str(row.get("symbol") or "").upper() in candidates:
                out.append(row)
                break
    return out


def load_latest_triage_bundle(
    data_dir: str | Path | None,
    program_id: str = "market_intelligence",
) -> dict[str, Any]:
    """Latest triage day + queue + evening snapshot for reports / status chat."""
    packed = latest_triage_day(data_dir, program_id)
    if not packed.get("ok"):
        return packed
    meta = packed.get("meta") if isinstance(packed.get("meta"), dict) else {}
    extra = meta.get("extra") if isinstance(meta.get("extra"), dict) else {}
    queue = list(packed.get("opportunity_queue") or extra.get("opportunity_queue") or [])
    evening = dict(packed.get("evening") or extra.get("evening") or {})
    if not queue or not evening:
        # Prefer sidecar if meta predates UTS.B
        path = packed.get("path")
        if path:
            qpath = Path(str(path)).with_suffix(".queue.json")
            if qpath.is_file():
                try:
                    side = json.loads(qpath.read_text(encoding="utf-8"))
                    if isinstance(side, dict):
                        queue = list(side.get("queue") or queue)
                        evening = dict(side.get("evening") or evening)
                except Exception:  # noqa: BLE001
                    pass
    packed["opportunity_queue"] = queue
    packed["evening"] = evening
    return packed


def format_triage_evening_lines(triage: dict[str, Any] | None) -> list[str]:
    """Evening honesty lines for universe triage / acceleration / near-misses."""
    if not isinstance(triage, dict) or not triage.get("ok"):
        return [
            "  Universe triage: (no ladder persisted yet — await M0 tick with "
            "universe_triage_persist)"
        ]
    cov = triage.get("coverage") if isinstance(triage.get("coverage"), dict) else {}
    evening = triage.get("evening") if isinstance(triage.get("evening"), dict) else {}
    queue = list(triage.get("opportunity_queue") or [])
    lines = [
        f"  Universe triage: scanned {cov.get('universe_scanned', '—')} · "
        f"ladder={'yes' if cov.get('rank_ladder_persisted') else 'no'} · "
        f"accel={cov.get('acceleration_status', '—')} "
        f"({cov.get('acceleration_symbols', 0)} syms) · "
        f"price_cov={cov.get('price_coverage_pct', '—')}%"
    ]
    accel = list(evening.get("accelerating") or [])
    if accel:
        bits = [
            f"{a.get('symbol')}#{a.get('rank')}Δ3={a.get('acceleration_3d')}"
            for a in accel[:6]
            if isinstance(a, dict)
        ]
        lines.append("  Accelerating (into / near watchlist): " + ", ".join(bits))
    else:
        status = cov.get("acceleration_status") or "pending_history"
        if status == "pending_history":
            lines.append(
                "  Accelerating: (pending — need ≥3 triage days of history)"
            )
        else:
            lines.append("  Accelerating: (none with positive accel in band today)")
    near = list(evening.get("near_misses") or [])
    band = evening.get("near_miss_band") or []
    if near:
        bits = [
            f"{n.get('symbol')}#{n.get('rank')}"
            + (
                f"Δ1={n.get('rank_delta_1d')}"
                if n.get("rank_delta_1d") is not None
                else ""
            )
            for n in near[:8]
            if isinstance(n, dict)
        ]
        band_s = f"#{band[0]}–#{band[1]}" if len(band) == 2 else "#16–#25"
        lines.append(f"  Near misses ({band_s}): " + ", ".join(bits))
    if queue:
        qbits = [
            f"{q.get('symbol')}({q.get('reason')})"
            for q in queue[:6]
            if isinstance(q, dict)
        ]
        lines.append(f"  Opportunity queue ({len(queue)}): " + ", ".join(qbits))
    return lines
