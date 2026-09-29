"""OI-CU0 CU.B — attributed learning story on qualifying closes.

prediction → allocation → outcome → error → cause|unknown_explicit
  → belief update|UNREVIEWED → next decision change

Never invent predictions after the fact (prediction_absent).
Never manufacture a vanity daily story when no qualifying close exists.
Technical_only outcomes must not silently rewrite fundamental thesis.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from atlas.investment.learning_objects import (
    attribution_required_for_close,
    ist_today,
    record_learning_event,
)

VERSION = "cu0.learning_story.v1"
STORY_KIND = "LEARNING_STORY"


def _f(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def stamp_packet_prediction(
    expected: dict[str, Any] | None,
    *,
    action: str | None = None,
    indicators: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """B1 — stamp stated prediction or prediction_absent (never reconstruct later)."""
    out = dict(expected) if isinstance(expected, dict) else {}
    er = _f(out.get("expected_return"))
    direction = str(out.get("expected_direction") or out.get("direction") or "").strip().lower()
    if direction in {"", "none", "null", "unknown"}:
        direction = ""
    # Soft infer direction only from explicit technical action already decided —
    # still "stated" as decide-time intent, not post-hoc reconstruction from P&L.
    if not direction and str(action or "").lower() == "buy":
        direction = "up"
        out["expected_direction"] = "up"
        out["direction_source"] = "action_buy"
    elif not direction and str(action or "").lower() in {"sell", "reduce"}:
        direction = "down"
        out["expected_direction"] = "down"
        out["direction_source"] = "action_sell"

    if er is not None or direction:
        out["prediction_status"] = "stated"
        if er is not None:
            out["expected_return"] = er
        if direction:
            out.setdefault("expected_direction", direction)
    else:
        out["prediction_status"] = "prediction_absent"
        out["expected_return"] = None
        out["expected_direction"] = None
        out["honesty"] = (
            "No E[R] or direction stated at decide-time — prediction_absent "
            "(do not invent after the outcome)."
        )
    out.setdefault("holding_horizon", out.get("holding_horizon") or "position")
    return out


def is_qualifying_close(
    *,
    event_kind: str | None = None,
    action: str | None = None,
    strategy_tag: str | None = None,
    trade: dict[str, Any] | None = None,
) -> bool:
    """True when a close exists that requires a learning story."""
    kind = str(event_kind or "").strip().lower()
    tag = str(strategy_tag or "").strip().lower()
    act = str(action or "").strip().lower()
    tr = trade if isinstance(trade, dict) else {}
    if kind in {"exit", "eod_flatten"} or tag == "eod_flatten":
        return True
    if act in {"sell", "reduce"}:
        return True
    if str(tr.get("side") or "").lower() in {"sell", "reduce"}:
        return True
    if tr.get("realized_pnl") is not None and kind == "exit":
        return True
    return False


def contradiction_context_from_packet(packet: dict[str, Any] | None) -> dict[str, Any] | None:
    """B4 — technical_only + thesis WATCH must surface contradiction."""
    pkt = packet if isinstance(packet, dict) else {}
    meta = pkt.get("meta") if isinstance(pkt.get("meta"), dict) else {}
    decomp = meta.get("decision_decomposition")
    if not isinstance(decomp, dict):
        decomp = meta.get("decomposition") if isinstance(meta.get("decomposition"), dict) else {}
    lab_policy = str(decomp.get("lab_policy") or meta.get("lab_policy") or "")
    thesis = str(decomp.get("fundamental_thesis") or decomp.get("thesis") or "")
    contra = list(decomp.get("contradictions") or [])
    if not contra and lab_policy != "technical_only":
        return None
    return {
        "decision_source": lab_policy or str(pkt.get("strategy_tag") or "unknown"),
        "fundamental_state": thesis or "ABSENT",
        "technical_signal": decomp.get("technical_signal") or pkt.get("action"),
        "contradictions": contra,
        "purpose": (
            "technical laboratory experiment"
            if lab_policy == "technical_only"
            else "lab decision"
        ),
        "rule": (
            "Technical experiment outcomes must not silently rewrite the fundamental thesis."
            if lab_policy == "technical_only"
            else None
        ),
    }


def ensure_close_attribution(
    *,
    packet: dict[str, Any] | None,
    trade: dict[str, Any] | None,
    laboratory_id: str | None,
    attribution: dict[str, Any] | None = None,
    data_dir: str | Path | None = None,
) -> dict[str, Any]:
    """B2 — attribution satisfied or unknown_explicit (never silent empty).

    F&O Lab v1 closes prefer observable underlier/premium evidence
    (``fno_option_attribution``) over equity DAV drivers that are usually empty.
    """
    pkt = packet if isinstance(packet, dict) else {}
    tr = trade if isinstance(trade, dict) else {}
    attr = dict(attribution) if isinstance(attribution, dict) else {}
    payload = dict(attr.get("payload") or {}) if isinstance(attr.get("payload"), dict) else {}
    causal = payload.get("causal_factors") if isinstance(payload.get("causal_factors"), dict) else None

    lab = str(laboratory_id or "").strip().lower()
    strat = str(pkt.get("strategy_tag") or "").strip().lower()
    fno_close = (
        lab in {"india_fno_learner", "fno_learner"}
        or "fno_lab_v1" in strat
        or isinstance(pkt.get("fno_lab_v1"), dict)
    )

    if causal is None and fno_close:
        fno_att = pkt.get("fno_lab_v1") if isinstance(pkt.get("fno_lab_v1"), dict) else {}
        if isinstance(fno_att.get("causal_factors"), dict):
            causal = dict(fno_att["causal_factors"])
            if isinstance(fno_att.get("fno_rt_evidence"), dict):
                payload["fno_rt_evidence"] = fno_att["fno_rt_evidence"]
    if causal is None and fno_close:
        try:
            from atlas.investment.fno_option_attribution import (
                build_fno_rt_evidence,
                evaluate_fno_causal_factors,
            )

            fno_att = pkt.get("fno_lab_v1") if isinstance(pkt.get("fno_lab_v1"), dict) else {}
            entry_pred = (
                pkt.get("entry_prediction")
                if isinstance(pkt.get("entry_prediction"), dict)
                else {}
            )
            expected = pkt.get("expected") if isinstance(pkt.get("expected"), dict) else {}
            dd = data_dir
            if dd is None:
                try:
                    from atlas.config import get_config

                    dd = get_config().paths.data
                except Exception:  # noqa: BLE001
                    dd = None
            evidence = build_fno_rt_evidence(
                underlying=fno_att.get("underlying") or pkt.get("underlying"),
                option_symbol=str(
                    fno_att.get("option_contract") or pkt.get("symbol") or tr.get("symbol") or ""
                )
                or None,
                option_right=fno_att.get("option_type"),
                entry_premium=_f(fno_att.get("entry_ltp") or entry_pred.get("entry_premium")),
                exit_premium=_f(fno_att.get("exit_ltp") or tr.get("price")),
                entry_time=entry_pred.get("entry_time") or entry_pred.get("recorded_at"),
                exit_time=tr.get("created_at") or pkt.get("closed_at"),
                realized_pnl=_f(tr.get("realized_pnl") or fno_att.get("realized_pnl")),
                prediction_error=pkt.get("prediction_error")
                if isinstance(pkt.get("prediction_error"), dict)
                else None,
                data_dir=dd,
                as_of_ist=str(pkt.get("as_of_ist") or "") or None,
                mark_source=str(fno_att.get("mark_source") or pkt.get("mark_source") or "")
                or None,
            )
            if evidence["observables"].get("prediction_error") is None and expected:
                evidence["observables"]["prediction_error"] = {
                    "predicted_er": expected.get("expected_return"),
                    "direction_match": None,
                    "status": expected.get("prediction_status"),
                }
            causal = evaluate_fno_causal_factors(evidence, packet=pkt)
            payload["fno_rt_evidence"] = evidence
        except Exception:  # noqa: BLE001
            causal = None
    if causal is None:
        try:
            from atlas.investment.causal_attribution import evaluate_causal_factors

            pnl = _f(tr.get("realized_pnl"))
            causal = evaluate_causal_factors(
                pkt,
                price_change_pct=None,
                pnl=pnl,
                sector_rel_pct=None,
                news_count=0,
                news_sentiment=None,
            )
        except Exception:  # noqa: BLE001
            causal = None

    if not isinstance(causal, dict):
        causal = {
            "version": VERSION,
            "helped": [],
            "hurt": [],
            "unknown": ["cause"],
            "missing_evidence": ["exit_path_evidence"],
            "narrative": "unknown_explicit — insufficient evidence to label helped/hurt",
            "status": "unknown_explicit",
        }
    else:
        causal = dict(causal)
        st = str(causal.get("status") or "").strip().lower()
        if st in {"evidence_backed", "partial", "attributed"}:
            # Preserve F&O / DAV statuses that already labeled factors.
            if st == "attributed" and not (causal.get("helped") or causal.get("hurt")):
                causal["status"] = "unknown_explicit"
        elif not (causal.get("helped") or causal.get("hurt")):
            causal.setdefault("unknown", ["cause"])
            causal["status"] = "unknown_explicit"
            if not causal.get("narrative"):
                causal["narrative"] = (
                    "unknown_explicit — no helped/hurt factors with durable evidence"
                )
        else:
            causal["status"] = causal.get("status") or "partial"

    payload["causal_factors"] = causal
    attr["payload"] = payload
    attr["status"] = causal.get("status") or "unknown_explicit"
    need = attribution_required_for_close(
        laboratory_id=laboratory_id,
        strategy_tag=str(pkt.get("strategy_tag") or ""),
    )
    attr["required"] = bool(need)
    attr["satisfied"] = True  # satisfied means addressed — incl. unknown_explicit
    return attr


def resolve_related_packet(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    symbol: str,
    as_of_ist: str | None = None,
) -> dict[str, Any] | None:
    """Best-effort: latest buy packet for symbol today, else latest packet."""
    if not data_dir or not symbol:
        return None
    day = as_of_ist or ist_today()
    path = (
        Path(data_dir)
        / "investment"
        / "decisions"
        / "by_day"
        / laboratory_id
        / f"{day}.jsonl"
    )
    if not path.is_file():
        return None
    buys: list[dict[str, Any]] = []
    any_rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            if str(row.get("symbol") or "").upper() != str(symbol).upper():
                continue
            any_rows.append(row)
            if str(row.get("action") or "").lower() == "buy":
                buys.append(row)
    except OSError:
        return None
    if buys:
        return buys[-1]
    return any_rows[-1] if any_rows else None


def build_learning_story(
    *,
    laboratory_id: str,
    symbol: str,
    experience: dict[str, Any] | None,
    packet: dict[str, Any] | None = None,
    trade: dict[str, Any] | None = None,
    as_of_ist: str | None = None,
) -> dict[str, Any]:
    """Seven-step attributed story from an EXPERIENCE + packet context."""
    exp = experience if isinstance(experience, dict) else {}
    pkt = packet if isinstance(packet, dict) else {}
    tr = trade if isinstance(trade, dict) else {}
    predicted = exp.get("predicted") if isinstance(exp.get("predicted"), dict) else {}
    expected = pkt.get("expected") if isinstance(pkt.get("expected"), dict) else {}
    pred_status = str(
        expected.get("prediction_status")
        or (
            "stated"
            if predicted.get("expected_return") is not None
            or predicted.get("expected_direction")
            else "prediction_absent"
        )
    )
    if pred_status not in {"stated", "prediction_absent"}:
        pred_status = "prediction_absent"

    attr = exp.get("attribution") if isinstance(exp.get("attribution"), dict) else {}
    causal = attr.get("causal_factors") if isinstance(attr.get("causal_factors"), dict) else {}
    cause_status = str(
        causal.get("status")
        or attr.get("status")
        or "unknown_explicit"
    )
    if cause_status in {"unknown", "all_unknown"} and not (
        causal.get("helped") or causal.get("hurt")
    ):
        cause_status = "unknown_explicit"
    if cause_status == "partial" and not (
        causal.get("helped") or causal.get("hurt")
    ):
        cause_status = "unknown_explicit"
    # evidence_backed / attributed / partial with labels stay as-is

    contra = contradiction_context_from_packet(pkt)
    belief = str(exp.get("belief_update") or "unchanged")
    if belief.lower() in {"unchanged", ""} and cause_status == "unknown_explicit":
        belief = "unchanged"  # honesty — no fake update

    # Technical stream must not claim fundamental thesis update
    if contra and contra.get("decision_source") == "technical_only":
        if belief.lower() not in {"unchanged", "unreviewed", "candidate"}:
            belief = "unchanged"
        belief_note = (
            "Technical experiment only — fundamental thesis not updated from this P&L."
        )
    else:
        belief_note = None

    pe = exp.get("prediction_error") if isinstance(exp.get("prediction_error"), dict) else {}
    outcome = exp.get("outcome") if isinstance(exp.get("outcome"), dict) else {}
    decision = exp.get("decision") if isinstance(exp.get("decision"), dict) else {}
    alloc = decision.get("allocation") if isinstance(decision.get("allocation"), dict) else {}

    story_id = str(uuid4())
    return {
        "version": VERSION,
        "kind": STORY_KIND,
        "story_id": story_id,
        "experience_id": exp.get("experience_id"),
        "laboratory_id": laboratory_id,
        "symbol": str(symbol or "").upper(),
        "as_of_ist": as_of_ist or ist_today() or exp.get("as_of_ist"),
        "event_kind": exp.get("event_kind"),
        "prediction": {
            "status": pred_status,
            "expected_return": predicted.get("expected_return"),
            "expected_direction": predicted.get("expected_direction"),
            "honesty": (
                "prediction_absent — no decide-time E[R]/direction"
                if pred_status == "prediction_absent"
                else "stated at decide-time"
            ),
        },
        "allocation": alloc or None,
        "outcome": {
            "realized_pnl": outcome.get("realized_pnl") or _f(tr.get("realized_pnl")),
            "realized_return_pct": outcome.get("realized_return_pct"),
            "trade_id": outcome.get("trade_id") or tr.get("id") or tr.get("trade_id"),
        },
        "error": pe,
        "cause": {
            "status": cause_status,
            "helped": list(causal.get("helped") or []),
            "hurt": list(causal.get("hurt") or []),
            "unknown": list(causal.get("unknown") or []),
            "narrative": causal.get("narrative"),
        },
        "belief_update": belief,
        "belief_note": belief_note,
        "next_decision_change": "none_stated",
        "contradiction_context": contra,
        "lessons": exp.get("lessons"),
        "honesty": (
            "Learning story required for qualifying closes only. "
            "Missing prediction stays prediction_absent; missing cause stays unknown_explicit."
        ),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


def record_learning_story_for_close(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    symbol: str,
    experience: dict[str, Any],
    packet: dict[str, Any] | None = None,
    trade: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist LEARNING_STORY when close qualifies; else explicit skip."""
    exp = experience if isinstance(experience, dict) else {}
    if not is_qualifying_close(
        event_kind=str(exp.get("event_kind") or ""),
        action=str((exp.get("decision") or {}).get("action") or ""),
        strategy_tag=str((exp.get("context") or {}).get("strategy_tag") or ""),
        trade=trade,
    ):
        return {
            "ok": True,
            "skipped": True,
            "reason": "no_qualifying_close",
            "honesty": "no qualifying learning story today (no vanity metric)",
        }
    story = build_learning_story(
        laboratory_id=laboratory_id,
        symbol=symbol,
        experience=exp,
        packet=packet,
        trade=trade,
        as_of_ist=str(exp.get("as_of_ist") or ist_today()),
    )
    result = record_learning_event(data_dir, story)
    result["story_id"] = story.get("story_id")
    result["skipped"] = False
    return result


def summarize_learning_stories(events: list[dict[str, Any]] | None) -> dict[str, Any]:
    rows = [e for e in (events or []) if isinstance(e, dict) and e.get("kind") == STORY_KIND]
    absent = sum(
        1
        for r in rows
        if str((r.get("prediction") or {}).get("status") or "") == "prediction_absent"
    )
    unk = sum(
        1
        for r in rows
        if str((r.get("cause") or {}).get("status") or "") == "unknown_explicit"
    )
    partial = sum(
        1
        for r in rows
        if str((r.get("cause") or {}).get("status") or "") == "partial"
    )
    backed = sum(
        1
        for r in rows
        if str((r.get("cause") or {}).get("status") or "") == "evidence_backed"
    )
    return {
        "stories": len(rows),
        "prediction_absent": absent,
        "unknown_explicit_cause": unk,
        "partial_cause": partial,
        "evidence_backed_cause": backed,
        "latest": rows[-1] if rows else None,
    }


def format_learning_story_lines(
    events: list[dict[str, Any]] | None,
    *,
    limit: int = 3,
) -> list[str]:
    """Evening: stories when closes exist; else honest none."""
    summary = summarize_learning_stories(events)
    lines = ["", "── Learning stories (OI-CU0 CU.B) ──"]
    n = int(summary.get("stories") or 0)
    if n == 0:
        lines.append(
            "  no qualifying learning story today "
            "(no vanity metric — need a close with attribution pass)"
        )
        return lines
    lines.append(
        f"  stories={n} · prediction_absent={summary.get('prediction_absent', 0)} · "
        f"unknown_explicit_cause={summary.get('unknown_explicit_cause', 0)}"
    )
    for row in [e for e in (events or []) if isinstance(e, dict) and e.get("kind") == STORY_KIND][
        -max(1, limit) :
    ]:
        pred = row.get("prediction") if isinstance(row.get("prediction"), dict) else {}
        cause = row.get("cause") if isinstance(row.get("cause"), dict) else {}
        out = row.get("outcome") if isinstance(row.get("outcome"), dict) else {}
        pnl = out.get("realized_pnl")
        pnl_s = f"{float(pnl):+.2f}" if pnl is not None else "—"
        contra = row.get("contradiction_context")
        extra = ""
        if isinstance(contra, dict) and contra.get("decision_source") == "technical_only":
            extra = " · technical_only experiment"
        lines.append(
            f"  · {row.get('symbol')}: pred={pred.get('status')} "
            f"pnl={pnl_s} cause={cause.get('status')} "
            f"belief={row.get('belief_update')}{extra}"
        )
    lines.append(
        "  Honesty: technical P&L does not rewrite fundamental thesis; "
        "unknown cause stays unknown_explicit."
    )
    return lines
