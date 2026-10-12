#!/usr/bin/env python3
"""OI-DELI0 Step 1 — read-only single-trade causal-chain tracer.

Reconstructs a closed round trip from durable stores. Every cell is either
filled from a named source or marked MISSING / CONFLICT / AMBIGUOUS /
CALCULATED / LOG_ONLY / NOT_APPLICABLE. Never changes trading behaviour.

Usage:
  .venv/bin/python scripts/trace_trade.py --trade-id <uuid>
      [--data-dir /data/atlas_data]
      [--db-dump-dir docs/traces/_db_dump]
      [--out-md docs/traces/....md]
      [--out-json docs/traces/....json]
      [--lab india_fno_learner]
      [--include-logs]
      [--strict]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
SCRIPT_VERSION = "trace_trade.v1"
FRESH_LTP_MAX_AGE_S = 15 * 60
UNDERLIER_ALIASES: dict[str, tuple[str, ...]] = {
    "NIFTY": ("_NSEI", "^NSEI", "NSEI"),
    "BANKNIFTY": ("^NSEBANK", "_NSEBANK", "NSEBANK"),
}
DIMENSION_ORDER = (
    "IDENTITY",
    "ACCOUNTING",
    "DECISION_LINKAGE",
    "DECISION_EVIDENCE",
    "ATTRIBUTION",
    "LEARNING",
)
STATUSES = {
    "OK",
    "MISSING",
    "CONFLICT",
    "AMBIGUOUS",
    "CALCULATED",
    "LOG_ONLY",
    "NOT_APPLICABLE",
}
GAP_CLASSES = {"PERSISTENCE", "LINKAGE", "COMPUTATION", "ATTRIBUTION", "LEARNING"}


# ---------------------------------------------------------------------------
# Cell model
# ---------------------------------------------------------------------------


@dataclass
class SourceRef:
    kind: str  # db | file | log | calculated
    ref: str
    sha256: str | None = None
    mtime_ist: str | None = None
    original_ts: str | None = None
    original_tz: str | None = None


@dataclass
class Cell:
    dimension: str
    step: int
    field: str
    value: Any
    status: str
    gap_class: str | None = None
    blocked_by: list[str] = field(default_factory=list)
    sources: list[SourceRef] = field(default_factory=list)
    note: str = ""

    def critical(self) -> bool:
        return self.status in {"MISSING", "CONFLICT", "AMBIGUOUS"}


# ---------------------------------------------------------------------------
# Time / hashing helpers
# ---------------------------------------------------------------------------


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace(" ", "T", 1)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        # tolerate missing T separator already handled; missing offset → UTC
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def to_ist(value: Any) -> datetime | None:
    dt = _parse_ts(value)
    return dt.astimezone(IST) if dt else None


def ist_iso(value: Any) -> str | None:
    dt = to_ist(value)
    return dt.isoformat() if dt else None


def ist_day(value: Any) -> str | None:
    dt = to_ist(value)
    return dt.date().isoformat() if dt else None


def file_meta(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    mtime = datetime.fromtimestamp(path.stat().st_mtime, IST).isoformat()
    return sha, mtime


def source_file(path: Path, pointer: str = "", original_ts: Any = None) -> SourceRef:
    sha, mtime = file_meta(path)
    dt = _parse_ts(original_ts)
    return SourceRef(
        kind="file",
        ref=f"{path.as_posix()}#{pointer}" if pointer else path.as_posix(),
        sha256=sha,
        mtime_ist=mtime,
        original_ts=dt.isoformat() if dt else (None if original_ts is None else str(original_ts)),
        original_tz=str(dt.tzinfo) if dt else None,
    )


def source_db(table: str, row_id: str, original_ts: Any = None) -> SourceRef:
    dt = _parse_ts(original_ts)
    return SourceRef(
        kind="db",
        ref=f"{table}:{row_id}",
        original_ts=dt.isoformat() if dt else None,
        original_tz=str(dt.tzinfo) if dt else None,
    )


def source_calc(formula: str) -> SourceRef:
    return SourceRef(kind="calculated", ref=formula)


def _json_load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl_load(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


def _git_sha(repo: Path) -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            or "unknown"
        )
    except Exception:  # noqa: BLE001
        return "unknown"


# ---------------------------------------------------------------------------
# Pairing (A28 / AMBIGUOUS)
# ---------------------------------------------------------------------------


def pair_round_trip(
    seed: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Pair entry/exit from trade ids and quantities.

    Returns dict with keys: status OK|AMBIGUOUS|MISSING, entry, exit, note, candidates.
    """
    seed_side = str(seed.get("side") or "").lower()
    seed_qty = float(seed.get("quantity") or 0)
    buys = [t for t in candidates if str(t.get("side") or "").lower() == "buy"]
    sells = [t for t in candidates if str(t.get("side") or "").lower() == "sell"]

    if seed_side == "buy":
        entry = dict(seed)
        matching_exits = [s for s in sells if abs(float(s.get("quantity") or 0) - seed_qty) < 1e-9]
        if len(matching_exits) == 1:
            return {
                "status": "OK",
                "entry": entry,
                "exit": dict(matching_exits[0]),
                "note": "unique equal-quantity buy/sell pair on symbol+portfolio+day",
                "candidates": [],
            }
        if len(matching_exits) == 0 and len(sells) == 1:
            return {
                "status": "OK",
                "entry": entry,
                "exit": dict(sells[0]),
                "note": "single sell on symbol+day (qty differs — reported)",
                "candidates": [],
            }
        if not sells:
            return {
                "status": "MISSING",
                "entry": entry,
                "exit": None,
                "note": "no sell candidates",
                "candidates": [],
            }
        return {
            "status": "AMBIGUOUS",
            "entry": entry,
            "exit": None,
            "note": "multiple sell candidates; refusing silent FIFO",
            "candidates": [str(s.get("id")) for s in matching_exits or sells],
        }

    if seed_side == "sell":
        exit_t = dict(seed)
        matching_entries = [b for b in buys if abs(float(b.get("quantity") or 0) - seed_qty) < 1e-9]
        if len(matching_entries) == 1:
            return {
                "status": "OK",
                "entry": dict(matching_entries[0]),
                "exit": exit_t,
                "note": "unique equal-quantity buy/sell pair on symbol+portfolio+day",
                "candidates": [],
            }
        if len(matching_entries) == 0 and len(buys) == 1:
            return {
                "status": "OK",
                "entry": dict(buys[0]),
                "exit": exit_t,
                "note": "single buy on symbol+day (qty differs — reported)",
                "candidates": [],
            }
        if not buys:
            return {
                "status": "MISSING",
                "entry": None,
                "exit": exit_t,
                "note": "no buy candidates",
                "candidates": [],
            }
        return {
            "status": "AMBIGUOUS",
            "entry": None,
            "exit": exit_t,
            "note": "multiple buy candidates; refusing silent FIFO",
            "candidates": [str(b.get("id")) for b in matching_entries or buys],
        }

    return {
        "status": "MISSING",
        "entry": None,
        "exit": None,
        "note": f"unknown side {seed_side!r}",
        "candidates": [],
    }


# ---------------------------------------------------------------------------
# Accounting helpers (acct.v1 / roc.v1 — check only)
# ---------------------------------------------------------------------------


def recompute_round_trip(
    entry: Mapping[str, Any],
    exit_t: Mapping[str, Any],
) -> dict[str, Any]:
    qty = float(exit_t.get("quantity") or 0)
    entry_price = float(entry.get("price") or 0)
    exit_price = float(exit_t.get("price") or 0)
    entry_fee = float(entry.get("fee") or 0)
    exit_fee = float(exit_t.get("fee") or 0)
    # Stored sell realized is already exit-fee net (F18). Check equals gross − exit_fee.
    gross = (exit_price - entry_price) * qty
    check_realized = gross - exit_fee
    stored = float(exit_t.get("realized_pnl") or 0)
    # Entry fees excluded from stored realized; round_trip_net subtracts them once.
    allocated_entry_fee = entry_fee  # full exit of this entry qty in unambiguous 1:1 case
    round_trip_net = stored - allocated_entry_fee
    entry_cost = qty * entry_price + allocated_entry_fee
    roc = (round_trip_net / entry_cost * 100.0) if entry_cost else None
    stored_ret = None
    # Some stores keep realized_return_pct elsewhere; caller may attach.
    return {
        "gross": gross,
        "check_realized_exit_fee_net": check_realized,
        "stored_realized": stored,
        "entry_fee_allocated": allocated_entry_fee,
        "exit_fee": exit_fee,
        "round_trip_net": round_trip_net,
        "entry_cost": entry_cost,
        "roc_v1_pct": roc,
        "stored_return_pct": stored_ret,
    }


def session_context_moves(prior_close: float, day_open: float, day_close: float) -> dict[str, float]:
    o2c = (day_close - day_open) / day_open * 100.0
    c2c = (day_close - prior_close) / prior_close * 100.0
    return {"open_to_close_pct": o2c, "close_to_close_pct": c2c}


# ---------------------------------------------------------------------------
# Attribution classifier (mechanical)
# ---------------------------------------------------------------------------


def classify_attribution(
    *,
    has_entry_exit_underlier_path: bool,
    has_iv: bool,
    helped_factors: Sequence[str],
    narrative: str | None,
    false_missing_session_bar_claim: bool,
) -> dict[str, Any]:
    notes: list[str] = []
    if "option_premium_path" in helped_factors:
        notes.append("mechanical: outcome channel listed as cause (circular)")
    if narrative and "premium path was the primary driver" in narrative.lower():
        notes.append("mechanical: LLM narrative uses premium path as cause")
    if false_missing_session_bar_claim:
        notes.append("mechanical: attribution claimed no session bar but daily bar exists")
    if not has_entry_exit_underlier_path and not has_iv:
        state = "NOT_EVALUABLE"
    elif has_entry_exit_underlier_path or has_iv:
        state = "PARTIAL"
    else:
        state = "NOT_EVALUABLE"
    return {"state": state, "notes": notes}


def first_blocking_dependency(cells: Sequence[Cell]) -> dict[str, Any]:
    by_dim: dict[str, list[Cell]] = {d: [] for d in DIMENSION_ORDER}
    for c in cells:
        by_dim.setdefault(c.dimension, []).append(c)
    for dim in DIMENSION_ORDER:
        bad = [c for c in by_dim.get(dim, []) if c.critical()]
        if bad:
            return {
                "dimension": dim,
                "fields": [c.field for c in bad],
                "gap_classes": sorted({c.gap_class for c in bad if c.gap_class}),
            }
    return {"dimension": None, "fields": [], "gap_classes": []}


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


class TraceSources:
    """Read-only accessors. Prefer live DB; optional dump dir for offline/agent netns."""

    def __init__(
        self,
        data_dir: Path,
        *,
        lab: str = "india_fno_learner",
        db_dump_dir: Path | None = None,
        include_logs: bool = False,
    ) -> None:
        self.data_dir = data_dir.resolve()
        self.lab = lab
        self.db_dump_dir = db_dump_dir.resolve() if db_dump_dir else None
        self.include_logs = include_logs
        self._conn = None
        self.db_mode = "none"
        self._connect()

    def _connect(self) -> None:
        # Explicit dump dir wins (tests / agent netns offline mode).
        if self.db_dump_dir and (self.db_dump_dir / "same_symbol_day.json").exists():
            self._conn = None
            self.db_mode = f"dump:{self.db_dump_dir}"
            return
        try:
            import psycopg
            from psycopg.rows import dict_row

            password = os.environ.get("ATLAS_DB_PASSWORD", "")
            if not password and Path("/data/atlas/.env").exists():
                for line in Path("/data/atlas/.env").read_text().splitlines():
                    if line.startswith("ATLAS_DB_PASSWORD="):
                        password = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
            conn = psycopg.connect(
                host=os.environ.get("ATLAS_DB_HOST", "localhost"),
                port=int(os.environ.get("ATLAS_DB_PORT", "5432")),
                dbname=os.environ.get("ATLAS_DB_NAME", "atlas"),
                user=os.environ.get("ATLAS_DB_USER", "atlas"),
                password=password,
                row_factory=dict_row,
                connect_timeout=3,
            )
            conn.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
            self._conn = conn
            self.db_mode = "live"
        except Exception as exc:  # noqa: BLE001
            self._conn = None
            self.db_mode = f"unavailable:{type(exc).__name__}:{exc}"

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def load_trade(self, trade_id: str) -> dict[str, Any] | None:
        if self._conn is not None:
            row = self._conn.execute(
                "SELECT * FROM sim.trades WHERE id = %s::uuid", (trade_id,)
            ).fetchone()
            return dict(row) if row else None
        if not self.db_dump_dir:
            return None
        for name in ("entry_trade.json", "exit_trade.json"):
            p = self.db_dump_dir / name
            if not p.exists():
                continue
            row = _json_load(p)
            if str(row.get("id")) == trade_id:
                return row
        day = self.db_dump_dir / "same_symbol_day.json"
        if day.exists():
            for t in _json_load(day).get("trades") or []:
                if str(t.get("id")) == trade_id:
                    return t
        return None

    def load_same_symbol_day(self, portfolio_id: str, symbol: str, day: str) -> list[dict[str, Any]]:
        if self._conn is not None:
            rows = self._conn.execute(
                """
                SELECT * FROM sim.trades
                WHERE portfolio_id = %s::uuid AND symbol = %s
                  AND (created_at AT TIME ZONE 'Asia/Kolkata')::date = %s::date
                ORDER BY created_at ASC
                """,
                (portfolio_id, symbol, day),
            ).fetchall()
            return [dict(r) for r in rows]
        if self.db_dump_dir:
            # Prefer explicit entry+exit dump files when both exist (multi-day holds).
            ep = self.db_dump_dir / "entry_trade.json"
            xp = self.db_dump_dir / "exit_trade.json"
            if ep.exists() and xp.exists():
                entry = _json_load(ep)
                exit_t = _json_load(xp)
                if (
                    str(entry.get("portfolio_id")) == str(portfolio_id)
                    and str(entry.get("symbol")) == str(symbol)
                    and str(exit_t.get("symbol")) == str(symbol)
                ):
                    return [entry, exit_t]
            day_path = self.db_dump_dir / "same_symbol_day.json"
            if day_path.exists():
                doc = _json_load(day_path)
                return [dict(t) for t in doc.get("trades") or []]
        return []

    def load_decision(self, decision_id: str | None) -> dict[str, Any] | None:
        if not decision_id:
            return None
        if self._conn is not None:
            row = self._conn.execute(
                "SELECT * FROM decision.decisions WHERE id = %s::uuid", (decision_id,)
            ).fetchone()
            return dict(row) if row else None
        if self.db_dump_dir:
            for name in ("entry_decision.json", "exit_decision.json"):
                p = self.db_dump_dir / name
                if not p.exists():
                    continue
                raw = _json_load(p)
                if raw is None:
                    continue
                if str(raw.get("id")) == decision_id:
                    return raw
        return None

    def path(self, *parts: str) -> Path:
        return self.data_dir.joinpath(*parts)

    def prediction_path(self, contract: str) -> Path:
        return self.path("investment", "fno", "lab_v1_predictions", f"{contract}.json")

    def pack_path(self, underlying: str, day: str) -> Path:
        return self.path("investment", "fno", "packs", f"{underlying}_{day}.json")

    def integrity_path(self, day: str) -> Path:
        return self.path("investment", "fno", "lab_v1_integrity", f"{day}.json")

    def learning_path(self, day: str) -> Path:
        return self.path("investment", "learning", self.lab, f"{day}.jsonl")

    def fel_path(self) -> Path:
        return self.path(
            "investment",
            "fel",
            "datasets",
            self.lab,
            f"DS-E-paper-round-trip-{self.lab}.jsonl",
        )

    def by_day_path(self, day: str) -> Path:
        return self.path("investment", "decisions", "by_day", self.lab, f"{day}.jsonl")

    def timeline_path(self, symbol: str) -> Path:
        return self.path("investment", "decisions", "timeline", f"{symbol}.jsonl")

    def kpi_path(self, day: str) -> Path:
        return self.path("market", "trading_kpis", self.lab, f"{day}.json")

    def thesis_path(self, symbol: str) -> Path:
        sym = str(symbol)
        if sym.endswith(".NS") or sym.endswith(".BO"):
            return self.path(
                "investment", "thesis_tracker", "market_intelligence", f"{sym}.json"
            )
        return self.path(
            "investment", "thesis_tracker", "market_intelligence", f"{sym}.NS.json"
        )

    def bars_path(self, alias: str) -> Path:
        # aliases may start with ^
        if alias.startswith("^"):
            # try both
            p1 = self.path("market", "bars", f"{alias}.json")
            p2 = self.path("market", "bars", f"_{alias[1:]}.json")
            if p1.exists():
                return p1
            return p2
        # cash equity often stored as SYMBOL.NS.json
        p = self.path("market", "bars", f"{alias}.json")
        if p.exists():
            return p
        if not str(alias).endswith(".NS"):
            p_ns = self.path("market", "bars", f"{alias}.NS.json")
            if p_ns.exists():
                return p_ns
        return p

    def intraday_path(self, sym: str, day: str) -> Path:
        return self.path("market", "bars_intraday", sym, f"{day}.json")


# ---------------------------------------------------------------------------
# Build cells
# ---------------------------------------------------------------------------


def is_cash_equity(symbol: str, lab: str | None = None) -> bool:
    sym = str(symbol or "")
    if sym.endswith(".NS") or sym.endswith(".BO"):
        return True
    if lab in {"equity_intraday_learner", "india_equity_learner"}:
        # lab default; still allow F&O symbols if ever mixed
        if re.search(r"\d{2}[A-Z]{3}\d{2}(CE|PE)$", sym):
            return False
        return True
    return False


def is_fno_contract(symbol: str) -> bool:
    return bool(re.search(r"\d{2}[A-Z]{3}\d{2}(CE|PE)$", str(symbol or "")))


def infer_underlying(symbol: str) -> str | None:
    if is_cash_equity(symbol):
        return str(symbol).removesuffix(".NS").removesuffix(".BO")
    m = re.match(r"^([A-Z]+)(\d{2}[A-Z]{3}\d{2})", symbol)
    if m:
        return m.group(1)
    # equity option often SYMBOL + date
    m2 = re.match(r"^([A-Z&]+)(\d{2}[A-Z]{3})", symbol)
    return m2.group(1) if m2 else None


def build_cells(sources: TraceSources, trade_id: str) -> tuple[list[Cell], dict[str, Any]]:
    cells: list[Cell] = []
    meta: dict[str, Any] = {"trade_id_seed": trade_id, "db_mode": sources.db_mode}

    seed = sources.load_trade(trade_id)
    if not seed:
        cells.append(
            Cell(
                "IDENTITY",
                0,
                "seed_trade",
                None,
                "MISSING",
                "PERSISTENCE",
                note=f"trade_id {trade_id} not found (db_mode={sources.db_mode})",
            )
        )
        return cells, meta

    day = ist_day(seed.get("created_at"))
    symbol = str(seed.get("symbol"))
    portfolio_id = str(seed.get("portfolio_id"))
    meta.update({"ist_day": day, "symbol": symbol, "portfolio_id": portfolio_id, "lab": sources.lab})

    day_trades = sources.load_same_symbol_day(portfolio_id, symbol, day or "")
    pair = pair_round_trip(seed, day_trades or [seed])
    entry, exit_t = pair.get("entry"), pair.get("exit")

    # IDENTITY
    cells.append(
        Cell(
            "IDENTITY",
            1,
            "round_trip_pair",
            {
                "entry_id": (entry or {}).get("id"),
                "exit_id": (exit_t or {}).get("id"),
                "candidates": pair.get("candidates"),
            },
            "OK" if pair["status"] == "OK" else pair["status"],
            None
            if pair["status"] == "OK"
            else ("PERSISTENCE" if pair["status"] == "MISSING" else None),
            note=pair.get("note") or "",
            sources=[source_db("sim.trades", str(seed.get("id")), seed.get("created_at"))],
        )
    )
    if pair["status"] == "AMBIGUOUS":
        cells[-1].status = "AMBIGUOUS"
        cells[-1].note = pair["note"]
    if entry and exit_t and pair["status"] == "OK":
        cells.append(
            Cell(
                "IDENTITY",
                1,
                "quantities",
                {
                    "entry_qty": entry.get("quantity"),
                    "exit_qty": exit_t.get("quantity"),
                    "entry_side": entry.get("side"),
                    "exit_side": exit_t.get("side"),
                },
                "OK",
                sources=[
                    source_db("sim.trades", str(entry["id"]), entry.get("created_at")),
                    source_db("sim.trades", str(exit_t["id"]), exit_t.get("created_at")),
                ],
            )
        )

    if not entry or not exit_t or pair["status"] != "OK":
        # Downstream blocked
        for dim, step, name in [
            ("ACCOUNTING", 7, "realized_pnl"),
            ("DECISION_LINKAGE", 3, "entry_decision"),
            ("DECISION_EVIDENCE", 1, "entry_snapshot"),
            ("ATTRIBUTION", 8, "attribution_state"),
            ("LEARNING", 9, "hypothesis"),
        ]:
            cells.append(
                Cell(
                    dim,
                    step,
                    name,
                    None,
                    "MISSING",
                    "PERSISTENCE",
                    blocked_by=["IDENTITY.round_trip_pair"],
                    note="blocked by identity pairing",
                )
            )
        return cells, meta

    entry_src = source_db("sim.trades", str(entry["id"]), entry.get("created_at"))
    exit_src = source_db("sim.trades", str(exit_t["id"]), exit_t.get("created_at"))
    cash_eq = is_cash_equity(symbol, sources.lab)
    fno = is_fno_contract(symbol)
    meta["instrument_class"] = "cash_equity" if cash_eq else ("fno" if fno else "unknown")

    # ACCOUNTING
    acct = recompute_round_trip(entry, exit_t)
    cells.append(
        Cell(
            "ACCOUNTING",
            7,
            "stored_realized_pnl",
            acct["stored_realized"],
            "OK" if abs(acct["stored_realized"] - acct["check_realized_exit_fee_net"]) < 1e-6 else "CONFLICT",
            None
            if abs(acct["stored_realized"] - acct["check_realized_exit_fee_net"]) < 1e-6
            else "COMPUTATION",
            sources=[exit_src],
            note="stored sell realized_pnl is exit-fee net (F18); check = (exit-entry)*qty - exit_fee",
        )
    )
    cells.append(
        Cell(
            "ACCOUNTING",
            7,
            "fees",
            {"entry_fee": entry.get("fee"), "exit_fee": exit_t.get("fee"), "profile": (exit_t.get("fees") or {}).get("profile_id")},
            "OK",
            sources=[entry_src, exit_src],
            note="zero-fee paper_demo expected for this lab profile",
        )
    )
    cells.append(
        Cell(
            "ACCOUNTING",
            7,
            "return_on_cost_roc_v1",
            round(acct["roc_v1_pct"], 4) if acct["roc_v1_pct"] is not None else None,
            "CALCULATED",
            sources=[source_calc("roc.v1 = round_trip_net / (qty*entry_price + entry_fee) * 100")],
            note=f"entry_cost={acct['entry_cost']}; round_trip_net={acct['round_trip_net']}",
        )
    )

    # prediction / stored return conflict (F&O lab prediction file; equity may omit)
    pred_path = sources.prediction_path(symbol)
    pred = None
    pred_src = None
    if pred_path.exists():
        pred = _json_load(pred_path)
        pred_src = source_file(pred_path, "", pred.get("entry_time"))
        stored_ret = (pred.get("prediction_error") or {}).get("realized_return_pct")
        if stored_ret is not None and acct["roc_v1_pct"] is not None:
            # also check exit-notional formula
            exit_notional = float(exit_t["price"]) * float(exit_t["quantity"])
            bad_denom = acct["stored_realized"] / exit_notional * 100.0 if exit_notional else None
            conflict = abs(float(stored_ret) - float(acct["roc_v1_pct"])) > 0.05
            cells.append(
                Cell(
                    "ACCOUNTING",
                    7,
                    "stored_realized_return_pct",
                    stored_ret,
                    "CONFLICT" if conflict else "OK",
                    "COMPUTATION" if conflict else None,
                    sources=[pred_src],
                    note=(
                        f"stored={stored_ret}; roc.v1={acct['roc_v1_pct']:.4f}; "
                        f"exit-notional formula would give {bad_denom:.4f}"
                        if bad_denom is not None
                        else f"stored={stored_ret}; roc.v1={acct['roc_v1_pct']:.4f}"
                    ),
                )
            )
    elif cash_eq:
        cells.append(
            Cell(
                "ACCOUNTING",
                7,
                "stored_realized_return_pct",
                None,
                "NOT_APPLICABLE",
                note="cash equity has no F&O lab_v1 prediction return field; roc.v1 calculated above",
            )
        )

    # DECISION_LINKAGE — entry
    entry_decision_id = entry.get("decision_id")
    entry_decision = sources.load_decision(str(entry_decision_id) if entry_decision_id else None)
    if entry_decision is None:
        cells.append(
            Cell(
                "DECISION_LINKAGE",
                3,
                "entry_decision",
                {"decision_id": entry_decision_id},
                "MISSING",
                "LINKAGE",
                sources=[entry_src],
                note="fill.decision_id missing or decision row not found",
            )
        )
    else:
        action = entry_decision.get("action") or {}
        payload = action.get("payload") if isinstance(action, dict) else {}
        action_kind = (payload or {}).get("kind") or action.get("key") or entry_decision.get("action_kind")
        why = entry_decision.get("why")
        conflict = str(action_kind).lower() == "hold"
        cells.append(
            Cell(
                "DECISION_LINKAGE",
                3,
                "entry_decision",
                {
                    "decision_id": entry_decision.get("id"),
                    "action": action_kind,
                    "symbol": (payload or {}).get("symbol"),
                    "why": why,
                    "created_at_ist": ist_iso(entry_decision.get("created_at")),
                },
                "CONFLICT" if conflict else "OK",
                "LINKAGE" if conflict else None,
                sources=[
                    entry_src,
                    source_db("decision.decisions", str(entry_decision["id"]), entry_decision.get("created_at")),
                ],
                note=(
                    "fill is BUY but linked engine decision is HOLD"
                    if conflict
                    else "entry decision linked"
                ),
            )
        )

    # prediction as historical overlay evidence (F&O); N/A for cash equity control-rule path
    if pred_path.exists() and pred is not None and pred_src is not None:
        pred_trade = str(pred.get("trade_id") or "")
        status = "OK"
        gap = None
        note = "prediction file is historical overlay evidence only (A5); not a decision record"
        if pred_trade and pred_trade != str(entry["id"]):
            status = "CONFLICT"
            gap = "PERSISTENCE"
            note = "prediction trade_id != entry fill — overwritten by later entry?"
        cells.append(
            Cell(
                "DECISION_LINKAGE",
                2,
                "entry_prediction",
                {
                    "trade_id": pred.get("trade_id"),
                    "thesis": pred.get("thesis"),
                    "reason": pred.get("reason"),
                    "expected_return": pred.get("expected_return"),
                    "predicted_probability": pred.get("predicted_probability"),
                    "horizon": pred.get("prediction_horizon"),
                    "er_model": pred.get("er_model"),
                    "prediction_type": "rule_output",
                    "calibration_status": "uncalibrated_default",
                    "entry_time_ist": ist_iso(pred.get("entry_time")),
                    "experiment_family": pred.get("experiment_family"),
                },
                status,
                gap,
                sources=[pred_src],
                note=note,
            )
        )
        # A16
        cells.append(
            Cell(
                "DECISION_LINKAGE",
                2,
                "experiment_family_definition",
                pred.get("experiment_family"),
                "OK",
                sources=[pred_src, source_calc("atlas.investment.fno_lab_v1.experiment_family_id")],
                note=(
                    "Identifier only — generated by experiment_family_id(underlying); "
                    "not a defined experiment protocol (A16)"
                ),
            )
        )
    elif cash_eq:
        cells.append(
            Cell(
                "DECISION_LINKAGE",
                2,
                "entry_prediction",
                None,
                "NOT_APPLICABLE",
                note="cash equity control-rule trade has no F&O lab_v1 prediction file; engine decision why is the record",
            )
        )
    else:
        cells.append(
            Cell(
                "DECISION_LINKAGE",
                2,
                "entry_prediction",
                None,
                "MISSING",
                "PERSISTENCE",
                note=f"no prediction file at {pred_path}",
            )
        )

    # packets
    by_day = sources.by_day_path(day or "")
    packets = _jsonl_load(by_day) if by_day.exists() else []
    hit = [
        p
        for p in packets
        if str(p.get("decision_id")) == str(entry_decision_id)
        or str(p.get("engine_decision_id")) == str(entry_decision_id)
        or str(p.get("fill_trade_id")) == str(entry["id"])
    ]
    cells.append(
        Cell(
            "DECISION_LINKAGE",
            3,
            "entry_decision_packet",
            {"matches": len(hit)},
            "MISSING" if not hit else "OK",
            "LINKAGE" if not hit else None,
            sources=[source_file(by_day)] if by_day.exists() else [],
            note="no by_day packet for engine decision / fill" if not hit else "packet found",
        )
    )

    # exit decision
    exit_decision_id = exit_t.get("decision_id")
    exit_decision = sources.load_decision(str(exit_decision_id) if exit_decision_id else None)
    if not exit_decision_id:
        cells.append(
            Cell(
                "DECISION_LINKAGE",
                6,
                "exit_decision",
                {"decision_id": None},
                "MISSING",
                "LINKAGE",
                sources=[exit_src],
                note="sell path passed decision_id=None",
            )
        )
    elif exit_decision is None:
        cells.append(
            Cell(
                "DECISION_LINKAGE",
                6,
                "exit_decision",
                {"decision_id": exit_decision_id},
                "MISSING",
                "LINKAGE",
                sources=[exit_src],
                note="exit decision_id set but decision row not found",
            )
        )
    else:
        ex_action = exit_decision.get("action") or {}
        ex_payload = ex_action.get("payload") if isinstance(ex_action, dict) else {}
        cells.append(
            Cell(
                "DECISION_LINKAGE",
                6,
                "exit_decision",
                {
                    "decision_id": exit_decision.get("id"),
                    "action": (ex_payload or {}).get("kind") or ex_action.get("key"),
                    "why": exit_decision.get("why"),
                    "created_at_ist": ist_iso(exit_decision.get("created_at")),
                },
                "OK",
                sources=[
                    exit_src,
                    source_db(
                        "decision.decisions",
                        str(exit_decision["id"]),
                        exit_decision.get("created_at"),
                    ),
                ],
                note="exit decision linked",
            )
        )

    # exit trigger from integrity (F&O) or from exit decision why (cash equity)
    integ_path = sources.integrity_path(day or "")
    trigger = None
    if cash_eq:
        cells.append(
            Cell(
                "DECISION_LINKAGE",
                6,
                "exit_trigger",
                {"source": "exit_decision.why", "why": (exit_decision or {}).get("why")},
                "OK" if exit_decision else "MISSING",
                "LINKAGE" if not exit_decision else None,
                sources=[
                    source_db(
                        "decision.decisions",
                        str(exit_decision["id"]),
                        exit_decision.get("created_at"),
                    )
                ]
                if exit_decision
                else [exit_src],
                note="cash equity: exit trigger is the engine sell decision why (no F&O integrity flatten)",
            )
        )
    elif integ_path.exists():
        integ = _json_load(integ_path)
        for o in integ.get("flatten_outcomes") or []:
            if str(o.get("trade_id")) == str(exit_t["id"]):
                trigger = o
                break
        cells.append(
            Cell(
                "DECISION_LINKAGE",
                6,
                "exit_trigger",
                {
                    "reason": (trigger or {}).get("reason"),
                    "exit_policy": integ.get("exit_policy"),
                    "status": (trigger or {}).get("status"),
                    "expiry": ((trigger or {}).get("attribution") or {}).get("expiry"),
                    "strike": ((trigger or {}).get("attribution") or {}).get("strike"),
                }
                if trigger
                else None,
                "OK" if trigger else "MISSING",
                "LINKAGE" if not trigger else None,
                sources=[source_file(integ_path, "flatten_outcomes", integ.get("recorded_at"))],
                note="trigger recoverable from integrity; expiry/strike null on record"
                if trigger
                else "no flatten_outcomes row for exit trade_id",
            )
        )
    else:
        cells.append(
            Cell(
                "DECISION_LINKAGE",
                6,
                "exit_trigger",
                None,
                "MISSING",
                "PERSISTENCE",
                note="integrity file absent",
            )
        )

    # DECISION_EVIDENCE — pack snapshot (F&O only)
    underlying = (pred or {}).get("underlying") or infer_underlying(symbol) or "UNKNOWN"
    if cash_eq:
        cells.append(
            Cell(
                "DECISION_EVIDENCE",
                1,
                "entry_pack_snapshot",
                None,
                "NOT_APPLICABLE",
                note="F&O pack snapshot not applicable to cash equity; entry evidence is engine decision + marks",
            )
        )
    else:
        pack_path = sources.pack_path(str(underlying), day or "")
        if pack_path.exists():
            pack = _json_load(pack_path)
            pack_as_of = to_ist(pack.get("as_of"))
            entry_ts = to_ist(entry.get("created_at"))
            age = (pack_as_of - entry_ts).total_seconds() if pack_as_of and entry_ts else None
            stale = age is not None and age > FRESH_LTP_MAX_AGE_S
            cells.append(
                Cell(
                    "DECISION_EVIDENCE",
                    1,
                    "entry_pack_snapshot",
                    {
                        "pack_as_of_ist": ist_iso(pack.get("as_of")),
                        "spot": (pack.get("spot") or {}).get("value"),
                        "atm": (pack.get("atm") or {}).get("strike"),
                        "age_s_after_entry": age,
                    },
                    "MISSING" if stale else "OK",
                    "PERSISTENCE" if stale else None,
                    sources=[source_file(pack_path, "as_of", pack.get("as_of"))],
                    note="pack overwritten after entry — stored copy is later version, not decision-time evidence"
                    if stale
                    else "pack as_of within freshness window of entry",
                )
            )
        else:
            cells.append(
                Cell(
                    "DECISION_EVIDENCE",
                    1,
                    "entry_pack_snapshot",
                    None,
                    "MISSING",
                    "PERSISTENCE",
                    note=f"pack missing: {pack_path}",
                )
            )

    cells.append(
        Cell(
            "DECISION_EVIDENCE",
            4,
            "order_intent",
            None,
            "MISSING",
            "PERSISTENCE",
            note="no order-intent record on paper path (A6); fill price/qty are execution facts, not intent records",
        )
    )

    # underlier / own-symbol session context + entry-to-exit path
    if cash_eq:
        aliases = (symbol, str(symbol).removesuffix(".NS"), f"{underlying}.NS")
    else:
        aliases = UNDERLIER_ALIASES.get(str(underlying), (f"{underlying}.NS",))
    bar_doc = None
    bar_path_used = None
    alias_used = None
    tried = []
    for alias in aliases:
        p = sources.bars_path(alias)
        tried.append(str(p))
        if p.exists():
            bar_doc = _json_load(p)
            bar_path_used = p
            alias_used = alias
            break
    if bar_doc and bar_path_used:
        bars = {b["date"]: b for b in bar_doc.get("bars") or [] if isinstance(b, dict) and "date" in b}
        day_bar = bars.get(day or "")
        # prior trading day: previous key before day
        dates = sorted(bars)
        prior = None
        if day in dates:
            idx = dates.index(day)
            prior = bars.get(dates[idx - 1]) if idx > 0 else None
        if day_bar and prior and prior.get("close") and day_bar.get("open") and day_bar.get("close"):
            moves = session_context_moves(float(prior["close"]), float(day_bar["open"]), float(day_bar["close"]))
            cells.append(
                Cell(
                    "DECISION_EVIDENCE",
                    5,
                    "underlier_session_context",
                    {
                        "alias": alias_used,
                        "prior_close": prior["close"],
                        "day_open": day_bar["open"],
                        "day_close": day_bar["close"],
                        **{k: round(v, 4) for k, v in moves.items()},
                    },
                    "OK",
                    sources=[source_file(bar_path_used, f"bars[{day}]", day)],
                    note="session context only — not entry-to-exit underlier path (A8)",
                )
            )
            cells.append(
                Cell(
                    "DECISION_EVIDENCE",
                    5,
                    "underlier_open_to_close_pct",
                    round(moves["open_to_close_pct"], 4),
                    "CALCULATED",
                    sources=[source_calc("(close-open)/open*100")],
                )
            )
            cells.append(
                Cell(
                    "DECISION_EVIDENCE",
                    5,
                    "underlier_close_to_close_pct",
                    round(moves["close_to_close_pct"], 4),
                    "CALCULATED",
                    sources=[source_calc("(close-prior_close)/prior_close*100")],
                )
            )
        else:
            cells.append(
                Cell(
                    "DECISION_EVIDENCE",
                    5,
                    "underlier_session_context",
                    {"alias": alias_used, "day_bar": day_bar, "prior": prior},
                    "MISSING",
                    "PERSISTENCE",
                    sources=[source_file(bar_path_used)],
                    note="bar file found but day/prior close incomplete",
                )
            )
    else:
        cells.append(
            Cell(
                "DECISION_EVIDENCE",
                5,
                "underlier_session_context",
                {"tried": tried},
                "MISSING",
                "PERSISTENCE",
                note="no underlier daily bar for aliases",
            )
        )

    # entry-to-exit underlier / asset path
    intra = sources.intraday_path(str(alias_used or symbol or underlying), day or "")
    if cash_eq:
        ep = float(entry["price"])
        xp = float(exit_t["price"])
        move_pct = (xp - ep) / ep * 100.0 if ep else None
        cells.append(
            Cell(
                "DECISION_EVIDENCE",
                5,
                "underlier_entry_to_exit_path",
                {
                    "entry_price": ep,
                    "exit_price": xp,
                    "move_pct": round(move_pct, 4) if move_pct is not None else None,
                    "entry_at_ist": ist_iso(entry.get("created_at")),
                    "exit_at_ist": ist_iso(exit_t.get("created_at")),
                },
                "OK",
                sources=[entry_src, exit_src],
                note="cash equity: fill prices are the asset path endpoints (not a separate underlier)",
            )
        )
        cells.append(
            Cell(
                "DECISION_EVIDENCE",
                5,
                "iv_greeks",
                None,
                "NOT_APPLICABLE",
                note="IV and option Greeks not applicable to cash-equity trades",
            )
        )
    else:
        cells.append(
            Cell(
                "DECISION_EVIDENCE",
                5,
                "underlier_entry_to_exit_path",
                None,
                "MISSING",
                "PERSISTENCE",
                sources=[source_file(intra)] if intra.exists() else [],
                note="requires entry/exit-time underlier prices or intraday bars; daily bar is not sufficient",
            )
        )
        cells.append(
            Cell(
                "DECISION_EVIDENCE",
                5,
                "iv_greeks",
                None,
                "MISSING",
                "PERSISTENCE",
                note="IV and Greeks never captured for this round trip",
            )
        )

    # ATTRIBUTION
    exit_day = ist_day(exit_t.get("created_at"))
    learning_days = []
    for d in (day, exit_day):
        if d and d not in learning_days:
            learning_days.append(d)
    experience = None
    story = None
    learning_path = sources.learning_path(day or "")
    for d in learning_days:
        lp = sources.learning_path(d)
        if not lp.exists():
            continue
        learning_path = lp
        for row in _jsonl_load(lp):
            if row.get("symbol") != symbol and row.get("symbol") != str(symbol).removesuffix(".NS"):
                # allow TRENT vs TRENT.NS
                if str(row.get("symbol") or "").removesuffix(".NS") != str(symbol).removesuffix(".NS"):
                    continue
            if row.get("kind") == "EXPERIENCE":
                experience = row
            elif row.get("kind") == "LEARNING_STORY":
                story = row
        if experience:
            break
    false_claim = False
    helped: list[str] = []
    narrative = None
    if experience:
        factors = ((experience.get("attribution") or {}).get("causal_factors") or {})
        helped = list(factors.get("helped") or [])
        for f in factors.get("factors") or []:
            if f.get("factor") == "underlying_move" and "no durable underlier session bar" in str(
                f.get("note") or ""
            ):
                false_claim = True
        # LLM narrative from integrity if present
        if trigger:
            narrative = (
                ((trigger.get("attribution") or {}).get("cognitive") or {})
                .get("advice", {})
                .get("payload", {})
                .get("summary")
            )
        attr = classify_attribution(
            has_entry_exit_underlier_path=bool(cash_eq),
            has_iv=False,
            helped_factors=helped,
            narrative=narrative,
            false_missing_session_bar_claim=false_claim,
        )
        cells.append(
            Cell(
                "ATTRIBUTION",
                8,
                "stored_attribution_status",
                (experience.get("attribution") or {}).get("status"),
                "OK",
                sources=[source_file(learning_path, "EXPERIENCE.attribution")],
                note="stored label reported verbatim",
            )
        )
        cells.append(
            Cell(
                "ATTRIBUTION",
                8,
                "trace_attribution_state",
                attr["state"],
                "OK" if attr["state"] != "NOT_EVALUABLE" else "MISSING",
                "ATTRIBUTION",
                sources=[source_file(learning_path)],
                note="; ".join(attr["notes"]) or "classified per §4.1",
            )
        )
        if false_claim:
            cells.append(
                Cell(
                    "ATTRIBUTION",
                    8,
                    "attribution_underlier_input_lookup",
                    "claimed_missing_session_bar",
                    "CONFLICT",
                    "LINKAGE",
                    note="session context bar exists via alias; attribution lookup failed to find it",
                    sources=[source_file(learning_path), source_file(bar_path_used)] if bar_path_used else [],
                )
            )
    else:
        cells.append(
            Cell(
                "ATTRIBUTION",
                8,
                "trace_attribution_state",
                None,
                "MISSING",
                "ATTRIBUTION",
                note="no EXPERIENCE row",
            )
        )

    # LEARNING
    lessons = (experience or {}).get("lessons") if experience else None
    hypothesis = None
    if isinstance(lessons, dict):
        hypothesis = lessons.get("strategy")
    cells.append(
        Cell(
            "LEARNING",
            9,
            "hypothesis",
            hypothesis,
            "MISSING",
            "LEARNING",
            sources=[source_file(learning_path)] if learning_path.exists() else [],
            note="observation-style lesson text is not a named hypothesis",
        )
    )
    cells.append(
        Cell(
            "LEARNING",
            10,
            "validation_test",
            None,
            "MISSING",
            "LEARNING",
            note="no validation test defined",
        )
    )
    if story is not None:
        cells.append(
            Cell(
                "LEARNING",
                9,
                "learning_story",
                {
                    "story_id": story.get("story_id"),
                    "cause": story.get("cause"),
                    "belief_update": story.get("belief_update"),
                },
                "OK",
                sources=[source_file(learning_path, "LEARNING_STORY")],
            )
        )

    # FEL features linkage
    fel_path = sources.fel_path()
    fel_row = None
    if fel_path.exists():
        for row in _jsonl_load(fel_path):
            blob = json.dumps(row, default=str)
            if str(entry["id"]) in blob or symbol in blob:
                fel_row = row
                break
    if fel_row is not None:
        feats = fel_row.get("features") or fel_row.get("rsi") or fel_row
        # detect null rsi/sma if present
        null_feats = {
            k: fel_row.get(k)
            for k in ("rsi", "sma_fast", "sma_slow")
            if k in fel_row and fel_row.get(k) is None
        }
        cells.append(
            Cell(
                "LEARNING",
                9,
                "fel_features",
                {"null_fields": null_feats, "keys_sample": list(fel_row.keys())[:20]},
                "MISSING" if null_feats else "OK",
                "LINKAGE" if null_feats else None,
                sources=[source_file(fel_path)],
                note="sma_margin exists on prediction/experience but FEL rsi/sma fields null"
                if null_feats
                else "FEL features present",
            )
        )

    # thesis tracker instrument class
    thesis_path = sources.thesis_path(symbol)
    if thesis_path.exists():
        thesis = _json_load(thesis_path)
        wrong_class = fno and str(thesis.get("symbol") or "").endswith(".NS")
        cells.append(
            Cell(
                "LEARNING",
                9,
                "thesis_tracker_instrument_class",
                {
                    "symbol": thesis.get("symbol"),
                    "horizon": thesis.get("horizon"),
                    "hypothesis": thesis.get("hypothesis"),
                    "decision": thesis.get("decision"),
                },
                "CONFLICT" if wrong_class else "OK",
                "LINKAGE" if wrong_class else None,
                sources=[source_file(thesis_path)],
                note=(
                    "option contract tracked as equity (.NS / long_term / idle) — A13"
                    if wrong_class
                    else "thesis tracker present for cash-equity symbol"
                ),
            )
        )

    # KPI presence (accounting cross-check context)
    kpi_path = sources.kpi_path(day or "")
    if kpi_path.exists():
        kpi = _json_load(kpi_path)
        cells.append(
            Cell(
                "ACCOUNTING",
                7,
                "lab_day_pnl_kpi",
                (kpi.get("kpis") or kpi).get("day_pnl"),
                "OK",
                sources=[source_file(kpi_path, "kpis.day_pnl")],
                note="lab-level day_pnl (all symbols); not this trade alone",
            )
        )

    meta["entry"] = entry
    meta["exit"] = exit_t
    meta["accounting"] = acct
    meta["underlying"] = underlying
    return cells, meta


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def render_md(
    cells: Sequence[Cell],
    meta: Mapping[str, Any],
    *,
    generated_at: str,
    git_sha: str,
) -> str:
    first = first_blocking_dependency(cells)
    lines: list[str] = []
    lines.append(f"# Trade trace — {meta.get('symbol')} / {meta.get('ist_day')}")
    lines.append("")
    lines.append(f"- **script:** `{SCRIPT_VERSION}`")
    lines.append(f"- **git_sha:** `{git_sha}`")
    lines.append(f"- **generated_at_ist:** `{generated_at}`")
    lines.append(f"- **lab:** `{meta.get('lab')}`")
    lines.append(f"- **portfolio_id:** `{meta.get('portfolio_id')}`")
    lines.append(f"- **seed_trade_id:** `{meta.get('trade_id_seed')}`")
    lines.append(f"- **db_mode:** `{meta.get('db_mode')}`")
    entry = meta.get("entry") or {}
    exit_t = meta.get("exit") or {}
    if entry:
        lines.append(
            f"- **entry:** `{entry.get('id')}` BUY {entry.get('quantity')} @ {entry.get('price')} "
            f"({ist_iso(entry.get('created_at'))})"
        )
    if exit_t:
        lines.append(
            f"- **exit:** `{exit_t.get('id')}` SELL {exit_t.get('quantity')} @ {exit_t.get('price')} "
            f"({ist_iso(exit_t.get('created_at'))})"
        )
    lines.append("")
    lines.append("## First blocking dependency")
    lines.append("")
    if first["dimension"]:
        lines.append(
            f"**{first['dimension']}** — fields: {', '.join(first['fields'])}; "
            f"gap classes: {', '.join(first['gap_classes']) or '—'}"
        )
    else:
        lines.append("None — no critical cells.")
    lines.append("")
    lines.append("## Cells")
    lines.append("")
    lines.append("| Dim | Step | Field | Status | Gap | Value | Note |")
    lines.append("|-----|------|-------|--------|-----|-------|------|")
    for c in cells:
        val = json.dumps(c.value, default=str)
        if len(val) > 120:
            val = val[:117] + "..."
        val = val.replace("|", "\\|")
        note = (c.note or "").replace("|", "\\|")
        lines.append(
            f"| {c.dimension} | {c.step} | {c.field} | {c.status} | {c.gap_class or ''} | `{val}` | {note} |"
        )
    lines.append("")
    lines.append("## Gap summary")
    lines.append("")
    from collections import Counter

    sc = Counter((c.status, c.gap_class, c.dimension) for c in cells if c.status != "OK")
    lines.append("| Status | Gap | Dimension | Count |")
    lines.append("|--------|-----|-----------|------:|")
    for (st, gap, dim), n in sorted(sc.items()):
        lines.append(f"| {st} | {gap or ''} | {dim} | {n} |")
    lines.append("")
    lines.append("## Raw sources")
    lines.append("")
    seen: set[str] = set()
    for c in cells:
        for s in c.sources:
            key = f"{s.kind}:{s.ref}:{s.sha256}"
            if key in seen:
                continue
            seen.add(key)
            lines.append(
                f"- `{s.kind}` `{s.ref}` sha256=`{s.sha256 or '—'}` "
                f"mtime_ist=`{s.mtime_ist or '—'}` original_ts=`{s.original_ts or '—'}`"
            )
    lines.append("")
    return "\n".join(lines)


def render_json(
    cells: Sequence[Cell],
    meta: Mapping[str, Any],
    *,
    generated_at: str,
    git_sha: str,
) -> dict[str, Any]:
    def cell_dict(c: Cell) -> dict[str, Any]:
        d = asdict(c)
        return d

    return {
        "script_version": SCRIPT_VERSION,
        "git_sha": git_sha,
        "generated_at_ist": generated_at,
        "meta": {k: v for k, v in meta.items() if k not in {"entry", "exit", "accounting"} or True},
        "first_blocking_dependency": first_blocking_dependency(cells),
        "cells": [cell_dict(c) for c in cells],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _ensure_out_outside_data(out: Path, data_dir: Path) -> None:
    try:
        out.resolve().relative_to(data_dir.resolve())
    except ValueError:
        return
    raise SystemExit(f"refusing to write output inside data-dir: {out}")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="OI-DELI0 read-only trade tracer")
    ap.add_argument("--trade-id", required=True)
    ap.add_argument("--data-dir", default="/data/atlas_data")
    ap.add_argument("--db-dump-dir", default=None, help="Optional read-only JSON dump of sim.trades / decisions")
    ap.add_argument("--lab", default="india_fno_learner")
    ap.add_argument("--out-md", default=None)
    ap.add_argument("--out-json", default=None)
    ap.add_argument("--include-logs", action="store_true")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(list(argv) if argv is not None else None)

    data_dir = Path(args.data_dir)
    dump = Path(args.db_dump_dir) if args.db_dump_dir else None
    sources = TraceSources(data_dir, lab=args.lab, db_dump_dir=dump, include_logs=args.include_logs)
    try:
        cells, meta = build_cells(sources, args.trade_id)
    finally:
        sources.close()

    if meta.get("entry") is None and any(c.field == "seed_trade" and c.status == "MISSING" for c in cells):
        print(f"unknown trade id: {args.trade_id} (db_mode={sources.db_mode})", file=sys.stderr)
        return 2

    generated_at = datetime.now(IST).isoformat()
    git_sha = _git_sha(Path(__file__).resolve().parents[1])
    md = render_md(cells, meta, generated_at=generated_at, git_sha=git_sha)
    payload = render_json(cells, meta, generated_at=generated_at, git_sha=git_sha)
    # strip bulky entry/exit from meta copy in JSON for cleanliness — keep accounting
    if isinstance(payload.get("meta"), dict):
        # convert datetimes in entry/exit
        for key in ("entry", "exit"):
            if key in payload["meta"] and isinstance(payload["meta"][key], dict):
                payload["meta"][key] = {
                    k: (v.isoformat() if isinstance(v, datetime) else v)
                    for k, v in payload["meta"][key].items()
                }

    symbol = meta.get("symbol") or "UNKNOWN"
    day = meta.get("ist_day") or "unknown"
    entry_id8 = str((meta.get("entry") or {}).get("id") or args.trade_id)[:8]
    default_stem = f"{day}_{symbol}_{entry_id8}"

    if args.out_md:
        out_md = Path(args.out_md)
        _ensure_out_outside_data(out_md, data_dir)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(md, encoding="utf-8")
    else:
        print(md)

    if args.out_json:
        out_json = Path(args.out_json)
        _ensure_out_outside_data(out_json, data_dir)
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    elif args.out_md:
        # if only md requested, still ok; if neither, md already printed
        pass

    if args.strict and any(c.critical() for c in cells):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
