"""Opportunity Discovery Engine v1 (IIP.2) — screen + theme hypothesis funnel.

Produces durable ``market/discovery/{ist_date}.json`` with interesting candidates
(why + horizon). Does not buy.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from atlas.investment.themes import expand_theme_candidates, list_themes

_log = logging.getLogger("atlas.investment.discovery")
_IST = ZoneInfo("Asia/Kolkata")

VERSION = "iip.2.discovery"
STORE_REL = Path("market") / "discovery"
HORIZONS = (
    "trading",
    "swing",
    "position",
    "long_term",
    "structural",
    "speculative",
)


def discovery_dir(data_dir: str | Path) -> Path:
    return Path(data_dir) / STORE_REL


def discovery_path(data_dir: str | Path, ist_date: str | None = None) -> Path:
    day = ist_date or datetime.now(_IST).strftime("%Y-%m-%d")
    return discovery_dir(data_dir) / f"{day}.json"


def _closes(bars: list[dict[str, Any]]) -> list[float]:
    out: list[float] = []
    for b in bars or []:
        try:
            out.append(float(b["close"]))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _volumes(bars: list[dict[str, Any]]) -> list[float]:
    out: list[float] = []
    for b in bars or []:
        try:
            out.append(float(b.get("volume") or 0.0))
        except (TypeError, ValueError):
            out.append(0.0)
    return out


def screen_symbol(
    symbol: str,
    bars: list[dict[str, Any]] | None,
    *,
    quality: dict[str, Any] | None = None,
    policy_delta: float = 0.0,
) -> list[dict[str, Any]]:
    """Return zero or more screen-hit reasons for one symbol."""
    hits: list[dict[str, Any]] = []
    closes = _closes(list(bars or []))
    vols = _volumes(list(bars or []))
    if len(closes) < 5:
        return hits

    last = closes[-1]
    # 52w-ish proximity using available window
    hi = max(closes)
    lo = min(closes)
    if hi > 0 and last >= 0.98 * hi:
        hits.append(
            {
                "symbol": symbol,
                "mode": "screen",
                "horizon": "swing",
                "why": f"Near window high ({last:.2f} vs max {hi:.2f})",
                "filter": "near_52w_high",
                "score": 0.55 + min(0.2, (last / hi - 0.98) * 10),
            }
        )
    if lo > 0 and last <= 1.02 * lo:
        hits.append(
            {
                "symbol": symbol,
                "mode": "screen",
                "horizon": "speculative",
                "why": f"Near window low ({last:.2f} vs min {lo:.2f})",
                "filter": "near_52w_low",
                "score": 0.35,
            }
        )

    # MA breakout: close > SMA20 and prior close <= SMA20
    if len(closes) >= 21:
        sma = sum(closes[-20:]) / 20.0
        prev_sma = sum(closes[-21:-1]) / 20.0
        if last > sma and closes[-2] <= prev_sma:
            hits.append(
                {
                    "symbol": symbol,
                    "mode": "screen",
                    "horizon": "swing",
                    "why": f"MA20 breakout (close {last:.2f} > SMA {sma:.2f})",
                    "filter": "ma20_breakout",
                    "score": 0.6,
                }
            )

    # Volume spike vs 20-day avg
    if len(vols) >= 21 and vols[-1] > 0:
        avg = sum(vols[-21:-1]) / 20.0
        if avg > 0 and vols[-1] >= 2.0 * avg:
            hits.append(
                {
                    "symbol": symbol,
                    "mode": "screen",
                    "horizon": "trading",
                    "why": f"Volume spike ({vols[-1]:.0f} ≥ 2× avg {avg:.0f})",
                    "filter": "volume_spike",
                    "score": 0.5 + min(0.25, (vols[-1] / avg - 2) * 0.05),
                }
            )

    # Momentum 5d
    if len(closes) >= 6 and closes[-6] > 0:
        mom = (last / closes[-6]) - 1.0
        if mom >= 0.05:
            hits.append(
                {
                    "symbol": symbol,
                    "mode": "screen",
                    "horizon": "swing",
                    "why": f"5d momentum {mom * 100:.1f}%",
                    "filter": "momentum_5d",
                    "score": 0.45 + min(0.25, mom),
                }
            )

    q = quality or {}
    try:
        roce = float(q["roce"]) if q.get("roce") is not None else None
    except (TypeError, ValueError):
        roce = None
    try:
        de = float(q["debt_to_equity"]) if q.get("debt_to_equity") is not None else None
    except (TypeError, ValueError):
        de = None
    if roce is not None and roce >= 20:
        hits.append(
            {
                "symbol": symbol,
                "mode": "screen",
                "horizon": "long_term",
                "why": f"ROCE {roce:.1f}% (≥20) from quality/snapshot",
                "filter": "roce_gate",
                "score": 0.5,
            }
        )
    if de is not None and de <= 0.3:
        hits.append(
            {
                "symbol": symbol,
                "mode": "screen",
                "horizon": "long_term",
                "why": f"Low leverage D/E {de:.2f} (≤0.3)",
                "filter": "debt_gate",
                "score": 0.45,
            }
        )

    if policy_delta and float(policy_delta) > 0.05:
        hits.append(
            {
                "symbol": symbol,
                "mode": "screen",
                "horizon": "structural",
                "why": f"Positive policy sector delta ({float(policy_delta):+.2f})",
                "filter": "policy_delta",
                "score": 0.4 + min(0.2, float(policy_delta)),
            }
        )

    for h in hits:
        h["source"] = "discovery_screen"
    return hits


def run_discovery(
    *,
    members: list[dict[str, Any]],
    bars_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    quality_by_symbol: dict[str, dict[str, Any]] | None = None,
    policy_by_symbol: dict[str, float] | None = None,
    themes: list[str] | None = None,
    max_interesting: int = 40,
    max_enqueue_research: int = 10,
    include_themes: bool = True,
) -> dict[str, Any]:
    """Build interesting funnel from screens + theme beneficiaries."""
    bars_by_symbol = bars_by_symbol or {}
    quality_by_symbol = quality_by_symbol or {}
    policy_by_symbol = policy_by_symbol or {}

    screen_hits: list[dict[str, Any]] = []
    for m in members:
        sym = str(m.get("symbol") or "").strip()
        if not sym:
            continue
        hits = screen_symbol(
            sym,
            bars_by_symbol.get(sym),
            quality=quality_by_symbol.get(sym),
            policy_delta=float(policy_by_symbol.get(sym) or 0.0),
        )
        screen_hits.extend(hits)

    # Collapse screens per symbol (best score + combined why)
    by_sym: dict[str, dict[str, Any]] = {}
    for h in screen_hits:
        sym = h["symbol"]
        cur = by_sym.get(sym)
        if cur is None or float(h.get("score") or 0) > float(cur.get("score") or 0):
            by_sym[sym] = {
                **h,
                "reasons": [h.get("why")],
                "filters": [h.get("filter")],
            }
        else:
            cur.setdefault("reasons", []).append(h.get("why"))
            cur.setdefault("filters", []).append(h.get("filter"))
            cur["score"] = max(float(cur.get("score") or 0), float(h.get("score") or 0))

    theme_hits = expand_theme_candidates(themes=themes) if include_themes else []
    # Prefer symbols already in member universe when available
    member_syms = {str(m.get("symbol")) for m in members}
    if member_syms:
        theme_hits = [t for t in theme_hits if t["symbol"] in member_syms] or theme_hits

    interesting: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Mix: take theme candidates first (hypothesis), then screens
    for row in sorted(theme_hits, key=lambda r: r.get("theme_id") or ""):
        sym = row["symbol"]
        if sym in seen:
            # Enrich existing with theme
            for it in interesting:
                if it["symbol"] == sym:
                    it.setdefault("themes", []).append(row.get("theme_id"))
                    it.setdefault("reasons", []).append(row.get("why"))
                    if it.get("mode") == "screen":
                        it["mode"] = "screen+hypothesis"
                    break
            continue
        seen.add(sym)
        interesting.append(
            {
                "symbol": sym,
                "mode": "hypothesis",
                "horizon": row.get("horizon") or "structural",
                "score": 0.55,
                "why": row.get("why"),
                "reasons": [row.get("why")],
                "themes": [row.get("theme_id")],
                "role": row.get("role"),
                "hypothesis": row.get("hypothesis"),
                "source": row.get("source"),
            }
        )
        if len(interesting) >= max_interesting:
            break

    for sym, row in sorted(by_sym.items(), key=lambda kv: -float(kv[1].get("score") or 0)):
        if len(interesting) >= max_interesting:
            break
        if sym in seen:
            for it in interesting:
                if it["symbol"] == sym:
                    it.setdefault("reasons", []).extend(row.get("reasons") or [])
                    it["score"] = max(float(it.get("score") or 0), float(row.get("score") or 0))
                    if it.get("mode") == "hypothesis":
                        it["mode"] = "screen+hypothesis"
                    break
            continue
        seen.add(sym)
        reasons = [r for r in (row.get("reasons") or []) if r]
        interesting.append(
            {
                "symbol": sym,
                "mode": "screen",
                "horizon": row.get("horizon") or "swing",
                "score": float(row.get("score") or 0),
                "why": "; ".join(reasons[:3]),
                "reasons": reasons,
                "filters": row.get("filters") or [],
                "themes": [],
                "source": "discovery_screen",
            }
        )

    # Cap and rank for research enqueue
    interesting = sorted(interesting, key=lambda r: -float(r.get("score") or 0))[
        : max(1, int(max_interesting))
    ]
    research_queue = [
        {
            "symbol": r["symbol"],
            "horizon": r.get("horizon"),
            "why": r.get("why"),
            "mode": r.get("mode"),
        }
        for r in interesting[: max(0, int(max_enqueue_research))]
    ]

    now = datetime.now(_IST)
    return {
        "version": VERSION,
        "ist_date": now.strftime("%Y-%m-%d"),
        "updated_at": now.isoformat(),
        "scanned": len(members),
        "screen_hit_symbols": len(by_sym),
        "theme_candidates": len(theme_hits),
        "themes_used": [t["theme_id"] for t in list_themes()]
        if include_themes and not themes
        else list(themes or []),
        "interesting": interesting,
        "interesting_count": len(interesting),
        "research_queue": research_queue,
        "max_interesting": max_interesting,
        "max_enqueue_research": max_enqueue_research,
        "note": (
            "Discovery only — not buys. Mix of screen filters and theme hypotheses. "
            "Research enqueue is a suggestion for IRA, not auto-deep."
        ),
    }


def save_discovery(data_dir: str | Path | None, doc: dict[str, Any]) -> Path | None:
    if not data_dir or not doc:
        return None
    path = discovery_path(data_dir, ist_date=str(doc.get("ist_date") or ""))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
        return path
    except Exception:  # noqa: BLE001
        _log.debug("discovery save failed", exc_info=True)
        return None


def load_latest_discovery(data_dir: str | Path | None) -> dict[str, Any]:
    if not data_dir:
        return {"interesting": [], "note": "no data_dir"}
    root = discovery_dir(data_dir)
    if not root.is_dir():
        return {"interesting": [], "note": "no discovery runs yet"}
    files = sorted(root.glob("*.json"), reverse=True)
    if not files:
        return {"interesting": [], "note": "no discovery runs yet"}
    try:
        raw = json.loads(files[0].read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw["path"] = str(files[0])
            return raw
    except Exception:  # noqa: BLE001
        _log.debug("discovery load failed", exc_info=True)
    return {"interesting": [], "note": "read_failed"}
