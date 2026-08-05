"""DI.3 — Staged KPI dashboards (D1–D6) with sample-size gates.

Gates (locked): hide edge metrics &lt;30 closed · provisional 30–99 · usable
100–299 · trusted ≥300. **Never mix strategy tags** — each tag is its own lane.

Stage 1 ships always (book/process honesty). Edge stats (win rate, PF, …)
appear only when the lane clears the gate. Stage 3 (Sharpe etc.) stays gated
at trusted (≥300) and is stubbed until enough exits exist.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

_log = logging.getLogger("atlas.investment.di_dashboards")

VERSION = "di.dashboard.1"
STORE_REL = Path("investment") / "decisions" / "dashboards"

# Closed attributable decisions per strategy_tag
GATE_HIDDEN_MAX = 29
GATE_PROVISIONAL_MAX = 99
GATE_USABLE_MAX = 299


def sample_tier(n_closed: int) -> str:
    n = max(0, int(n_closed or 0))
    if n <= GATE_HIDDEN_MAX:
        return "hidden"
    if n <= GATE_PROVISIONAL_MAX:
        return "provisional"
    if n <= GATE_USABLE_MAX:
        return "usable"
    return "trusted"


def tier_label(tier: str) -> str:
    return {
        "hidden": "hidden (<30 closed)",
        "provisional": "provisional (30–99)",
        "usable": "usable (100–299)",
        "trusted": "trusted (≥300)",
    }.get(tier, tier)


def _f(x: Any, default: float | None = None) -> float | None:
    if x is None:
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _safe_div(a: float, b: float) -> float | None:
    if b == 0:
        return None
    return a / b


def classify_exits_by_strategy(
    attributions: list[dict[str, Any]],
    packets_by_id: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group exit attributions by packet strategy_tag (never mix)."""
    lanes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for attr in attributions:
        if not isinstance(attr, dict):
            continue
        if str(attr.get("trigger") or "") not in {"exit", "manual"}:
            continue
        did = str(attr.get("decision_id") or "")
        pkt = packets_by_id.get(did) if did else None
        tag = "unknown"
        if isinstance(pkt, dict) and pkt.get("strategy_tag"):
            tag = str(pkt["strategy_tag"])
        elif isinstance(attr.get("payload"), dict):
            tag = str((attr["payload"].get("extra") or {}).get("strategy_tag") or tag)
        grades = attr.get("grades") if isinstance(attr.get("grades"), dict) else {}
        pnl = grades.get("pnl")
        if pnl is None and isinstance(attr.get("payload"), dict):
            pnl = attr["payload"].get("pnl")
        lanes[tag].append(
            {
                "attribution": attr,
                "packet": pkt,
                "pnl": _f(pnl),
                "grades": grades,
            }
        )
    return dict(lanes)


def edge_metrics_for_lane(
    exits: list[dict[str, Any]], *, tier: str
) -> dict[str, Any]:
    """Win rate / PF / expectancy — only when tier allows; else honest hide."""
    n = len(exits)
    base = {
        "n_closed": n,
        "tier": tier,
        "tier_label": tier_label(tier),
        "edge_visible": tier != "hidden",
        "edge_status": "hidden" if tier == "hidden" else tier,
    }
    if tier == "hidden":
        base["note"] = (
            f"Edge metrics hidden until ≥30 closed exits for this strategy_tag "
            f"(have {n})."
        )
        return base

    pnls = [e["pnl"] for e in exits if e.get("pnl") is not None]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    flats = [p for p in pnls if p == 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    win_rate = _safe_div(len(wins), len(pnls)) if pnls else None
    avg_win = _safe_div(gross_win, len(wins)) if wins else None
    avg_loss = _safe_div(sum(losses), len(losses)) if losses else None  # negative
    profit_factor = _safe_div(gross_win, gross_loss) if gross_loss else (
        None if not wins else float("inf")
    )
    expectancy = _safe_div(sum(pnls), len(pnls)) if pnls else None

    # Consecutive losses (from chronological order if created_at present)
    ordered = sorted(
        exits,
        key=lambda e: str((e.get("attribution") or {}).get("created_at") or ""),
    )
    streak = 0
    max_streak = 0
    for e in ordered:
        p = e.get("pnl")
        if p is not None and p < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    base.update(
        {
            "wins": len(wins),
            "losses": len(losses),
            "flats": len(flats),
            "win_rate": round(win_rate, 4) if win_rate is not None else None,
            "profit_factor": (
                round(profit_factor, 4)
                if isinstance(profit_factor, float) and profit_factor != float("inf")
                else ("inf" if profit_factor == float("inf") else None)
            ),
            "expectancy": round(expectancy, 4) if expectancy is not None else None,
            "avg_win": round(avg_win, 4) if avg_win is not None else None,
            "avg_loss": round(avg_loss, 4) if avg_loss is not None else None,
            "consecutive_losses_max": max_streak,
            "provisional": tier == "provisional",
            "note": (
                "Provisional — treat cautiously until 100 closed."
                if tier == "provisional"
                else (
                    "Usable sample."
                    if tier == "usable"
                    else "Trusted sample (≥300)."
                )
            ),
        }
    )
    if tier != "trusted":
        base["stage3_sharpe"] = None
        base["stage3_note"] = "Sharpe/Sortino/Calmar reserved for trusted (≥300) sample."
    else:
        base["stage3_sharpe"] = None  # still stub until returns series wired
        base["stage3_note"] = "Trusted gate open; Sharpe series not yet computed (Stage 3 stub)."
    return base


def build_di_dashboards(
    *,
    data_dir: str | Path | None = None,
    portfolio_key: str = "india_equity_learner",
    portfolio: dict[str, Any] | None = None,
    trading_kpis: dict[str, Any] | None = None,
    packets: list[dict[str, Any]] | None = None,
    attributions: list[dict[str, Any]] | None = None,
    evolution: dict[str, Any] | None = None,
    observations: list[dict[str, Any]] | None = None,
    fundamentals_coverage: dict[str, Any] | None = None,
    ist_date: str | None = None,
) -> dict[str, Any]:
    """Assemble D1–D6 Stage-1 dashboards + gated D2 edge lanes."""
    port = portfolio if isinstance(portfolio, dict) else {}
    kpis = trading_kpis if isinstance(trading_kpis, dict) else {}
    pkt_list = [p for p in (packets or []) if isinstance(p, dict)]
    attr_list = [a for a in (attributions or []) if isinstance(a, dict)]
    obs_list = [o for o in (observations or []) if isinstance(o, dict)]
    evo = evolution if isinstance(evolution, dict) else {}
    fund = fundamentals_coverage if isinstance(fundamentals_coverage, dict) else {}

    packets_by_id = {
        str(p["decision_id"]): p for p in pkt_list if p.get("decision_id")
    }
    lanes = classify_exits_by_strategy(attr_list, packets_by_id)
    strategy_lanes: dict[str, Any] = {}
    for tag, exits in sorted(lanes.items()):
        tier = sample_tier(len(exits))
        strategy_lanes[tag] = edge_metrics_for_lane(exits, tier=tier)

    # Completeness
    comps = [
        float((p.get("meta") or {}).get("completeness") or 0)
        for p in pkt_list
        if isinstance(p.get("meta"), dict)
    ]
    avg_completeness = round(sum(comps) / len(comps), 3) if comps else None
    with_obs = sum(1 for p in pkt_list if p.get("observation_ids"))
    obs_cite_rate = (
        round(with_obs / len(pkt_list), 4) if pkt_list else None
    )
    with_parent = sum(1 for p in pkt_list if p.get("parent_decision_id"))

    # D1 Process / session
    d1 = {
        "id": "D1",
        "title": "Process / session",
        "stage": 1,
        "metrics": {
            "fills_today": kpis.get("fills_today"),
            "buys_today": kpis.get("buys_today"),
            "sells_today": kpis.get("sells_today"),
            "fees_paid": kpis.get("fees_paid"),
            "plan_fill_rate": kpis.get("plan_fill_rate"),
            "portfolio_gate_blocks": kpis.get("portfolio_gate_blocks"),
            "size_trims": kpis.get("size_trims"),
            "top_no_fill_reasons": kpis.get("top_no_fill_reasons"),
            "phase": kpis.get("phase"),
            "confidence": kpis.get("confidence"),
            "process_score": (port.get("process_proxies") or {}).get("process_score")
            if isinstance(port.get("process_proxies"), dict)
            else None,
            "process_flags": (port.get("process_proxies") or {}).get("counts")
            if isinstance(port.get("process_proxies"), dict)
            else None,
        },
    }

    # D2 Trading — stage 1 always; edge per strategy_tag gated
    d2 = {
        "id": "D2",
        "title": "Trading (execution edge)",
        "stage": 1,
        "metrics_stage1": {
            "fills_today": kpis.get("fills_today"),
            "fees_paid": kpis.get("fees_paid"),
            "consecutive_losses_hint": "see strategy_lanes when exits exist",
        },
        "strategy_lanes": strategy_lanes,
        "note": "Edge metrics never mix strategy_tags. Gates: 30 / 100 / 300.",
    }

    # D3 Portfolio
    d3 = {
        "id": "D3",
        "title": "Portfolio (book health)",
        "stage": 1,
        "metrics": {
            "cash": kpis.get("cash") if kpis.get("cash") is not None else _f(port.get("cash")),
            "holdings_value": kpis.get("holdings_value")
            if kpis.get("holdings_value") is not None
            else _f(port.get("holdings_value")),
            "equity": kpis.get("equity")
            if kpis.get("equity") is not None
            else _f(port.get("equity") or port.get("equity_value")),
            "day_pnl": kpis.get("day_pnl")
            if kpis.get("day_pnl") is not None
            else _f(port.get("day_pnl")),
            "total_pnl": kpis.get("total_pnl")
            if kpis.get("total_pnl") is not None
            else _f(port.get("total_pnl")),
            "net_contributed_capital": kpis.get("net_contributed_capital")
            if kpis.get("net_contributed_capital") is not None
            else _f(port.get("net_contributed_capital")),
            "open_positions": kpis.get("open_positions")
            if kpis.get("open_positions") is not None
            else len(port.get("positions") or []),
            "plan_fill_rate": kpis.get("plan_fill_rate"),
            "max_drawdown": None,  # Stage 2 when series exists
            "max_drawdown_note": "Max drawdown tracked once equity curve series is durable.",
        },
    }

    # D4 Learning
    d4 = {
        "id": "D4",
        "title": "Learning (markets)",
        "stage": 1,
        "metrics": {
            "packets_recorded": len(pkt_list),
            "exit_attributions": sum(
                1 for a in attr_list if a.get("trigger") in {"exit", "manual"}
            ),
            "revisit_attributions": sum(
                1 for a in attr_list if a.get("trigger") == "revisit"
            ),
            "lessons_count": kpis.get("lessons_count"),
            "research_studied": kpis.get("research_studied"),
            "pending_revisits": evo.get("pending_revisits"),
            "done_revisits": evo.get("done_revisits"),
        },
    }

    # D5 Research
    gaps = fund.get("learner_gaps") if isinstance(fund.get("learner_gaps"), dict) else {}
    d5 = {
        "id": "D5",
        "title": "Research (what don’t we know?)",
        "stage": 1,
        "metrics": {
            "fundamentals_symbols": fund.get("symbols"),
            "with_pe": fund.get("with_pe"),
            "with_fcf": fund.get("with_fcf"),
            "pe_coverage_pct": fund.get("pe_coverage_pct"),
            "watchlist_gaps": gaps.get("symbols_with_gaps"),
            "watchlist_checked": gaps.get("symbols_checked"),
            "honesty": fund.get("note")
            or gaps.get("honesty")
            or "Missing PE/FCF stay missing — never invent industry averages.",
            "import_hint": gaps.get("import_hint")
            or "POST /v1/market/fundamentals/import",
        },
    }

    # D6 Intelligence — Atlas-the-product
    meta_doc = port.get("meta_learning") if isinstance(port.get("meta_learning"), dict) else {}
    prox_doc = (
        port.get("process_proxies")
        if isinstance(port.get("process_proxies"), dict)
        else {}
    )
    d6_metrics = {
        "avg_packet_completeness": avg_completeness,
        "packets_n": len(pkt_list),
        "observation_citation_rate": obs_cite_rate,
        "observations_recent": len(obs_list),
        "pending_revisits": evo.get("pending_revisits"),
        "done_revisits": evo.get("done_revisits"),
        "open_evolution": evo.get("open_evolution"),
        "genealogy_parent_rate": (
            round(with_parent / len(pkt_list), 4) if pkt_list else None
        ),
        "priors_blocked_exits": sum(
            1
            for a in attr_list
            if isinstance(a.get("grades"), dict)
            and a["grades"].get("may_update_priors") is False
        ),
        "fundamentals_holes": gaps.get("symbols_with_gaps"),
    }
    if meta_doc or prox_doc:
        try:
            from atlas.investment.meta_learning import enrich_d6_metrics

            d6_metrics = enrich_d6_metrics(
                d6_metrics, meta=meta_doc, process_proxies=prox_doc
            )
        except Exception:  # noqa: BLE001
            pass
    d6 = {
        "id": "D6",
        "title": "Intelligence (Atlas-the-product)",
        "stage": 2 if meta_doc.get("intelligence_score") is not None else 1,
        "metrics": d6_metrics,
        "note": (
            "D6 scores whether Atlas is becoming a better decision system — "
            "not portfolio vanity. Meta-learning proposals never auto-edit strategy."
        ),
        "meta_learning": {
            "week": meta_doc.get("week"),
            "intelligence_score": meta_doc.get("intelligence_score"),
            "proposals": (meta_doc.get("proposals") or [])[:3],
        }
        if meta_doc
        else None,
    }

    doc = {
        "version": VERSION,
        "portfolio_key": portfolio_key,
        "ist_date": ist_date,
        "sample_gates": {
            "hidden": "n≤29",
            "provisional": "30–99",
            "usable": "100–299",
            "trusted": "n≥300",
            "rule": "never mix strategy_tags",
        },
        "dashboards": {
            "D1": d1,
            "D2": d2,
            "D3": d3,
            "D4": d4,
            "D5": d5,
            "D6": d6,
        },
        "strategy_lane_summary": {
            tag: {
                "n_closed": lane.get("n_closed"),
                "tier": lane.get("tier"),
                "win_rate": lane.get("win_rate"),
                "edge_visible": lane.get("edge_visible"),
            }
            for tag, lane in strategy_lanes.items()
        },
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
            _log.debug("di dashboard mirror failed", exc_info=True)
    return doc


def format_di_dashboard_section(doc: dict[str, Any] | None) -> list[str]:
    """Evening-mail / operator plain-text block."""
    if not isinstance(doc, dict) or not doc.get("dashboards"):
        return []
    lines = ["", "DI dashboards (staged · sample-gated):"]
    d3 = (doc.get("dashboards") or {}).get("D3") or {}
    m3 = d3.get("metrics") or {}
    lines.append(
        f"  D3 book: equity={m3.get('equity')} cash={m3.get('cash')} "
        f"day_pnl={m3.get('day_pnl')} open={m3.get('open_positions')}"
    )
    d6 = (doc.get("dashboards") or {}).get("D6") or {}
    m6 = d6.get("metrics") or {}
    lines.append(
        f"  D6 intelligence: packet_completeness={m6.get('avg_packet_completeness')} "
        f"obs_cite={m6.get('observation_citation_rate')} "
        f"revisits pending/done={m6.get('pending_revisits')}/{m6.get('done_revisits')} "
        f"priors_blocked={m6.get('priors_blocked_exits')}"
    )
    if m6.get("intelligence_score") is not None:
        lines.append(
            f"  D6 score={m6.get('intelligence_score')} · "
            f"incomplete={m6.get('incomplete_packets_pct')}% · "
            f"process={m6.get('process_score')} · "
            f"overconf={m6.get('overconfidence_rate')}"
        )
    summary = doc.get("strategy_lane_summary") or {}
    if summary:
        lines.append("  D2 strategy lanes (never mixed):")
        for tag, row in list(summary.items())[:8]:
            wr = row.get("win_rate")
            wr_s = f"{float(wr):.0%}" if wr is not None else "—"
            vis = "visible" if row.get("edge_visible") else "hidden"
            lines.append(
                f"    · {tag}: n={row.get('n_closed')} tier={row.get('tier')} "
                f"edge={vis} win_rate={wr_s}"
            )
    else:
        lines.append("  D2 strategy lanes: (no closed exits yet — edge metrics hidden)")
    d5 = ((doc.get("dashboards") or {}).get("D5") or {}).get("metrics") or {}
    if d5.get("watchlist_gaps"):
        lines.append(
            f"  D5 research holes: {d5.get('watchlist_gaps')}/{d5.get('watchlist_checked')} "
            f"names missing PE/FCF (import required)"
        )
    return lines


def collect_dashboard_inputs(
    *,
    data_dir: str | Path | None,
    portfolio_key: str,
    portfolio: dict[str, Any] | None = None,
    ist_date: str | None = None,
) -> dict[str, Any]:
    """Best-effort load from DI stores for API / evening."""
    from atlas.investment.decision_attribution import DecisionAttributionStore
    from atlas.investment.decision_packets import DecisionPacketStore, ist_today
    from atlas.investment.decision_timeline import DecisionTimelineStore
    from atlas.investment.observations import DecisionObservationStore
    from atlas.investment.fundamentals import fundamentals_view
    from atlas.investment.trading_kpis import load_day_kpis

    day = ist_date or ist_today()
    port = portfolio if isinstance(portfolio, dict) else {}
    kpis = port.get("kpis") if isinstance(port.get("kpis"), dict) else {}
    if not kpis and data_dir:
        kpis = load_day_kpis(
            data_dir, portfolio_key=portfolio_key, ist_date=day
        ).get("kpis") or {}

    packets: list[dict[str, Any]] = []
    try:
        pstore = DecisionPacketStore(data_dir=data_dir)
        packets = pstore.list_day(portfolio_key=portfolio_key, ts_ist=day, limit=200)
        # Also recent for completeness across days
        if len(packets) < 20:
            # scan a few recent symbols from portfolio
            for p in (port.get("positions") or [])[:10]:
                if isinstance(p, dict) and p.get("symbol"):
                    packets.extend(
                        pstore.list_symbol(
                            symbol=str(p["symbol"]),
                            limit=10,
                            portfolio_key=portfolio_key,
                        )
                    )
    except Exception:  # noqa: BLE001
        _log.debug("dashboard packets load failed", exc_info=True)

    attributions: list[dict[str, Any]] = []
    try:
        astore = DecisionAttributionStore(data_dir=data_dir)
        attributions = astore.list_portfolio(portfolio_key=portfolio_key, limit=200)
    except Exception:  # noqa: BLE001
        _log.debug("dashboard attributions load failed", exc_info=True)

    evolution: dict[str, Any] = {}
    try:
        tstore = DecisionTimelineStore(data_dir=data_dir)
        evolution = tstore.learning_counts(portfolio_key=portfolio_key)
    except Exception:  # noqa: BLE001
        evolution = dict(port.get("evolution") or {})

    observations: list[dict[str, Any]] = list(port.get("observations") or [])
    if not observations and data_dir:
        try:
            ostore = DecisionObservationStore(data_dir=data_dir)
            observations = ostore.list_since(since_hours=72.0, limit=40)
        except Exception:  # noqa: BLE001
            pass

    fund_cov = port.get("fundamentals_coverage") if isinstance(
        port.get("fundamentals_coverage"), dict
    ) else {}
    if not fund_cov and data_dir:
        try:
            fv = fundamentals_view(data_dir, program_id="market_intelligence", limit=5)
            fund_cov = dict(fv.get("coverage") or {})
            syms = [
                str(p.get("symbol"))
                for p in (port.get("positions") or [])
                if isinstance(p, dict) and p.get("symbol")
            ]
            if syms:
                from atlas.investment.fundamentals import learner_fundamentals_gaps

                fund_cov["learner_gaps"] = learner_fundamentals_gaps(
                    data_dir, syms, program_id="market_intelligence"
                )
        except Exception:  # noqa: BLE001
            pass

    return build_di_dashboards(
        data_dir=data_dir,
        portfolio_key=portfolio_key,
        portfolio=port,
        trading_kpis=kpis,
        packets=packets,
        attributions=attributions,
        evolution=evolution,
        observations=observations,
        fundamentals_coverage=fund_cov,
        ist_date=day,
    )
