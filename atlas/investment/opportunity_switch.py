"""UTS.C/D — Opportunity-cost switching: E[R]×confidence + hold-vs-challenger review.

LOOP0 L1: E[R] is the versioned prototype (``er_model=prototype_v1``). Missing
terms contribute 0 and lower completeness; the number is still emitted so
switch math can run. ``evaluate_switch`` still fail-closes if a caller passes
``None``. Honesty lives on the packet snapshot, not by refusing to score.
"""

from __future__ import annotations

from typing import Any

VERSION = "uts.d.opportunity_switch"

# Reason codes (shared with UTS.D packets / evening)
REASON_ADVANTAGE_CLEARED = "switch_advantage_cleared"
REASON_BLOCKED_COSTS = "switch_blocked_costs"
REASON_BLOCKED_MISSING_ER = "switch_blocked_missing_er"
REASON_BLOCKED_PLC_A = "switch_blocked_plc_a"
REASON_BLOCKED_COLD_START = "switch_blocked_cold_start"
REASON_HOLD_INCUMBENT = "hold_incumbent"
REASON_EXPLORATORY = "switch_exploratory"
REASON_BLOCKED_LAB_CONTRACT = "lab_instrument_rejected"

# Label → numeric confidence. very_low is insufficient for switching.
_CONF_FROM_LABEL: dict[str, float | None] = {
    "very_low": None,
    "very-low": None,
    "low": 0.35,
    "medium": 0.55,
    "high": 0.75,
}

# Map ranker score (≈0..1) to a bounded expected-return estimate.
# score 0.5 → 0%; score 1.0 → +12%; score 0.0 → −12%. Honesty: heuristic only.
_DEFAULT_ER_SCALE = 0.24

DEFAULT_SWITCH_COST = 0.01  # 100 bps all-in proxy
DEFAULT_THRESHOLD = 0.02
DEFAULT_PENALTY_K = 0.02
DEFAULT_PENALTY_M = 0.01


def risk_adjusted_score(
    expected_return: float | None,
    confidence: float | None,
) -> float | None:
    """Committee-style score: E[R] × confidence. None if either input missing."""
    if expected_return is None or confidence is None:
        return None
    try:
        er = float(expected_return)
        conf = float(confidence)
    except (TypeError, ValueError):
        return None
    if conf <= 0:
        return None
    return round(er * conf, 6)


def confidence_penalty(
    confidence_hold: float | None,
    confidence_challenger: float | None,
    *,
    k: float = DEFAULT_PENALTY_K,
    m: float = DEFAULT_PENALTY_M,
) -> float:
    """Extra friction for flipping away from better-calibrated holds / joint uncertainty."""
    if confidence_hold is None or confidence_challenger is None:
        return 0.0
    try:
        ch = float(confidence_hold)
        cc = float(confidence_challenger)
        kk = float(k)
        mm = float(m)
    except (TypeError, ValueError):
        return 0.0
    return round(
        max(0.0, kk * max(0.0, ch - cc) + mm * (1.0 - min(cc, ch))),
        6,
    )


def expected_advantage(
    expected_return_challenger: float | None,
    expected_return_hold: float | None,
    *,
    transaction_cost: float = DEFAULT_SWITCH_COST,
    slippage: float = 0.0,
    tax_cost: float = 0.0,
    confidence_hold: float | None = None,
    confidence_challenger: float | None = None,
    penalty_k: float = DEFAULT_PENALTY_K,
    penalty_m: float = DEFAULT_PENALTY_M,
) -> dict[str, Any]:
    """Compute net expected advantage of switching hold → challenger."""
    if expected_return_challenger is None or expected_return_hold is None:
        return {
            "ok": False,
            "advantage": None,
            "reason_code": REASON_BLOCKED_MISSING_ER,
            "costs": None,
            "confidence_penalty": None,
            "gross": None,
            "honesty": "Expected return missing for hold and/or challenger — no switch.",
        }
    try:
        er_n = float(expected_return_challenger)
        er_h = float(expected_return_hold)
        cost = max(0.0, float(transaction_cost)) + max(0.0, float(slippage)) + max(
            0.0, float(tax_cost)
        )
    except (TypeError, ValueError):
        return {
            "ok": False,
            "advantage": None,
            "reason_code": REASON_BLOCKED_MISSING_ER,
            "costs": None,
            "confidence_penalty": None,
            "gross": None,
            "honesty": "Non-numeric expected return — no switch.",
        }
    pen = confidence_penalty(
        confidence_hold, confidence_challenger, k=penalty_k, m=penalty_m
    )
    gross = er_n - er_h
    adv = gross - cost - pen
    return {
        "ok": True,
        "advantage": round(adv, 6),
        "gross": round(gross, 6),
        "costs": round(cost, 6),
        "confidence_penalty": pen,
        "reason_code": None,
        "honesty": None,
    }


def evaluate_switch(
    *,
    expected_return_challenger: float | None,
    expected_return_hold: float | None,
    confidence_challenger: float | None = None,
    confidence_hold: float | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    transaction_cost: float = DEFAULT_SWITCH_COST,
    slippage: float = 0.0,
    tax_cost: float = 0.0,
    penalty_k: float = DEFAULT_PENALTY_K,
    penalty_m: float = DEFAULT_PENALTY_M,
) -> dict[str, Any]:
    """Decide switch vs hold from expected advantage vs threshold."""
    adv = expected_advantage(
        expected_return_challenger,
        expected_return_hold,
        transaction_cost=transaction_cost,
        slippage=slippage,
        tax_cost=tax_cost,
        confidence_hold=confidence_hold,
        confidence_challenger=confidence_challenger,
        penalty_k=penalty_k,
        penalty_m=penalty_m,
    )
    if not adv.get("ok"):
        return {
            "version": VERSION,
            "decision": "hold",
            "reason_code": adv.get("reason_code") or REASON_BLOCKED_MISSING_ER,
            "expected_advantage": None,
            "threshold": float(threshold),
            "risk_adjusted_challenger": risk_adjusted_score(
                expected_return_challenger, confidence_challenger
            ),
            "risk_adjusted_hold": risk_adjusted_score(
                expected_return_hold, confidence_hold
            ),
            **{k: adv.get(k) for k in ("gross", "costs", "confidence_penalty", "honesty")},
        }
    try:
        thr = float(threshold)
    except (TypeError, ValueError):
        thr = DEFAULT_THRESHOLD
    advantage = float(adv["advantage"])
    if advantage > thr:
        decision = "switch"
        code = REASON_ADVANTAGE_CLEARED
    elif advantage > 0:
        decision = "hold"
        code = REASON_BLOCKED_COSTS
    else:
        decision = "hold"
        code = REASON_HOLD_INCUMBENT
    return {
        "version": VERSION,
        "decision": decision,
        "reason_code": code,
        "expected_advantage": advantage,
        "threshold": thr,
        "gross": adv.get("gross"),
        "costs": adv.get("costs"),
        "confidence_penalty": adv.get("confidence_penalty"),
        "risk_adjusted_challenger": risk_adjusted_score(
            expected_return_challenger, confidence_challenger
        ),
        "risk_adjusted_hold": risk_adjusted_score(
            expected_return_hold, confidence_hold
        ),
        "honesty": None,
    }


def confidence_from_label(label: Any) -> float | None:
    """Map ranker/plan confidence label → float, or None if insufficient."""
    if label is None:
        return None
    if isinstance(label, (int, float)):
        v = float(label)
        if v <= 0 or v > 1.5:
            return None
        return max(0.0, min(1.0, v if v <= 1.0 else v / 100.0))
    key = str(label).strip().lower().replace(" ", "_")
    if key in _CONF_FROM_LABEL:
        return _CONF_FROM_LABEL[key]
    return None


def expected_return_from_row(
    row: dict[str, Any] | None,
    *,
    er_scale: float = _DEFAULT_ER_SCALE,
) -> float | None:
    """Versioned prototype E[R] — always numeric for a dict row (LOOP0 L1).

    ``er_scale`` is accepted for call-site compatibility; prototype_v1 uses its
    own stack scale. Prefer ``estimate_opportunity_metrics`` for the snapshot.
    """
    del er_scale  # prototype_v1 scale is versioned in expected_return_prototype
    from atlas.investment.expected_return_prototype import compute_prototype_er

    return compute_prototype_er(row).get("expected_return")


def estimate_opportunity_metrics(
    row: dict[str, Any] | None,
    *,
    er_scale: float = _DEFAULT_ER_SCALE,
) -> dict[str, Any]:
    """Attachable metrics for a ranked / plan / holding row."""
    del er_scale
    from atlas.investment.expected_return_prototype import compute_prototype_er

    snap = compute_prototype_er(row)
    er = snap.get("expected_return")
    conf = snap.get("confidence")
    ras = risk_adjusted_score(er, conf)
    missing = list(snap.get("missing_terms") or [])
    computable = er is not None and conf is not None
    return {
        "version": VERSION,
        "er_model": snap.get("er_model"),
        "er_basis": snap.get("er_basis"),
        "er_completeness": snap.get("er_completeness"),
        "er_inputs": snap.get("er_inputs"),
        "expected_return": er,
        "confidence": conf,
        "risk_adjusted_score": ras,
        "missing": missing,
        "present_terms": list(snap.get("present_terms") or []),
        "computable": computable,
        "honesty": snap.get("honesty")
        if computable
        else (
            "E[R]/confidence not computable — switch evaluation will fail closed."
        ),
    }


def attach_opportunity_metrics(
    target: dict[str, Any],
    row: dict[str, Any] | None = None,
    *,
    er_scale: float = _DEFAULT_ER_SCALE,
) -> dict[str, Any]:
    """Merge opportunity metrics onto ``target`` (mutates and returns it)."""
    src = row if isinstance(row, dict) else target
    metrics = estimate_opportunity_metrics(src, er_scale=er_scale)
    target["expected_return"] = metrics["expected_return"]
    target["opportunity_confidence"] = metrics["confidence"]
    target["risk_adjusted_score"] = metrics["risk_adjusted_score"]
    target["er_model"] = metrics.get("er_model")
    target["er_basis"] = metrics.get("er_basis")
    target["er_completeness"] = metrics.get("er_completeness")
    target["er_inputs"] = metrics.get("er_inputs")
    target["opportunity_metrics"] = metrics
    return target


def enrich_positions_with_opportunity(
    positions: list[dict[str, Any]] | None,
    ranked_by_symbol: dict[str, dict[str, Any]] | None = None,
    *,
    er_scale: float = _DEFAULT_ER_SCALE,
) -> list[dict[str, Any]]:
    """Attach opportunity metrics to open holdings when a ranked row is known."""
    ranked_by_symbol = {
        str(k).strip().upper(): v
        for k, v in (ranked_by_symbol or {}).items()
        if isinstance(v, dict)
    }
    out: list[dict[str, Any]] = []
    for pos in positions or []:
        if not isinstance(pos, dict):
            continue
        row = dict(pos)
        sym = str(row.get("symbol") or "").strip().upper()
        src = ranked_by_symbol.get(sym) or ranked_by_symbol.get(
            sym.replace(".NS", "") + ".NS"
        )
        # Prefer ranked evidence; fall back to fields already on the position.
        attach_opportunity_metrics(row, src if src is not None else row, er_scale=er_scale)
        out.append(row)
    return out


def opportunity_switch_enabled(
    cfg: dict[str, Any] | None, portfolio_key: str | None
) -> bool:
    """Learner books default ON; other books OFF unless cfg forces."""
    cfg = cfg or {}
    if cfg.get("opportunity_switch_enabled") is not None:
        return bool(cfg.get("opportunity_switch_enabled"))
    pk = (portfolio_key or "").lower()
    return "learner" in pk or "laboratory" in pk


def _qty(pos: dict[str, Any]) -> float:
    for k in ("qty", "quantity", "shares"):
        try:
            v = float(pos.get(k) or 0)
        except (TypeError, ValueError):
            continue
        if v > 0:
            return v
    return 0.0


def _sym(row: dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return ""
    return str(row.get("symbol") or "").strip().upper()


def review_hold_vs_challengers(
    hold: dict[str, Any],
    challengers: list[dict[str, Any]] | None,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    cold_start_threshold: float = 0.05,
    transaction_cost: float = DEFAULT_SWITCH_COST,
    slippage: float = 0.0,
    tax_cost: float = 0.0,
    penalty_k: float = DEFAULT_PENALTY_K,
    penalty_m: float = DEFAULT_PENALTY_M,
    exploratory: bool = False,
    challenger_plc_a_ok: dict[str, bool] | None = None,
    er_scale: float = _DEFAULT_ER_SCALE,
    laboratory_id: str | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """UTS.D — evaluate one open hold against challenger rows (pure, no I/O).

    Always returns a decision for the hold (silence is a bug). Picks the
    challenger with the highest cleared advantage when multiple qualify.
    """
    hold_sym = _sym(hold)
    hold_metrics = estimate_opportunity_metrics(hold, er_scale=er_scale)
    thr = float(cold_start_threshold) if exploratory else float(threshold)
    base = {
        "version": VERSION,
        "hold_symbol": hold_sym,
        "hold_qty": _qty(hold),
        "challenger_symbol": None,
        "decision": "hold",
        "reason_code": REASON_HOLD_INCUMBENT,
        "expected_advantage": None,
        "threshold": thr,
        "exploratory": bool(exploratory),
        "label": "exploratory" if exploratory else "calibrated",
        "hold_metrics": hold_metrics,
        "challenger_metrics": None,
        "evaluated_challengers": 0,
    }
    if not hold_sym or _qty(hold) <= 0:
        base["reason_code"] = REASON_HOLD_INCUMBENT
        base["honesty"] = "No open quantity — nothing to review."
        return base
    if not hold_metrics.get("computable"):
        # Prototype_v1 always scores a dict row; this branch is the remaining
        # fail-closed path (malformed hold / non-numeric internals).
        conf_l = str(hold.get("confidence") or "").strip().lower()
        phase_l = str(hold.get("phase") or "").strip().lower()
        if conf_l in {"very_low", "very-low"} or phase_l == "learning":
            base["reason_code"] = REASON_BLOCKED_COLD_START
        else:
            base["reason_code"] = REASON_BLOCKED_MISSING_ER
        base["honesty"] = hold_metrics.get("honesty")
        return base

    plc_map = {
        str(k).strip().upper(): bool(v)
        for k, v in (challenger_plc_a_ok or {}).items()
    }
    best_switch: dict[str, Any] | None = None
    best_blocked: dict[str, Any] | None = None
    evaluated = 0

    for raw in challengers or []:
        if not isinstance(raw, dict):
            continue
        chal_sym = _sym(raw)
        if not chal_sym or chal_sym == hold_sym:
            continue
        try:
            from atlas.investment.lab_contracts import is_instrument_permitted

            inst = is_instrument_permitted(
                laboratory_id, chal_sym, cfg=cfg, instrument=raw, path="switch"
            )
            if not inst.allowed:
                blocked = {
                    "challenger_symbol": chal_sym,
                    "decision": "hold",
                    "reason_code": REASON_BLOCKED_LAB_CONTRACT,
                    "expected_advantage": None,
                    "challenger_metrics": None,
                }
                if best_blocked is None:
                    best_blocked = blocked
                continue
        except Exception:  # noqa: BLE001
            pass
        c_metrics = estimate_opportunity_metrics(raw, er_scale=er_scale)
        evaluated += 1
        if chal_sym in plc_map and not plc_map[chal_sym]:
            blocked = {
                "challenger_symbol": chal_sym,
                "decision": "hold",
                "reason_code": REASON_BLOCKED_PLC_A,
                "expected_advantage": None,
                "challenger_metrics": c_metrics,
            }
            if best_blocked is None:
                best_blocked = blocked
            continue
        if not c_metrics.get("computable"):
            blocked = {
                "challenger_symbol": chal_sym,
                "decision": "hold",
                "reason_code": REASON_BLOCKED_MISSING_ER,
                "expected_advantage": None,
                "challenger_metrics": c_metrics,
            }
            if best_blocked is None:
                best_blocked = blocked
            continue
        ev = evaluate_switch(
            expected_return_challenger=c_metrics.get("expected_return"),
            expected_return_hold=hold_metrics.get("expected_return"),
            confidence_challenger=c_metrics.get("confidence"),
            confidence_hold=hold_metrics.get("confidence"),
            threshold=thr,
            transaction_cost=transaction_cost,
            slippage=slippage,
            tax_cost=tax_cost,
            penalty_k=penalty_k,
            penalty_m=penalty_m,
        )
        row = {
            "challenger_symbol": chal_sym,
            "decision": ev.get("decision"),
            "reason_code": ev.get("reason_code"),
            "expected_advantage": ev.get("expected_advantage"),
            "challenger_metrics": c_metrics,
            "evaluation": ev,
        }
        if ev.get("decision") == "switch":
            adv = float(ev.get("expected_advantage") or 0)
            if best_switch is None or adv > float(
                best_switch.get("expected_advantage") or -1e9
            ):
                best_switch = row
        elif best_blocked is None or (
            (ev.get("expected_advantage") or -1e9)
            > (best_blocked.get("expected_advantage") or -1e9)
        ):
            best_blocked = row

    base["evaluated_challengers"] = evaluated
    if best_switch is not None:
        code = REASON_EXPLORATORY if exploratory else REASON_ADVANTAGE_CLEARED
        base.update(
            {
                "challenger_symbol": best_switch["challenger_symbol"],
                "decision": "switch",
                "reason_code": code,
                "expected_advantage": best_switch.get("expected_advantage"),
                "challenger_metrics": best_switch.get("challenger_metrics"),
                "evaluation": best_switch.get("evaluation"),
            }
        )
        return base
    if best_blocked is not None:
        base.update(
            {
                "challenger_symbol": best_blocked.get("challenger_symbol"),
                "decision": "hold",
                "reason_code": best_blocked.get("reason_code") or REASON_HOLD_INCUMBENT,
                "expected_advantage": best_blocked.get("expected_advantage"),
                "challenger_metrics": best_blocked.get("challenger_metrics"),
                "evaluation": best_blocked.get("evaluation"),
            }
        )
        return base
    base["honesty"] = "No eligible challengers to compare."
    return base


def review_portfolio_switches(
    positions: list[dict[str, Any]] | None,
    challengers: list[dict[str, Any]] | None,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    cold_start_threshold: float = 0.05,
    transaction_cost: float = DEFAULT_SWITCH_COST,
    slippage: float = 0.0,
    tax_cost: float = 0.0,
    penalty_k: float = DEFAULT_PENALTY_K,
    penalty_m: float = DEFAULT_PENALTY_M,
    exploratory: bool = False,
    challenger_plc_a_ok: dict[str, bool] | None = None,
    er_scale: float = _DEFAULT_ER_SCALE,
    max_holds: int = 40,
    laboratory_id: str | None = None,
    cfg: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Review every open hold (qty>0) — one decision row each."""
    out: list[dict[str, Any]] = []
    for pos in positions or []:
        if not isinstance(pos, dict) or _qty(pos) <= 0:
            continue
        out.append(
            review_hold_vs_challengers(
                pos,
                challengers,
                threshold=threshold,
                cold_start_threshold=cold_start_threshold,
                transaction_cost=transaction_cost,
                slippage=slippage,
                tax_cost=tax_cost,
                penalty_k=penalty_k,
                penalty_m=penalty_m,
                exploratory=exploratory,
                challenger_plc_a_ok=challenger_plc_a_ok,
                er_scale=er_scale,
                laboratory_id=laboratory_id,
                cfg=cfg,
            )
        )
        if len(out) >= max(1, int(max_holds)):
            break
    return out
