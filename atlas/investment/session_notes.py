"""Durable per-IST-day session notes for evening reports / outage honesty.

Paper trading writes aggregated hold / feed reasons; investor reports reads them
so the evening email can explain zero fills honestly.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

_log = logging.getLogger("atlas.investment.session_notes")

STORE_REL = Path("market") / "session_notes"


def notes_dir(data_dir: str | Path) -> Path:
    return Path(data_dir) / STORE_REL


def notes_path(data_dir: str | Path, *, portfolio_key: str, ist_date: str) -> Path:
    safe_key = (portfolio_key or "default").replace("/", "_").strip() or "default"
    return notes_dir(data_dir) / safe_key / f"{ist_date}.json"


def load_day_notes(
    data_dir: str | Path | None,
    *,
    portfolio_key: str,
    ist_date: str,
) -> dict[str, Any]:
    if not data_dir:
        return {}
    path = notes_path(data_dir, portfolio_key=portfolio_key, ist_date=ist_date)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:  # noqa: BLE001
        _log.debug("session notes read failed: %s", path, exc_info=True)
        return {}


def merge_day_notes(
    data_dir: str | Path | None,
    *,
    portfolio_key: str,
    ist_date: str,
    reason_counts: dict[str, int],
    samples: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge reason counters into today's note file (idempotent across ticks)."""
    if not data_dir:
        return {}
    path = notes_path(data_dir, portfolio_key=portfolio_key, ist_date=ist_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_day_notes(data_dir, portfolio_key=portfolio_key, ist_date=ist_date)
    counts = dict(existing.get("reason_counts") or {})
    for k, v in (reason_counts or {}).items():
        key = str(k)
        try:
            counts[key] = int(counts.get(key, 0)) + int(v)
        except (TypeError, ValueError):
            continue
    incoming: list[str] = []
    seen_in: set[str] = set()
    for s in samples or []:
        text = str(s).strip()
        if not text or text in seen_in:
            continue
        seen_in.add(text)
        incoming.append(text)
    # Recency: this tick's lines go last. An early `len>=40` break used to freeze
    # the first 40 uniques of the day (so post-bounce switch_review never appeared).
    prior = [str(s) for s in (existing.get("samples") or []) if str(s) not in seen_in]
    sample_list = (prior + incoming)[-40:]
    doc: dict[str, Any] = {
        "ist_date": ist_date,
        "portfolio_key": portfolio_key or "default",
        "reason_counts": counts,
        "samples": sample_list,
    }
    if extra:
        for k, v in extra.items():
            if v is not None:
                doc[k] = v
    # Preserve prior extras not overwritten
    for k, v in existing.items():
        if k not in doc and k not in {"reason_counts", "samples"}:
            doc[k] = v
    try:
        path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        _log.debug("session notes write failed: %s", path, exc_info=True)
    return doc


def classify_action(action: str) -> str | None:
    """Map a journal action string to a coarse evening-report bucket."""
    a = (action or "").lower()
    if ": buy " in a or a.endswith(" buy") or ":buy" in a.replace(" ", ""):
        return None  # fills aren't "why no fill"
    if ": sell " in a or ":sell" in a.replace(" ", ""):
        return None
    if "switch_blocked" in a or "switch_review" in a:
        return "switch_blocked"
    if "plc_a_hold" in a:
        return "plc_a_hold"
    if "portfolio_hold" in a or "concentration_name" in a:
        return "portfolio_hold"
    if "fno_no_cash_alts" in a:
        return "fno_no_cash_alts"
    if "intraday_yahoo_budget" in a:
        return "intraday_yahoo_budget"
    if "session_closed" in a:
        return "session_closed"
    if "empty_live_feed" in a:
        return "empty_live_feed"
    if "empty_feed" in a:
        return "empty_feed"
    if "feed_error" in a:
        return "feed_error"
    if "research_hold" in a:
        return "research_hold"
    if "policy_block" in a:
        return "policy_block"
    if "pack_block" in a:
        return "pack_block"
    if "mark_only" in a:
        return "mark_only"
    if "yahoo_cooldown" in a or "rate gate" in a or "429" in a:
        return "yahoo_cooldown"
    if "gap (" in a or ": gap" in a:
        return "capability_gap"
    if "next_alt" in a:
        return "next_alternatives"
    if "cannot size" in a or "size_block" in a or "min lot" in a:
        return "size_block"
    if "insufficient margin" in a or ": margin (" in a:
        return "margin"
    if ": hold @" in a:
        # Paper trading journals engine holds as "SYM: hold @ price (why…)".
        if "cannot size" in a or "min lot" in a:
            return "size_block"
        return "strategy_hold"
    if "feed_exhausted" in a:
        return "feed_exhausted"
    return "other_idle"


REASON_LABELS = {
    "session_closed": "Market session closed (outside NSE cash hours / weekend)",
    "empty_live_feed": "Live price feed empty (often internet / Yahoo outage)",
    "empty_feed": "Bar feed empty",
    "feed_error": "Live feed errors while fetching bars",
    "research_hold": "Research gate held buys (MVR / thesis / MoS incomplete)",
    "plc_a_hold": "PLC.A buy gate held (fundamentals / thesis trigger incomplete)",
    "portfolio_hold": "Portfolio gate held (concentration / cash buffer / name cap)",
    "switch_blocked": "Hold-vs-challenger switch blocked (missing E[R] or costs)",
    "policy_block": "Policy engine blocked the order",
    "pack_block": "Instrument pack validation blocked the order",
    "mark_only": "Same bar already decided — mark-to-market only (no new decision)",
    "yahoo_cooldown": "Yahoo rate gate / cooldown (deferred marks; not a strategy hold)",
    "capability_gap": "Capability gap (missing feed / pack capability)",
    "strategy_hold": "Strategy decided hold (no buy/sell signal)",
    "size_block": "Buy signal existed but portfolio cash/budget cannot size 1 whole share",
    "margin": "Index-proxy lot blocked by margin (not cash-equity concentration)",
    "next_alternatives": "Primary names idle — tried next ranked alternatives",
    "fno_no_cash_alts": "F&O lab skipped cash-equity alternatives (operator contracts only)",
    "intraday_yahoo_budget": "Intraday lab capped at ≤3 names (Yahoo 5m budget; no extra alts)",
    "feed_exhausted": "Replay feed exhausted",
    "other_idle": "Other idle / skip reasons",
}

# Clock / feed noise — report after decision reasons so evening is not 2000× session_closed.
_CLOCK_REASON_KEYS = frozenset(
    {
        "session_closed",
        "mark_only",
        "next_alternatives",
        "feed_exhausted",
        "yahoo_cooldown",
    }
)


def samples_for_notes(actions: list[str] | None, *, cap: int = 24) -> list[str]:
    """Keep this-tick decision lines; do not let session_closed occupy the whole window."""
    cap = max(8, int(cap))
    raw = [str(a).strip() for a in (actions or []) if str(a).strip()]
    if len(raw) <= cap:
        return raw
    decisions: list[str] = []
    clock: list[str] = []
    for a in raw:
        bucket = classify_action(a)
        if bucket in _CLOCK_REASON_KEYS or bucket is None:
            clock.append(a)
        else:
            decisions.append(a)
    keep_d = decisions[-max(8, cap // 2) :]
    keep_c = clock[-(cap - len(keep_d)) :]
    return keep_c + keep_d


def format_session_tick_histogram(notes: dict[str, Any] | None) -> list[str]:
    """Below-the-fold tick reason histogram — mark_only / session_closed last."""
    notes = notes or {}
    counts = notes.get("reason_counts") or {}
    if not counts:
        return []
    ordered = sorted(
        ((k, int(v)) for k, v in counts.items() if int(v) > 0),
        key=lambda kv: (-kv[1], kv[0]),
    )
    decision = [(k, n) for k, n in ordered if k not in _CLOCK_REASON_KEYS]
    clock = [(k, n) for k, n in ordered if k in _CLOCK_REASON_KEYS]
    lines = [
        "",
        "── Session tick histogram (below the fold) ──",
    ]
    total = sum(int(v) for v in counts.values())
    lines.append(f"  total journal buckets: {total}")
    for key, n in (decision + clock)[:12]:
        label = REASON_LABELS.get(key, key)
        prefix = "clock: " if key in _CLOCK_REASON_KEYS else ""
        lines.append(f"  {prefix}{label} ×{n}")
    mark_n = int(counts.get("mark_only") or 0)
    if mark_n:
        lines.append(
            f"  mark_only={mark_n} — same-bar re-mark only; not new decisions"
        )
    return lines


def format_no_fill_reasons(notes: dict[str, Any] | None) -> list[str]:
    """Human lines explaining why the evening report shows zero fills."""
    notes = notes or {}
    counts = notes.get("reason_counts") or {}
    if not counts:
        return [
            "No simulated fills in this snapshot — and no session reason counters "
            "were recorded yet (worker may have been down or outside market hours)."
        ]
    ordered = sorted(
        ((k, int(v)) for k, v in counts.items() if int(v) > 0),
        key=lambda kv: (-kv[1], kv[0]),
    )
    # Prefer *decision* buckets; clock noise (session_closed / mark_only) last.
    decision = [(k, n) for k, n in ordered if k not in _CLOCK_REASON_KEYS]
    clock = [(k, n) for k, n in ordered if k in _CLOCK_REASON_KEYS]
    lines: list[str] = []
    for key, n in (decision + clock)[:8]:
        label = REASON_LABELS.get(key, key)
        prefix = "" if key not in _CLOCK_REASON_KEYS else "clock: "
        lines.append(f"{prefix}{label} ×{n}")
    gap = notes.get("feed_gap_days")
    if gap is not None:
        try:
            gd = float(gap)
            if gd >= 1:
                lines.append(
                    f"Price feed resumed after ~{gd:.0f} calendar day(s) gap — "
                    "existing holdings were kept; marks refresh on live bars."
                )
        except (TypeError, ValueError):
            pass
    return lines
