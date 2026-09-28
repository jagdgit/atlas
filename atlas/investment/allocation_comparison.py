"""OI-ICR1 — Allocation Comparison Packet (ACP).

Per-incumbent Next-₹1 packet: incumbent vs challengers vs cash vs benchmark,
with provenance and a deterministic decision (KEEP / HOLD / SWITCH_REVIEW /
EXIT_REVIEW). ADD is never emitted automatically in ICR.1 — ICR.0 still
requires an explicit ACP decision=ADD (future ICR.2 densify).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from atlas.investment.capital_allocation import (
    CASH_SYMBOL,
    DEFAULT_CASH_CONFIDENCE,
    DEFAULT_CASH_ER,
    cash_row,
)
from atlas.investment.incumbent_capital import (
    acp_path,
    allocation_state_hash,
)
from atlas.investment.opportunity_switch import (
    DEFAULT_SWITCH_COST,
    DEFAULT_THRESHOLD,
    REASON_ADVANTAGE_CLEARED,
    REASON_ADVANTAGE_UNCLEAR,
    REASON_BLOCKED_MISSING_ER,
    REASON_BLOCKED_PLC_A,
    REASON_HOLD_INCUMBENT,
    estimate_opportunity_metrics,
    expected_advantage,
    review_hold_vs_challengers,
)

VERSION = "icr.4.acp.v1"
_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.allocation_comparison")

DECISION_KEEP = "KEEP"
DECISION_HOLD = "HOLD"
DECISION_ADD = "ADD"
DECISION_SWITCH_REVIEW = "SWITCH_REVIEW"
DECISION_EXIT_REVIEW = "EXIT_REVIEW"

REASON_EXIT_AVOID = "exit_review_thesis_avoid"
REASON_EXIT_QUARANTINE = "exit_review_identity_quarantine"
REASON_EXIT_MOS = "exit_review_mos_negative"
REASON_SWITCH = "switch_review_advantage"
REASON_KEEP = "keep_incumbent"
REASON_HOLD_THIN = "hold_thin_evidence"
REASON_HOLD_DEFAULT = "hold_default"
REASON_ADVANTAGE_UNCLEAR = "advantage_unclear"


def ist_today() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def _sym(row: dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return ""
    return str(row.get("symbol") or "").strip().upper()


def _f(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _qty(row: dict[str, Any] | None) -> float:
    if not isinstance(row, dict):
        return 0.0
    for k in ("qty", "quantity", "shares"):
        v = _f(row.get(k))
        if v is not None and v > 0:
            return v
    return 0.0


def _stance_identity(awareness: dict[str, Any] | None, symbol: str) -> tuple[str, str, dict]:
    stance = "ABSENT"
    identity = "UNKNOWN"
    ident_row: dict[str, Any] = {}
    try:
        from atlas.investment.lab_contracts import thesis_stance_from_awareness

        stance = str(thesis_stance_from_awareness(awareness) or "ABSENT").upper()
    except Exception:  # noqa: BLE001
        pass
    try:
        from atlas.investment.thesis_identity import validate_thesis_identity

        ident_row = validate_thesis_identity(symbol, awareness if isinstance(awareness, dict) else None)
        identity = str(ident_row.get("identity") or "UNKNOWN").upper()
    except Exception:  # noqa: BLE001
        pass
    return stance, identity, ident_row


def _mos(awareness: dict[str, Any] | None) -> float | None:
    if not isinstance(awareness, dict):
        return None
    val = awareness.get("valuation") if isinstance(awareness.get("valuation"), dict) else {}
    return _f(val.get("margin_of_safety_pct"))


def _leg_from_row(row: dict[str, Any], *, role: str) -> dict[str, Any]:
    metrics = estimate_opportunity_metrics(row)
    return {
        "symbol": _sym(row) or role,
        "role": role,
        "qty": _qty(row) if role == "incumbent" else None,
        "avg_price": _f(row.get("avg_price") or row.get("avg_cost")),
        "mark": _f(row.get("mark") or row.get("price")),
        "expected_return": metrics.get("expected_return"),
        "er_completeness": metrics.get("er_completeness"),
        "er_model": metrics.get("er_model"),
        "er_basis": metrics.get("er_basis"),
        "er_inputs": metrics.get("er_inputs"),
        "confidence": metrics.get("confidence"),
        "opportunity_score": metrics.get("risk_adjusted_score"),
        "missing_terms": list(metrics.get("missing") or []),
        "plc_a_status": row.get("plc_a_status"),
    }


def decide_acp(
    *,
    stance: str,
    identity: str,
    mos: float | None,
    review: dict[str, Any] | None,
    incumbent_er_completeness: float | None,
) -> tuple[str, str, str]:
    """Return (decision, reason_code, why_line). Never auto-ADD in ICR.1."""
    if identity == "QUARANTINED":
        return (
            DECISION_EXIT_REVIEW,
            REASON_EXIT_QUARANTINE,
            "Identity quarantine — re-establish thesis before trusting capital in this name",
        )
    if stance in {"AVOID", "INVALID"}:
        return (
            DECISION_EXIT_REVIEW,
            REASON_EXIT_AVOID,
            f"Thesis {stance} — EXIT_REVIEW (not auto-sell); no ADD",
        )
    if mos is not None and mos < -25.0:
        return (
            DECISION_EXIT_REVIEW,
            REASON_EXIT_MOS,
            f"MoS {mos:.1f}% deeply negative — EXIT_REVIEW vs challengers/cash",
        )
    rev = review if isinstance(review, dict) else {}
    rev_reason = str(rev.get("reason_code") or "")
    if str(rev.get("decision") or "").lower() == "switch" or rev_reason == REASON_ADVANTAGE_CLEARED:
        chal = rev.get("challenger_symbol") or "?"
        return (
            DECISION_SWITCH_REVIEW,
            REASON_SWITCH,
            f"Challenger {chal} clears switch advantage — SWITCH_REVIEW",
        )
    # ICR.4 — missing_er / plc_a / unclear ≠ permanent incumbent lock-in
    if rev_reason in {
        REASON_BLOCKED_MISSING_ER,
        REASON_ADVANTAGE_UNCLEAR,
        REASON_BLOCKED_PLC_A,
        "switch_blocked_missing_er",
    }:
        return (
            DECISION_HOLD,
            REASON_ADVANTAGE_UNCLEAR,
            "Advantage unclear (thin E[R], PLC.A block, or incomplete challenger) — "
            "HOLD; cash stays competitor; densify — not missing_er lock-in",
        )
    try:
        comp = float(incumbent_er_completeness) if incumbent_er_completeness is not None else 0.0
    except (TypeError, ValueError):
        comp = 0.0
    if comp < 0.45:
        return (
            DECISION_HOLD,
            REASON_HOLD_THIN,
            "Thin E[R] completeness — HOLD + densify evidence (cash remains competitor)",
        )
    if rev_reason == REASON_HOLD_INCUMBENT:
        return (
            DECISION_KEEP,
            REASON_KEEP,
            "Incumbent wins after costs vs best challenger — KEEP (not permanent veto)",
        )
    return (
        DECISION_HOLD,
        REASON_HOLD_DEFAULT,
        "No clear rotate edge — HOLD; cash and challengers stay in the set",
    )


def build_allocation_comparison_packet(
    *,
    hold: dict[str, Any],
    challengers: list[dict[str, Any]] | None,
    cash: float,
    laboratory_id: str,
    awareness: dict[str, Any] | None = None,
    review: dict[str, Any] | None = None,
    equity: float | None = None,
    benchmark: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    as_of_ist: str | None = None,
    evidence_ids: list[str] | None = None,
    technical_refs: dict[str, Any] | None = None,
    decision_packet_ids: list[str] | None = None,
    challenger_plc_a_ok: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Build one ACP for an open swing holding."""
    cfg = cfg or {}
    day = (as_of_ist or ist_today()).strip()
    sym = _sym(hold)
    stance, identity, ident_row = _stance_identity(awareness, sym)
    mos = _mos(awareness)
    qty = _qty(hold)
    mark = _f(hold.get("mark") or hold.get("price")) or 0.0
    eq = _f(equity)
    weight = None
    if eq and eq > 0 and mark > 0 and qty > 0:
        weight = round((qty * mark) / eq, 4)

    plc_map = {
        str(k).strip().upper(): bool(v)
        for k, v in (challenger_plc_a_ok or {}).items()
    }
    rev = review
    if rev is None:
        rev = review_hold_vs_challengers(
            hold,
            challengers,
            threshold=float(cfg.get("switch_threshold") or DEFAULT_THRESHOLD),
            transaction_cost=float(cfg.get("switch_cost") or DEFAULT_SWITCH_COST),
            laboratory_id=laboratory_id,
            cfg=cfg,
            challenger_plc_a_ok=plc_map or None,
        )

    incumbent = _leg_from_row(hold, role="incumbent")
    incumbent.update(
        {
            "thesis_stance": stance,
            "identity": identity,
            "identity_detail": {
                k: ident_row.get(k)
                for k in (
                    "status",
                    "identity_pack",
                    "thesis_pack",
                    "thesis_invalid",
                    "reasons",
                )
                if k in ident_row
            },
            "mos_pct": mos,
            "concentration_weight": weight,
        }
    )

    chal_legs: list[dict[str, Any]] = []
    held = {sym}
    for c in challengers or []:
        if not isinstance(c, dict):
            continue
        cs = _sym(c)
        if not cs or cs in held:
            continue
        leg = _leg_from_row(c, role="challenger")
        if cs in plc_map and not plc_map[cs]:
            leg["challenger_status"] = "plc_a_blocked"
            leg["plc_a_status"] = "blocked"
        else:
            leg["challenger_status"] = leg.get("challenger_status") or "ok"
            leg["plc_a_status"] = "ok"
        if rev and str(rev.get("challenger_symbol") or "").upper() == cs:
            leg["is_best"] = True
            leg["expected_advantage"] = rev.get("expected_advantage")
            leg["reason_code"] = rev.get("reason_code")
            if rev.get("challenger_status"):
                leg["challenger_status"] = rev.get("challenger_status")
        chal_legs.append(leg)
        if len(chal_legs) >= 3:
            break
    best_sym = str((rev or {}).get("challenger_symbol") or "").upper()
    if best_sym and best_sym not in {_sym(x) for x in chal_legs}:
        for c in challengers or []:
            if _sym(c) == best_sym:
                leg = _leg_from_row(c, role="challenger")
                leg["is_best"] = True
                leg["expected_advantage"] = (rev or {}).get("expected_advantage")
                if best_sym in plc_map and not plc_map[best_sym]:
                    leg["challenger_status"] = "plc_a_blocked"
                else:
                    leg["challenger_status"] = (
                        (rev or {}).get("challenger_status") or "ok"
                    )
                chal_legs.insert(0, leg)
                break

    cash_doc = cash_row(
        cash,
        expected_return=float(cfg.get("cash_expected_return") or DEFAULT_CASH_ER),
        confidence=float(cfg.get("cash_confidence") or DEFAULT_CASH_CONFIDENCE),
    )
    cash_leg = {
        "symbol": CASH_SYMBOL,
        "role": "cash",
        "expected_return": cash_doc.get("expected_return"),
        "er_completeness": cash_doc.get("er_completeness"),
        "er_model": cash_doc.get("er_model") or "cash_v1",
        "confidence": cash_doc.get("confidence"),
        "opportunity_score": cash_doc.get("opportunity_score"),
        "cash": cash_doc.get("cash"),
        "challenger_status": "cash_competitor",
    }

    vs_cash = expected_advantage(
        cash_leg.get("expected_return"),
        incumbent.get("expected_return"),
        transaction_cost=0.0,
        confidence_hold=incumbent.get("confidence"),
        confidence_challenger=cash_leg.get("confidence"),
    )
    inc_vs_cash = expected_advantage(
        incumbent.get("expected_return"),
        cash_leg.get("expected_return"),
        transaction_cost=float(cfg.get("switch_cost") or DEFAULT_SWITCH_COST),
        confidence_hold=cash_leg.get("confidence"),
        confidence_challenger=incumbent.get("confidence"),
    )

    decision, reason_code, why = decide_acp(
        stance=stance,
        identity=identity,
        mos=mos,
        review=rev,
        incumbent_er_completeness=incumbent.get("er_completeness"),
    )

    state_hash = allocation_state_hash(
        laboratory_id=laboratory_id,
        symbol=sym,
        held=qty,
        stance=stance,
        identity=identity,
        extra={
            "decision": decision,
            "best_chal": best_sym,
            "mos": mos,
            "er_c": incumbent.get("er_completeness"),
        },
    )
    acp_id = str(uuid.uuid4())
    rejected: list[dict[str, Any]] = []
    for leg in chal_legs:
        if leg.get("is_best"):
            continue
        rejected.append(
            {
                "symbol": leg.get("symbol"),
                "why": "not_best_challenger",
                "expected_return": leg.get("expected_return"),
                "challenger_status": leg.get("challenger_status"),
            }
        )
    if decision != DECISION_SWITCH_REVIEW and best_sym:
        rejected.append(
            {
                "symbol": best_sym,
                "why": reason_code,
                "expected_return": (
                    (rev or {}).get("challenger_metrics", {}).get("expected_return")
                    if isinstance((rev or {}).get("challenger_metrics"), dict)
                    else None
                ),
                "challenger_status": (rev or {}).get("challenger_status"),
            }
        )
    if decision in {DECISION_KEEP, DECISION_HOLD, DECISION_EXIT_REVIEW}:
        rejected.append(
            {
                "symbol": CASH_SYMBOL,
                "why": "not_chosen_this_packet",
                "expected_return": cash_leg.get("expected_return"),
            }
        )

    er_legs = [incumbent, *chal_legs, cash_leg]
    er_symmetry = {
        "version": "icr.4",
        "all_legs_scored": all(
            isinstance(leg, dict) and leg.get("expected_return") is not None
            for leg in er_legs
        ),
        "legs": [
            {
                "symbol": leg.get("symbol"),
                "role": leg.get("role"),
                "expected_return": leg.get("expected_return"),
                "er_model": leg.get("er_model"),
                "er_completeness": leg.get("er_completeness"),
                "challenger_status": leg.get("challenger_status"),
            }
            for leg in er_legs
            if isinstance(leg, dict)
        ],
        "note": (
            "Prototype E[R] always on ACP legs; block is advantage_unclear — "
            "not missing_er lock-in. PLC.A-blocked challengers stay visible."
        ),
    }

    provenance = {
        "acp_id": acp_id,
        "candidate_set": [sym, *[x.get("symbol") for x in chal_legs], CASH_SYMBOL],
        "er_model": incumbent.get("er_model"),
        "er_inputs_incumbent": incumbent.get("er_inputs"),
        "er_symmetry": er_symmetry,
        "evidence_ids": list(evidence_ids or []),
        "decision_packet_ids": list(decision_packet_ids or []),
        "technical_refs": technical_refs if isinstance(technical_refs, dict) else {},
        "thesis_stance": stance,
        "identity": identity,
        "scientist_notes": None,
        "final_decision": decision,
        "reason_code": reason_code,
        "switch_review": {
            "decision": (rev or {}).get("decision"),
            "reason_code": (rev or {}).get("reason_code"),
            "expected_advantage": (rev or {}).get("expected_advantage"),
            "challenger_symbol": (rev or {}).get("challenger_symbol"),
            "challenger_status": (rev or {}).get("challenger_status"),
        },
    }

    return {
        "version": VERSION,
        "kind": "allocation_comparison_packet",
        "acp_id": acp_id,
        "laboratory_id": laboratory_id,
        "as_of_ist": day,
        "created_at": datetime.now(_IST).isoformat(),
        "state_hash": state_hash,
        "available_capital": round(float(cash), 2),
        "equity": eq,
        "incumbent": incumbent,
        "challengers": chal_legs,
        "cash": cash_leg,
        "benchmark": benchmark
        if isinstance(benchmark, dict)
        else {"symbol": "NIFTY", "note": "stub — RS filled when MTL available"},
        "switch_cost": {
            "transaction_cost": float(cfg.get("switch_cost") or DEFAULT_SWITCH_COST),
            "min_advantage": float(cfg.get("switch_threshold") or DEFAULT_THRESHOLD),
        },
        "concentration": {"name_weight": weight, "symbol": sym},
        "incumbent_vs_cash": inc_vs_cash,
        "cash_vs_incumbent_raw": vs_cash,
        "decision": decision,
        "reason_code": reason_code,
        "why": why,
        "rejected": rejected,
        "er_symmetry": er_symmetry,
        "provenance": provenance,
        # Slim awareness for deterministic Evidence Completeness Gate (not LLM)
        "awareness": awareness if isinstance(awareness, dict) else {},
        "operator_line": format_acp_one_liner(
            {
                "incumbent": incumbent,
                "challengers": chal_legs,
                "cash": cash_leg,
                "decision": decision,
                "why": why,
                "switch_cost": {
                    "min_advantage": float(
                        cfg.get("switch_threshold") or DEFAULT_THRESHOLD
                    )
                },
                "review": rev,
            }
        ),
        "honesty": (
            "Technical BUY does not imply ADD. Cash is always a competitor. "
            "ICR.4: prototype E[R] on every leg; advantage_unclear ≠ missing_er "
            "lock-in. EXIT_REVIEW is not auto-liquidation."
        ),
    }


def format_acp_one_liner(doc: dict[str, Any]) -> str:
    inc = doc.get("incumbent") if isinstance(doc.get("incumbent"), dict) else {}
    chal = None
    for c in doc.get("challengers") or []:
        if isinstance(c, dict) and c.get("is_best"):
            chal = c
            break
    if chal is None:
        chals = [c for c in (doc.get("challengers") or []) if isinstance(c, dict)]
        chal = chals[0] if chals else {}
    cash = doc.get("cash") if isinstance(doc.get("cash"), dict) else {}
    rev = doc.get("review") if isinstance(doc.get("review"), dict) else {}
    adv = rev.get("expected_advantage")
    if adv is None and isinstance(chal, dict):
        adv = chal.get("expected_advantage")
    thr = (doc.get("switch_cost") or {}).get("min_advantage")
    return (
        f"{inc.get('symbol') or '?'}: {doc.get('decision') or '?'} — "
        f"own E[R]={inc.get('expected_return')} "
        f"(c={inc.get('er_completeness')}) · "
        f"best={chal.get('symbol') or '—'} E[R]={chal.get('expected_return')} · "
        f"cash E[R]={cash.get('expected_return')} · "
        f"adv={adv} min={thr} · {doc.get('why') or ''}"
    )[:280]


def persist_acp(data_dir: str | Path | None, acp: dict[str, Any]) -> dict[str, Any]:
    if not data_dir or not isinstance(acp, dict):
        return {"ok": False, "reason": "no_data_dir"}
    lab = str(acp.get("laboratory_id") or "unknown")
    sym = str((acp.get("incumbent") or {}).get("symbol") or "UNKNOWN")
    state_hash = str(acp.get("state_hash") or "nohash")
    # Phase 6 — attach evidence lineage on ACP before write
    try:
        from atlas.investment.evidence_lineage import build_evidence_lineage

        if not acp.get("evidence_lineage"):
            acp["evidence_lineage"] = build_evidence_lineage(
                decision_id=str(acp.get("acp_id") or ""),
                acp_id=str(acp.get("acp_id") or "") or None,
                evidence_refs=list(acp.get("evidence_refs") or []),
                observation_ids=list(acp.get("observation_ids") or []),
                extra={"kind": "ACP", "symbol": sym},
            )
    except Exception:  # noqa: BLE001
        pass
    # Decision Evidence Completeness Gate (deterministic; not Ollama)
    try:
        from atlas.investment.evidence_completeness import (
            apply_completeness_to_uncertainty,
            evaluate_evidence_completeness,
            format_why_not_evaluable,
            persist_completeness,
        )

        if not acp.get("evidence_completeness"):
            aw = acp.get("awareness") if isinstance(acp.get("awareness"), dict) else {}
            mark = None
            try:
                mark = (acp.get("incumbent") or {}).get("mark") or (
                    acp.get("incumbent") or {}
                ).get("price")
            except Exception:  # noqa: BLE001
                mark = None
            market = {
                "ltp": mark,
                "price": mark,
                "provider": (acp.get("provenance") or {}).get("price_provider")
                if isinstance(acp.get("provenance"), dict)
                else None,
            }
            comp = evaluate_evidence_completeness(
                symbol=sym,
                laboratory_id=lab,
                awareness=aw,
                market=market,
                fundamentals=aw.get("fundamentals")
                if isinstance(aw.get("fundamentals"), dict)
                else None,
            )
            acp["evidence_completeness"] = {
                "decision": comp.get("decision"),
                "decision_evaluable": comp.get("decision_evaluable"),
                "usable_evidence_pct": comp.get("usable_evidence_pct"),
                "required_missing": comp.get("required_missing"),
                "material_missing": comp.get("material_missing"),
                "stale": comp.get("stale"),
                "conflicting": comp.get("conflicting"),
                "why": format_why_not_evaluable(comp),
            }
            persist_completeness(data_dir, comp)
            apply_completeness_to_uncertainty(data_dir, comp)
    except Exception:  # noqa: BLE001
        _log.debug("evidence completeness on ACP skipped", exc_info=True)
    # Phase 5 — opportunity competition snapshot (candidate_set → winner)
    try:
        from atlas.investment.competition_snapshot import (
            build_competition_snapshot,
            persist_competition,
        )

        cand_rows: list[dict[str, Any]] = []
        inc = acp.get("incumbent") if isinstance(acp.get("incumbent"), dict) else {}
        if inc.get("symbol"):
            cand_rows.append(
                {
                    "symbol": inc.get("symbol"),
                    "expected_return": inc.get("expected_return"),
                    "notes": "incumbent",
                }
            )
        for c in acp.get("challengers") or []:
            if not isinstance(c, dict) or not c.get("symbol"):
                continue
            cand_rows.append(
                {
                    "symbol": c.get("symbol"),
                    "expected_return": c.get("expected_return"),
                    "notes": "challenger",
                }
            )
        cash = acp.get("cash") if isinstance(acp.get("cash"), dict) else {}
        if cash.get("expected_return") is not None:
            cand_rows.append(
                {
                    "symbol": CASH_SYMBOL,
                    "expected_return": cash.get("expected_return"),
                    "notes": "cash",
                }
            )
        snap = build_competition_snapshot(
            laboratory_id=lab,
            candidates=cand_rows,
            decision=str(acp.get("decision") or "") or None,
            incumbent=str(inc.get("symbol") or "") or None,
            as_of_ist=str(acp.get("as_of_ist") or "") or None,
        )
        persist_competition(data_dir, snap)
        acp["competition"] = {
            "winner": snap.get("winner"),
            "candidate_set": snap.get("candidate_set"),
        }
        try:
            from atlas.investment.l5_validation import observe_candidates_from_competition

            observe_candidates_from_competition(
                data_dir,
                laboratory_id=lab,
                snap=snap,
                as_of_ist=str(acp.get("as_of_ist") or "") or None,
            )
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        _log.debug("ACP competition snapshot skipped", exc_info=True)
    path = acp_path(data_dir, lab, sym, state_hash)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(acp, indent=2, default=str), encoding="utf-8")
        # Latest pointer for UI / evening (same dir).
        latest = path.parent / f"{sym}_latest.json"
        latest.write_text(
            json.dumps(
                {
                    "path": str(path),
                    "state_hash": state_hash,
                    "acp_id": acp.get("acp_id"),
                    "decision": acp.get("decision"),
                    "operator_line": acp.get("operator_line"),
                    "as_of_ist": acp.get("as_of_ist"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return {"ok": True, "path": str(path), "latest": str(latest)}
    except OSError as exc:
        _log.debug("ACP persist failed", exc_info=True)
        return {"ok": False, "reason": type(exc).__name__}


def load_latest_acp_summary(
    data_dir: str | Path | None,
    laboratory_id: str,
    symbol: str,
) -> dict[str, Any] | None:
    if not data_dir:
        return None
    lab = str(laboratory_id or "").strip() or "unknown"
    sym = str(symbol or "").strip().upper()
    latest = Path(data_dir) / "investment" / "allocation" / lab / f"{sym}_latest.json"
    if not latest.is_file():
        return None
    try:
        meta = json.loads(latest.read_text(encoding="utf-8"))
        if not isinstance(meta, dict):
            return None
        path = Path(str(meta.get("path") or ""))
        if path.is_file():
            doc = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(doc, dict):
                exit_res = (
                    doc.get("exit_resolution")
                    if isinstance(doc.get("exit_resolution"), dict)
                    else {}
                )
                return {
                    "decision": doc.get("decision"),
                    "reason_code": doc.get("reason_code"),
                    "operator_line": doc.get("operator_line") or meta.get("operator_line"),
                    "state_hash": doc.get("state_hash"),
                    "acp_id": doc.get("acp_id"),
                    "as_of_ist": doc.get("as_of_ist"),
                    "why": doc.get("why"),
                    "best_challenger": next(
                        (
                            c.get("symbol")
                            for c in (doc.get("challengers") or [])
                            if isinstance(c, dict) and c.get("is_best")
                        ),
                        None,
                    ),
                    "exit_action": exit_res.get("action"),
                    "exit_line": exit_res.get("operator_line"),
                    "waiting_for": exit_res.get("waiting_for") or [],
                    "scientist_line": (
                        (doc.get("scientist_notes") or {}).get("operator_line")
                        if isinstance(doc.get("scientist_notes"), dict)
                        else None
                    ),
                    "scientist_summary": (
                        (doc.get("scientist_notes") or {}).get("summary")
                        if isinstance(doc.get("scientist_notes"), dict)
                        else None
                    ),
                }
        return meta
    except Exception:  # noqa: BLE001
        return None


def build_and_persist_lab_acps(
    *,
    data_dir: str | Path | None,
    holds: list[dict[str, Any]] | None,
    challengers: list[dict[str, Any]] | None,
    cash: float,
    laboratory_id: str,
    reviews: list[dict[str, Any]] | None = None,
    awareness_by_symbol: dict[str, dict[str, Any]] | None = None,
    equity: float | None = None,
    cfg: dict[str, Any] | None = None,
    as_of_ist: str | None = None,
    challenger_plc_a_ok: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Build+persist ACP for every open hold (swing ICR.1/4)."""
    from atlas.investment.incumbent_capital import register_acp_decision_today

    aw_map = awareness_by_symbol or {}
    review_by = {
        str(r.get("hold_symbol") or "").upper(): r
        for r in (reviews or [])
        if isinstance(r, dict)
    }
    packets: list[dict[str, Any]] = []
    persisted = 0
    reused = 0
    day = (as_of_ist or ist_today()).strip()
    for hold in holds or []:
        if not isinstance(hold, dict) or _qty(hold) <= 0:
            continue
        sym = _sym(hold)
        acp = build_allocation_comparison_packet(
            hold=hold,
            challengers=challengers,
            cash=cash,
            laboratory_id=laboratory_id,
            awareness=aw_map.get(sym) or aw_map.get(sym.replace(".NS", "")),
            review=review_by.get(sym),
            equity=equity,
            cfg=cfg,
            as_of_ist=as_of_ist,
            challenger_plc_a_ok=challenger_plc_a_ok,
        )
        # ICR.4 / EXP0 — one decision per state_hash per IST day
        if data_dir:
            reg = register_acp_decision_today(
                data_dir,
                laboratory_id=laboratory_id,
                state_hash=str(acp.get("state_hash") or ""),
                symbol=sym,
                decision=str(acp.get("decision") or ""),
                as_of_ist=day,
            )
            if not reg.get("first"):
                acp["same_state_today"] = True
                prior = reg.get("prior") or {}
                acp["prior_decision_today"] = prior.get("decision")
                reused += 1
        packets.append(acp)
        if data_dir:
            out = persist_acp(data_dir, acp)
            if out.get("ok"):
                persisted += 1
            # Phase 4 — material unknowns → acquisition tasks (not infinite HOLD)
            try:
                from atlas.investment.uncertainty_queue import enqueue_from_awareness

                aw = aw_map.get(sym) or aw_map.get(sym.replace(".NS", ""))
                enqueue_from_awareness(
                    data_dir,
                    laboratory_id=laboratory_id,
                    symbol=sym,
                    awareness=aw if isinstance(aw, dict) else None,
                )
            except Exception:  # noqa: BLE001
                _log.debug("uncertainty enqueue skipped", exc_info=True)
    return {
        "version": VERSION,
        "laboratory_id": laboratory_id,
        "count": len(packets),
        "persisted": persisted,
        "same_state_reused": reused,
        "packets": packets,
        "lines": [p.get("operator_line") for p in packets if p.get("operator_line")],
    }


def format_acp_evening_lines(build_result: dict[str, Any] | None, *, limit: int = 8) -> list[str]:
    if not isinstance(build_result, dict) or not build_result.get("lines"):
        # Fallback: try nothing — evening can load from disk separately
        return []
    lines = [
        "",
        "── Incumbent ACP (OI-ICR1 — why own / vs challenger / vs cash) ──",
    ]
    for line in (build_result.get("lines") or [])[:limit]:
        lines.append(f"  {line}")
    return lines


def format_acp_evening_from_disk(
    data_dir: str | Path | None,
    laboratory_id: str,
    symbols: list[str],
    *,
    limit: int = 8,
) -> list[str]:
    if not data_dir or not symbols:
        return []
    lines = [
        "",
        "── Incumbent ACP (OI-ICR1 — why own / vs challenger / vs cash) ──",
    ]
    n = 0
    for sym in symbols:
        if n >= limit:
            break
        summary = load_latest_acp_summary(data_dir, laboratory_id, sym)
        if not summary:
            continue
        lines.append(f"  {summary.get('operator_line') or summary}")
        if summary.get("exit_line"):
            lines.append(f"    → {summary.get('exit_line')}")
        n += 1
    if n == 0:
        return []
    return lines
