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


def _format_fundamentals_clarity_section(cov: dict[str, Any]) -> list[str]:
    """Store vs watchlist fundamentals — no PE/FCF conflation (OI-RLD0 D3)."""
    lines = ["", "Fundamentals coverage (DI.4):"]
    n = int(cov.get("symbols") or 0)
    pe = cov.get("with_pe", 0)
    fcf = cov.get("with_fcf", 0)
    roe = cov.get("with_roe")
    pb = cov.get("with_pb")
    roic = cov.get("with_roic")
    ind = cov.get("with_industry_pe_median")
    lines.append("  ACTIVE STORE / BOOK")
    lines.append(f"    PE        {pe}/{n}")
    lines.append(f"    FCF       {fcf}/{n}")
    lines.append(
        f"    ROE       {roe}/{n}" if roe is not None else f"    ROE       ?/{n}"
    )
    lines.append(f"    P/B       {pb}/{n}" if pb is not None else f"    P/B       ?/{n}")
    lines.append(
        f"    ROIC      {roic}/{n}" if roic is not None else f"    ROIC      ?/{n}"
    )
    lines.append(
        f"    Industry PE {ind}/{n}"
        if ind is not None
        else f"    Industry PE ?/{n}"
    )

    gaps = cov.get("learner_gaps") if isinstance(cov.get("learner_gaps"), dict) else {}
    checked = int(gaps.get("symbols_checked") or 0)
    if checked:
        miss_pe = int(gaps.get("missing_pe") or 0)
        miss_fcf = int(gaps.get("missing_fcf") or 0)
        miss_roe = gaps.get("missing_roe")
        with_pe_w = checked - miss_pe
        with_fcf_w = checked - miss_fcf
        lines.append("  ACTIVE WATCHLIST / OPEN-BOOK PRIORITY")
        lines.append(f"    PE        {with_pe_w}/{checked}")
        lines.append(f"    FCF       {with_fcf_w}/{checked}")
        if miss_roe is not None:
            lines.append(f"    ROE       {checked - int(miss_roe)}/{checked}")
        else:
            # Infer from gaps list when available
            gl = gaps.get("gaps") if isinstance(gaps.get("gaps"), list) else []
            roe_miss = sum(
                1
                for g in gl
                if isinstance(g, dict) and "roe" in (g.get("missing") or [])
            )
            if gl:
                lines.append(f"    ROE       {checked - roe_miss}/{checked}")
            else:
                lines.append(f"    ROE       ?/{checked}")
        if gaps.get("symbols_with_gaps"):
            lines.append(
                f"    Names with any critical gap: "
                f"{gaps.get('symbols_with_gaps')}/{checked}"
            )
        lines.append(
            "    Priority: open books + deep watchlist first "
            "(missing ≠ zero; never invent)."
        )
        lines.append(
            "    Fill: GET /v1/market/fundamentals/learner-template "
            "· or POST /v1/market/fundamentals/yahoo-enrich"
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
    return lines


def ranking_trust_status(
    *,
    triage: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
    fundamentals_coverage: dict[str, Any] | None = None,
    coverage_kpis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """OI-RLD0 — is the ranked list trustworthy enough to present as ranked?"""
    triage = triage if isinstance(triage, dict) else {}
    plan = plan if isinstance(plan, dict) else {}
    fund = (
        fundamentals_coverage
        if isinstance(fundamentals_coverage, dict)
        else {}
    )
    kpis = coverage_kpis if isinstance(coverage_kpis, dict) else {}
    cov = triage.get("coverage") if isinstance(triage.get("coverage"), dict) else {}

    price_pct = cov.get("price_coverage_pct")
    if price_pct is None:
        price_pct = kpis.get("price_coverage_pct")
    try:
        price_pct_f = float(price_pct) if price_pct is not None else None
    except (TypeError, ValueError):
        price_pct_f = None

    accel = str(
        cov.get("acceleration_status")
        or kpis.get("acceleration_status")
        or ""
    ).lower()
    hist_ok = accel not in {"", "pending_history", "unknown", "none"}
    if accel in {"ok", "ready", "sufficient", "active"}:
        hist_ok = True
    # Also treat explicit bar depth if present
    depth = cov.get("median_bars") or cov.get("history_days") or kpis.get("median_bars")
    try:
        if depth is not None and float(depth) >= 60:
            hist_ok = True
    except (TypeError, ValueError):
        pass
    # D2 — durable history readiness is the learning foundation (≠ UTS acceleration)
    try:
        dur_hist = cov.get("durable_history_ok_pct")
        if dur_hist is None:
            dur_hist = kpis.get("durable_history_ok_pct")
        if dur_hist is not None and float(dur_hist) >= 95.0:
            hist_ok = True
    except (TypeError, ValueError):
        pass

    fund_n = fund.get("with_pe")
    fund_tot = fund.get("symbols")
    try:
        fund_ok = (
            fund_n is not None
            and fund_tot is not None
            and int(fund_tot) > 0
            and float(fund_n) / float(fund_tot) >= 0.8
        )
    except (TypeError, ValueError):
        fund_ok = False

    phase = str(plan.get("phase") or "").lower()
    conf = str(plan.get("confidence") or "").lower()
    cold = phase in {"learning", "cold_start"} or conf in {"very_low"}

    price_ok = price_pct_f is not None and price_pct_f >= 95.0
    sector_ok = bool(
        cov.get("sector_coverage_ok")
        or kpis.get("sector_coverage_ok")
        or (cov.get("sector_mapped_pct") or 0) >= 80
    )

    reasons: list[str] = []
    if price_pct_f is None:
        reasons.append("Price coverage = unknown")
    elif not price_ok:
        reasons.append(f"Price coverage = {price_pct_f:.1f}% (need ≥95%)")
    else:
        reasons.append(f"Price coverage = {price_pct_f:.1f}%")

    if not hist_ok:
        reasons.append(
            f"Historical depth = insufficient ({accel or 'pending_history'})"
        )
    else:
        dh = cov.get("durable_history_ok_pct") or kpis.get("durable_history_ok_pct")
        reasons.append(
            f"Historical depth = ok"
            + (f" (durable history {dh}%)" if dh is not None else f" ({accel or depth or 'ok'})")
        )

    if fund_tot:
        reasons.append(
            f"Fundamental coverage = {fund_n}/{fund_tot} PE"
            + (" (thin)" if not fund_ok else "")
        )
    else:
        reasons.append("Fundamental coverage = unknown")

    if not sector_ok:
        reasons.append("Sector data sparse or missing")

    # D2 / OI-MKT-COV Phase 1B — live Yahoo last-price alone is not enough
    durable_ok = bool(
        cov.get("durable_bars_ok")
        or kpis.get("durable_bars_ok")
        or str(cov.get("readiness_grade") or kpis.get("readiness_grade") or "")
        .upper()
        in {"A", "B"}
    )
    if durable_ok:
        grade = cov.get("readiness_grade") or kpis.get("readiness_grade") or "B"
        reasons.append(f"Durable OHLCV readiness ≥ B (grade={grade})")
    else:
        reasons.append(
            "Durable OHLCV store not ready (OI-MKT-COV Phase 1B required)"
        )

    # D2 contract: price ≥95% + min history + durable ≥B
    # Acceleration multi-day / sector sparsity are soft warnings, not hard blocks.
    trustworthy = bool(price_ok and hist_ok and durable_ok)
    if cold:
        reasons.append(
            "Plan still phase=learning / confidence very_low — ranks provisional for edge"
        )
        trustworthy = False
    elif conf == "low":
        reasons.append(
            "Confidence=low — ranks usable for triage; not a proven trading edge"
        )

    return {
        "trustworthy": trustworthy,
        "status": "TRUSTWORTHY" if trustworthy else "NOT YET TRUSTWORTHY",
        "price_coverage_pct": price_pct_f,
        "history_ok": hist_ok,
        "durable_bars_ok": durable_ok,
        "fundamentals_ok": fund_ok,
        "sector_ok": sector_ok,
        "reasons": reasons,
    }


def format_ranking_movements_section(
    *,
    ranked: list[dict[str, Any]] | None = None,
    triage: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
    fundamentals_coverage: dict[str, Any] | None = None,
    coverage_kpis: dict[str, Any] | None = None,
    max_rows: int = 15,
) -> list[str]:
    """Watchlist ranking + day/3d movements for morning/evening mail."""
    rows: list[dict[str, Any]] = []
    if isinstance(ranked, list) and ranked:
        rows = [r for r in ranked if isinstance(r, dict) and r.get("symbol")]
    elif isinstance(plan, dict):
        rows = [
            c
            for c in (plan.get("candidates") or [])
            if isinstance(c, dict) and c.get("symbol")
        ]
    if not rows and isinstance(triage, dict):
        # Prefer deep-watch band from persisted ladder when available.
        ladder = [
            r
            for r in (triage.get("rows") or [])
            if isinstance(r, dict) and r.get("symbol")
        ]
        if ladder:
            try:
                max_wl = int(
                    ((triage.get("meta") or {}).get("max_watchlist"))
                    or ((triage.get("coverage") or {}).get("max_watchlist"))
                    or 15
                )
            except (TypeError, ValueError):
                max_wl = 15
            rows = [
                r
                for r in ladder
                if isinstance(r.get("rank"), (int, float)) and int(r["rank"]) <= max_wl
            ] or ladder[:max_wl]

    trust = ranking_trust_status(
        triage=triage,
        plan=plan,
        fundamentals_coverage=fundamentals_coverage,
        coverage_kpis=coverage_kpis,
    )
    lines = ["", "Ranking & movements (deep watchlist):"]
    lines.append(f"  Ranking status: RANKING: {trust['status']}")
    for reason in trust.get("reasons") or []:
        lines.append(f"  Reason: {reason}")
    if not trust.get("trustworthy"):
        lines.append(
            "  Provisional ranking below — do not treat order/scores as strategy edge."
        )

    if not rows:
        lines.append(
            "  (no ranked watchlist yet — await Investment Universe / M0 tick)"
        )
        return lines

    moved = 0
    for r in rows[: max(1, int(max_rows))]:
        sym = r.get("symbol")
        rank = r.get("rank", "?")
        score = r.get("score")
        conf = r.get("confidence") or r.get("phase") or "—"
        d1 = r.get("rank_delta_1d")
        d3 = r.get("rank_delta_3d")
        accel = r.get("acceleration_3d")
        px = r.get("last_price")
        if d1 is not None or d3 is not None or accel is not None:
            moved += 1

        def _delta(v: Any) -> str:
            if v is None:
                return "—"
            try:
                n = int(v)
            except (TypeError, ValueError):
                return str(v)
            return f"{n:+d}" if n != 0 else "0"

        score_s = f"{float(score):.3f}" if isinstance(score, (int, float)) else "—"
        px_s = f"{float(px):.2f}" if isinstance(px, (int, float)) else "—"
        lines.append(
            f"  #{rank} {sym}  score={score_s}  conf={conf}  "
            f"Δ1={_delta(d1)}  Δ3={_delta(d3)}  accel3={_delta(accel)}  px={px_s}"
        )

    if moved == 0:
        lines.append(
            "  Movements: (none yet — need ≥2 triage days with prices; "
            "cold-start ranks stay flat until bars land)"
        )

    # Append accelerating / near-miss one-liners when triage evening is present.
    try:
        from atlas.investment.triage_memory import format_triage_evening_lines

        if isinstance(triage, dict) and triage.get("ok"):
            # Skip the first coverage line — already have ranking table.
            triage_lines = format_triage_evening_lines(triage)
            for ln in triage_lines[1:]:
                lines.append(ln)
    except Exception:  # noqa: BLE001
        pass
    return lines


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
    ]
    data_dir: str | None = None
    try:
        from atlas.config import get_config

        data_dir = str(get_config().paths.data)
    except Exception:  # noqa: BLE001
        data_dir = None

    # OI-LINT0 Phase 6 — learning-first header (allocation → experiences → …)
    exp_doc: dict[str, Any] | None = None
    try:
        from atlas.investment.evening_learning_header import (
            BELOW_FOLD_MARKER,
            format_learning_first_header,
            format_process_metrics_below_fold,
        )
        from atlas.investment.session_notes import (
            format_session_tick_histogram,
            load_day_notes,
        )

        header_lines, _alloc, _learn = format_learning_first_header(
            port=port,
            plan=plan,
            decision_rows=decision_rows,
            day_trades=day_trades,
            buys=buys,
            sells=sells,
            evo=evo,
            data_dir=data_dir,
        )
        lines.extend(header_lines)
        try:
            from atlas.investment.experience_integrity import build_experience_metrics

            exp_doc = (
                port.get("experience_metrics")
                if isinstance(port.get("experience_metrics"), dict)
                else build_experience_metrics(
                    packets=decision_rows,
                    attributions=port.get("attributions")
                    or port.get("recent_attributions"),
                    observations=obs,
                    evolution=evo,
                    positions=pos,
                    fills_buy=len(buys),
                    fills_sell=len(sells),
                )
            )
        except Exception:  # noqa: BLE001
            exp_doc = None
        if isinstance(exp_doc, dict) and int(exp_doc.get("decision_evaluations") or 0) > 20 and int(
            exp_doc.get("trading_experiences") or 0
        ) == 0:
            lines.append(
                "  Note: high evaluation count with 0 trading experiences = "
                "routine checks / open hypotheses — not proven learning."
            )
        lines.extend(
            [
                "",
                BELOW_FOLD_MARKER,
            ]
        )
        lab_key = str(port.get("portfolio_key") or "india_equity_learner")
        ist_day = str(plan.get("as_of") or port.get("ist_date") or "")[:10]
        session_notes = port.get("session_note") if isinstance(port.get("session_note"), dict) else None
        if session_notes is None and data_dir and ist_day:
            session_notes = load_day_notes(
                data_dir, portfolio_key=lab_key, ist_date=ist_day
            )
        lines.extend(format_session_tick_histogram(session_notes))
        lines.extend(format_process_metrics_below_fold(port=port, plan=plan))
    except Exception:  # noqa: BLE001
        # Fallback — preserve pre-Phase-6 experience block if header import fails
        try:
            from atlas.investment.experience_integrity import (
                build_experience_metrics,
                format_experience_metrics_lines,
            )

            exp_doc = (
                port.get("experience_metrics")
                if isinstance(port.get("experience_metrics"), dict)
                else None
            )
            if exp_doc is None:
                exp_doc = build_experience_metrics(
                    packets=decision_rows,
                    attributions=port.get("attributions")
                    or port.get("recent_attributions"),
                    observations=obs,
                    evolution=evo,
                    positions=pos,
                    fills_buy=len(buys),
                    fills_sell=len(sells),
                )
            lines.extend(format_experience_metrics_lines(exp_doc))
        except Exception:  # noqa: BLE001
            lines.extend(
                [
                    f"  Decisions frozen: {len(decision_rows)} "
                    f"(buy={buys_n} sell={sells_n} hold/watch={holds_n})",
                    f"  Sim fills: buys={len(buys)} sells={len(sells)}",
                ]
            )
    lines.append(
        f"  Packet breakdown (raw activity): buy={buys_n} sell={sells_n} "
        f"hold/watch={holds_n} total={len(decision_rows)}"
    )
    lines.extend(
        [
        f"  Packets still missing PE/FCF/MoS: {with_unk}/{len(decision_rows) or 0}",
        f"  Observations ingested: {len(obs)}",
        f"  Revisits due today / future / done: "
        f"{evo.get('revisits_due_today', '—')}/"
        f"{evo.get('pending_future', '—')}/"
        f"{evo.get('done_revisits', '—')}"
        f" (pending total={evo.get('pending_revisits', '—')})",
        ]
    )
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
        f"  Fundamentals PE: {cov.get('with_pe', 0)}/{cov.get('symbols', 0)}"
        f" · FCF holes (watchlist): {gaps.get('missing_fcf', gaps.get('symbols_with_gaps', '—'))}",
        ]
    )
    # Operator brief — changed / causes / uncertain / tomorrow (avoid repeating later)
    lines.extend(["", "── What changed today ──"])
    changed_bits: list[str] = []
    if buys or sells:
        changed_bits.append(
            f"fills buys={len(buys)} sells={len(sells)}"
        )
    if obs:
        changed_bits.append(f"{len(obs)} observations")
    if int(evo.get("done_revisits") or 0) > 0:
        changed_bits.append(f"{evo.get('done_revisits')} revisits completed")
    attrs_n = len(port.get("attributions") or port.get("recent_attributions") or [])
    if attrs_n:
        changed_bits.append(f"{attrs_n} attribution records loaded")
    if not changed_bits:
        changed_bits.append("no material fills — holdings still under observation")
    lines.append("  · " + "; ".join(changed_bits))

    # DAV.1 — causes first (not buried under ranking noise)
    try:
        from atlas.investment.causal_attribution import format_causal_learning_lines

        lines.extend(
            format_causal_learning_lines(
                port.get("attributions") or port.get("recent_attributions")
            )
        )
    except Exception:  # noqa: BLE001
        pass

    lines.extend(["", "── What Atlas is uncertain about ──"])
    uncertain: list[str] = []
    if with_unk:
        uncertain.append(
            f"{with_unk} packets still missing PE/FCF/MoS at decide-time"
        )
    if gaps.get("missing_fcf") or (
        isinstance(gaps.get("symbols_with_gaps"), int)
        and int(gaps.get("symbols_with_gaps") or 0) > 0
    ):
        uncertain.append(
            "FCF / quality metrics thin — switch & buy gates stay fail-closed"
        )
    switch_blocks = sum(
        1
        for d in decision_rows
        if isinstance(d, dict)
        and "missing_er" in str(d.get("strategy_tag") or d.get("reasons_against") or "")
    )
    if switch_blocks:
        uncertain.append(
            f"{switch_blocks} hold/switch reviews blocked on missing E[R]/confidence"
        )
    if str(plan.get("phase") or kpis.get("phase") or "") == "learning":
        uncertain.append("ranking still cold-start (phase=learning / confidence low)")
    if not uncertain:
        uncertain.append("(no hard uncertainty flags listed)")
    for u in uncertain[:6]:
        lines.append(f"  · {u}")

    lines.extend(["", "── What Atlas will do tomorrow ──"])
    tomorrow = [
        "Keep Strategy V1 (SMA/RSI + PLC exits) as control — no silent strategy mutation",
        "RLD: raise price coverage ≥95% before trusting ranks; FCF/fundamentals for open books",
        "News/sector timeline on open books — attribution needs evidence, not all-unknown",
        "Count evaluations ≠ unique states ≠ trading experiences (never inflate IQ on HOLDs)",
    ]
    for t in tomorrow:
        lines.append(f"  · {t}")

    # UTS — ranking table + movements + triage honesty
    try:
        ranked = port.get("ranked") if isinstance(port.get("ranked"), list) else None
        if ranked is None and isinstance(plan, dict):
            ranked = plan.get("candidates")
        triage_doc = port.get("triage") if isinstance(port.get("triage"), dict) else None
        ranking_lines = format_ranking_movements_section(
            ranked=ranked if isinstance(ranked, list) else None,
            triage=triage_doc,
            plan=plan,
            fundamentals_coverage=cov,
            coverage_kpis=port.get("coverage_kpis")
            if isinstance(port.get("coverage_kpis"), dict)
            else None,
        )
        lines.extend(ranking_lines)
        if not any("Universe triage" in ln or "Accelerating" in ln for ln in ranking_lines):
            from atlas.investment.triage_memory import format_triage_evening_lines

            lines.extend(format_triage_evening_lines(triage_doc))
    except Exception:  # noqa: BLE001
        pass
    # UTS.F — missed opportunity ledger honesty
    try:
        from atlas.investment.missed_opportunity import (
            format_missed_opportunity_evening_lines,
            load_missed_ledger,
        )

        miss_doc = (
            port.get("missed_opportunities")
            if isinstance(port.get("missed_opportunities"), dict)
            else None
        )
        if miss_doc is None:
            try:
                from atlas.config import get_config

                miss_doc = load_missed_ledger(
                    str(get_config().paths.data),
                    laboratory_id=str(
                        port.get("portfolio_key") or "india_equity_learner"
                    ),
                )
            except Exception:  # noqa: BLE001
                miss_doc = None
        lines.extend(format_missed_opportunity_evening_lines(miss_doc))
    except Exception:  # noqa: BLE001
        pass
    # OI-MTL0 — open-book market timeline (price/tech/fund/sector/market/news/policy/atlas)
    try:
        from atlas.investment.market_timeline import (
            build_open_book_timelines,
            format_market_timeline_evening_lines,
            load_timeline_day,
        )

        tl = (
            port.get("market_timeline")
            if isinstance(port.get("market_timeline"), dict)
            else None
        )
        if tl is None:
            try:
                from atlas.config import get_config

                data_dir = str(get_config().paths.data)
                lab = str(
                    port.get("portfolio_key")
                    or port.get("laboratory_id")
                    or "india_equity_learner"
                )
                tl = load_timeline_day(data_dir, laboratory_id=lab)
                if not tl.get("ok") or not tl.get("rows"):
                    syms: list[str] = []
                    for p in pos:
                        s = str(p.get("symbol") or "").strip().upper()
                        if s and s not in syms:
                            syms.append(s)
                    if not syms:
                        for s in (
                            "APOLLOHOSP.NS",
                            "ASIANPAINT.NS",
                            "BHARTIARTL.NS",
                            "CIPLA.NS",
                            "EICHERMOT.NS",
                        ):
                            syms.append(s)
                        for c in (plan.get("candidates") or [])[:5]:
                            if isinstance(c, dict) and c.get("symbol"):
                                s = str(c["symbol"]).upper()
                                if s not in syms:
                                    syms.append(s)
                    dec_map: dict[str, list] = {}
                    for d in decision_rows:
                        if not isinstance(d, dict) or not d.get("symbol"):
                            continue
                        dec_map.setdefault(str(d["symbol"]).upper(), []).append(d)
                    tl = build_open_book_timelines(
                        data_dir,
                        syms[:8],
                        laboratory_id=lab,
                        decisions_by_symbol=dec_map,
                        persist=True,
                    )
            except Exception:  # noqa: BLE001
                tl = None
        lines.extend(format_market_timeline_evening_lines(tl))
    except Exception:  # noqa: BLE001
        pass
    # UTS.G — hard coverage KPI block
    try:
        from atlas.investment.coverage_kpis import (
            build_coverage_kpis,
            format_coverage_kpi_evening_lines,
        )

        from atlas.config import get_config

        kpis = port.get("coverage_kpis") if isinstance(port.get("coverage_kpis"), dict) else None
        if kpis is None:
            kpis = build_coverage_kpis(
                str(get_config().paths.data),
                program_id=str(port.get("program_id") or "market_intelligence"),
                laboratory_id=str(port.get("portfolio_key") or "india_equity_learner"),
            )
        lines.extend(format_coverage_kpi_evening_lines(kpis))
    except Exception:  # noqa: BLE001
        pass
    # DAV — sizing learning journal (proposals only)
    try:
        from atlas.investment.sizing_learning import (
            format_sizing_learning_evening_lines,
            load_sizing_journal,
        )

        from atlas.config import get_config

        sz = (
            port.get("sizing_learning")
            if isinstance(port.get("sizing_learning"), dict)
            else None
        )
        if sz is None:
            sz = load_sizing_journal(
                str(get_config().paths.data),
                laboratory_id=str(port.get("portfolio_key") or "india_equity_learner"),
            )
        lines.extend(format_sizing_learning_evening_lines(sz))
    except Exception:  # noqa: BLE001
        pass
    # CF.1 — counterfactual panels (beat / matched / lost)
    try:
        from atlas.investment.counterfactual_learning import (
            format_counterfactual_evening_lines,
        )
        from atlas.config import get_config

        lines.extend(
            format_counterfactual_evening_lines(
                str(get_config().paths.data),
                laboratory_id=str(port.get("portfolio_key") or "india_equity_learner"),
            )
        )
    except Exception:  # noqa: BLE001
        pass
    # Atlas IQ detail stays below operational ranking noise (Phase 6)
    iq = port.get("atlas_iq") if isinstance(port.get("atlas_iq"), dict) else None
    if iq:
        try:
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
        except Exception:  # noqa: BLE001
            pass
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
        due_n = evo.get("revisits_due_today")
        future_n = evo.get("pending_future")
        if due_n is not None or future_n is not None:
            if int(due_n or 0) == 0 and int(future_n or 0) > 0:
                blockers.append(
                    f"Revisits scheduled but not due yet "
                    f"(future={future_n}, due_today=0, done=0) — "
                    "evolution mission OK; waiting on due_ist (not dead)"
                )
            elif int(due_n or 0) > 0:
                blockers.append(
                    f"{due_n} revisits due today with 0 done — "
                    "confirm Decision Evolution is ticking / Host Guard budget"
                )
            else:
                blockers.append(
                    f"{evo.get('pending_revisits')} revisits pending, 0 done"
                )
        else:
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

    lines.extend([""])
    try:
        from atlas.investment.plc_exits import format_exit_rules_lines

        lines.extend(format_exit_rules_lines())
    except Exception:  # noqa: BLE001
        lines.extend(
            [
                "  When Atlas sells (current rule — P10 sim):",
                "    · Technical exit: SMA fast falls below SMA slow while a position is held.",
            ]
        )
    # PLC.B — surface primary failure causes from recent exit attributions
    recent_attrs = [
        a
        for a in (port.get("attributions") or port.get("recent_attributions") or [])
        if isinstance(a, dict)
    ]
    causes = []
    for a in recent_attrs[:20]:
        payload = a.get("payload") if isinstance(a.get("payload"), dict) else a
        extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
        cause = (
            payload.get("failure_cause")
            or extra.get("failure_cause")
            or a.get("failure_cause")
        )
        code = extra.get("exit_reason_code") or a.get("exit_reason_code")
        sym = a.get("symbol") or payload.get("symbol")
        if cause or code:
            causes.append(
                f"{sym or '?'}: exit={code or '?'} cause={cause or 'unlabeled'}"
            )
    if causes:
        lines.append("  Primary exit causes (recent):")
        for c in causes[:8]:
            lines.append(f"    · {c}")
    lines.extend(
        [
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
    # PLC.C — cite today's open-book daily packs when present on the portfolio doc
    pack_ids: list[str] = []
    for row in obs:
        if not isinstance(row, dict):
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else row
        if str(payload.get("kind") or "") != "open_book_daily_pack":
            continue
        oid = str(row.get("id") or payload.get("id") or "").strip()
        sym = str(payload.get("symbol") or row.get("symbol") or "").strip()
        if oid:
            pack_ids.append(f"{sym or '?'}→{oid[:12]}")
    if pack_ids:
        lines.append(
            "  Open-book daily packs today (PLC.C sensory continuity): "
            + ", ".join(pack_ids[:10])
        )
    elif pos:
        lines.append(
            "  Open-book daily packs today: (none yet — market_observer PLC.C "
            "records once per IST day when Host Guard allows)"
        )
    # PLC.D — open buy hypotheses
    try:
        from atlas.config import get_config
        from atlas.investment.plc_hypothesis import format_hypothesis_digest_lines

        data_dir = str(get_config().paths.data)
        lab = str(
            port.get("portfolio_key")
            or port.get("laboratory_id")
            or "india_equity_learner"
        )
        lines.extend(
            format_hypothesis_digest_lines(
                data_dir, laboratory_id=lab, portfolio_key=lab, limit=6
            )
        )
    except Exception:  # noqa: BLE001
        pass
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


def _lab_books_arg(
    portfolio: dict[str, Any] | None,
    lab_books: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if lab_books:
        return [b for b in lab_books if isinstance(b, dict)]
    if isinstance(portfolio, dict) and isinstance(portfolio.get("lab_books"), list):
        return [b for b in portfolio["lab_books"] if isinstance(b, dict)]
    return []


def format_three_lab_books_section(
    lab_books: list[dict[str, Any]] | None,
) -> list[str]:
    """Compact cash / positions board for all three paper laboratories."""
    from atlas.investment.laboratory import MAIL_LAB_TITLES

    books = [b for b in (lab_books or []) if isinstance(b, dict)]
    if not books:
        return []
    lines = ["", "══ Three laboratories (paper books) ══"]
    for book in books:
        key = str(
            book.get("portfolio_key") or book.get("laboratory_id") or "lab"
        ).strip()
        title = MAIL_LAB_TITLES.get(key) or str(book.get("label") or key)
        cash = book.get("cash")
        equity = book.get("equity")
        if equity is None:
            equity = book.get("equity_value")
        lines.append(f"{title} [{key}]")
        lines.append(
            f"  Cash {_money(cash)} · holdings {_money(book.get('holdings_value'))} "
            f"· equity {_money(equity)}"
        )
        pnl = book.get("day_pnl")
        tot = book.get("total_pnl")
        if pnl is not None or tot is not None:
            lines.append(
                f"  P&L today {_signed_money(pnl)} · total {_signed_money(tot)}"
            )
        basis = book.get("valuation_basis")
        if basis:
            lines.append(f"  Valuation: {basis}")
        pos = book.get("positions") or book.get("holdings") or []
        if isinstance(pos, dict):
            pos = [
                {"symbol": k, **(v if isinstance(v, dict) else {})}
                for k, v in pos.items()
            ]
        pos_rows = [p for p in pos if isinstance(p, dict)]
        if not pos_rows:
            lines.append("  Positions: (none)")
        else:
            lines.append(f"  Positions ({len(pos_rows)}):")
            for p in pos_rows[:12]:
                lines.append(
                    f"    · {p.get('symbol')}: qty={p.get('quantity') or p.get('qty')} "
                    f"avg={p.get('avg_price') or p.get('avg_cost')} "
                    f"mark={p.get('mark')} uPnL={_signed_money(p.get('unrealized_pnl'))}"
                )
        reasons = book.get("no_fill_reasons")
        if isinstance(reasons, list) and reasons:
            lines.append(f"  Idle/hold: {reasons[0]}")
    lines.append(
        "Books are isolated laboratories — do not add the three equities into one P&L."
    )
    return lines


def format_morning_report(
    *,
    plan: dict[str, Any] | None,
    portfolio: dict[str, Any] | None = None,
    policy_snap: dict[str, Any] | None = None,
    program_id: str = "market_intelligence",
    research_digest: dict[str, Any] | None = None,
    catch_up: bool = False,
    laboratory_id: str | None = None,
    morning_hypothesis: dict[str, Any] | None = None,
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
    lines.extend(format_three_lab_books_section(_lab_books_arg(portfolio)))
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

    # BRE.4 — morning hypotheses / evidence needed
    try:
        from atlas.investment.morning_hypothesis import format_morning_hypothesis_section

        mh = morning_hypothesis
        if mh is None and isinstance(portfolio, dict):
            mh = portfolio.get("morning_hypothesis")
        lines.extend(format_morning_hypothesis_section(mh if isinstance(mh, dict) else None))
    except Exception:  # noqa: BLE001
        pass

    # OI-DCA0 — Daily Cognitive Agenda
    try:
        from atlas.investment.daily_cognitive_agenda import format_agenda_section

        agenda = None
        if isinstance(portfolio, dict):
            agenda = portfolio.get("cognitive_agenda")
        lines.extend(
            format_agenda_section(
                agenda if isinstance(agenda, dict) else None, when="morning"
            )
        )
    except Exception:  # noqa: BLE001
        pass

    # Ranking & movements (UTS) — full watchlist table with Δ1/Δ3/accel
    try:
        ranked = None
        triage = None
        if isinstance(portfolio, dict):
            ranked = portfolio.get("ranked") if isinstance(portfolio.get("ranked"), list) else None
            triage = portfolio.get("triage") if isinstance(portfolio.get("triage"), dict) else None
        lines.extend(
            format_ranking_movements_section(
                ranked=ranked,
                triage=triage,
                plan=plan,
                fundamentals_coverage=(
                    portfolio.get("fundamentals_coverage")
                    if isinstance(portfolio, dict)
                    and isinstance(portfolio.get("fundamentals_coverage"), dict)
                    else None
                ),
                coverage_kpis=(
                    portfolio.get("coverage_kpis")
                    if isinstance(portfolio, dict)
                    and isinstance(portfolio.get("coverage_kpis"), dict)
                    else None
                ),
            )
        )
    except Exception:  # noqa: BLE001
        pass

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
    lines.extend(format_three_lab_books_section(_lab_books_arg(portfolio)))

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

    # BRE.1 — mind-change + evidence delta (structured; may be empty/unchanged)
    try:
        from atlas.investment.world_state import (
            format_evidence_delta_section,
            format_mind_change_section,
        )

        wso_rows = []
        if isinstance(portfolio, dict):
            wso_rows = list(portfolio.get("world_states") or portfolio.get("wsos") or [])
        delta = None
        if isinstance(portfolio, dict) and isinstance(portfolio.get("evidence_delta"), dict):
            delta = portfolio.get("evidence_delta")
        lines.extend(format_mind_change_section(wso_rows))
        lines.extend(format_evidence_delta_section(delta))
        # Amendment C — Belief Revisions /week (JIS core line)
        try:
            from atlas.investment.daily_cognitive_agenda import (
                format_jis_revisions_section,
            )

            jis = None
            if isinstance(portfolio, dict):
                jis = portfolio.get("jis_revisions")
            lines.extend(
                format_jis_revisions_section(jis if isinstance(jis, dict) else None)
            )
        except Exception:  # noqa: BLE001
            pass
        # OI-SELF-REFLECT evening narrative
        try:
            from atlas.reasoning.reflection import format_reflection_section

            refl = None
            if isinstance(portfolio, dict):
                refl = portfolio.get("reflection")
            lines.extend(
                format_reflection_section(refl if isinstance(refl, dict) else None)
            )
        except Exception:  # noqa: BLE001
            pass
        # OI-DCA0 evening progress
        try:
            from atlas.investment.daily_cognitive_agenda import format_agenda_section

            agenda = None
            if isinstance(portfolio, dict):
                agenda = portfolio.get("cognitive_agenda")
            lines.extend(
                format_agenda_section(
                    agenda if isinstance(agenda, dict) else None, when="evening"
                )
            )
        except Exception:  # noqa: BLE001
            pass
        # BRE.5 — lab-level global mind
        try:
            from atlas.investment.global_mind import format_global_mind_section

            gw = None
            if isinstance(portfolio, dict):
                gw = portfolio.get("global_wso")
            lines.extend(format_global_mind_section(gw if isinstance(gw, dict) else None))
        except Exception:  # noqa: BLE001
            pass
        # MEM.1 — memory distill
        try:
            from atlas.investment.memory_distill import format_memory_distill_section

            md = None
            if isinstance(portfolio, dict):
                md = portfolio.get("memory_distill")
            lines.extend(
                format_memory_distill_section(md if isinstance(md, dict) else None)
            )
        except Exception:  # noqa: BLE001
            pass
        # IQ.1 — calibration slice
        try:
            from atlas.investment.learning_intelligence import format_calibration_section

            iq = portfolio.get("atlas_iq") if isinstance(portfolio, dict) else None
            curve = None
            if isinstance(iq, dict):
                curve = iq.get("confidence_calibration")
            rev = None
            if isinstance(portfolio, dict):
                rev = portfolio.get("revision_calibration")
            lines.extend(
                format_calibration_section(
                    confidence_curve=curve if isinstance(curve, dict) else None,
                    revision_calibration=rev if isinstance(rev, dict) else None,
                )
            )
        except Exception:  # noqa: BLE001
            pass
        # META.1 — reasoning-pattern ledger
        try:
            from atlas.investment.meta_cognition import format_meta_cognition_section

            meta = None
            if isinstance(portfolio, dict):
                meta = portfolio.get("meta_cognition")
            lines.extend(
                format_meta_cognition_section(meta if isinstance(meta, dict) else None)
            )
        except Exception:  # noqa: BLE001
            pass
        # GENE.1 — decision genealogy sample
        try:
            from atlas.investment.decision_genealogy import (
                format_genealogy_evening_lines,
            )

            gens = None
            if isinstance(portfolio, dict):
                gens = portfolio.get("genealogies")
            lines.extend(
                format_genealogy_evening_lines(gens if isinstance(gens, list) else None)
            )
        except Exception:  # noqa: BLE001
            pass
        # CWS — cognitive work quota
        try:
            from atlas.investment.cognitive_work import format_cws_section

            cws = portfolio.get("cognitive_work") if isinstance(portfolio, dict) else None
            lines.extend(format_cws_section(cws if isinstance(cws, dict) else None))
        except Exception:  # noqa: BLE001
            pass
        cq = None
        if isinstance(portfolio, dict):
            cq = portfolio.get("curiosity_queue")
        if isinstance(cq, dict) and cq.get("enqueued_tonight"):
            lines.extend(
                [
                    "",
                    "--- Curiosity queue (CUR.1) ---",
                    f"enqueued_tonight={cq.get('enqueued_tonight')} "
                    f"(unknowns → research; max_n={cq.get('max_n')})",
                ]
            )
            for it in list(cq.get("items") or [])[-5:]:
                if isinstance(it, dict) and it.get("status") in {"queued", "ira_started"}:
                    lines.append(
                        f"  {it.get('symbol')}: {it.get('unknown')} [{it.get('status')}]"
                    )
        if isinstance(cq, dict) and (
            cq.get("news_drain")
            or cq.get("allocation_filtered_skipped")
            or cq.get("work_started_n")
        ):
            try:
                from atlas.investment.research_intelligence import (
                    format_research_intelligence_lines,
                )

                lines.extend(format_research_intelligence_lines(cq))
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        lines.extend(
            [
                "",
                "--- Belief / mind-change (WSO) ---",
                "No beliefs changed today.",
                "",
                "--- Evidence delta (today) ---",
                "Evidence delta unavailable.",
            ]
        )

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
        # BRE.3 — join async decide-time rationale sidecars
        try:
            from atlas.investment.decide_rationale import format_decide_rationale_lines
            from atlas.config import get_config

            lines.extend(
                format_decide_rationale_lines(
                    str(get_config().paths.data),
                    decision_rows,
                    laboratory_id=str(lab or "india_equity_learner"),
                )
            )
        except Exception:  # noqa: BLE001
            pass
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

    # DI.4 — fundamentals honesty (store vs watchlist — never conflate)
    try:
        cov = None
        if isinstance(portfolio, dict):
            cov = portfolio.get("fundamentals_coverage")
        if isinstance(cov, dict):
            lines.extend(_format_fundamentals_clarity_section(cov))
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
        lab_note = None
        try:
            from atlas.investment.index_proxy_lot import KPI_LABEL, VALUATION_BASIS

            basis = str(portfolio.get("valuation_basis") or "")
            if VALUATION_BASIS in basis or portfolio.get("kpi_label"):
                lab_note = str(portfolio.get("kpi_label") or KPI_LABEL)
        except Exception:  # noqa: BLE001
            lab_note = None
        lines.append(
            f"End-of-day portfolio snapshot{f' — {lab_note}' if lab_note else ''}:"
        )
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
    lab_books: list[dict[str, Any]] | None = None,
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
    lines.extend(
        format_three_lab_books_section(_lab_books_arg(None, lab_books))
    )
    lines.append("")
    lines.append("Not a live broker order. Simulation Program only (P10).")
    return subject, "\n".join(lines)


def format_hourly_activity_report(
    *,
    portfolio: dict[str, Any] | None = None,
    program_id: str = "market_intelligence",
    laboratory_id: str | None = None,
    hour: int = 12,
    ist_date: str | None = None,
) -> tuple[str, str]:
    """OI-HOURLY0 — hourly activity / learning / CWS awareness (08–20 IST)."""
    port = portfolio if isinstance(portfolio, dict) else {}
    lab = _laboratory_label(port, laboratory_id)
    day = ist_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    subject = f"[Atlas][{lab}] Hourly {hour:02d}:00 IST — {day}"
    lines = [
        "Atlas hourly activity digest (simulation — not broker orders)",
        f"Date: {day} · Hour: {hour:02d}:00 IST",
        f"Program: {program_id}",
        f"Laboratory: {lab}",
    ]
    lines.extend(format_three_lab_books_section(_lab_books_arg(port)))
    lines.extend(
        [
            "",
            "══ Activity this hour (operator awareness) ══",
        ]
    )
    cash = port.get("cash")
    equity = port.get("equity") or port.get("equity_value")
    lines.append(f"Book: cash={_money(cash)} · equity={_money(equity)}")
    day_pnl = port.get("day_pnl")
    total_pnl = port.get("total_pnl")
    lines.append(
        f"P&L: today={_signed_money(day_pnl)} · total={_signed_money(total_pnl)}"
    )
    pos = port.get("positions") or port.get("holdings") or []
    if isinstance(pos, dict):
        pos_rows = [
            {"symbol": k, **(v if isinstance(v, dict) else {})} for k, v in pos.items()
        ]
    else:
        pos_rows = [p for p in (pos or []) if isinstance(p, dict)]
    lines.append(f"Open positions: {len(pos_rows)}")
    for p in pos_rows[:6]:
        lines.append(
            f"  · {p.get('symbol')}: qty={p.get('quantity') or p.get('qty')} "
            f"mark={p.get('mark')} uPnL={_signed_money(p.get('unrealized_pnl'))}"
        )
    notes = port.get("session_note") or port.get("reason_counts")
    if isinstance(notes, dict) and notes.get("reason_counts"):
        rc = notes.get("reason_counts") or notes
        top = sorted(rc.items(), key=lambda kv: -int(kv[1] or 0))[:5]
        lines.append("Session reason tops: " + ", ".join(f"{k}={v}" for k, v in top))
    elif isinstance(port.get("no_fill_reasons"), list):
        lines.append("Recent idle/hold samples:")
        for r in list(port.get("no_fill_reasons") or [])[:4]:
            lines.append(f"  · {r}")

    lines.append("")
    lines.append("══ Learning / cognition ══")
    dec = list(port.get("decisions") or [])
    buys = sum(1 for d in dec if str((d or {}).get("action") or "").lower() == "buy")
    sells = sum(1 for d in dec if str((d or {}).get("action") or "").lower() == "sell")
    holds = sum(
        1 for d in dec if str((d or {}).get("action") or "").lower() in {"hold", "watch"}
    )
    lines.append(f"Decisions snapshot: buy={buys} sell={sells} hold/watch={holds}")
    try:
        from atlas.investment.cognitive_work import format_cws_section

        lines.extend(format_cws_section(port.get("cognitive_work")))
    except Exception:  # noqa: BLE001
        pass
    lines.append("")
    lines.append(
        "Honesty: Hourly mail is awareness, not a claim of edge. "
        "Evening remains the deep judgment report."
    )
    lines.append("— Atlas Resource OS / Market Program · P10 simulation only")
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
        self._llm = None
        self._reasoning = None
        self._logger = logger or logging.getLogger("atlas.investment.reports")
        # LI.1b: keys are "laboratory_id|YYYY-MM-DD" (legacy bare dates → default swing lab)
        self._sent_morning_dates: set[str] = set()
        self._sent_evening_dates: set[str] = set()
        self._sent_hourly_keys: set[str] = set()
        self._sent_weekly_keys: set[str] = set()
        self._load_sent_flags()

    def bind_research(self, research: Any) -> None:
        self._research = research

    def bind_llm(self, llm: Any) -> None:
        """Optional LLM for BRE.2 evening belief revision."""
        self._llm = llm

    def bind_reasoning(self, reasoning: Any) -> None:
        """OI-SELF0 — ReasoningService for Belief Core reflection / JIS."""
        self._reasoning = reasoning

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
            for k in raw.get("hourly") or []:
                self._sent_hourly_keys.add(str(k))
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
            hourly = sorted(self._sent_hourly_keys)[-400:]
            weekly = sorted(self._sent_weekly_keys)[-30:]
            self._sent_morning_dates = set(morning)
            self._sent_evening_dates = set(evening)
            self._sent_hourly_keys = set(hourly)
            self._sent_weekly_keys = set(weekly)
            path.write_text(
                json.dumps(
                    {
                        "morning": morning,
                        "evening": evening,
                        "hourly": hourly,
                        "weekly": weekly,
                    },
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

    def already_sent_hourly(
        self,
        ist_date: str | None = None,
        *,
        hour: int,
        laboratory_id: str | None = None,
    ) -> bool:
        day = ist_date or self.ist_today()
        key = f"{self._lab_day_key(laboratory_id, day)}|{int(hour):02d}"
        return key in self._sent_hourly_keys

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
        port = dict(portfolio) if isinstance(portfolio, dict) else {}
        if isinstance(snap, dict):
            plan = (snap.get("extra") or {}).get("daily_plan") or snap.get("daily_plan")
            capital = _portfolio_planning_capital(portfolio)
            if not plan or capital is not None:
                plan = plan_from_watchlist(
                    snap,
                    capital=capital if capital is not None else 10_000.0,
                    portfolio_key=(portfolio or {}).get("portfolio_key"),
                )
            # Attach ranked (+ triage if present) so morning mail has movements.
            if snap.get("ranked"):
                port.setdefault("ranked", list(snap.get("ranked") or []))
            if port.get("triage") is None and self._data_dir:
                try:
                    from atlas.investment.triage_memory import load_latest_triage_bundle

                    port["triage"] = load_latest_triage_bundle(
                        self._data_dir, program_id=program_id
                    )
                except Exception:  # noqa: BLE001
                    pass
            portfolio = port
        # BRE.4 — morning hypothesis / evidence-needed BATCH
        try:
            from atlas.investment.morning_hypothesis import run_morning_hypothesis_batch
            from atlas.investment.world_state import sync_open_book_wsos

            lab = str(
                port.get("laboratory_id")
                or port.get("portfolio_key")
                or "india_equity_learner"
            )
            pos = port.get("positions") or port.get("holdings") or []
            if isinstance(pos, dict):
                syms = [str(k) for k in pos.keys() if k]
            else:
                syms = [
                    str(p.get("symbol"))
                    for p in (pos or [])
                    if isinstance(p, dict) and p.get("symbol")
                ]
            wsos: list = []
            if syms and self._data_dir:
                wsos = sync_open_book_wsos(self._data_dir, lab, syms)
                port["world_states"] = wsos
            mh = run_morning_hypothesis_batch(
                self._data_dir,
                laboratory_id=lab,
                llm=getattr(self, "_llm", None),
                wsos=wsos,
                plan=plan if isinstance(plan, dict) else None,
                open_symbols=set(syms),
            )
            port["morning_hypothesis"] = mh
            # OI-DCA0 — publish today's thinking agenda
            try:
                from atlas.investment.daily_cognitive_agenda import build_daily_agenda

                ranked = []
                if isinstance(plan, dict):
                    ranked = list(plan.get("candidates") or [])
                if isinstance(port.get("ranked"), list):
                    ranked = list(port.get("ranked") or ranked)
                agenda = build_daily_agenda(
                    self._data_dir,
                    laboratory_id=lab,
                    wsos=wsos,
                    open_symbols=set(syms),
                    ranked=ranked,
                )
                port["cognitive_agenda"] = agenda
            except Exception:  # noqa: BLE001
                self._logger.debug("DCA morning publish skipped", exc_info=True)
            portfolio = port
        except Exception:  # noqa: BLE001
            self._logger.debug("BRE.4 morning batch skipped", exc_info=True)
        policy = load_snapshot(self._data_dir) if self._data_dir else None
        subject, body = format_morning_report(
            plan=plan,
            portfolio=portfolio,
            policy_snap=policy,
            program_id=program_id,
            research_digest=self._research_digest(program_id),
            catch_up=catch_up,
            laboratory_id=_laboratory_label(portfolio),
            morning_hypothesis=(
                portfolio.get("morning_hypothesis")
                if isinstance(portfolio, dict)
                else None
            ),
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
            "morning_hypothesis": (
                portfolio.get("morning_hypothesis")
                if isinstance(portfolio, dict)
                else None
            ),
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
        try:
            from atlas.activity import record_activity

            record_activity(
                domain="market",
                worker="investor_mailer",
                action="send_morning_plan",
                target=lab,
                result="completed" if ok else "failed",
                summary=(
                    f"Sent morning investor plan for {lab}"
                    if ok
                    else f"Morning investor plan failed for {lab}"
                ),
                evidence={"laboratory_id": lab, "as_of": today, "sent": ok},
            )
        except Exception:  # noqa: BLE001
            pass
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
        port = dict(portfolio) if isinstance(portfolio, dict) else {}
        # BRE.1 — ensure WSO shells for open positions; attach evening sections
        try:
            from atlas.investment.world_state import (
                evidence_delta_counts,
                sync_open_book_wsos,
            )

            lab = str(
                port.get("laboratory_id")
                or port.get("portfolio_key")
                or "india_equity_learner"
            )
            pos = port.get("positions") or port.get("holdings") or []
            if isinstance(pos, dict):
                syms = [str(k) for k in pos.keys() if k]
            else:
                syms = [
                    str(p.get("symbol"))
                    for p in (pos or [])
                    if isinstance(p, dict) and p.get("symbol")
                ]
            if syms and self._data_dir:
                # J2 — stamp WSO unknowns from open-book fundamental gaps
                miss_map: dict[str, list[str]] = {}
                try:
                    from atlas.investment.fundamentals import (
                        OPEN_BOOK_CRITICAL_FIELDS,
                        learner_fundamentals_gaps,
                    )

                    gaps_doc = learner_fundamentals_gaps(
                        self._data_dir,
                        syms,
                        program_id=program_id
                        if program_id
                        else "market_intelligence",
                        critical_fields=OPEN_BOOK_CRITICAL_FIELDS,
                    )
                    port["fundamentals_coverage"] = {
                        **(
                            port.get("fundamentals_coverage")
                            if isinstance(port.get("fundamentals_coverage"), dict)
                            else {}
                        ),
                        "learner_gaps": gaps_doc,
                    }
                    for g in gaps_doc.get("gaps") or []:
                        if not isinstance(g, dict):
                            continue
                        gs = str(g.get("symbol") or "").strip()
                        if gs:
                            miss_map[gs] = [str(x) for x in (g.get("missing") or [])]
                            miss_map[gs.upper()] = miss_map[gs]
                except Exception:  # noqa: BLE001
                    self._logger.debug("J2 open-book gaps skipped", exc_info=True)
                wsos = sync_open_book_wsos(
                    self._data_dir,
                    lab,
                    syms,
                    missing_fundamentals=miss_map or None,
                )
                port["world_states"] = wsos
                seed_n = 0
                news_n = 0
                for row in list(port.get("observations") or []):
                    if not isinstance(row, dict):
                        continue
                    from atlas.investment.symbol_aliases import news_is_evidence

                    kind = str(row.get("kind") or "")
                    if "news" not in kind and "news" not in str(row.get("source") or ""):
                        continue
                    if news_is_evidence(row):
                        news_n += 1
                    else:
                        seed_n += 1
                port["evidence_delta"] = evidence_delta_counts(
                    news_n=news_n,
                    seed_news_n=seed_n,
                    fundamentals_n=int(
                        (port.get("fundamentals_coverage") or {}).get("with_pe") or 0
                    )
                    if isinstance(port.get("fundamentals_coverage"), dict)
                    else 0,
                )
                # CUR.1 / J4 — unknowns → curiosity queue + real IRA work (persist statuses)
                try:
                    from atlas.investment.capital_allocation import (
                        load_allocation_table,
                        merge_allocation_curiosity,
                    )
                    from atlas.investment.curiosity import (
                        drain_queue_work,
                        save_queue,
                    )

                    alloc_tbl = load_allocation_table(self._data_dir, lab)
                    blockers = []
                    try:
                        from atlas.investment.capital_allocation import (
                            allocation_blocking_unknowns,
                        )

                        blockers = allocation_blocking_unknowns(alloc_tbl)
                    except Exception:  # noqa: BLE001
                        blockers = []
                    qdoc = drain_queue_work(
                        self._data_dir,
                        laboratory_id=lab,
                        research=self._research,
                        wsos=wsos,
                        open_symbols=set(syms),
                        max_starts=2,
                        trigger="evening_curiosity",
                        allocation_blockers=blockers,
                    )
                    qdoc = merge_allocation_curiosity(qdoc, alloc_tbl)
                    save_queue(self._data_dir, qdoc)
                    port["curiosity_queue"] = qdoc
                    started = list(qdoc.get("work_started") or [])
                    if started:
                        port["curiosity_ira_started"] = started
                        ed = dict(port.get("evidence_delta") or {})
                        ed["research"] = int(ed.get("research") or 0) + len(started)
                        ed["material"] = bool(
                            ed.get("bars")
                            or ed.get("fundamentals")
                            or ed.get("news")
                            or ed.get("policy")
                            or ed.get("research")
                        )
                        port["evidence_delta"] = ed
                except Exception:  # noqa: BLE001
                    self._logger.debug("curiosity enqueue skipped", exc_info=True)
                # BRE.3 — last-chance drain of decide-time rationales before BRE.2
                try:
                    from atlas.investment.decide_rationale import (
                        DEFAULT_DECIDE_LLM_PASSES,
                        drain_pending_rationales,
                    )

                    bre3 = drain_pending_rationales(
                        self._data_dir,
                        laboratory_id=lab,
                        llm=getattr(self, "_llm", None),
                        max_passes=DEFAULT_DECIDE_LLM_PASSES,
                    )
                    port["decide_rationale"] = {
                        "done": bre3.get("done"),
                        "deferred": bre3.get("deferred"),
                        "skipped": bre3.get("skipped"),
                        "pending": bre3.get("pending"),
                    }
                except Exception:  # noqa: BLE001
                    self._logger.debug("BRE.3 evening drain skipped", exc_info=True)
                # BRE.2 — budgeted LLM semantic revise (or honest skip)
                try:
                    from atlas.investment.belief_revision import revise_beliefs_budgeted

                    revised = revise_beliefs_budgeted(
                        port.get("world_states"),
                        evidence_delta=port.get("evidence_delta"),
                        llm=getattr(self, "_llm", None),
                        data_dir=self._data_dir,
                    )
                    port["world_states"] = revised
                except Exception:  # noqa: BLE001
                    self._logger.debug("BRE.2 revise skipped", exc_info=True)
                # BRE.5 — distill global WSO from revision history (deterministic + budgeted LLM)
                try:
                    from atlas.investment.global_mind import distill_global_mind

                    gw = distill_global_mind(
                        self._data_dir,
                        laboratory_id=lab,
                        wsos=port.get("world_states"),
                        llm=getattr(self, "_llm", None),
                        # Phase 3: Belief Core exists — allow budgeted LLM narrative
                        allow_llm_narrative=bool(getattr(self, "_llm", None)),
                    )
                    port["global_wso"] = gw
                except Exception:  # noqa: BLE001
                    self._logger.debug("BRE.5 global distill skipped", exc_info=True)
                # MEM.1 — episodic → semantic/procedural distill
                try:
                    from atlas.investment.memory_distill import run_memory_distill

                    md = run_memory_distill(
                        self._data_dir,
                        laboratory_id=lab,
                        wsos=port.get("world_states"),
                        llm=getattr(self, "_llm", None),
                        allow_llm=bool(getattr(self, "_llm", None)),
                    )
                    port["memory_distill"] = md
                except Exception:  # noqa: BLE001
                    self._logger.debug("MEM.1 distill skipped", exc_info=True)
                # OI-SELF-REFLECT — nightly Belief Core reflection
                try:
                    from atlas.reasoning.reflection import (
                        format_reflection_section,
                        merge_jis,
                        run_nightly_reflection,
                    )

                    reflection = run_nightly_reflection(
                        getattr(self, "_reasoning", None),
                        laboratory_id=lab,
                        allow_llm_narrative=bool(getattr(self, "_llm", None)),
                    )
                    port["reflection"] = reflection
                    port["reflection_section"] = format_reflection_section(reflection)
                except Exception:  # noqa: BLE001
                    self._logger.debug("SELF-REFLECT evening skipped", exc_info=True)
                # IQ.1 — revision calibration snapshot for evening
                try:
                    from atlas.investment.learning_intelligence import (
                        build_revision_calibration,
                    )

                    port["revision_calibration"] = build_revision_calibration(
                        port.get("world_states")
                    )
                except Exception:  # noqa: BLE001
                    self._logger.debug("IQ.1 revision calibration skipped", exc_info=True)
                # META.1 — reasoning-pattern ledger
                try:
                    from atlas.investment.meta_cognition import run_meta_cognition

                    meta = run_meta_cognition(
                        self._data_dir,
                        laboratory_id=lab,
                        wsos=port.get("world_states"),
                    )
                    port["meta_cognition"] = meta
                except Exception:  # noqa: BLE001
                    self._logger.debug("META.1 ledger skipped", exc_info=True)
                # GENE.1 — assemble genealogy for today's material decisions
                try:
                    from atlas.investment.decision_genealogy import build_genealogy
                    from atlas.investment.decision_packets import DecisionPacketStore

                    gene_rows: list = []
                    packets = list(port.get("decisions") or [])[:12]
                    pkt_store = DecisionPacketStore(data_dir=self._data_dir)
                    attr_store = getattr(self, "_decision_attributions", None)
                    for p in packets:
                        if not isinstance(p, dict):
                            continue
                        if str(p.get("action") or "").lower() not in {"buy", "sell"}:
                            continue
                        did = p.get("decision_id") or p.get("id")
                        if not did:
                            continue
                        gene_rows.append(
                            build_genealogy(
                                str(did),
                                data_dir=self._data_dir,
                                packet=p,
                                packets_store=pkt_store,
                                attributions_store=attr_store,
                                laboratory_id=lab,
                                persist=True,
                            )
                        )
                    port["genealogies"] = gene_rows
                except Exception:  # noqa: BLE001
                    self._logger.debug("GENE.1 assemble skipped", exc_info=True)
                # CWS — daily cognitive quota drain (structural)
                try:
                    from atlas.investment.cognitive_work import run_cws_pass

                    pos = port.get("positions") or port.get("holdings") or []
                    if isinstance(pos, dict):
                        syms = [str(k) for k in pos.keys()]
                    else:
                        syms = [
                            str(p.get("symbol"))
                            for p in (pos or [])
                            if isinstance(p, dict) and p.get("symbol")
                        ]
                    port["cognitive_work"] = run_cws_pass(
                        self._data_dir,
                        laboratory_id=lab,
                        wsos=port.get("world_states")
                        if isinstance(port.get("world_states"), list)
                        else None,
                        open_symbols=syms,
                        research=self._research,
                    )
                    # Attach agenda + JIS revision counts for evening sections
                    try:
                        from atlas.investment.daily_cognitive_agenda import (
                            count_belief_revisions,
                            load_agenda,
                        )

                        cws = port.get("cognitive_work")
                        if isinstance(cws, dict) and isinstance(
                            cws.get("cognitive_agenda"), dict
                        ):
                            port["cognitive_agenda"] = cws["cognitive_agenda"]
                        else:
                            port["cognitive_agenda"] = load_agenda(
                                self._data_dir, lab
                            )
                        port["jis_revisions"] = count_belief_revisions(
                            self._data_dir, lab, days=7
                        )
                        # Merge Belief Core JIS (OI-SELF-REFLECT)
                        try:
                            from atlas.reasoning.reflection import (
                                belief_core_jis,
                                merge_jis,
                            )

                            core = None
                            if getattr(self, "_reasoning", None) is not None:
                                core = belief_core_jis(self._reasoning, days=7)
                            elif isinstance(port.get("reflection"), dict):
                                core = (port.get("reflection") or {}).get("jis")
                            if core:
                                port["jis_revisions"] = merge_jis(
                                    port.get("jis_revisions"), core
                                )
                        except Exception:  # noqa: BLE001
                            self._logger.debug(
                                "Belief Core JIS merge skipped", exc_info=True
                            )
                    except Exception:  # noqa: BLE001
                        self._logger.debug("DCA/JIS evening attach skipped", exc_info=True)
                except Exception:  # noqa: BLE001
                    self._logger.debug("CWS evening skipped", exc_info=True)
        except Exception:  # noqa: BLE001
            pass
        if isinstance(port, dict):
            no_fill = port.get("no_fill_reasons")
        subject, body = format_evening_report(
            plan=plan,
            portfolio=port or None,
            policy_snap=policy,
            program_id=program_id,
            trades=port.get("recent_trades") if port else None,
            research_digest=self._research_digest(program_id),
            no_fill_reasons=list(no_fill) if no_fill else None,
            catch_up=catch_up,
            decisions=port.get("decisions") if port else None,
            laboratory_id=_laboratory_label(port or portfolio),
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
        try:
            from atlas.activity import record_activity

            record_activity(
                domain="market",
                worker="investor_mailer",
                action="send_evening_digest",
                target=lab,
                result="completed" if ok else "failed",
                summary=(
                    f"Sent evening EOD digest for {lab}"
                    if ok
                    else f"Evening EOD digest failed for {lab}"
                ),
                evidence={"laboratory_id": lab, "as_of": today, "sent": ok},
            )
        except Exception:  # noqa: BLE001
            pass
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

    def preview_hourly(
        self,
        *,
        program_id: str = "market_intelligence",
        portfolio: dict[str, Any] | None = None,
        hour: int | None = None,
    ) -> dict[str, Any]:
        """OI-HOURLY0 — compact activity + learning + CWS digest."""
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo("Asia/Kolkata"))
        h = int(hour if hour is not None else now.hour)
        lab = _laboratory_label(portfolio)
        port = dict(portfolio) if isinstance(portfolio, dict) else {}
        # CWS pass each hourly tick
        try:
            from atlas.investment.cognitive_work import format_cws_section, run_cws_pass

            pos = port.get("positions") or port.get("holdings") or []
            if isinstance(pos, dict):
                syms = [str(k) for k in pos.keys()]
            else:
                syms = [
                    str(p.get("symbol"))
                    for p in (pos or [])
                    if isinstance(p, dict) and p.get("symbol")
                ]
            cws = run_cws_pass(
                self._data_dir,
                laboratory_id=lab,
                wsos=port.get("world_states") if isinstance(port.get("world_states"), list) else None,
                open_symbols=syms,
                research=self._research,
            )
            port["cognitive_work"] = cws
            if isinstance(cws, dict) and isinstance(cws.get("cognitive_agenda"), dict):
                port["cognitive_agenda"] = cws["cognitive_agenda"]
        except Exception:  # noqa: BLE001
            self._logger.debug("CWS hourly skipped", exc_info=True)

        subject, body = format_hourly_activity_report(
            portfolio=port,
            program_id=program_id,
            laboratory_id=lab,
            hour=h,
            ist_date=now.strftime("%Y-%m-%d"),
        )
        return {
            "subject": subject,
            "body": body,
            "recipients": self.recipients(),
            "ready": self.available(),
            "hour": h,
            "laboratory_id": lab,
            "as_of": now.strftime("%Y-%m-%d"),
        }

    def send_hourly(
        self,
        *,
        program_id: str = "market_intelligence",
        portfolio: dict[str, Any] | None = None,
        force: bool = False,
        hour: int | None = None,
        laboratory_id: str | None = None,
    ) -> dict[str, Any]:
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo("Asia/Kolkata"))
        h = int(hour if hour is not None else now.hour)
        lab = _laboratory_label(portfolio, laboratory_id)
        preview = self.preview_hourly(
            program_id=program_id, portfolio=portfolio, hour=h
        )
        if not self.available():
            return {
                "sent": False,
                "reason": "email_unavailable",
                "status": self.status(),
                **{k: preview[k] for k in ("subject", "body", "recipients", "as_of", "hour")},
            }
        today = self.ist_today()
        key = f"{self._lab_day_key(lab, today)}|{h:02d}"
        if not force and key in self._sent_hourly_keys:
            return {
                "sent": False,
                "reason": "already_sent_this_hour",
                "as_of": today,
                "hour": h,
                "laboratory_id": lab,
                **{k: preview[k] for k in ("subject", "body", "recipients")},
            }
        ok = self._deliver(preview["subject"], preview["body"])
        if ok:
            self._sent_hourly_keys.add(key)
            self._persist_sent_flags()
        try:
            from atlas.activity import record_activity

            record_activity(
                domain="market",
                worker="investor_mailer",
                action="send_hourly_digest",
                target=lab,
                result="completed" if ok else "failed",
                summary=(
                    f"Sent hourly {h:02d}:00 IST digest for {lab}"
                    if ok
                    else f"Hourly digest failed for {lab} hour={h}"
                ),
                evidence={"laboratory_id": lab, "as_of": today, "hour": h, "sent": ok},
            )
        except Exception:  # noqa: BLE001
            pass
        return {
            "sent": ok,
            "as_of": today,
            "hour": h,
            "recipients": preview["recipients"],
            "subject": preview["subject"],
            "body": preview["body"],
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
