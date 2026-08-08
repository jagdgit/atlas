"""Investor email reports — morning plan + trade decision digests.

Uses shared SMTP EmailSender with per-send recipients (Gmail app password via env).
Market Program only — not a new OS; not ops Notifier fan-out.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from atlas.investment.daily_plan import plan_from_watchlist
from atlas.investment.government_policy import format_policy_brief, load_snapshot


def parse_recipients(raw: str | list[str] | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return [p.strip() for p in str(raw).split(",") if p.strip()]


def resolve_investor_recipients(
    *,
    config_to: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> list[str]:
    """Prefer dedicated investor env, then email to_addrs env, then config list."""
    env = env if env is not None else os.environ
    for key in (
        "ATLAS_INVESTOR_REPORT_TO",
        "ATLAS_EMAIL_INVESTOR_TO_ADDRS",
        "ATLAS_EMAIL_TO_ADDRS",
    ):
        if env.get(key):
            return parse_recipients(env.get(key))
    return list(config_to or [])


def _portfolio_planning_capital(portfolio: dict[str, Any] | None) -> float | None:
    """Use marked book equity for plan sizing; registry/default capital is not cash truth."""
    if not isinstance(portfolio, dict):
        return None
    for key in ("equity", "equity_value"):
        value = portfolio.get(key)
        if value is not None:
            try:
                amount = float(value)
                if amount > 0:
                    return amount
            except (TypeError, ValueError):
                pass
    value = portfolio.get("cash")
    try:
        amount = float(value) if value is not None else 0.0
        return amount if amount > 0 else None
    except (TypeError, ValueError):
        return None


def _money(value: Any) -> str:
    if value is None:
        return "unavailable"
    try:
        return f"₹{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _signed_money(value: Any) -> str:
    if value is None:
        return "unavailable (market close marks missing)"
    try:
        return f"{float(value):+,.2f}"
    except (TypeError, ValueError):
        return str(value)


def format_learned_today_section(
    *,
    plan: dict[str, Any] | None = None,
    portfolio: dict[str, Any] | None = None,
    decisions: list[dict[str, Any]] | None = None,
    trades: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Operator-facing: how much Atlas learned today + sell rule + under watch.

    Placed near the top of the evening mail so cold-start noise does not bury it.
    """
    plan = plan if isinstance(plan, dict) else {}
    port = portfolio if isinstance(portfolio, dict) else {}
    decision_rows = list(decisions or port.get("decisions") or [])
    trade_rows = list(trades or [])
    if not trade_rows:
        trade_rows = list(port.get("recent_trades") or [])
    day_trades = [t for t in trade_rows if isinstance(t, dict)]
    if any("ist_day_match" in t for t in day_trades):
        day_trades = [t for t in day_trades if t.get("ist_day_match")]
    buys = [t for t in day_trades if str(t.get("side") or "").lower() == "buy"]
    sells = [t for t in day_trades if str(t.get("side") or "").lower() == "sell"]

    buys_n = sum(
        1 for d in decision_rows if isinstance(d, dict) and str(d.get("action") or "").lower() == "buy"
    )
    sells_n = sum(
        1 for d in decision_rows if isinstance(d, dict) and str(d.get("action") or "").lower() == "sell"
    )
    holds_n = sum(
        1
        for d in decision_rows
        if isinstance(d, dict) and str(d.get("action") or "").lower() in {"hold", "watch"}
    )
    with_unk = sum(
        1 for d in decision_rows if isinstance(d, dict) and (d.get("unknowns") or [])
    )

    kpis = port.get("kpis") if isinstance(port.get("kpis"), dict) else {}
    prox = port.get("process_proxies") if isinstance(port.get("process_proxies"), dict) else {}
    meta = port.get("meta_learning") if isinstance(port.get("meta_learning"), dict) else {}
    evo = port.get("evolution") if isinstance(port.get("evolution"), dict) else {}
    cov = (
        port.get("fundamentals_coverage")
        if isinstance(port.get("fundamentals_coverage"), dict)
        else {}
    )
    gaps = cov.get("learner_gaps") if isinstance(cov.get("learner_gaps"), dict) else {}
    obs = list(port.get("observations") or [])

    pos = port.get("positions") or port.get("holdings") or []
    if isinstance(pos, dict):
        pos = [{"symbol": k, **(v if isinstance(v, dict) else {})} for k, v in pos.items()]
    pos = [p for p in pos if isinstance(p, dict) and p.get("symbol")]

    plan_syms = [
        str(c.get("symbol"))
        for c in (plan.get("candidates") or [])
        if isinstance(c, dict) and c.get("symbol")
    ]
    avoid_syms = [
        str(a.get("symbol"))
        for a in (plan.get("avoids") or [])
        if isinstance(a, dict) and a.get("symbol")
    ]

    # Learning grade for the day (honest cold-start language)
    fills_ok = len(buys) + len(sells)
    packets_ok = len(decision_rows) > 0
    fund_ok = int(cov.get("with_pe") or 0) > 0
    exits_ok = len(sells) > 0 or int(kpis.get("sells_today") or 0) > 0
    if exits_ok and fund_ok and packets_ok:
        day_grade = "substantive — exits + evidence present"
    elif fills_ok and packets_ok:
        day_grade = (
            "partial — decisions + fills recorded; outcomes still open "
            "(need sells / revisits / PE-FCF import)"
        )
    elif packets_ok:
        day_grade = "thin — packets only; few or no fills"
    else:
        day_grade = "none yet — no decision packets today"

    lines = [
        "",
        "══════════════════════════════════════",
        "WHAT ATLAS LEARNED TODAY (read this first)",
        "══════════════════════════════════════",
        f"  Day learning grade: {day_grade}",
        f"  Decisions frozen: {len(decision_rows)} "
        f"(buy={buys_n} sell={sells_n} hold/watch={holds_n})",
        f"  Sim fills: buys={len(buys)} sells={len(sells)}",
        f"  Packets still missing PE/FCF/MoS: {with_unk}/{len(decision_rows) or 0}",
        f"  Observations ingested: {len(obs)}",
        f"  Revisits pending/done: {evo.get('pending_revisits', '—')}/"
        f"{evo.get('done_revisits', '—')}",
    ]
    if evo.get("open_books") is not None:
        lines.append(
            f"  Open books full schedule: "
            f"{evo.get('open_books_with_full_schedule', 0)}/{evo.get('open_books', 0)}"
            f" · overdue={evo.get('overdue_revisits', 0)}"
        )
    if evo.get("host_guard_reason") and not evo.get("host_guard_budget", 1):
        lines.append(
            f"  Evolution Host Guard thinned: {evo.get('host_guard_reason')} "
            "(pending kept — not invented done)"
        )
    lines.extend(
        [
        f"  Process score: {prox.get('process_score', '—')}/10 · "
        f"Atlas intelligence_score: {meta.get('intelligence_score', '—')}",
        f"  Fundamentals store PE coverage: {cov.get('with_pe', 0)}/"
        f"{cov.get('symbols', 0)} · watchlist holes: "
        f"{gaps.get('symbols_with_gaps', '—')}/{gaps.get('symbols_checked', '—')}",
        ]
    )
    iq = port.get("atlas_iq") if isinstance(port.get("atlas_iq"), dict) else None
    if iq:
        from atlas.investment.learning_intelligence import (
            format_atlas_iq_section,
            format_evolution_narrative_section,
        )

        lines.extend(format_atlas_iq_section(iq))
        narr = port.get("evolution_narrative")
        events = port.get("evolution_events")
        if narr or events:
            lines.extend(
                format_evolution_narrative_section(
                    events if isinstance(events, list) else None,
                    narrative=narr if isinstance(narr, list) else None,
                )
            )
        readiness = port.get("readiness") if isinstance(port.get("readiness"), dict) else None
        if readiness is None and isinstance(iq.get("readiness"), dict):
            readiness = iq.get("readiness")
        if isinstance(readiness, dict):
            blocking = readiness.get("blocking") or []
            lines.append(
                f"  Dataset readiness: "
                f"{'READY' if readiness.get('ready') else 'NOT READY'}"
                f"{(' · blocking=' + ','.join(blocking)) if blocking else ''}"
                f" · live_nn=False"
            )
    lines.extend(
        [
            "",
            "  What still blocks “sufficient” learning:",
        ]
    )
    blockers = []
    if not fund_ok:
        blockers.append(
            "Import PE/FCF (GET /v1/market/fundamentals/learner-template) — "
            "every packet today lists pe_missing/fcf_missing"
        )
    if not exits_ok:
        blockers.append(
            "No sells yet — strategy edge / attribution need closed exits "
            "(SMA fast below slow while holding; see sell rule below)"
        )
    if int(evo.get("done_revisits") or 0) == 0 and int(evo.get("pending_revisits") or 0) > 0:
        blockers.append(
            f"Start/confirm Decision Evolution mission — "
            f"{evo.get('pending_revisits')} revisits pending, 0 done"
        )
    if str(plan.get("phase") or kpis.get("phase") or "") == "learning":
        blockers.append(
            "phase=learning / cold-start — ranking still provisional until more bars + outcomes"
        )
    if not blockers:
        blockers.append("(no hard blockers listed)")
    for b in blockers:
        lines.append(f"    · {b}")

    lines.extend(
        [
            "",
            "  When Atlas sells (current rule — P10 sim):",
            "    · Technical exit: SMA fast falls below SMA slow while a position is held,",
            "      and RSI is not oversold (default >30) — typically exits full position.",
            "    · Not yet: fixed calendar stop, hard MoS stop, or thesis-falsifier auto-sell.",
            "    · Thesis falsifiers are reviewed on revisits / exit attribution — they do not",
            "      alone force a sell in v1 strategy.",
            "",
            "  Under observation now (so Atlas does not forget open books):",
        ]
    )
    if pos:
        for p in pos[:15]:
            lines.append(
                f"    · HOLDING {p.get('symbol')}: qty={p.get('quantity') or p.get('qty')} "
                f"avg={p.get('avg_price') or p.get('avg_cost')} "
                f"mark={p.get('mark')} unrealized={_signed_money(p.get('unrealized_pnl'))} "
                f"— waiting for SMA exit / revisit"
            )
    else:
        lines.append("    · (no open positions)")
    if plan_syms:
        lines.append(
            "  Today’s plan watch (ranked candidates Atlas is deliberately tracking):"
        )
        lines.append("    · " + ", ".join(plan_syms[:12]))
    if avoid_syms:
        lines.append("  Explicit avoids / weaker ranks today:")
        lines.append("    · " + ", ".join(avoid_syms[:12]))
    buy_syms = sorted(
        {
            str(t.get("symbol"))
            for t in buys
            if t.get("symbol")
        }
        | {
            str(d.get("symbol"))
            for d in decision_rows
            if isinstance(d, dict)
            and str(d.get("action") or "").lower() == "buy"
            and d.get("symbol")
        }
    )
    if buy_syms:
        lines.append("  New buys recorded today (decision memory started):")
        lines.append("    · " + ", ".join(buy_syms[:12]))
    lines.append(
        "  Continuity: every material decision is a Decision Packet; open positions stay on "
        "the timeline until exit + attribution. Watchlist holes ≠ forgotten — they stay as "
        "unknowns until you import fundamentals or research fills them."
    )
    return lines


def _laboratory_label(portfolio: dict[str, Any] | None, laboratory_id: str | None = None) -> str:
    from atlas.investment.laboratory import normalize_laboratory_id

    if laboratory_id:
        return normalize_laboratory_id(laboratory_id=laboratory_id)
    if isinstance(portfolio, dict):
        return normalize_laboratory_id(
            laboratory_id=portfolio.get("laboratory_id"),
            portfolio_key=portfolio.get("portfolio_key"),
        )
    return normalize_laboratory_id()


def format_morning_report(
    *,
    plan: dict[str, Any] | None,
    portfolio: dict[str, Any] | None = None,
    policy_snap: dict[str, Any] | None = None,
    program_id: str = "market_intelligence",
    research_digest: dict[str, Any] | None = None,
    catch_up: bool = False,
    laboratory_id: str | None = None,
) -> tuple[str, str]:
    plan = plan or {}
    as_of = plan.get("as_of") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lab = _laboratory_label(portfolio, laboratory_id)
    subject = f"[Atlas][{lab}] Morning investment plan — {as_of} ({program_id})"
    lines = [
        "Atlas morning report (simulation — not broker orders)",
        f"Date: {as_of}",
        f"Program: {program_id}",
        f"Laboratory: {lab}",
        f"Phase: {plan.get('phase')} · confidence: {plan.get('confidence')}",
        f"Capital: {plan.get('capital')} · deploy fraction: {plan.get('deploy_fraction')}",
    ]
    if catch_up:
        lines.append(
            "Note: catch-up send — morning window was missed (offline / internet / restart)."
        )
    lines.extend(
        [
            "",
            "Summary:",
            str(plan.get("summary") or "(no plan yet)"),
            "",
            "Selected candidates — why & suggested notional:",
        ]
    )
    for c in plan.get("candidates") or []:
        lines.append(
            f"  {c.get('rank', '?')}. {c.get('symbol')} ({c.get('sector') or '—'}) "
            f"— ₹{c.get('suggested_notional', 0)} "
            f"(weight {c.get('suggested_weight', 0)})"
        )
        why = (c.get("why") or "").strip()
        if why:
            lines.append(f"     Why: {why}")
        for ex in (c.get("explanations") or [])[:4]:
            if isinstance(ex, dict):
                lines.append(f"     {ex.get('sign', '·')} {ex.get('text', '')}")
            else:
                lines.append(f"     · {ex}")
        # IRA morning: thesis one-liner when digest provided
        if research_digest:
            for s in research_digest.get("studied") or []:
                if s.get("symbol") == c.get("symbol") and s.get("thesis"):
                    lines.append(
                        f"     Thesis ({s.get('stance') or '?'}): {s.get('thesis')} "
                        f"[cov {s.get('coverage')}% / conf {s.get('confidence')}]"
                    )
                    break
    avoids = plan.get("avoids") or []
    if avoids:
        lines.append("")
        lines.append("Avoid / weaker relative set:")
        for a in avoids[:8]:
            if isinstance(a, dict):
                lines.append(f"  - {a.get('symbol')}: {a.get('why') or a.get('reason') or ''}")
            else:
                lines.append(f"  - {a}")
    for note in plan.get("notes") or []:
        lines.append(f"Note: {note}")

    if portfolio:
        lines.append("")
        lines.append("Current portfolio snapshot:")
        equity = portfolio.get("equity")
        if equity is None:
            equity = portfolio.get("equity_value")
        lines.append(f"  Cash available: {_money(portfolio.get('cash'))}")
        lines.append(f"  Holdings value: {_money(portfolio.get('holdings_value'))}")
        lines.append(f"  Total portfolio equity: {_money(equity)}")
        lines.append(
            f"  Total P&L after deposits/withdrawals: {_money(portfolio.get('total_pnl'))}"
        )
        pos = portfolio.get("positions") or portfolio.get("holdings") or []
        if isinstance(pos, dict):
            pos = [{"symbol": k, **(v if isinstance(v, dict) else {})} for k, v in pos.items()]
        for p in list(pos)[:20]:
            if not isinstance(p, dict):
                continue
            lines.append(
                f"  · {p.get('symbol')}: qty={p.get('quantity') or p.get('qty')} "
                f"avg={p.get('avg_price') or p.get('avg_cost')} "
                f"mark={p.get('mark')} unrealized={_signed_money(p.get('unrealized_pnl'))}"
            )
        if pos:
            lines.append(
                "  Learning status: open observation only — no strategy outcome "
                "is proven until exit/review against thesis falsifiers."
            )
        from atlas.investment.trading_kpis import format_kpi_section

        lines.extend(format_kpi_section(portfolio.get("kpis")))

    if policy_snap:
        lines.append("")
        lines.append(format_policy_brief(policy_snap, limit=6))

    _append_research_section(lines, research_digest, heading="Research studied (IRA)")

    lines.append("")
    lines.append("— Atlas Resource OS / Market Program · P10 simulation only")
    return subject, "\n".join(lines)


def format_evening_report(
    *,
    plan: dict[str, Any] | None,
    portfolio: dict[str, Any] | None = None,
    policy_snap: dict[str, Any] | None = None,
    program_id: str = "market_intelligence",
    trades: list[dict[str, Any]] | None = None,
    research_digest: dict[str, Any] | None = None,
    no_fill_reasons: list[str] | None = None,
    catch_up: bool = False,
    decisions: list[dict[str, Any]] | None = None,
    laboratory_id: str | None = None,
) -> tuple[str, str]:
    """Post-NSE close digest: what we planned, what filled, portfolio end state."""
    plan = plan or {}
    as_of = plan.get("as_of") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lab = _laboratory_label(portfolio, laboratory_id)
    subject = f"[Atlas][{lab}] Evening EOD digest — {as_of} ({program_id})"
    lines = [
        "Atlas evening report (simulation — not broker orders)",
        f"Date: {as_of}",
        f"Program: {program_id}",
        f"Laboratory: {lab}",
        "Window: after NSE cash equity close (~15:30 IST)",
        f"Morning phase was: {plan.get('phase')} · confidence: {plan.get('confidence')}",
    ]
    if catch_up:
        lines.append(
            "Note: catch-up send — report delayed (host offline / internet / Atlas restart)."
        )

    # Operator-first: learning grade, sell rule, under observation
    try:
        decision_rows_early = list(decisions or [])
        if not decision_rows_early and isinstance(portfolio, dict):
            decision_rows_early = list(portfolio.get("decisions") or [])
        day_trades_early = list(trades or [])
        if isinstance(portfolio, dict) and not day_trades_early:
            day_trades_early = list(portfolio.get("recent_trades") or [])
        lines.extend(
            format_learned_today_section(
                plan=plan,
                portfolio=portfolio if isinstance(portfolio, dict) else None,
                decisions=decision_rows_early,
                trades=day_trades_early,
            )
        )
    except Exception:  # noqa: BLE001
        pass

    lines.extend(
        [
            "",
            "Morning plan recap:",
            str(plan.get("summary") or "(no plan recorded)"),
            "",
            "Candidates (planned) — why & suggested notional:",
        ]
    )
    for c in plan.get("candidates") or []:
        lines.append(
            f"  {c.get('rank', '?')}. {c.get('symbol')} ({c.get('sector') or '—'}) "
            f"— ₹{c.get('suggested_notional', 0)} "
            f"(weight {c.get('suggested_weight', 0)})"
        )
        why = (c.get("why") or "").strip()
        if why:
            lines.append(f"     Why: {why}")
        for ex in (c.get("explanations") or [])[:4]:
            if isinstance(ex, dict):
                lines.append(f"     {ex.get('sign', '·')} {ex.get('text', '')}")
            else:
                lines.append(f"     · {ex}")

    trades = list(trades or [])
    if portfolio and not trades:
        trades = list(portfolio.get("recent_trades") or [])
    # Prefer today's IST fills when portfolio tagged them; fall back to recent ledger.
    day_trades = [t for t in trades if isinstance(t, dict) and t.get("ist_day_match") is not False]
    if any(isinstance(t, dict) and "ist_day_match" in t for t in trades):
        day_trades = [t for t in trades if isinstance(t, dict) and t.get("ist_day_match")]
    else:
        day_trades = [t for t in trades if isinstance(t, dict)]
    lines.append("")
    lines.append(f"Simulated fills today / recent ({len(day_trades)}):")
    if not day_trades:
        lines.append("  (no fills recorded in this snapshot)")
        reasons = list(no_fill_reasons or [])
        if not reasons and portfolio:
            reasons = list(portfolio.get("no_fill_reasons") or [])
        if reasons:
            lines.append("  Why no fills:")
            for r in reasons[:10]:
                lines.append(f"    · {r}")
    for t in day_trades[:25]:
        if not isinstance(t, dict):
            continue
        side = (t.get("side") or t.get("action") or "?").upper()
        lines.append(
            f"  · {side} {t.get('symbol')} × {t.get('quantity') or t.get('qty')} "
            f"@ {t.get('price') or t.get('fill_price')}"
            + (
                f" — {t.get('reason') or t.get('note') or ''}"
                if (t.get("reason") or t.get("note"))
                else ""
            )
        )
        for key in ("rationale", "why"):
            if t.get(key):
                lines.append(f"     {t.get(key)}")

    # DI.1 — Decisions today (packets), not only fills.
    decision_rows = list(decisions or [])
    if not decision_rows and isinstance(portfolio, dict):
        decision_rows = list(portfolio.get("decisions") or [])
    try:
        from atlas.investment.decision_packets import format_decisions_section

        lines.extend(format_decisions_section(decision_rows))
    except Exception:  # noqa: BLE001
        lines.append("")
        lines.append(f"Decisions today ({len(decision_rows)}):")
        if not decision_rows:
            lines.append("  (no decision packets recorded)")

    # DI.2 — evolution open/closed counts
    try:
        from atlas.investment.decision_timeline import format_evolution_section

        evo = None
        if isinstance(portfolio, dict):
            evo = portfolio.get("evolution")
        if evo:
            lines.extend(format_evolution_section(evo))
    except Exception:  # noqa: BLE001
        pass

    # DI.4 — fundamentals honesty (empty PE theater)
    try:
        cov = None
        if isinstance(portfolio, dict):
            cov = portfolio.get("fundamentals_coverage")
        if isinstance(cov, dict):
            lines.append("")
            lines.append("Fundamentals coverage (DI.4):")
            lines.append(
                f"  Store symbols={cov.get('symbols', 0)} "
                f"with_pe={cov.get('with_pe', 0)} with_fcf={cov.get('with_fcf', 0)}"
            )
            by_prov = cov.get("by_provider") or {}
            pe_by = by_prov.get("pe_by_provider") if isinstance(by_prov, dict) else None
            if isinstance(pe_by, dict) and pe_by:
                parts = [f"{k}={v}" for k, v in sorted(pe_by.items())]
                lines.append(f"  PE by provider: {', '.join(parts)}")
            if isinstance(by_prov, dict) and by_prov.get("symbols_with_conflicts"):
                lines.append(
                    f"  Provider conflicts: {by_prov.get('symbols_with_conflicts')} "
                    "(prefer higher tier — never invent blended PE)"
                )
            if cov.get("note"):
                lines.append(f"  Note: {cov.get('note')}")
            gaps = cov.get("learner_gaps") or {}
            if gaps.get("symbols_with_gaps"):
                lines.append(
                    f"  Watchlist gaps: {gaps.get('symbols_with_gaps')}/"
                    f"{gaps.get('symbols_checked')} names missing PE/FCF/ROE "
                    "(import or yahoo-enrich — never invent)"
                )
                if gaps.get("missing_pe") is not None:
                    lines.append(
                        f"  Missing PE={gaps.get('missing_pe')} "
                        f"FCF={gaps.get('missing_fcf')} · "
                        f"industry_pe_median present={gaps.get('with_industry_pe_median', 0)}"
                    )
                for g in (gaps.get("gaps") or [])[:5]:
                    if isinstance(g, dict):
                        lines.append(
                            f"    · {g.get('symbol')}: missing "
                            f"{', '.join(g.get('missing') or [])}"
                        )
                lines.append(
                    "  Fill: GET /v1/market/fundamentals/learner-template "
                    "· or POST /v1/market/fundamentals/yahoo-enrich"
                )
    except Exception:  # noqa: BLE001
        pass

    # DI.Obs — recent observations
    try:
        from atlas.investment.observations import format_observations_section

        obs_rows = None
        if isinstance(portfolio, dict):
            obs_rows = portfolio.get("observations")
        if obs_rows is not None:
            lines.extend(format_observations_section(obs_rows))
    except Exception:  # noqa: BLE001
        pass

    # DI.Attr — outcome grades
    try:
        from atlas.investment.decision_attribution import format_attribution_section

        attrs = None
        if isinstance(portfolio, dict):
            attrs = portfolio.get("attributions")
        if attrs is not None:
            lines.extend(format_attribution_section(attrs))
    except Exception:  # noqa: BLE001
        pass

    # DI.3 — staged dashboards
    try:
        from atlas.investment.di_dashboards import format_di_dashboard_section

        dash = None
        if isinstance(portfolio, dict):
            dash = portfolio.get("di_dashboards")
        if dash:
            lines.extend(format_di_dashboard_section(dash))
    except Exception:  # noqa: BLE001
        pass

    # DI.5 — process proxies
    try:
        from atlas.investment.process_proxies import format_process_proxies_section

        prox = None
        if isinstance(portfolio, dict):
            prox = portfolio.get("process_proxies")
        if prox:
            lines.extend(format_process_proxies_section(prox))
    except Exception:  # noqa: BLE001
        pass

    # DI.6 — meta-learning
    try:
        from atlas.investment.meta_learning import format_meta_learning_section

        meta = None
        if isinstance(portfolio, dict):
            meta = portfolio.get("meta_learning")
        if meta:
            lines.extend(format_meta_learning_section(meta))
    except Exception:  # noqa: BLE001
        pass

    # DI.7 — ML export gate (never live NN)
    try:
        ml = None
        if isinstance(portfolio, dict):
            ml = portfolio.get("ml_export")
        if isinstance(ml, dict) and ml.get("gate"):
            g = ml["gate"]
            lines.append("")
            lines.append("ML export gate (DI.7):")
            lines.append(
                f"  allowed={g.get('allowed')} · total_closed={g.get('total_closed')} "
                f"· trusted_tags={g.get('trusted_strategy_tags') or []}"
            )
            lines.append(
                "  live_nn_trading=False — walk-forward must beat rules first"
            )
            if not g.get("allowed"):
                lines.append(f"  blocked: {(g.get('reason') or '')[:140]}")
    except Exception:  # noqa: BLE001
        pass

    # LQ.9 — AtlasNet §8.2 hard gate (prep ≠ train)
    try:
        an = None
        if isinstance(portfolio, dict):
            an = portfolio.get("atlasnet_prep") or portfolio.get("atlasnet")
        if isinstance(an, dict) and (an.get("hard_gate") or an.get("atlasnet_status")):
            hg = an.get("hard_gate") if isinstance(an.get("hard_gate"), dict) else {}
            lines.append("")
            lines.append("AtlasNet hard gate (LQ.9 / §8.2):")
            lines.append(
                f"  status={an.get('atlasnet_status') or hg.get('atlasnet_status')} "
                f"· train_allowed={an.get('train_allowed', hg.get('train_allowed'))} "
                f"· export_allowed={an.get('export_allowed')} "
                f"· live_nn=False"
            )
            blocking = hg.get("blocking") or []
            if blocking:
                lines.append(f"  blocking: {', '.join(str(x) for x in blocking[:8])}")
    except Exception:  # noqa: BLE001
        pass

    if portfolio:
        lines.append("")
        lines.append("End-of-day portfolio snapshot:")
        equity_val = portfolio.get("equity")
        if equity_val is None:
            equity_val = portfolio.get("equity_value")
        day_pnl = portfolio.get("day_pnl")
        total_pnl = portfolio.get("total_pnl")
        lines.append(f"  Cash available: {_money(portfolio.get('cash'))}")
        lines.append(f"  Holdings at latest close: {_money(portfolio.get('holdings_value'))}")
        lines.append(f"  Total portfolio equity: {_money(equity_val)}")
        lines.append(
            "  Today's market P&L: ₹"
            + _signed_money(day_pnl)
            + (
                f" ({float(portfolio.get('day_return_pct')):+.2f}%)"
                if portfolio.get("day_return_pct") is not None
                else ""
            )
        )
        lines.append(
            "  Total P&L after cash flows: ₹"
            + _signed_money(total_pnl)
            + (
                f" ({float(portfolio.get('total_return_pct')):+.2f}%)"
                if portfolio.get("total_return_pct") is not None
                else ""
            )
        )
        lines.append(
            f"  Net contributed capital: {_money(portfolio.get('net_contributed_capital'))}"
        )
        lines.append(
            f"  Valuation basis: {portfolio.get('valuation_basis') or 'average cost'}"
        )
        if portfolio.get("trade_count") is not None:
            lines.append(f"  Trade count (ledger): {portfolio.get('trade_count')}")
        if portfolio.get("fees_paid") is not None:
            lines.append(f"  Fees paid: {portfolio.get('fees_paid')}")
        if portfolio.get("feed_gap_days") is not None:
            lines.append(
                f"  Feed gap (calendar days since last bar seen): {portfolio.get('feed_gap_days')}"
            )
        pos = portfolio.get("positions") or portfolio.get("holdings") or []
        if isinstance(pos, dict):
            pos = [{"symbol": k, **(v if isinstance(v, dict) else {})} for k, v in pos.items()]
        for p in list(pos)[:20]:
            if not isinstance(p, dict):
                continue
            lines.append(
                f"  · {p.get('symbol')}: qty={p.get('quantity') or p.get('qty')} "
                f"avg={p.get('avg_price') or p.get('avg_cost')} "
                f"mark={p.get('mark')} unrealized={_signed_money(p.get('unrealized_pnl'))}"
            )
        if pos:
            lines.append(
                "  Learning status: open observation only — no strategy outcome "
                "is proven until exit/review against thesis falsifiers."
            )
        from atlas.investment.trading_kpis import format_kpi_section

        lines.extend(format_kpi_section(portfolio.get("kpis")))

    if policy_snap:
        lines.append("")
        lines.append(format_policy_brief(policy_snap, limit=6))

    _append_research_section(
        lines,
        research_digest,
        heading="Research studied / decided / learned (IRA)",
        evening=True,
    )

    lines.append("")
    lines.append("— Atlas Resource OS / Market Program · P10 simulation only")
    return subject, "\n".join(lines)


def _append_research_section(
    lines: list[str],
    digest: dict[str, Any] | None,
    *,
    heading: str,
    evening: bool = False,
) -> None:
    if not digest:
        return
    studied = list(digest.get("studied") or [])
    lessons = list(digest.get("lessons") or [])
    gaps = list(digest.get("open_gaps") or [])
    if not (studied or lessons or gaps):
        return
    lines.append("")
    lines.append(heading + ":")
    if studied:
        lines.append("  Studied:")
        for s in studied[:10]:
            mvr = "MVR✓" if s.get("mvr_satisfied") else "MVR…"
            lines.append(
                f"  · {s.get('symbol')} [{mvr}] cov={s.get('coverage')}% "
                f"conf={s.get('confidence')} phase={s.get('phase')}"
            )
            if s.get("thesis"):
                lines.append(f"     Thesis ({s.get('stance') or '?'}): {s.get('thesis')}")
    if evening and lessons:
        lines.append("  Lessons from trading experience:")
        for lesson in lessons[-8:]:
            lines.append(f"  · {lesson}")
    if gaps:
        lines.append("  Open questions / gaps (fact ≠ estimate ≠ gap):")
        for g in gaps[:8]:
            lines.append(f"  · {g}")


def format_weekly_research_report(
    *,
    digest: dict[str, Any] | None,
    program_id: str = "market_intelligence",
) -> tuple[str, str]:
    """IRA.17 — weekly research learning digest."""
    digest = digest or {}
    as_of = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    subject = f"[Atlas] Weekly research learning — {as_of} ({program_id})"
    lines = [
        "Atlas weekly research learning digest (simulation — not broker orders)",
        f"Date: {as_of}",
        f"Program: {program_id}",
        f"Dossiers tracked: {digest.get('count') or 0}",
        "",
        "What we studied:",
    ]
    studied = list(digest.get("studied") or [])
    if not studied:
        lines.append("  (no research dossiers yet — run on-demand Research or paper ticks)")
    for s in studied[:12]:
        lines.append(
            f"  · {s.get('symbol')} [{('MVR✓' if s.get('mvr_satisfied') else 'MVR…')}] "
            f"cov={s.get('coverage')}% conf={s.get('confidence')} stance={s.get('stance')}"
        )
        if s.get("thesis"):
            lines.append(f"     {s.get('thesis')}")
    lines.append("")
    lines.append("Belief changes / ThesisOutcomes:")
    changes = list(digest.get("belief_changes") or digest.get("lessons") or [])
    if not changes:
        lines.append("  (no held/weakened/falsified outcomes yet)")
    for c in changes[:15]:
        lines.append(f"  · {c}")
    gaps = list(digest.get("open_gaps") or [])
    if gaps:
        lines.append("")
        lines.append("Open gaps (fact ≠ estimate ≠ gap):")
        for g in gaps[:10]:
            lines.append(f"  · {g}")
    # DI.6 — attach meta-learning if caller embedded it on digest
    meta = digest.get("meta_learning")
    if isinstance(meta, dict) and meta.get("version"):
        try:
            from atlas.investment.meta_learning import format_meta_learning_section

            lines.extend(format_meta_learning_section(meta))
        except Exception:  # noqa: BLE001
            pass
    lines.append("")
    lines.append("— Atlas Resource OS / Market Program · P10 simulation only")
    return subject, "\n".join(lines)


def format_trade_report(
    *,
    side: str,
    symbol: str,
    quantity: float,
    price: float,
    fee: float = 0.0,
    reason: str = "",
    decision: dict[str, Any] | None = None,
    mission_id: str | None = None,
    fees: dict[str, Any] | None = None,
    realized_pnl: float | None = None,
    policy_note: str = "",
    thesis: dict[str, Any] | None = None,
    laboratory_id: str | None = None,
    portfolio_key: str | None = None,
) -> tuple[str, str]:
    side_u = (side or "").upper()
    from atlas.investment.laboratory import normalize_laboratory_id

    lab = normalize_laboratory_id(
        laboratory_id=laboratory_id, portfolio_key=portfolio_key
    )
    subject = f"[Atlas][{lab}] {side_u} {symbol} × {quantity:g} @ {price:.2f}"
    lines = [
        "Atlas trade decision report (simulation fill)",
        f"Time (UTC): {datetime.now(timezone.utc).isoformat()}",
        f"Laboratory: {lab}",
        f"Side: {side_u}",
        f"Symbol: {symbol}",
        f"Quantity: {quantity:g}",
        f"Price: {price:.4f}",
        f"Fee: {fee:.4f}",
    ]
    if fees:
        lines.append(f"Fee breakdown: {fees}")
    if realized_pnl is not None:
        lines.append(f"Realized PnL: {realized_pnl:.4f}")
    if mission_id:
        lines.append(f"Mission: {mission_id}")
    if reason:
        lines.append("")
        lines.append(f"Why (tick summary): {reason}")
    if decision:
        lines.append("")
        lines.append("Decision detail:")
        for key in ("id", "action", "rationale", "confidence", "rule", "status"):
            if decision.get(key) is not None:
                lines.append(f"  {key}: {decision.get(key)}")
        opts = decision.get("options") or decision.get("chosen") or {}
        if isinstance(opts, dict) and opts:
            lines.append(f"  options: {opts}")
        expl = decision.get("explanations") or decision.get("why") or []
        if isinstance(expl, str) and expl:
            lines.append(f"  why: {expl}")
        elif isinstance(expl, list):
            for e in expl[:8]:
                lines.append(f"  · {e}")
        research_gate = decision.get("research_gate")
        if isinstance(research_gate, dict):
            lines.append(
                "  research gate: "
                + ("allowed" if research_gate.get("allowed") else "blocked")
                + f" · action={research_gate.get('action')}"
                + (
                    f" · reasons={research_gate.get('reasons')}"
                    if research_gate.get("reasons")
                    else ""
                )
            )
        portfolio_gate = decision.get("portfolio_gate")
        if isinstance(portfolio_gate, dict):
            lines.append(
                "  portfolio gate: "
                + ("allowed" if portfolio_gate.get("allowed") else "blocked")
                + (
                    f" · reasons={portfolio_gate.get('reasons')}"
                    if portfolio_gate.get("reasons")
                    else ""
                )
            )
    if thesis and isinstance(thesis, dict):
        lines.append("")
        lines.append(f"Linked thesis: {thesis.get('id') or '(none)'}")
        if thesis.get("summary"):
            lines.append(f"  {thesis.get('summary')}")
        if thesis.get("falsifiers"):
            lines.append(f"  Falsifiers: {', '.join(str(x) for x in thesis.get('falsifiers')[:4])}")
    if policy_note:
        lines.append("")
        lines.append(f"Policy / government context: {policy_note}")
    lines.append("")
    lines.append("Not a live broker order. Simulation Program only (P10).")
    return subject, "\n".join(lines)


class InvestorReportMailer:
    """Thin wrapper: build report bodies and send via EmailSender.send_to.

    Dedup is **IST calendar day** and persisted under ``data_dir`` so restarts /
    outages do not double-send, and SMTP failures do not mark the day as sent.
    """

    name = "investor_reports"
    VERSION = "ir.3"

    def __init__(
        self,
        email: Any,
        *,
        data_dir: str | None = None,
        recipients: list[str] | None = None,
        enabled: bool = True,
        research: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._email = email
        self._data_dir = data_dir
        self._recipients = list(recipients or [])
        self._enabled = bool(enabled)
        self._research = research
        self._logger = logger or logging.getLogger("atlas.investment.reports")
        # LI.1b: keys are "laboratory_id|YYYY-MM-DD" (legacy bare dates → default swing lab)
        self._sent_morning_dates: set[str] = set()
        self._sent_evening_dates: set[str] = set()
        self._sent_weekly_keys: set[str] = set()
        self._load_sent_flags()

    def bind_research(self, research: Any) -> None:
        self._research = research

    @staticmethod
    def ist_today() -> str:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")

    @staticmethod
    def _lab_day_key(laboratory_id: str | None, ist_date: str) -> str:
        from atlas.investment.laboratory import normalize_laboratory_id

        lab = normalize_laboratory_id(laboratory_id=laboratory_id)
        return f"{lab}|{ist_date}"

    def _sent_flags_path(self):
        from pathlib import Path

        if not self._data_dir:
            return None
        return Path(self._data_dir) / "market" / "investor_reports_sent.json"

    def _load_sent_flags(self) -> None:
        path = self._sent_flags_path()
        if path is None or not path.is_file():
            return
        try:
            import json

            from atlas.investment.laboratory import DEFAULT_SWING_LAB

            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return
            for d in raw.get("morning") or []:
                s = str(d)
                if "|" not in s:
                    s = f"{DEFAULT_SWING_LAB}|{s}"
                self._sent_morning_dates.add(s)
            for d in raw.get("evening") or []:
                s = str(d)
                if "|" not in s:
                    s = f"{DEFAULT_SWING_LAB}|{s}"
                self._sent_evening_dates.add(s)
            for k in raw.get("weekly") or []:
                self._sent_weekly_keys.add(str(k))
        except Exception:  # noqa: BLE001
            self._logger.debug("investor sent-flags load failed", exc_info=True)

    def _persist_sent_flags(self) -> None:
        path = self._sent_flags_path()
        if path is None:
            return
        try:
            import json

            path.parent.mkdir(parents=True, exist_ok=True)
            morning = sorted(self._sent_morning_dates)[-120:]
            evening = sorted(self._sent_evening_dates)[-120:]
            weekly = sorted(self._sent_weekly_keys)[-30:]
            self._sent_morning_dates = set(morning)
            self._sent_evening_dates = set(evening)
            self._sent_weekly_keys = set(weekly)
            path.write_text(
                json.dumps(
                    {"morning": morning, "evening": evening, "weekly": weekly},
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001
            self._logger.debug("investor sent-flags persist failed", exc_info=True)

    def already_sent_morning(
        self, ist_date: str | None = None, *, laboratory_id: str | None = None
    ) -> bool:
        key = self._lab_day_key(laboratory_id, ist_date or self.ist_today())
        return key in self._sent_morning_dates

    def already_sent_evening(
        self, ist_date: str | None = None, *, laboratory_id: str | None = None
    ) -> bool:
        key = self._lab_day_key(laboratory_id, ist_date or self.ist_today())
        return key in self._sent_evening_dates
    def _research_digest(self, program_id: str) -> dict[str, Any] | None:
        if self._research is None or not hasattr(self._research, "daily_digest"):
            return None
        try:
            return self._research.daily_digest(program_id=program_id)
        except Exception:  # noqa: BLE001
            self._logger.debug("research digest failed", exc_info=True)
            return None

    def recipients(self) -> list[str]:
        got = resolve_investor_recipients(config_to=self._recipients)
        return got

    def available(self) -> bool:
        if not self._enabled:
            return False
        if self._email is None:
            return False
        to = self.recipients()
        if not to:
            return False
        if hasattr(self._email, "smtp_ready"):
            return bool(self._email.smtp_ready())
        if hasattr(self._email, "can_send"):
            return bool(self._email.can_send())
        return bool(getattr(self._email, "available", lambda: False)())

    def status(self) -> dict[str, Any]:
        """Config readiness for the Market page (no secrets)."""
        smtp = {}
        if self._email is not None and hasattr(self._email, "status"):
            try:
                smtp = self._email.status()
            except Exception:  # noqa: BLE001
                smtp = {}
        recipients = self.recipients()
        ready = self.available()
        missing: list[str] = []
        if not smtp.get("host"):
            missing.append("ATLAS_EMAIL_HOST (e.g. smtp.gmail.com)")
        if not smtp.get("from_addr") and not smtp.get("username"):
            missing.append("ATLAS_EMAIL_USERNAME / ATLAS_EMAIL_FROM_ADDR")
        if not smtp.get("password_set"):
            missing.append("ATLAS_SMTP_PASSWORD (Gmail App Password)")
        if not recipients:
            missing.append("ATLAS_INVESTOR_REPORT_TO (comma-separated receivers)")
        return {
            "version": self.VERSION,
            "enabled": self._enabled,
            "ready": ready,
            "recipients": recipients,
            "smtp": smtp,
            "missing": missing,
            "hint": (
                "Set Gmail App Password + receivers in .env, restart Atlas, "
                "then Preview → Send on the Market page."
                if missing
                else "SMTP looks configured — Preview the report, then Send test email."
            ),
        }

    def preview_morning(
        self,
        *,
        program_id: str = "market_intelligence",
        portfolio: dict[str, Any] | None = None,
        catch_up: bool = False,
    ) -> dict[str, Any]:
        """Build the morning email without sending — for Market page review."""
        from atlas.investment import watchlists as wl

        snap = wl.latest(program_id)
        plan = None
        if isinstance(snap, dict):
            plan = (snap.get("extra") or {}).get("daily_plan") or snap.get("daily_plan")
            capital = _portfolio_planning_capital(portfolio)
            if not plan or capital is not None:
                plan = plan_from_watchlist(
                    snap,
                    capital=capital if capital is not None else 10_000.0,
                    portfolio_key=(portfolio or {}).get("portfolio_key"),
                )
        policy = load_snapshot(self._data_dir) if self._data_dir else None
        subject, body = format_morning_report(
            plan=plan,
            portfolio=portfolio,
            policy_snap=policy,
            program_id=program_id,
            research_digest=self._research_digest(program_id),
            catch_up=catch_up,
            laboratory_id=_laboratory_label(portfolio),
        )
        return {
            "subject": subject,
            "body": body,
            "recipients": self.recipients(),
            "ready": self.available(),
            "has_plan": bool(plan and (plan.get("candidates") or plan.get("summary"))),
            "as_of": (plan or {}).get("as_of"),
            "catch_up": catch_up,
            "laboratory_id": _laboratory_label(portfolio),
        }

    def send_morning(
        self,
        *,
        program_id: str = "market_intelligence",
        portfolio: dict[str, Any] | None = None,
        force: bool = False,
        catch_up: bool = False,
        laboratory_id: str | None = None,
    ) -> dict[str, Any]:
        lab = _laboratory_label(portfolio, laboratory_id)
        preview = self.preview_morning(
            program_id=program_id, portfolio=portfolio, catch_up=catch_up
        )
        if not self.available():
            return {
                "sent": False,
                "reason": "email_unavailable",
                "status": self.status(),
                **{k: preview[k] for k in ("subject", "body", "recipients", "as_of")},
            }
        today = self.ist_today()
        if not force and self.already_sent_morning(today, laboratory_id=lab):
            return {
                "sent": False,
                "reason": "already_sent_today",
                "as_of": today,
                "laboratory_id": lab,
                **{k: preview[k] for k in ("subject", "body", "recipients")},
            }
        ok = self._deliver(preview["subject"], preview["body"])
        if ok:
            self._sent_morning_dates.add(self._lab_day_key(lab, today))
            self._persist_sent_flags()
        return {
            "sent": ok,
            "as_of": today,
            "recipients": preview["recipients"],
            "subject": preview["subject"],
            "body": preview["body"],
            "catch_up": catch_up,
            "laboratory_id": lab,
            "reason": None if ok else "smtp_send_failed",
        }

    def preview_evening(
        self,
        *,
        program_id: str = "market_intelligence",
        portfolio: dict[str, Any] | None = None,
        catch_up: bool = False,
    ) -> dict[str, Any]:
        from atlas.investment import watchlists as wl

        snap = wl.latest(program_id)
        plan = None
        if isinstance(snap, dict):
            plan = (snap.get("extra") or {}).get("daily_plan") or snap.get("daily_plan")
            capital = _portfolio_planning_capital(portfolio)
            if not plan or capital is not None:
                plan = plan_from_watchlist(
                    snap,
                    capital=capital if capital is not None else 10_000.0,
                    portfolio_key=(portfolio or {}).get("portfolio_key"),
                )
        policy = load_snapshot(self._data_dir) if self._data_dir else None
        no_fill = None
        if isinstance(portfolio, dict):
            no_fill = portfolio.get("no_fill_reasons")
        subject, body = format_evening_report(
            plan=plan,
            portfolio=portfolio,
            policy_snap=policy,
            program_id=program_id,
            trades=(portfolio or {}).get("recent_trades") if isinstance(portfolio, dict) else None,
            research_digest=self._research_digest(program_id),
            no_fill_reasons=list(no_fill) if no_fill else None,
            catch_up=catch_up,
            decisions=(portfolio or {}).get("decisions") if isinstance(portfolio, dict) else None,
            laboratory_id=_laboratory_label(portfolio),
        )
        return {
            "subject": subject,
            "body": body,
            "recipients": self.recipients(),
            "ready": self.available(),
            "has_plan": bool(plan and (plan.get("candidates") or plan.get("summary"))),
            "as_of": (plan or {}).get("as_of"),
            "catch_up": catch_up,
            "laboratory_id": _laboratory_label(portfolio),
        }

    def send_evening(
        self,
        *,
        program_id: str = "market_intelligence",
        portfolio: dict[str, Any] | None = None,
        force: bool = False,
        catch_up: bool = False,
        laboratory_id: str | None = None,
    ) -> dict[str, Any]:
        lab = _laboratory_label(portfolio, laboratory_id)
        preview = self.preview_evening(
            program_id=program_id, portfolio=portfolio, catch_up=catch_up
        )
        if not self.available():
            return {
                "sent": False,
                "reason": "email_unavailable",
                "status": self.status(),
                **{k: preview[k] for k in ("subject", "body", "recipients", "as_of")},
            }
        today = self.ist_today()
        if not force and self.already_sent_evening(today, laboratory_id=lab):
            return {
                "sent": False,
                "reason": "already_sent_today",
                "as_of": today,
                "laboratory_id": lab,
                **{k: preview[k] for k in ("subject", "body", "recipients")},
            }
        ok = self._deliver(preview["subject"], preview["body"])
        if ok:
            self._sent_evening_dates.add(self._lab_day_key(lab, today))
            self._persist_sent_flags()
        return {
            "sent": ok,
            "as_of": today,
            "recipients": preview["recipients"],
            "subject": preview["subject"],
            "body": preview["body"],
            "catch_up": catch_up,
            "laboratory_id": lab,
            "reason": None if ok else "smtp_send_failed",
        }

    def send_trade(self, **kwargs: Any) -> dict[str, Any]:
        if not self.available():
            return {"sent": False, "reason": "email_unavailable", "status": self.status()}
        if "thesis" not in kwargs and self._research is not None and kwargs.get("symbol"):
            try:
                aw = self._research.awareness(str(kwargs["symbol"]))
                if isinstance(aw.get("thesis"), dict):
                    kwargs = {**kwargs, "thesis": aw.get("thesis")}
            except Exception:  # noqa: BLE001
                pass
        subject, body = format_trade_report(**kwargs)
        ok = self._deliver(subject, body)
        return {
            "sent": ok,
            "recipients": self.recipients(),
            "subject": subject,
            "body": body,
            "reason": None if ok else "smtp_send_failed",
        }

    def preview_weekly_research(
        self,
        *,
        program_id: str = "market_intelligence",
    ) -> dict[str, Any]:
        digest = None
        if self._research is not None and hasattr(self._research, "weekly_learning_digest"):
            try:
                digest = self._research.weekly_learning_digest(program_id=program_id)
            except Exception:  # noqa: BLE001
                self._logger.debug("weekly digest failed", exc_info=True)
                digest = None
        if not isinstance(digest, dict):
            digest = {}
        # DI.6 — embed meta-learning into weekly body
        try:
            from atlas.config import get_config
            from atlas.investment.meta_learning import collect_meta_learning_inputs

            data_dir = str(get_config().paths.data)
            digest["meta_learning"] = collect_meta_learning_inputs(
                data_dir=data_dir,
                portfolio_key="india_equity_learner",
            )
        except Exception:  # noqa: BLE001
            self._logger.debug("DI.6 weekly meta-learning skipped", exc_info=True)
        subject, body = format_weekly_research_report(digest=digest, program_id=program_id)
        return {
            "subject": subject,
            "body": body,
            "recipients": self.recipients(),
            "ready": self.available(),
            "digest": digest,
        }

    def send_weekly_research(
        self,
        *,
        program_id: str = "market_intelligence",
        force: bool = False,
    ) -> dict[str, Any]:
        preview = self.preview_weekly_research(program_id=program_id)
        if not self.available():
            return {
                "sent": False,
                "reason": "email_unavailable",
                "status": self.status(),
                **{k: preview[k] for k in ("subject", "body", "recipients")},
            }
        # ISO week key
        today = datetime.now(timezone.utc)
        week_key = f"{today.isocalendar()[0]}-W{today.isocalendar()[1]:02d}"
        if not force and week_key in self._sent_weekly_keys:
            return {
                "sent": False,
                "reason": "already_sent_this_week",
                "week": week_key,
                **{k: preview[k] for k in ("subject", "body", "recipients")},
            }
        ok = self._deliver(preview["subject"], preview["body"])
        if ok:
            self._sent_weekly_keys.add(week_key)
            self._persist_sent_flags()
        return {
            "sent": ok,
            "week": week_key,
            "recipients": preview["recipients"],
            "subject": preview["subject"],
            "body": preview["body"],
            "reason": None if ok else "smtp_send_failed",
        }

    def _deliver(self, subject: str, body: str) -> bool:
        to = self.recipients()
        try:
            if hasattr(self._email, "send_to"):
                return bool(self._email.send_to(to, subject, body))
            return bool(self._email.send(subject, body))
        except Exception:  # noqa: BLE001
            self._logger.exception("investor report send failed")
            return False
