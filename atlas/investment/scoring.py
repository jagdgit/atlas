"""IIP.6 — Investment Scoring (multi-axis + dual confidence).

``research_confidence`` = how well we understand the company/theme.
``investment_confidence`` = how attractive owning it is *now*.
Overall score ≠ buy. High research + low investment → watch path.
"""

from __future__ import annotations

from typing import Any

VERSION = "iip.6.scoring"

AXES: tuple[str, ...] = (
    "business",
    "growth",
    "financial_health",
    "management",
    "valuation",
    "technical",
    "macro_theme",
    "risk",
)

# Horizon → axis weight tilts (normalized later)
HORIZON_WEIGHTS: dict[str, dict[str, float]] = {
    "swing": {
        "business": 0.08,
        "growth": 0.10,
        "financial_health": 0.10,
        "management": 0.08,
        "valuation": 0.18,
        "technical": 0.28,
        "macro_theme": 0.08,
        "risk": 0.10,
    },
    "position": {
        "business": 0.12,
        "growth": 0.14,
        "financial_health": 0.14,
        "management": 0.10,
        "valuation": 0.22,
        "technical": 0.12,
        "macro_theme": 0.08,
        "risk": 0.08,
    },
    "long_term": {
        "business": 0.16,
        "growth": 0.14,
        "financial_health": 0.14,
        "management": 0.14,
        "valuation": 0.18,
        "technical": 0.06,
        "macro_theme": 0.10,
        "risk": 0.08,
    },
    "structural": {
        "business": 0.14,
        "growth": 0.12,
        "financial_health": 0.12,
        "management": 0.12,
        "valuation": 0.14,
        "technical": 0.04,
        "macro_theme": 0.20,
        "risk": 0.12,
    },
    "speculative": {
        "business": 0.08,
        "growth": 0.18,
        "financial_health": 0.08,
        "management": 0.08,
        "valuation": 0.12,
        "technical": 0.22,
        "macro_theme": 0.12,
        "risk": 0.12,
    },
}

CONF_LABELS = ("very_low", "low", "medium", "high")

# Score band for UI beside research gate
SCORE_BANDS: tuple[tuple[float, str], ...] = (
    (0.75, "strong"),
    (0.55, "moderate"),
    (0.35, "weak"),
    (0.0, "insufficient"),
)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _conf_rank(label: str | None) -> float:
    s = str(label or "very_low").strip().lower()
    if s in CONF_LABELS:
        return CONF_LABELS.index(s) / (len(CONF_LABELS) - 1)
    return 0.0


def _label_from_01(x: float) -> str:
    if x >= 0.75:
        return "high"
    if x >= 0.55:
        return "medium"
    if x >= 0.30:
        return "low"
    return "very_low"


def score_band(overall: float) -> str:
    for floor, name in SCORE_BANDS:
        if overall >= floor:
            return name
    return "insufficient"


def _section_score(sections: dict[str, Any], name: str) -> float:
    sec = sections.get(name) if isinstance(sections.get(name), dict) else {}
    if not sec:
        return 0.25
    conf = _conf_rank(sec.get("confidence"))
    status = str(sec.get("status") or "")
    gaps = len(sec.get("gaps") or [])
    fields = sec.get("fields") if isinstance(sec.get("fields"), dict) else {}
    evidence = fields.get("evidence") if isinstance(fields.get("evidence"), list) else []
    base = 0.35 + 0.45 * conf
    if status in {"present", "stale"}:
        base += 0.08
    if evidence:
        base += min(0.12, 0.03 * len(evidence))
    base -= min(0.25, 0.04 * gaps)
    return _clamp01(base)


def _axis_scores(
    *,
    sections: dict[str, Any],
    valuation: dict[str, Any] | None,
    mkg: dict[str, Any] | None,
    technical: dict[str, Any] | None,
    quality: dict[str, Any] | None,
) -> dict[str, float]:
    val = valuation if isinstance(valuation, dict) else {}
    axes: dict[str, float] = {
        "business": _section_score(sections, "business"),
        "growth": _section_score(sections, "growth"),
        "financial_health": _section_score(sections, "financial_health"),
        "management": _section_score(sections, "management"),
        "risk": _section_score(sections, "risks"),
    }

    # Valuation / MoS
    mos = val.get("margin_of_safety_pct")
    method = str(val.get("method") or "")
    vscore = _section_score(sections, "valuation")
    if mos is not None:
        try:
            m = float(mos)
            # Map MoS −20…+40 → 0…1 around 15% as attractive
            vscore = _clamp01(0.45 + m / 50.0)
        except (TypeError, ValueError):
            pass
    elif method in {"insufficient", ""}:
        vscore = min(vscore, 0.35)
    axes["valuation"] = _clamp01(vscore)

    # Technical (optional; neutral if missing)
    tech = technical if isinstance(technical, dict) else {}
    if tech.get("score") is not None:
        axes["technical"] = _clamp01(float(tech["score"]))
    elif tech.get("rsi") is not None:
        try:
            rsi = float(tech["rsi"])
            # Prefer mid-range RSI for position; extremes score lower
            axes["technical"] = _clamp01(1.0 - abs(rsi - 50.0) / 50.0)
        except (TypeError, ValueError):
            axes["technical"] = 0.5
    else:
        axes["technical"] = 0.5

    # Macro / theme from MKG
    mkg = mkg if isinstance(mkg, dict) else {}
    why = mkg.get("why_own") if isinstance(mkg.get("why_own"), dict) else mkg
    themes = why.get("themes") if isinstance(why, dict) else None
    policies = why.get("policies") if isinstance(why, dict) else None
    t_n = len(themes or [])
    p_n = len(policies or [])
    if t_n or p_n:
        axes["macro_theme"] = _clamp01(0.4 + 0.15 * min(3, t_n) + 0.12 * min(3, p_n))
    elif why.get("status") == "unknown_relation":
        axes["macro_theme"] = 0.25
    else:
        axes["macro_theme"] = 0.4

    # Quality seed nudges (never invent)
    q = quality if isinstance(quality, dict) else {}
    if q.get("roe") is not None:
        try:
            roe = float(q["roe"])
            if roe > 1.5:
                roe = roe / 100.0
            axes["financial_health"] = _clamp01(
                0.6 * axes["financial_health"] + 0.4 * _clamp01(roe / 0.25)
            )
        except (TypeError, ValueError):
            pass
    if q.get("debt_to_equity") is not None:
        try:
            de = float(q["debt_to_equity"])
            # Low debt better
            debt_score = _clamp01(1.0 - de / 2.0)
            axes["risk"] = _clamp01(0.5 * axes["risk"] + 0.5 * debt_score)
            axes["financial_health"] = _clamp01(
                0.7 * axes["financial_health"] + 0.3 * debt_score
            )
        except (TypeError, ValueError):
            pass

    return axes


def _normalize_weights(horizon: str) -> dict[str, float]:
    key = (horizon or "long_term").strip().lower().replace("-", "_")
    if key not in HORIZON_WEIGHTS:
        key = "long_term"
    w = dict(HORIZON_WEIGHTS[key])
    s = sum(w.values()) or 1.0
    return {k: v / s for k, v in w.items()}


def compute_investment_score(
    *,
    symbol: str = "",
    sections: dict[str, Any] | None = None,
    valuation: dict[str, Any] | None = None,
    coverage: float = 0.0,
    research_confidence: str | None = None,
    research_quality: dict[str, Any] | str | None = None,
    mvr_satisfied: bool = False,
    mkg: dict[str, Any] | None = None,
    technical: dict[str, Any] | None = None,
    quality: dict[str, Any] | None = None,
    horizon: str = "long_term",
    critical_flags: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compute multi-axis score + dual confidence + recommended path."""
    sections = sections if isinstance(sections, dict) else {}
    axes = _axis_scores(
        sections=sections,
        valuation=valuation,
        mkg=mkg,
        technical=technical,
        quality=quality,
    )
    weights = _normalize_weights(horizon)
    overall = sum(axes[a] * weights.get(a, 0.0) for a in AXES)
    overall = _clamp01(overall)
    band = score_band(overall)

    # Research confidence: understanding (coverage, quality, MVR, section depth)
    rq = research_quality
    if isinstance(rq, dict):
        rq_level = str(rq.get("level") or "basic")
    else:
        rq_level = str(rq or "basic")
    rq_map = {"basic": 0.2, "developing": 0.45, "substantive": 0.7, "deep": 0.9}
    cov01 = _clamp01(float(coverage or 0) / 100.0)
    conf01 = _conf_rank(research_confidence)
    research_01 = _clamp01(
        0.35 * cov01
        + 0.25 * conf01
        + 0.25 * rq_map.get(rq_level, 0.2)
        + (0.15 if mvr_satisfied else 0.0)
    )
    # Presence of MKG edges mildly lifts research understanding
    why = (mkg or {}).get("why_own") if isinstance(mkg, dict) else None
    if isinstance(why, dict) and why.get("status") == "ok":
        research_01 = _clamp01(research_01 + 0.05)

    # Investment confidence: attractiveness now (valuation + risk + overall − flags)
    mos = None
    if isinstance(valuation, dict) and valuation.get("margin_of_safety_pct") is not None:
        try:
            mos = float(valuation["margin_of_safety_pct"])
        except (TypeError, ValueError):
            mos = None
    inv_01 = _clamp01(
        0.40 * axes["valuation"]
        + 0.20 * axes["financial_health"]
        + 0.15 * (1.0 - abs(axes["risk"] - 0.7))  # prefer controlled risk
        + 0.15 * overall
        + 0.10 * axes["macro_theme"]
    )
    if mos is not None:
        inv_01 = _clamp01(0.55 * inv_01 + 0.45 * _clamp01(0.4 + mos / 40.0))
    flags = [f for f in (critical_flags or []) if isinstance(f, dict)]
    if any(f.get("kind") == "thesis_invalidating" for f in flags):
        inv_01 = min(inv_01, 0.15)
        research_01 = max(research_01, 0.4)  # we may understand the problem well

    research_label = _label_from_01(research_01)
    investment_label = _label_from_01(inv_01)

    # Path: high research + low investment → watch (Done-when)
    path = "watch"
    path_reason = "default_watch"
    if any(f.get("kind") == "thesis_invalidating" for f in flags):
        path = "avoid"
        path_reason = "critical_flag"
    elif research_01 >= 0.55 and inv_01 < 0.40:
        path = "watch"
        path_reason = "high_research_low_investment"
    elif research_01 < 0.35:
        path = "watch"
        path_reason = "research_insufficient"
    elif inv_01 >= 0.55 and research_01 >= 0.45 and band in {"moderate", "strong"}:
        path = "buy_eligible"
        path_reason = "dual_confidence_pass"
    elif inv_01 < 0.25:
        path = "avoid"
        path_reason = "investment_confidence_very_low"
    else:
        path = "watch"
        path_reason = "score_band_" + band

    return {
        "version": VERSION,
        "symbol": symbol,
        "horizon": (horizon or "long_term").strip().lower(),
        "axes": {k: round(v, 3) for k, v in axes.items()},
        "weights": {k: round(v, 3) for k, v in weights.items()},
        "overall": round(overall, 3),
        "score_band": band,
        "research_confidence": research_label,
        "research_confidence_score": round(research_01, 3),
        "investment_confidence": investment_label,
        "investment_confidence_score": round(inv_01, 3),
        "path": path,
        "path_reason": path_reason,
        "note": (
            "Overall score ≠ buy. Research confidence = understanding; "
            "investment confidence = attractiveness now. "
            "High research + low investment → watch."
        ),
    }


def score_from_awareness(
    awareness: dict[str, Any],
    *,
    horizon: str | None = None,
    technical: dict[str, Any] | None = None,
    quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convenience: build score from IRA awareness dict."""
    aw = awareness if isinstance(awareness, dict) else {}
    # Prefer dossier sections if embedded; else rebuild lightly from section_confidence
    sections = aw.get("sections") if isinstance(aw.get("sections"), dict) else {}
    if not sections and isinstance(aw.get("section_confidence"), dict):
        sections = {
            k: {"confidence": v, "status": "present", "gaps": [], "fields": {}}
            for k, v in aw["section_confidence"].items()
        }
    hz = horizon
    if not hz and isinstance(aw.get("timing"), dict):
        hz = (aw.get("timing") or {}).get("horizon")
    hz = hz or "long_term"
    flags_sum = aw.get("critical_flags") if isinstance(aw.get("critical_flags"), dict) else {}
    active = flags_sum.get("active") if isinstance(flags_sum, dict) else []
    return compute_investment_score(
        symbol=str(aw.get("symbol") or ""),
        sections=sections,
        valuation=aw.get("valuation") if isinstance(aw.get("valuation"), dict) else {},
        coverage=float(aw.get("coverage") or 0),
        research_confidence=str(aw.get("confidence") or "very_low"),
        research_quality=aw.get("research_quality"),
        mvr_satisfied=bool(aw.get("mvr_satisfied")),
        mkg=aw.get("mkg") if isinstance(aw.get("mkg"), dict) else {},
        technical=technical or (aw.get("timing") if isinstance(aw.get("timing"), dict) else {}),
        quality=quality,
        horizon=str(hz),
        critical_flags=list(active or []),
    )


def attach_score_to_ranked_row(
    row: dict[str, Any],
    score: dict[str, Any],
) -> dict[str, Any]:
    """Persist score fields onto a ranking / daily-plan candidate."""
    out = dict(row)
    out["investment_score"] = score.get("overall")
    out["score_band"] = score.get("score_band")
    out["research_confidence"] = score.get("research_confidence")
    out["investment_confidence"] = score.get("investment_confidence")
    out["score_path"] = score.get("path")
    out["score_horizon"] = score.get("horizon")
    out["score"] = {
        "overall": score.get("overall"),
        "band": score.get("score_band"),
        "research_confidence": score.get("research_confidence"),
        "investment_confidence": score.get("investment_confidence"),
        "path": score.get("path"),
        "path_reason": score.get("path_reason"),
        "axes": score.get("axes"),
    }
    return out
