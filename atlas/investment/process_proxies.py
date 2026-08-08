"""DI.5 — Process proxies (Atlas has no emotions; track process instead).

Locked map (human idea → Atlas proxy):

| Human idea         | Atlas proxy                                              |
|--------------------|----------------------------------------------------------|
| FOMO               | Buy after ≥X% gap without plan rank                      |
| Revenge            | Re-entry same symbol within Y hours after a loss         |
| Hesitation         | Missed plan candidates / signal→no-fill                  |
| Plan violation     | Fill outside daily plan without logged alt reason        |
| Overconfidence     | Size at ceiling despite low investment_confidence        |
| Journal completion | Packet completeness / reasons / revisit hygiene          |

Never invent psychology — only countable process events.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_log = logging.getLogger("atlas.investment.process_proxies")

VERSION = "di.process.1"
STORE_REL = Path("investment") / "decisions" / "process_proxies"
_IST = ZoneInfo("Asia/Kolkata")

# Tunables (operator-facing; keep conservative)
FOMO_GAP_PCT = 3.0
REVENGE_HOURS = 24.0
LOW_CONFIDENCE = frozenset({"very_low", "low"})
JOURNAL_COMPLETENESS_OK = 0.55

PROXY_KEYS = (
    "fomo",
    "revenge",
    "hesitation",
    "plan_violation",
    "overconfidence",
    "journal_incomplete",
)

PROXY_LABELS = {
    "fomo": "FOMO proxy — buy after gap without plan rank",
    "revenge": "Revenge proxy — re-entry after recent loss",
    "hesitation": "Hesitation proxy — missed plan / signal no-fill",
    "plan_violation": "Plan violation — fill outside plan without alt reason",
    "overconfidence": "Overconfidence proxy — full size at low confidence",
    "journal_incomplete": "Journal incomplete — thin packet / missing reasons",
}


def _f(x: Any) -> float | None:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _sym(x: Any) -> str:
    return str(x or "").strip().upper()


def gap_pct_from_bars(
    bars: list[dict[str, Any]] | None, cursor: int | None = None
) -> float | None:
    """Day-open style gap: prior bar close → current open/close, in percent."""
    if not bars or len(bars) < 2:
        return None
    i = int(cursor) if cursor is not None else len(bars) - 1
    i = max(1, min(i, len(bars) - 1))
    prev = bars[i - 1]
    cur = bars[i]
    prev_close = _f(prev.get("close") if isinstance(prev, dict) else None)
    cur_open = _f(
        (cur.get("open") if isinstance(cur, dict) else None)
        or (cur.get("close") if isinstance(cur, dict) else None)
    )
    if prev_close is None or cur_open is None or prev_close == 0:
        return None
    return round(100.0 * (cur_open - prev_close) / prev_close, 3)


def plan_index(plan: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """symbol → candidate row (rank, suggested_notional, …)."""
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(plan, dict):
        return out
    for c in plan.get("candidates") or []:
        if not isinstance(c, dict) or not c.get("symbol"):
            continue
        out[_sym(c["symbol"])] = c
    return out


def recent_loss_symbols(
    trades: list[dict[str, Any]] | None,
    *,
    within_hours: float = REVENGE_HOURS,
    now: datetime | None = None,
) -> set[str]:
    """Symbols with a closed sell (or explicit loss) inside the revenge window."""
    now = now or datetime.now(_IST)
    cutoff = now - timedelta(hours=float(within_hours))
    lost: set[str] = set()
    for t in trades or []:
        if not isinstance(t, dict):
            continue
        side = str(t.get("side") or "").lower()
        if side not in {"sell", "exit"}:
            continue
        pnl = _f(t.get("pnl") if t.get("pnl") is not None else t.get("realized_pnl"))
        if pnl is None or pnl >= 0:
            continue
        ts_raw = t.get("ts") or t.get("created_at") or t.get("filled_at")
        if ts_raw:
            try:
                ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=_IST)
                if ts.astimezone(_IST) < cutoff:
                    continue
            except Exception:  # noqa: BLE001
                pass
        lost.add(_sym(t.get("symbol")))
    return {s for s in lost if s}


def detect_packet_flags(
    packet: dict[str, Any],
    *,
    plan: dict[str, Any] | None = None,
    recent_losses: set[str] | None = None,
    gap_pct: float | None = None,
    fomo_gap_pct: float = FOMO_GAP_PCT,
) -> list[dict[str, Any]]:
    """Return process-proxy flags for one Decision Packet (may be empty)."""
    if not isinstance(packet, dict):
        return []
    action = str(packet.get("action") or "").lower()
    sym = _sym(packet.get("symbol"))
    flags: list[dict[str, Any]] = []
    plan_link = packet.get("plan_link") if isinstance(packet.get("plan_link"), dict) else {}
    in_plan = bool(plan_link.get("in_daily_plan"))
    rank = plan_link.get("rank")
    if rank is None and plan:
        cand = plan_index(plan).get(sym)
        if cand:
            in_plan = True
            rank = cand.get("rank")
    prices = packet.get("prices") if isinstance(packet.get("prices"), dict) else {}
    gap = gap_pct if gap_pct is not None else _f(prices.get("gap_pct"))
    score = (
        packet.get("investment_score")
        if isinstance(packet.get("investment_score"), dict)
        else {}
    )
    inv_conf = str(
        score.get("investment_confidence")
        or (score.get("axes") or {}).get("investment_confidence")
        or ""
    ).lower()
    gates = packet.get("gates") if isinstance(packet.get("gates"), dict) else {}
    pg = gates.get("portfolio") if isinstance(gates.get("portfolio"), dict) else {}
    tag = str(packet.get("strategy_tag") or "")
    reasons = [str(r).lower() for r in (packet.get("reasons_for") or [])]
    against = [str(r).lower() for r in (packet.get("reasons_against") or [])]
    completeness = float((packet.get("meta") or {}).get("completeness") or 0.0)

    # --- FOMO ---
    if action == "buy" and gap is not None and abs(gap) >= float(fomo_gap_pct):
        if not in_plan or rank is None:
            flags.append(
                {
                    "proxy": "fomo",
                    "severity": abs(gap) / max(float(fomo_gap_pct), 0.1),
                    "detail": (
                        f"buy after {gap}% gap without plan rank "
                        f"(in_plan={in_plan}, rank={rank})"
                    ),
                    "gap_pct": gap,
                }
            )

    # --- Revenge ---
    if action == "buy" and sym and recent_losses and sym in recent_losses:
        flags.append(
            {
                "proxy": "revenge",
                "severity": 1.0,
                "detail": f"re-entry {sym} within {REVENGE_HOURS}h of a loss",
            }
        )

    # --- Plan violation ---
    exempt_tags = {
        "plan_watch",
        "plan_hold",
        "research_forced_hold",
        "policy_block",
        "session_closed",
        "capability_gap",
        "portfolio_trim",
    }
    if action == "buy" and not in_plan and tag not in exempt_tags:
        alt_ok = tag == "next_alternative" and (
            any("alt" in r or "alternative" in r for r in reasons)
            or bool(plan_link.get("as_alt"))
        )
        if not alt_ok:
            flags.append(
                {
                    "proxy": "plan_violation",
                    "severity": 1.0,
                    "detail": f"buy {sym} outside daily plan (tag={tag or '?'})",
                }
            )

    # --- Overconfidence ---
    if action == "buy" and inv_conf in LOW_CONFIDENCE:
        at_ceiling = False
        if gates.get("trimmed_from") is None and pg.get("allowed") is True:
            binding = str(
                gates.get("binding")
                or (pg.get("trim") or {}).get("binding")
                or ""
            )
            if binding in {"max_name", "max_sector", "max_exposure", "name", "sector"}:
                at_ceiling = True
            sq = _f(prices.get("suggested_qty"))
            fq = _f(prices.get("filled_qty"))
            if sq is not None and fq is not None and fq >= sq * 0.95:
                at_ceiling = True
        if at_ceiling:
            flags.append(
                {
                    "proxy": "overconfidence",
                    "severity": 1.0,
                    "detail": (
                        f"full/near-full size with investment_confidence={inv_conf}"
                    ),
                }
            )

    # --- Journal incomplete (packet hygiene) ---
    # Hold/watch with a reason is still a valid decision journal; only flag thin
    # completeness or buys/sells missing any rationale.
    if action in {"buy", "sell"}:
        thin = completeness < JOURNAL_COMPLETENESS_OK
        no_reasons = not reasons and not against
        if thin or no_reasons:
            flags.append(
                {
                    "proxy": "journal_incomplete",
                    "severity": 1.0 - completeness,
                    "detail": (
                        f"completeness={completeness:.2f}"
                        + ("; missing reasons" if no_reasons else "")
                    ),
                }
            )
    elif action in {"hold", "watch"} and completeness < 0.25 and not reasons and not against:
        flags.append(
            {
                "proxy": "journal_incomplete",
                "severity": 1.0 - completeness,
                "detail": f"empty hold/watch journal completeness={completeness:.2f}",
            }
        )

    return flags


def build_process_scorecard(
    *,
    portfolio_key: str = "india_equity_learner",
    ist_date: str | None = None,
    packets: list[dict[str, Any]] | None = None,
    plan: dict[str, Any] | None = None,
    trades: list[dict[str, Any]] | None = None,
    kpis: dict[str, Any] | None = None,
    evolution: dict[str, Any] | None = None,
    data_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Day-level process scorecard + hesitation from plan→fill fidelity."""
    pkt_list = [p for p in (packets or []) if isinstance(p, dict)]
    kpis = kpis if isinstance(kpis, dict) else {}
    evo = evolution if isinstance(evolution, dict) else {}
    losses = recent_loss_symbols(trades)
    counts: Counter[str] = Counter()
    events: list[dict[str, Any]] = []

    for p in pkt_list:
        flags = list((p.get("meta") or {}).get("process_flags") or [])
        if not flags:
            flags = detect_packet_flags(p, plan=plan, recent_losses=losses)
        for fl in flags:
            if not isinstance(fl, dict):
                continue
            key = str(fl.get("proxy") or "")
            if key not in PROXY_KEYS:
                continue
            counts[key] += 1
            events.append(
                {
                    "proxy": key,
                    "symbol": p.get("symbol"),
                    "decision_id": p.get("decision_id"),
                    "action": p.get("action"),
                    "detail": fl.get("detail"),
                }
            )

    planned = int(kpis.get("candidates_planned") or 0)
    filled = int(kpis.get("candidates_filled") or 0)
    fill_rate = kpis.get("plan_fill_rate")
    hesitation_missed = max(0, planned - filled)
    if planned >= 2 and fill_rate is not None and float(fill_rate) < 0.5:
        counts["hesitation"] += hesitation_missed or 1
        events.append(
            {
                "proxy": "hesitation",
                "symbol": None,
                "decision_id": None,
                "action": "day",
                "detail": (
                    f"plan fill {filled}/{planned} "
                    f"(rate={fill_rate}) — missed candidates"
                ),
            }
        )
    elif (
        hesitation_missed > 0
        and planned >= 1
        and filled == 0
        and int(kpis.get("fills_today") or 0) == 0
    ):
        top = kpis.get("top_no_fill_reasons") or []
        if top:
            counts["hesitation"] += 1
            events.append(
                {
                    "proxy": "hesitation",
                    "symbol": None,
                    "decision_id": None,
                    "action": "day",
                    "detail": f"0 fills with {planned} planned; reasons={top[:3]}",
                }
            )

    comps = [
        float((p.get("meta") or {}).get("completeness") or 0)
        for p in pkt_list
        if isinstance(p.get("meta"), dict)
    ]
    avg_comp = round(sum(comps) / len(comps), 3) if comps else None
    with_reasons = sum(
        1
        for p in pkt_list
        if (p.get("reasons_for") or p.get("reasons_against"))
    )
    reason_rate = round(with_reasons / len(pkt_list), 4) if pkt_list else None
    pending = evo.get("pending_revisits")
    done = evo.get("done_revisits")
    revisit_done_rate = None
    if isinstance(pending, (int, float)) and isinstance(done, (int, float)):
        tot = pending + done
        revisit_done_rate = round(done / tot, 4) if tot else None

    journal_completion_pct = None
    if avg_comp is not None and reason_rate is not None:
        journal_completion_pct = round(
            100.0 * (0.6 * avg_comp + 0.4 * reason_rate), 1
        )

    penalty = (
        counts["fomo"] * 1.5
        + counts["revenge"] * 2.0
        + counts["plan_violation"] * 1.5
        + counts["overconfidence"] * 1.0
        + counts["hesitation"] * 0.5
        + counts["journal_incomplete"] * 0.3
    )
    process_score = round(max(0.0, min(10.0, 10.0 - penalty)), 1)

    doc: dict[str, Any] = {
        "version": VERSION,
        "portfolio_key": portfolio_key,
        "ist_date": ist_date,
        "counts": {k: int(counts.get(k, 0)) for k in PROXY_KEYS},
        "events": events[:40],
        "event_count": len(events),
        "process_score": process_score,
        "journal_completion_pct": journal_completion_pct,
        "avg_packet_completeness": avg_comp,
        "reason_coverage": reason_rate,
        "revisit_done_rate": revisit_done_rate,
        "thresholds": {
            "fomo_gap_pct": FOMO_GAP_PCT,
            "revenge_hours": REVENGE_HOURS,
            "journal_completeness_ok": JOURNAL_COMPLETENESS_OK,
        },
        "labels": dict(PROXY_LABELS),
        "honesty": (
            "These are process proxies — Atlas has no emotions. "
            "Flags are countable events, not diagnoses."
        ),
    }
    if data_dir and ist_date:
        try:
            path = (
                Path(data_dir)
                / STORE_REL
                / portfolio_key.replace("/", "_")
                / f"{ist_date}.json"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8"
            )
            doc["mirror_path"] = str(path)
        except Exception:  # noqa: BLE001
            _log.debug("process scorecard mirror failed", exc_info=True)
    return doc


def format_process_proxies_section(doc: dict[str, Any] | None) -> list[str]:
    if not isinstance(doc, dict) or not doc.get("counts"):
        return []
    lines = ["", "Process proxies (DI.5 — no emotions, countable process):"]
    lines.append(
        f"  Score {doc.get('process_score')}/10 · "
        f"journal {doc.get('journal_completion_pct')}% · "
        f"events {doc.get('event_count', 0)}"
    )
    counts = doc.get("counts") or {}
    bits = [f"{k}={counts.get(k, 0)}" for k in PROXY_KEYS if counts.get(k)]
    if bits:
        lines.append("  Flags: " + " · ".join(bits))
    else:
        lines.append("  Flags: none — clean process day (or no packets yet)")
    for ev in (doc.get("events") or [])[:5]:
        if isinstance(ev, dict):
            lines.append(
                f"    · {ev.get('proxy')}: {ev.get('symbol') or 'day'} — "
                f"{(ev.get('detail') or '')[:90]}"
            )
    return lines


def collect_process_scorecard(
    *,
    data_dir: str | Path | None,
    portfolio_key: str = "india_equity_learner",
    portfolio: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
    ist_date: str | None = None,
) -> dict[str, Any]:
    """Best-effort load packets/plan/kpis and build scorecard (API / evening)."""
    from atlas.investment.decision_packets import DecisionPacketStore, ist_today
    from atlas.investment.decision_timeline import DecisionTimelineStore
    from atlas.investment.trading_kpis import load_day_kpis

    day = ist_date or ist_today()
    port = portfolio if isinstance(portfolio, dict) else {}
    kpis = port.get("kpis") if isinstance(port.get("kpis"), dict) else {}
    if not kpis and data_dir:
        kpis = load_day_kpis(
            data_dir, portfolio_key=portfolio_key, ist_date=day
        ).get("kpis") or {}

    plan_doc = plan
    if plan_doc is None:
        try:
            from atlas.investment import watchlists as wl

            snap = wl.latest("market_intelligence")
            if isinstance(snap, dict):
                plan_doc = (snap.get("extra") or {}).get("daily_plan") or snap.get(
                    "daily_plan"
                )
        except Exception:  # noqa: BLE001
            plan_doc = None

    packets: list[dict[str, Any]] = []
    try:
        pstore = DecisionPacketStore(data_dir=data_dir)
        packets = pstore.list_day(portfolio_key=portfolio_key, ts_ist=day, limit=200)
    except Exception:  # noqa: BLE001
        _log.debug("process proxies packets load failed", exc_info=True)

    evolution: dict[str, Any] = dict(port.get("evolution") or {})
    try:
        tstore = DecisionTimelineStore(data_dir=data_dir)
        evolution = tstore.learning_counts(portfolio_key=portfolio_key) or evolution
    except Exception:  # noqa: BLE001
        pass

    trades = list(port.get("recent_trades") or [])

    return build_process_scorecard(
        portfolio_key=portfolio_key,
        ist_date=day,
        packets=packets,
        plan=plan_doc if isinstance(plan_doc, dict) else None,
        trades=trades,
        kpis=kpis,
        evolution=evolution,
        data_dir=data_dir,
    )
