"""Investment ranking (IL.3) — Universe → score → ranked watchlist with WHY.

Deterministic, no LLM. Every ranked row exposes signed explanation lines so the
operator can answer "why this stock?" Cold start never invents confidence.
"""

from __future__ import annotations

from typing import Any

PHASE_LEARNING = "learning"
PHASE_ACTIVE = "active"

CONF_VERY_LOW = "very_low"
CONF_LOW = "low"
CONF_MEDIUM = "medium"
CONF_HIGH = "high"

DEFAULT_WEIGHTS: dict[str, float] = {
    "momentum": 0.35,
    "liquidity": 0.25,
    "quality": 0.15,
    "policy": 0.15,
    "experience": 0.10,
}

_LEARNING_LINE = {
    "sign": "·",
    "text": "Learning — insufficient market history yet",
    "component": "cold_start",
}


def rank_universe(
    members: list[dict[str, Any]],
    *,
    bars_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    quality_by_symbol: dict[str, dict[str, Any]] | None = None,
    policy_delta_by_symbol: dict[str, float] | None = None,
    experience_bias_by_symbol: dict[str, float] | None = None,
    max_watchlist: int = 15,
    weights: dict[str, float] | None = None,
    lookback_short: int = 5,
    lookback_long: int = 20,
    min_bars: int = 5,
    cold_start_coverage: float = 0.25,
) -> list[dict[str, Any]]:
    """Score membership → top ``max_watchlist`` with WHY ± lines.

    Cold start (IL-Q10): when fewer than ``cold_start_coverage`` of members have
    enough bars, scores stay neutral, order follows membership, and every row is
    labeled ``phase=learning`` / ``confidence=very_low``.
    """
    rows = [dict(m) for m in (members or [])]
    if not rows:
        return []

    bars_map = bars_by_symbol or {}
    quality_map = quality_by_symbol or {}
    policy_map = policy_delta_by_symbol or {}
    exp_map = experience_bias_by_symbol or {}
    w = _normalize_weights(weights or DEFAULT_WEIGHTS)
    max_n = max(1, int(max_watchlist))
    short_n = max(2, int(lookback_short))
    long_n = max(short_n, int(lookback_long))
    need = max(2, int(min_bars))
    coverage_floor = min(1.0, max(0.0, float(cold_start_coverage)))

    covered = 0
    mom_raw: dict[str, float | None] = {}
    liq_raw: dict[str, float | None] = {}
    for i, row in enumerate(rows):
        sym = str(row.get("symbol") or "").strip()
        if not sym:
            continue
        bars = list(bars_map.get(sym) or [])
        if len(bars) >= need:
            covered += 1
        mom_raw[sym] = _momentum_return(bars, short_n=short_n, long_n=long_n)
        liq_raw[sym] = _avg_volume(bars, long_n)

    coverage = covered / max(1, len(rows))
    cold = coverage < coverage_floor

    mom_n = _normalize_optional(mom_raw)
    liq_n = _normalize_optional(liq_raw)

    scored: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        sym = str(row.get("symbol") or "").strip()
        if not sym:
            continue
        bars = list(bars_map.get(sym) or [])
        has_bars = len(bars) >= need

        components: dict[str, float] = {}
        explanations: list[dict[str, str]] = []

        # Momentum
        m = mom_n.get(sym, 0.5)
        components["momentum"] = m
        if not has_bars or mom_raw.get(sym) is None:
            explanations.append(
                {"sign": "·", "text": "Momentum — insufficient bars", "component": "momentum"}
            )
        elif m >= 0.65:
            explanations.append(
                {"sign": "+", "text": "Strong momentum", "component": "momentum"}
            )
        elif m <= 0.35:
            explanations.append(
                {"sign": "−", "text": "Weak momentum", "component": "momentum"}
            )
        else:
            explanations.append(
                {"sign": "·", "text": "Neutral momentum", "component": "momentum"}
            )

        # Liquidity
        lq = liq_n.get(sym, 0.5)
        components["liquidity"] = lq
        if not has_bars or liq_raw.get(sym) is None:
            explanations.append(
                {
                    "sign": "·",
                    "text": "Liquidity — insufficient volume history",
                    "component": "liquidity",
                }
            )
        elif lq >= 0.65:
            explanations.append(
                {"sign": "+", "text": "High liquidity", "component": "liquidity"}
            )
        elif lq <= 0.35:
            explanations.append(
                {"sign": "−", "text": "Thin liquidity", "component": "liquidity"}
            )

        # Quality (optional — omit from ± list when absent)
        q_row = quality_map.get(sym)
        if isinstance(q_row, dict) and q_row:
            q = _quality_score(q_row)
            components["quality"] = q
            if q >= 0.65:
                text = "Positive quality proxy"
                if q_row.get("screener_source") or q_row.get("screener_score") is not None:
                    text = "Positive quality / screener proxy"
                explanations.append(
                    {
                        "sign": "+",
                        "text": text,
                        "component": "quality",
                    }
                )
            elif q <= 0.35:
                text = "Weak quality proxy"
                if q_row.get("screener_source") or q_row.get("screener_score") is not None:
                    text = "Weak quality / screener proxy"
                explanations.append(
                    {
                        "sign": "−",
                        "text": text,
                        "component": "quality",
                    }
                )
        else:
            components["quality"] = 0.5  # neutral; weight still applied stably

        # Policy soft nudge
        p_delta = float(policy_map.get(sym) or 0.0)
        p = _clamp01(0.5 + p_delta)
        components["policy"] = p
        if p_delta >= 0.02:
            explanations.append(
                {"sign": "+", "text": "Policy prefer / trust", "component": "policy"}
            )
        elif p_delta <= -0.02:
            explanations.append(
                {"sign": "−", "text": "Policy avoid / caution", "component": "policy"}
            )

        # Experience / mentor bias
        e_bias = float(exp_map.get(sym) or 0.0)
        e = _clamp01(0.5 + 0.5 * e_bias)
        components["experience"] = e
        if e_bias <= -0.05:
            explanations.append(
                {
                    "sign": "−",
                    "text": "Slight mentor caution",
                    "component": "experience",
                }
            )
        elif e_bias >= 0.05:
            explanations.append(
                {
                    "sign": "+",
                    "text": "Experience support",
                    "component": "experience",
                }
            )

        if cold:
            explanations.insert(0, dict(_LEARNING_LINE))
            score = 0.5  # neutral; membership order breaks ties
            phase = PHASE_LEARNING
            confidence = CONF_VERY_LOW
        else:
            score = sum(w[k] * components.get(k, 0.5) for k in w)
            phase = PHASE_ACTIVE
            confidence = _confidence_for(has_bars=has_bars, coverage=coverage)

        scored.append(
            {
                "symbol": sym,
                "name": str(row.get("name") or ""),
                "sector": str(row.get("sector") or ""),
                "nse_symbol": str(row.get("nse_symbol") or ""),
                "exchange": str(row.get("exchange") or "NSE"),
                "asset_class": str(row.get("asset_class") or "cash_equity"),
                "score": round(float(score), 4),
                "components": {k: round(float(v), 4) for k, v in components.items()},
                "explanations": explanations,
                "reason": _reason_from(explanations),
                "confidence": confidence,
                "phase": phase,
                "_member_idx": i,
                "_has_bars": has_bars,
            }
        )

    # Sort: score desc, then membership order (stable cold-start / ties).
    scored.sort(key=lambda r: (-float(r["score"]), int(r["_member_idx"])))
    out: list[dict[str, Any]] = []
    for rank, row in enumerate(scored[:max_n], start=1):
        row["rank"] = rank
        row.pop("_member_idx", None)
        row.pop("_has_bars", None)
        out.append(row)
    return out


def summarize_phase(ranked: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate phase/confidence for journal / snapshot extra."""
    if not ranked:
        return {"phase": PHASE_LEARNING, "confidence": CONF_VERY_LOW, "count": 0}
    phases = {str(r.get("phase") or "") for r in ranked}
    confs = [str(r.get("confidence") or CONF_VERY_LOW) for r in ranked]
    phase = PHASE_LEARNING if PHASE_LEARNING in phases else PHASE_ACTIVE
    # Worst (most honest) confidence wins for the snapshot label.
    order = (CONF_VERY_LOW, CONF_LOW, CONF_MEDIUM, CONF_HIGH)
    conf = CONF_VERY_LOW
    for c in order:
        if c in confs:
            conf = c
            break
    return {"phase": phase, "confidence": conf, "count": len(ranked)}


def _normalize_weights(raw: dict[str, float]) -> dict[str, float]:
    base = dict(DEFAULT_WEIGHTS)
    for k, v in (raw or {}).items():
        if k in base:
            try:
                base[k] = max(0.0, float(v))
            except (TypeError, ValueError):
                pass
    total = sum(base.values()) or 1.0
    return {k: v / total for k, v in base.items()}


def _momentum_return(
    bars: list[dict[str, Any]],
    *,
    short_n: int,
    long_n: int,
) -> float | None:
    short = _period_return(bars, short_n)
    long = _period_return(bars, long_n)
    if short is None and long is None:
        return None
    if short is None:
        return long
    if long is None:
        return short
    return 0.6 * short + 0.4 * long


def _period_return(bars: list[dict[str, Any]], n: int) -> float | None:
    if len(bars) < n + 1:
        return None
    try:
        window = bars[-(n + 1) :]
        first = float(window[0]["close"])
        last = float(window[-1]["close"])
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    if first == 0:
        return None
    return (last - first) / first


def _avg_volume(bars: list[dict[str, Any]], n: int) -> float | None:
    if not bars:
        return None
    window = bars[-max(1, n) :]
    vols: list[float] = []
    for b in window:
        try:
            vols.append(float(b.get("volume") or 0.0))
        except (TypeError, ValueError):
            continue
    if not vols:
        return None
    return sum(vols) / len(vols)


def _quality_score(q: dict[str, Any]) -> float:
    """Map optional fundamentals / screener fields into [0, 1]. Missing → neutral 0.5."""
    parts: list[float] = []
    if "roe" in q:
        try:
            # ROE 0%→0.3, 15%→0.7, 30%+→1.0 (soft). Accept fraction (0.15) or %.
            roe = float(q["roe"])
            roe_pct = roe * 100.0 if abs(roe) <= 1.5 else roe
            parts.append(_clamp01(0.3 + roe_pct / 50.0))
        except (TypeError, ValueError):
            pass
    if "debt_to_equity" in q or "debt_equity" in q:
        try:
            de = float(q.get("debt_to_equity", q.get("debt_equity")))
            # Lower leverage better: 0→1.0, 1→0.5, 2+→~0.2
            parts.append(_clamp01(1.0 - de / 2.0))
        except (TypeError, ValueError):
            pass
    # IL.8 — screener-class fields (operator snapshot or computed)
    if "pe" in q and q["pe"] is not None:
        try:
            pe = float(q["pe"])
            # Prefer moderate PE: ~15→0.8, 5→0.5, 40→0.2
            if pe > 0:
                parts.append(_clamp01(1.0 - abs(pe - 15.0) / 40.0))
        except (TypeError, ValueError):
            pass
    if "promoter_holding" in q and q["promoter_holding"] is not None:
        try:
            ph = float(q["promoter_holding"])
            ph_pct = ph * 100.0 if abs(ph) <= 1.5 else ph
            parts.append(_clamp01(ph_pct / 100.0))
        except (TypeError, ValueError):
            pass
    if "screener_score" in q and q["screener_score"] is not None:
        try:
            parts.append(_clamp01(float(q["screener_score"])))
        except (TypeError, ValueError):
            pass
    if not parts:
        return 0.5
    return sum(parts) / len(parts)


def _normalize_optional(raw: dict[str, float | None]) -> dict[str, float]:
    """Min-max present values to [0, 1]; missing → 0.5."""
    present = {k: v for k, v in raw.items() if v is not None}
    if not present:
        return {k: 0.5 for k in raw}
    vals = list(present.values())
    lo, hi = min(vals), max(vals)
    out: dict[str, float] = {}
    for k, v in raw.items():
        if v is None:
            out[k] = 0.5
        elif hi == lo:
            out[k] = 0.5
        else:
            out[k] = (float(v) - lo) / (hi - lo)
    return out


def _confidence_for(*, has_bars: bool, coverage: float) -> str:
    if not has_bars:
        return CONF_LOW
    if coverage >= 0.8:
        return CONF_HIGH
    if coverage >= 0.5:
        return CONF_MEDIUM
    return CONF_LOW


def _reason_from(explanations: list[dict[str, str]], *, limit: int = 4) -> str:
    """Short human join of the most salient ± / learning lines."""
    preferred = [e for e in explanations if e.get("sign") in {"+", "−"}]
    if not preferred:
        preferred = [e for e in explanations if e.get("component") == "cold_start"]
    if not preferred:
        preferred = list(explanations)
    bits: list[str] = []
    for e in preferred[:limit]:
        sign = e.get("sign") or "·"
        text = (e.get("text") or "").strip()
        if text:
            bits.append(f"{sign} {text}")
    return "; ".join(bits) if bits else "· Neutral"


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))
