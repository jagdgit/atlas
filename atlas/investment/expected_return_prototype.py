"""LOOP0 L1 — versioned expected-return prototype (not alpha).

Always emits a number plus the input snapshot so a later session can answer
"why was E[R] 4.2% on 17 Aug?" from the packet, not from today's code.

Belief and experience terms are **zero unless already on the row**. L2 consult
fills belief_adj; closed-trade hit-rate fills experience. This module does not
call an LLM and does not invent fundamentals.
"""

from __future__ import annotations

from typing import Any

ER_MODEL = "prototype_v1"
ER_BASIS = "prototype"
VERSION = "loop0.l1.er_prototype_v1"

# Maps weighted signed factors in [-1, 1] into a ±12% envelope (UTS.C scale).
STACK_SCALE = 0.24

WEIGHTS: dict[str, float] = {
    "momentum": 0.30,
    "sector_rs": 0.20,
    "valuation": 0.20,
    "quality": 0.15,
    "belief": 0.075,
    "experience": 0.075,
}

COMPLETENESS_CONF_CAP = 0.6
PROTOTYPE_LOW_CONF = 0.35  # label "low"
BELIEF_BOUND = 0.02
EXPERIENCE_BOUND = 0.02
SECTOR_RS_FULL_PCT = 8.0  # ±8% RS vs benchmark → ±1 factor
MOM_MOVE_FULL = 0.12  # ±12% price move → ±1 factor
QUALITY_ROE_REF = 0.15


def _f(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _components(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("components")
    return raw if isinstance(raw, dict) else {}


def _momentum_factor(row: dict[str, Any]) -> tuple[float | None, str | None]:
    comps = _components(row)
    mom = _f(comps.get("momentum"))
    if mom is not None:
        return _clamp((mom - 0.5) * 2.0, -1.0, 1.0), "components.momentum"
    score = _f(row.get("score"))
    if score is not None:
        return _clamp((score - 0.5) * 2.0, -1.0, 1.0), "score"
    move = _f(row.get("pct_move") if row.get("pct_move") is not None else row.get("ret_20d"))
    if move is not None:
        return _clamp(move / MOM_MOVE_FULL, -1.0, 1.0), "pct_move"
    return None, None


def _sector_rs_factor(row: dict[str, Any]) -> tuple[float | None, str | None]:
    comps = _components(row)
    rs = _f(comps.get("sector_rs"))
    src = "components.sector_rs"
    if rs is None:
        rs = _f(row.get("rs_vs_benchmark_pct"))
        src = "rs_vs_benchmark_pct"
    if rs is None:
        market = row.get("market") if isinstance(row.get("market"), dict) else {}
        rs = _f(market.get("rs_vs_benchmark_pct"))
        src = "market.rs_vs_benchmark_pct"
    if rs is None:
        lanes = row.get("lanes") if isinstance(row.get("lanes"), dict) else {}
        sector = lanes.get("sector") if isinstance(lanes.get("sector"), dict) else {}
        rs = _f(sector.get("rs_vs_benchmark_pct"))
        src = "lanes.sector.rs_vs_benchmark_pct"
    if rs is None:
        return None, None
    # Ranker-style 0..1 vs already-a-percent.
    if 0.0 <= rs <= 1.0 and src.startswith("components."):
        return _clamp((rs - 0.5) * 2.0, -1.0, 1.0), src
    return _clamp(rs / SECTOR_RS_FULL_PCT, -1.0, 1.0), src


def _pe_median(row: dict[str, Any]) -> float | None:
    for key in ("industry_pe_median", "pe_sector_median", "sector_pe", "peer_pe"):
        v = _f(row.get(key))
        if v is not None and v > 0:
            return v
    return None


def _valuation_factor(row: dict[str, Any]) -> tuple[float | None, str | None]:
    comps = _components(row)
    explicit = _f(comps.get("valuation"))
    if explicit is not None:
        return _clamp((explicit - 0.5) * 2.0, -1.0, 1.0), "components.valuation"
    pe = _f(row.get("pe"))
    median = _pe_median(row)
    if pe is None or median is None or pe <= 0 or median <= 0:
        return None, None
    # Cheaper than sector median → positive.
    return _clamp((median - pe) / median, -1.0, 1.0), "pe_vs_industry_median"


def _quality_factor(row: dict[str, Any]) -> tuple[float | None, str | None]:
    roe = _f(row.get("roe"))
    de = _f(row.get("debt_to_equity") if row.get("debt_to_equity") is not None else row.get("debt_equity"))
    comps = _components(row)
    q = _f(comps.get("quality"))
    if roe is not None:
        x = _clamp((roe - QUALITY_ROE_REF) / QUALITY_ROE_REF, -1.0, 1.0)
        if de is not None:
            # High leverage trims quality; 0.5 D/E ≈ neutral.
            x = _clamp(x - _clamp((de - 0.5) / 1.5, -0.4, 0.4), -1.0, 1.0)
            return x, "roe_debt"
        return x, "roe"
    if q is not None:
        phase = str(row.get("phase") or "").strip().lower()
        # Ranker fills quality=0.5 when the map is empty — do not treat dummy
        # learning neutrals as a real quality observation.
        if phase == "learning" and abs(q - 0.5) < 1e-9:
            return None, None
        return _clamp((q - 0.5) * 2.0, -1.0, 1.0), "components.quality"
    return None, None


def _belief_factor(row: dict[str, Any]) -> tuple[float | None, str | None]:
    adj = _f(row.get("belief_adj"))
    if adj is None:
        adj = _f(row.get("belief_consult_score"))
    if adj is None:
        return None, None
    bounded = _clamp(adj, -BELIEF_BOUND, BELIEF_BOUND)
    return _clamp(bounded / BELIEF_BOUND, -1.0, 1.0), "belief_adj"


def _experience_factor(row: dict[str, Any]) -> tuple[float | None, str | None]:
    n = _f(row.get("closed_trade_n"))
    hit = _f(row.get("closed_trade_hit_rate"))
    if n is None or hit is None or n < 3:
        return None, None
    adj = _clamp((hit - 0.5) * 2.0 * EXPERIENCE_BOUND, -EXPERIENCE_BOUND, EXPERIENCE_BOUND)
    return _clamp(adj / EXPERIENCE_BOUND, -1.0, 1.0), "closed_trade_hit_rate"


_TERM_FNS = {
    "momentum": _momentum_factor,
    "sector_rs": _sector_rs_factor,
    "valuation": _valuation_factor,
    "quality": _quality_factor,
    "belief": _belief_factor,
    "experience": _experience_factor,
}


def confidence_for_prototype(label: Any, completeness: float) -> float:
    """Numeric confidence for switch math. Caps at low while incomplete.

    Imported by opportunity_switch; kept here so the cap rule lives next to
    the model version.
    """
    base: float | None = None
    if isinstance(label, (int, float)):
        v = float(label)
        if 0 < v <= 1.5:
            base = max(0.0, min(1.0, v if v <= 1.0 else v / 100.0))
    elif label is not None:
        key = str(label).strip().lower().replace(" ", "_")
        mapped = {
            "very_low": None,
            "very-low": None,
            "low": 0.35,
            "medium": 0.55,
            "high": 0.75,
        }
        if key in mapped:
            base = mapped[key]
    if base is None:
        base = PROTOTYPE_LOW_CONF
    if completeness < COMPLETENESS_CONF_CAP:
        base = min(float(base), PROTOTYPE_LOW_CONF)
    return round(float(base), 4)


def overlay_fundamentals_for_er(
    row: dict[str, Any], fund: dict[str, Any] | None
) -> dict[str, Any]:
    """Copy PE / ROE / D/E onto a switch row when the ranker omitted them."""
    if not isinstance(row, dict) or not isinstance(fund, dict):
        return row
    aliases = {
        "pe": ("pe", "trailing_pe"),
        "industry_pe_median": (
            "industry_pe_median",
            "pe_sector_median",
            "sector_pe",
            "peer_pe",
        ),
        "roe": ("roe",),
        "debt_to_equity": ("debt_to_equity", "debt_equity", "de"),
        "rs_vs_benchmark_pct": ("rs_vs_benchmark_pct",),
    }
    for dest, keys in aliases.items():
        if row.get(dest) is not None:
            continue
        for k in keys:
            if fund.get(k) is not None:
                row[dest] = fund.get(k)
                break
    return row


def compute_prototype_er(row: dict[str, Any] | None) -> dict[str, Any]:
    """Return versioned E[R] + input snapshot. Never silent for a dict row."""
    if not isinstance(row, dict):
        return {
            "er_model": ER_MODEL,
            "er_basis": ER_BASIS,
            "expected_return": None,
            "er_completeness": 0.0,
            "er_inputs": {"error": "no_row"},
            "confidence": None,
            "missing_terms": list(WEIGHTS),
            "present_terms": [],
        }

    terms: dict[str, Any] = {}
    present: list[str] = []
    missing: list[str] = []
    weighted = 0.0
    present_w = 0.0
    for name, fn in _TERM_FNS.items():
        w = float(WEIGHTS[name])
        factor, source = fn(row)
        present_flag = factor is not None
        x = 0.0 if factor is None else float(factor)
        contrib = w * x * STACK_SCALE
        weighted += contrib
        terms[name] = {
            "weight": w,
            "factor": None if factor is None else round(x, 6),
            "contribution": round(contrib, 6),
            "present": present_flag,
            "source": source,
        }
        if present_flag:
            present.append(name)
            present_w += w
        else:
            missing.append(name)

    total_w = sum(WEIGHTS.values()) or 1.0
    completeness = round(present_w / total_w, 4)
    er = round(weighted, 6)
    conf = confidence_for_prototype(row.get("confidence"), completeness)
    snapshot = {
        "er_model": ER_MODEL,
        "er_basis": ER_BASIS,
        "stack_scale": STACK_SCALE,
        "weights": dict(WEIGHTS),
        "phase": row.get("phase"),
        "confidence_label": row.get("confidence"),
        "symbol": row.get("symbol"),
        "terms": terms,
        "missing_terms": missing,
        "present_terms": present,
    }
    return {
        "er_model": ER_MODEL,
        "er_basis": ER_BASIS,
        "expected_return": er,
        "er_completeness": completeness,
        "er_inputs": snapshot,
        "confidence": conf,
        "missing_terms": missing,
        "present_terms": present,
        "honesty": (
            f"{ER_MODEL} completeness={completeness:.2f} — prototype, not alpha."
            + (
                f" Missing: {', '.join(missing)}."
                if missing
                else ""
            )
        ),
    }


def expected_block_from_metrics(metrics: dict[str, Any] | None) -> dict[str, Any]:
    """Packet ``expected`` block — durable E[R] snapshot."""
    m = metrics if isinstance(metrics, dict) else {}
    return {
        "holding_horizon": "position",
        "return_band": None,
        "expected_return": m.get("expected_return"),
        "er_model": m.get("er_model") or ER_MODEL,
        "er_basis": m.get("er_basis") or ER_BASIS,
        "er_completeness": m.get("er_completeness"),
        "er_inputs": m.get("er_inputs") if isinstance(m.get("er_inputs"), dict) else {},
        "opportunity_confidence": m.get("confidence"),
        "thesis_id": m.get("thesis_id"),
        "falsifiers": [],
    }
