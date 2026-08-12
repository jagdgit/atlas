"""OI-EXP0 / OI-RLD0 — Experience Integrity.

Decision evaluations ≠ unique decision states ≠ trading experiences.

Prevents repeated identical HOLD / switch_blocked packets from inflating
packet counts, Atlas IQ, and “learning” metrics. Never invents outcomes.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "exp.integrity.v2"
_IST = ZoneInfo("Asia/Kolkata")

# Routine holds that are checks, not independent investment decisions
ROUTINE_HOLD_TAGS = frozenset(
    {
        "engine_hold",
        "capability_gap",
        "policy_block",
        "switch_blocked_cold_start",
        "switch_blocked_missing_er",
        "switch_blocked_research",
        "switch_blocked_no_mark",
        "switch_blocked_costs",
        "switch_blocked_plc_a",
        "hold_incumbent",
    }
)


def ist_day(now: datetime | None = None) -> str:
    dt = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_IST).date().isoformat()


def classify_experience_kind(
    *,
    action: str | None,
    strategy_tag: str | None = None,
    trigger: str | None = None,
) -> str:
    """Classify a packet / attribution / timeline event for integrity metrics."""
    act = str(action or "").strip().lower()
    tag = str(strategy_tag or "").strip().lower()
    trig = str(trigger or "").strip().lower()
    if trig == "revisit":
        return "revisit"
    if act in {"buy", "sell"}:
        return "investment_decision"
    if tag.startswith("switch_blocked") or tag in ROUTINE_HOLD_TAGS or act == "hold":
        return "hold_review"
    if act in {"watch", "observe"}:
        return "observation"
    return "hold_review" if act else "observation"


def fingerprint(
    *,
    portfolio_key: str,
    symbol: str,
    action: str,
    strategy_tag: str,
    ist_day_s: str | None = None,
    reason_code: str | None = None,
) -> str:
    """Stable id for one routine check per symbol/day/reason."""
    day = ist_day_s or ist_day()
    raw = "|".join(
        [
            str(portfolio_key or ""),
            str(symbol or "").upper(),
            str(action or "").lower(),
            str(strategy_tag or "").lower(),
            str(reason_code or strategy_tag or "").lower(),
            day,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def is_routine_hold(*, action: str | None, strategy_tag: str | None) -> bool:
    act = str(action or "").strip().lower()
    tag = str(strategy_tag or "").strip().lower()
    if act in {"buy", "sell"}:
        return False
    if tag.startswith("switch_blocked") or tag in ROUTINE_HOLD_TAGS:
        return True
    return act == "hold"


def should_record_packet(
    existing: list[dict[str, Any]] | None,
    *,
    portfolio_key: str,
    symbol: str,
    action: str,
    strategy_tag: str,
    reason_code: str | None = None,
    ist_day_s: str | None = None,
) -> tuple[bool, str]:
    """Return (record?, skip_reason). Buys/sells always record."""
    if not is_routine_hold(action=action, strategy_tag=strategy_tag):
        return True, "material_or_trade"
    day = ist_day_s or ist_day()
    fp = fingerprint(
        portfolio_key=portfolio_key,
        symbol=symbol,
        action=action,
        strategy_tag=strategy_tag,
        ist_day_s=day,
        reason_code=reason_code,
    )
    for row in existing or []:
        if not isinstance(row, dict):
            continue
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        if meta.get("experience_fingerprint") == fp:
            return False, "duplicate_routine_hold_same_day"
        if (
            str(row.get("symbol") or "").upper() == str(symbol or "").upper()
            and str(row.get("action") or "").lower() == str(action or "").lower()
            and str(row.get("strategy_tag") or "").lower()
            == str(strategy_tag or "").lower()
            and str(meta.get("ist_day") or row.get("ts_ist") or "")[:10] == day
        ):
            return False, "duplicate_routine_hold_same_day"
    return True, "first_routine_hold_today"


def _primary_reason(packet: dict[str, Any]) -> str:
    meta = packet.get("meta") if isinstance(packet.get("meta"), dict) else {}
    for key in ("reason_code", "primary_reason", "block_reason"):
        val = meta.get(key)
        if val:
            return str(val).strip().lower()[:120]
    against = packet.get("reasons_against") or []
    if isinstance(against, list) and against:
        return str(against[0]).strip().lower()[:120]
    for_ = packet.get("reasons_for") or []
    if isinstance(for_, list) and for_:
        return str(for_[0]).strip().lower()[:120]
    return str(packet.get("strategy_tag") or "").strip().lower()[:120]


def material_decision_state(packet: dict[str, Any]) -> str:
    """Collapse routine HOLD spam: same action+tag+reason = one state (any symbol).

    Buys/sells keep symbol so each fill decision stays distinct.
    """
    act = str(packet.get("action") or "").strip().lower()
    tag = str(packet.get("strategy_tag") or "").strip().lower()
    reason = _primary_reason(packet) or tag
    if act in {"buy", "sell"}:
        sym = str(packet.get("symbol") or "").upper()
        return f"{act}|{sym}|{tag}|{reason}"
    return f"{act}|{tag}|{reason}"


def build_experience_metrics(
    *,
    packets: list[dict[str, Any]] | None = None,
    attributions: list[dict[str, Any]] | None = None,
    observations: list[dict[str, Any]] | None = None,
    evolution: dict[str, Any] | None = None,
    positions: list[dict[str, Any]] | None = None,
    fills_buy: int | None = None,
    fills_sell: int | None = None,
) -> dict[str, Any]:
    """Operator-facing experience counts (not activity vanity).

    Permanent RLD.1 split:
      decision_evaluations → unique_decision_states → trading_experiences
    """
    pkts = [p for p in (packets or []) if isinstance(p, dict)]
    attrs = [a for a in (attributions or []) if isinstance(a, dict)]
    obs = [o for o in (observations or []) if isinstance(o, dict)]
    evo = evolution if isinstance(evolution, dict) else {}
    pos = [p for p in (positions or []) if isinstance(p, dict)]

    open_syms = {
        str(p.get("symbol") or "").upper()
        for p in pos
        if float(p.get("qty") or p.get("quantity") or p.get("shares") or 0) > 0
        and p.get("symbol")
    }

    buys = [p for p in pkts if str(p.get("action") or "").lower() == "buy"]
    sells = [p for p in pkts if str(p.get("action") or "").lower() == "sell"]
    holds = [
        p
        for p in pkts
        if str(p.get("action") or "").lower() in {"hold", "watch"}
    ]
    routine = [
        p
        for p in holds
        if is_routine_hold(
            action=p.get("action"), strategy_tag=str(p.get("strategy_tag") or "")
        )
    ]
    unique_buy_ids = {
        str(p.get("decision_id") or "") for p in buys if p.get("decision_id")
    }
    unique_sell_ids = {
        str(p.get("decision_id") or "") for p in sells if p.get("decision_id")
    }
    hold_fps: set[str] = set()
    for p in holds:
        meta = p.get("meta") if isinstance(p.get("meta"), dict) else {}
        fp = meta.get("experience_fingerprint")
        if fp:
            hold_fps.add(str(fp))
        else:
            hold_fps.add(
                fingerprint(
                    portfolio_key=str(p.get("portfolio_key") or ""),
                    symbol=str(p.get("symbol") or ""),
                    action=str(p.get("action") or "hold").lower(),
                    strategy_tag=str(p.get("strategy_tag") or ""),
                    ist_day_s=str(meta.get("ist_day") or p.get("ts_ist") or "")[:10]
                    or ist_day(),
                    reason_code=_primary_reason(p),
                )
            )

    unique_states = {material_decision_state(p) for p in pkts}

    meaningful_changes = 0
    for a in attrs:
        trig = str(a.get("trigger") or "").lower()
        if trig in {"exit", "manual"}:
            meaningful_changes += 1
        grades = a.get("grades") if isinstance(a.get("grades"), dict) else {}
        if str(grades.get("thesis_correct") or "").lower() in {"no", "broken"}:
            meaningful_changes += 1

    closed_trades = sum(
        1 for a in attrs if str(a.get("trigger") or "").lower() == "exit"
    )
    attributed_with_causes = 0
    attributed_all_unknown = 0
    for a in attrs:
        payload = a.get("payload") if isinstance(a.get("payload"), dict) else {}
        causal = payload.get("causal_factors")
        if not isinstance(causal, dict):
            continue
        helped = causal.get("helped") or []
        hurt = causal.get("hurt") or []
        unknown = causal.get("unknown") or []
        if helped or hurt:
            attributed_with_causes += 1
        elif unknown and not helped and not hurt:
            attributed_all_unknown += 1

    done_rev = int(evo.get("done_revisits") or 0)
    pending_rev = int(evo.get("pending_revisits") or 0)

    packet_n = len(pkts)
    unique_checks = len(hold_fps)
    unique_state_n = len(unique_states)
    trading_experiences = attributed_with_causes
    activity_inflation = None
    if packet_n > 0:
        activity_inflation = round(1.0 - (unique_state_n / packet_n), 3)

    fb = int(fills_buy) if fills_buy is not None else len(unique_buy_ids)
    fs = int(fills_sell) if fills_sell is not None else len(unique_sell_ids)
    actual_fills = fb + fs

    return {
        "version": VERSION,
        # RLD.1 — three-tier truth table
        "decision_evaluations": packet_n,
        "unique_decision_states": unique_state_n,
        "trading_experiences": trading_experiences,
        "actual_fills": actual_fills,
        "fills_buy": fb,
        "fills_sell": fs,
        "revisits": done_rev,
        "attributed_trade_outcomes": attributed_with_causes,
        "attributed_all_unknown": attributed_all_unknown,
        # Compat / detail
        "unique_investment_decisions": len(unique_buy_ids) + len(unique_sell_ids),
        "unique_buys": len(unique_buy_ids),
        "unique_sells": len(unique_sell_ids),
        "open_positions": len(open_syms),
        "meaningful_decision_changes": meaningful_changes,
        "revisits_done": done_rev,
        "revisits_pending": pending_rev,
        "observations": len(obs),
        "closed_trades": closed_trades,
        "attributed_outcomes_with_causes": attributed_with_causes,
        "attribution_records": len(attrs),
        "packets_raw": packet_n,
        "hold_packets_raw": len(holds),
        "routine_hold_packets": len(routine),
        "unique_hold_checks": unique_checks,
        "independent_experiments": closed_trades,
        "activity_inflation_ratio": activity_inflation,
        "honesty": (
            "Decision evaluations ≠ unique decision states ≠ trading experiences. "
            "Packets/HOLDs are activity; learning requires outcome + attribution."
        ),
    }


def build_maturity_split(
    *,
    experience_metrics: dict[str, Any] | None = None,
    system_score: float | None = None,
    genealogy_pct: float | None = None,
    readiness_grade: str | None = None,
    durable_bars_ok: bool | None = None,
) -> dict[str, Any]:
    """Split System Maturity vs Trading Evidence Maturity (operator honesty).

    Atlas IQ / process scores measure system maturity — not trading edge.
    """
    exp = experience_metrics if isinstance(experience_metrics, dict) else {}
    closed = int(exp.get("closed_trades") or 0)
    with_causes = int(
        exp.get("attributed_trade_outcomes")
        or exp.get("attributed_outcomes_with_causes")
        or 0
    )
    all_unk = int(exp.get("attributed_all_unknown") or 0)
    trading_xp = int(exp.get("trading_experiences") or 0)
    fills = int(exp.get("actual_fills") or 0)
    gene = float(genealogy_pct) if genealogy_pct is not None else 0.0

    # Trading evidence: starts near zero until closed + attributed outcomes exist.
    trade_bits = [
        min(40.0, closed * 10.0),
        min(30.0, with_causes * 10.0),
        min(15.0, trading_xp * 5.0),
        min(15.0, gene * 0.15),
    ]
    trading = round(sum(trade_bits), 1)
    if closed == 0 and fills == 0:
        trading = min(trading, 5.0)

    system = round(float(system_score), 1) if system_score is not None else None

    if with_causes == 0 and all_unk > 0:
        attr_label = "low (all-unknown)"
    elif with_causes > 0:
        attr_label = "emerging" if with_causes < 5 else "forming"
    else:
        attr_label = "insufficient"

    strategy_label = (
        "insufficient"
        if closed < 3
        else ("thin sample" if closed < 20 else "measurable")
    )
    data_label = readiness_grade or ("B+" if durable_bars_ok else "unknown")

    return {
        "version": "rld.maturity.v1",
        "system_maturity": system,
        "trading_evidence_maturity": trading,
        "strategy_evidence": strategy_label,
        "attribution_maturity": attr_label,
        "data_readiness": data_label,
        "counts": {
            "closed_trades": closed,
            "attributed_with_causes": with_causes,
            "attributed_all_unknown": all_unk,
            "trading_experiences": trading_xp,
            "genealogy_pct": genealogy_pct,
        },
        "honesty": (
            "System Maturity ≠ Trading Evidence. IQ/process rises with coverage "
            "and revisit plumbing; trading evidence needs closed outcomes + "
            "helped/hurt causes — not packet volume."
        ),
    }


def format_experience_metrics_lines(doc: dict[str, Any] | None) -> list[str]:
    lines = ["", "── Learning dataset truth (not activity vanity) ──"]
    if not isinstance(doc, dict):
        lines.append("  (metrics unavailable)")
        return lines
    lines.extend(
        [
            f"  Decision evaluations:       {doc.get('decision_evaluations', doc.get('packets_raw', 0))}",
            f"  Unique decision states:     {doc.get('unique_decision_states', '—')}",
            f"  Revisits completed:         {doc.get('revisits', doc.get('revisits_done', 0))}",
            f"  Actual fills:               {doc.get('actual_fills', 0)}"
            f" (buys={doc.get('fills_buy', 0)} sells={doc.get('fills_sell', 0)})",
            f"  Closed trades:              {doc.get('closed_trades', 0)}",
            f"  Attributed trade outcomes:  {doc.get('attributed_trade_outcomes', 0)}"
            f" (all-unknown={doc.get('attributed_all_unknown', 0)})",
            f"  Trading experiences:        {doc.get('trading_experiences', 0)}"
            f"  ← decision → outcome → causes",
            f"  Open positions under watch: {doc.get('open_positions', '—')}",
            f"  Observations: {doc.get('observations', 0)} · "
            f"attribution records: {doc.get('attribution_records', 0)}",
            f"  Per-symbol hold checks (deduped): {doc.get('unique_hold_checks', 0)} · "
            f"routine hold packets raw: {doc.get('routine_hold_packets', 0)}",
        ]
    )
    infl = doc.get("activity_inflation_ratio")
    if infl is not None and float(infl) > 0.3:
        lines.append(
            f"  ⚠ Activity inflation ~{100 * float(infl):.0f}% — "
            "repeated HOLDs must not be read as independent learning"
        )
    lines.append(f"  Honesty: {doc.get('honesty')}")
    return lines


def experience_quality_score(doc: dict[str, Any] | None) -> float | None:
    """0–100 proxy for IQ: evidence of real learning, not packet spam."""
    if not isinstance(doc, dict):
        return None
    score = 15.0
    score += min(25.0, 5.0 * float(doc.get("unique_investment_decisions") or 0))
    score += min(15.0, 3.0 * float(doc.get("revisits_done") or 0))
    score += min(15.0, 5.0 * float(doc.get("attributed_outcomes_with_causes") or 0))
    score += min(15.0, 5.0 * float(doc.get("closed_trades") or 0))
    score += min(10.0, 1.0 * float(doc.get("observations") or 0))
    # Prefer unique states over raw packets when scoring inflation
    infl = doc.get("activity_inflation_ratio")
    if infl is not None and float(infl) > 0.5:
        score -= min(20.0, 40.0 * float(infl))
    # Trading experiences are the only true learning units
    te = float(doc.get("trading_experiences") or 0)
    if te == 0 and float(doc.get("decision_evaluations") or 0) > 20:
        score -= 10.0
    return round(max(0.0, min(100.0, score)), 1)
