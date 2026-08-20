"""OI-LINT0 Phase 6 — learning-first evening report header.

Above the fold: allocation · experiences · prediction error · closed trades ·
contradictions · revisions · research · LLM failures · news/policy freshness ·
tomorrow's investigation queue.

Below the fold: tick histogram (mark_only last) · process score · IQ — not edge.
"""

from __future__ import annotations

from typing import Any

BELOW_FOLD_MARKER = "── Below the fold (activity / process — not edge) ──"


def _packet_contradictions(decision_rows: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for d in decision_rows:
        if not isinstance(d, dict):
            continue
        meta = d.get("meta") if isinstance(d.get("meta"), dict) else {}
        decomp = meta.get("decision_decomposition")
        if not isinstance(decomp, dict):
            decomp = meta.get("decomposition") if isinstance(meta.get("decomposition"), dict) else {}
        for c in list(decomp.get("contradictions") or []):
            sym = str(d.get("symbol") or "?")
            line = f"{sym}: {c}"
            if line not in seen:
                seen.add(line)
                out.append(line)
        for c in list(d.get("reasons_against") or []):
            if "contradiction" in str(c).lower() or "technical_buy_vs" in str(c):
                sym = str(d.get("symbol") or "?")
                line = f"{sym}: {c}"
                if line not in seen:
                    seen.add(line)
                    out.append(line)
    return out


def _llm_failure_count(port: dict[str, Any], learning_summary: dict[str, Any] | None) -> int:
    kinds = (learning_summary or {}).get("by_kind")
    if isinstance(kinds, dict) and int(kinds.get("llm_failure") or 0) > 0:
        return int(kinds["llm_failure"])
    dr = port.get("decide_rationale") if isinstance(port.get("decide_rationale"), dict) else {}
    if dr.get("skipped") or dr.get("skip_reason"):
        return 1
    for key in ("belief_revision", "research_scientist", "memory_distill"):
        blk = port.get(key)
        if isinstance(blk, dict) and (
            blk.get("llm_failed") or "LLM_UNAVAILABLE" in str(blk.get("reason") or "")
        ):
            return max(1, int(blk.get("llm_failed") or 1))
    return 0


def _news_policy_freshness(port: dict[str, Any]) -> dict[str, Any]:
    delta = port.get("evidence_delta") if isinstance(port.get("evidence_delta"), dict) else {}
    tl = port.get("market_timeline") if isinstance(port.get("market_timeline"), dict) else {}
    rows = list(tl.get("rows") or []) if isinstance(tl.get("rows"), list) else []
    news_rows = sum(
        1
        for r in rows
        if isinstance(r, dict)
        and int((r.get("counts") or {}).get("news") or 0) > 0
    )
    pol_rows = sum(
        1
        for r in rows
        if isinstance(r, dict)
        and int((r.get("counts") or {}).get("policy") or 0) > 0
    )
    return {
        "news_events": int(delta.get("news") or 0),
        "policy_events": int(delta.get("policy") or 0),
        "open_books_with_news": news_rows,
        "open_books_with_policy": pol_rows,
    }


def _investigate_tomorrow(
    port: dict[str, Any],
    alloc: dict[str, Any] | None,
    cq: dict[str, Any] | None,
) -> list[str]:
    items: list[str] = []
    try:
        from atlas.investment.capital_allocation import allocation_blocking_unknowns

        for b in allocation_blocking_unknowns(alloc if isinstance(alloc, dict) else None)[:4]:
            if isinstance(b, dict):
                items.append(
                    f"{b.get('symbol')}: resolve {b.get('unknown')} (blocks next-rupee)"
                )
    except Exception:  # noqa: BLE001
        pass
    if isinstance(cq, dict):
        for it in list(cq.get("items") or []):
            if not isinstance(it, dict):
                continue
            if str(it.get("status") or "") in {"queued", "ira_started", "unknown_explicit"}:
                items.append(
                    f"{it.get('symbol')}: {it.get('unknown')} [{it.get('status')}]"
                )
            if len(items) >= 6:
                break
    evo = port.get("evolution") if isinstance(port.get("evolution"), dict) else {}
    due = int(evo.get("revisits_due_today") or 0)
    if due > 0:
        items.append(f"{due} belief revisits due tomorrow")
    if not items:
        items.append("(no allocation blockers queued — monitor open books + challengers)")
    return items[:8]


def format_learning_first_header(
    *,
    port: dict[str, Any],
    plan: dict[str, Any],
    decision_rows: list[dict[str, Any]],
    day_trades: list[dict[str, Any]],
    buys: list[dict[str, Any]],
    sells: list[dict[str, Any]],
    evo: dict[str, Any],
    data_dir: str | None = None,
) -> tuple[list[str], dict[str, Any] | None, dict[str, Any] | None]:
    """Above-the-fold Phase 6 block. Returns (lines, alloc_doc, learning_summary)."""
    lines: list[str] = []
    lab = str(port.get("portfolio_key") or port.get("laboratory_id") or "india_equity_learner")
    alloc: dict[str, Any] | None = None
    learning_summary: dict[str, Any] | None = None

    # 1 — Next ₹1 / allocation
    try:
        from atlas.investment.capital_allocation import (
            format_allocation_evening_lines,
            load_allocation_table,
        )

        alloc = (
            port.get("challenger_table_doc")
            if isinstance(port.get("challenger_table_doc"), dict)
            else None
        )
        if alloc is None and data_dir:
            alloc = load_allocation_table(data_dir, lab)
        elif alloc is None:
            try:
                from atlas.config import get_config

                alloc = load_allocation_table(str(get_config().paths.data), lab)
            except Exception:  # noqa: BLE001
                alloc = None
        lines.extend(format_allocation_evening_lines(alloc))
    except Exception:  # noqa: BLE001
        lines.extend(
            [
                "",
                "── Next ₹1 / challenger table ──",
                "  (unavailable)",
            ]
        )

    # 2 — Experience truth table
    try:
        from atlas.investment.experience_integrity import (
            build_experience_metrics,
            format_experience_metrics_lines,
        )

        pos = port.get("positions") or port.get("holdings") or []
        if isinstance(pos, dict):
            pos = [{"symbol": k, **(v if isinstance(v, dict) else {})} for k, v in pos.items()]
        exp_doc = (
            port.get("experience_metrics")
            if isinstance(port.get("experience_metrics"), dict)
            else None
        )
        if exp_doc is None:
            exp_doc = build_experience_metrics(
                packets=decision_rows,
                attributions=port.get("attributions") or port.get("recent_attributions"),
                observations=list(port.get("observations") or []),
                evolution=evo,
                positions=[p for p in pos if isinstance(p, dict)],
                fills_buy=len(buys),
                fills_sell=len(sells),
            )
        lines.extend(format_experience_metrics_lines(exp_doc))
    except Exception:  # noqa: BLE001
        pass

    # 3 — Prediction error / learning objects
    try:
        from atlas.investment.learning_objects import (
            format_learning_objects_lines,
            load_learning_events,
            summarize_learning_day,
        )

        dd = data_dir
        if not dd:
            try:
                from atlas.config import get_config

                dd = str(get_config().paths.data)
            except Exception:  # noqa: BLE001
                dd = None
        if dd:
            evs = load_learning_events(dd, lab)
            learning_summary = summarize_learning_day(evs)
            lines.extend(format_learning_objects_lines(learning_summary))
    except Exception:  # noqa: BLE001
        pass

    # 4 — Closed trades today
    lines.extend(["", "── Closed trades today ──"])
    if sells:
        for t in sells[:8]:
            sym = t.get("symbol") or "?"
            pnl = t.get("realized_pnl")
            pnl_s = f" PnL={float(pnl):+.2f}" if pnl is not None else ""
            lines.append(
                f"  · SELL {sym} × {t.get('quantity') or t.get('qty')} "
                f"@ {t.get('price') or t.get('fill_price')}{pnl_s}"
            )
    else:
        lines.append("  (no closes today — open books still under observation)")

    # 5 — Contradictions
    contra = _packet_contradictions(decision_rows)
    lines.extend(["", "── Contradictions (thesis vs technical) ──"])
    if contra:
        for c in contra[:6]:
            lines.append(f"  · {c}")
    else:
        lines.append("  (none flagged on today's packets)")

    # 6 — Revisions summary
    lines.extend(["", "── Belief revisions ──"])
    done = int(evo.get("done_revisits") or 0)
    pending = int(evo.get("pending_revisits") or 0)
    due = int(evo.get("revisits_due_today") or 0)
    lines.append(
        f"  done={done} · pending={pending} · due_tomorrow={due}"
    )
    jis = port.get("jis_revisions") if isinstance(port.get("jis_revisions"), dict) else {}
    if jis.get("revisions_this_week") is not None:
        lines.append(f"  revisions this week: {jis.get('revisions_this_week')}")

    # 7 — Research resolved / remaining
    cq = port.get("curiosity_queue") if isinstance(port.get("curiosity_queue"), dict) else None
    lines.extend(["", "── Research queue (allocation-sensitive) ──"])
    if isinstance(cq, dict):
        items = [i for i in (cq.get("items") or []) if isinstance(i, dict)]
        by_st: dict[str, int] = {}
        for it in items:
            st = str(it.get("status") or "queued")
            by_st[st] = by_st.get(st, 0) + 1
        if by_st:
            lines.append("  " + " · ".join(f"{k}={v}" for k, v in sorted(by_st.items())))
        drain = cq.get("news_drain") if isinstance(cq.get("news_drain"), dict) else {}
        if drain:
            lines.append(
                f"  news drain: resolved={drain.get('resolved', 0)} · "
                f"explicit_unknown={drain.get('unknown_explicit', 0)}"
            )
        skipped = int(cq.get("allocation_filtered_skipped") or 0)
        if skipped:
            lines.append(f"  filtered (no allocation impact): {skipped}")
        for it in items[-4:]:
            lines.append(
                f"  · {it.get('symbol')}: {it.get('unknown')} [{it.get('status')}]"
            )
    else:
        lines.append("  (no curiosity queue doc on portfolio snapshot)")

    # 8 — LLM failures
    llm_n = _llm_failure_count(port, learning_summary)
    lines.extend(["", "── LLM failures (honest, not hidden) ──"])
    if llm_n:
        lines.append(f"  {llm_n} LLM failure(s) today — beliefs stay unreviewed, not invented")
    else:
        lines.append("  (none recorded today)")

    # 9 — News / policy freshness
    fresh = _news_policy_freshness(port)
    lines.extend(["", "── News & policy freshness ──"])
    lines.append(
        f"  evidence_delta: news={fresh['news_events']} · policy={fresh['policy_events']}"
    )
    if fresh["open_books_with_news"] or fresh["open_books_with_policy"]:
        lines.append(
            f"  open-book timeline rows with news={fresh['open_books_with_news']} · "
            f"policy={fresh['open_books_with_policy']}"
        )
    if fresh["news_events"] == 0 and fresh["policy_events"] == 0:
        lines.append("  (no tier-1/2 news or policy events landed today — gaps stay unknown)")

    # 10 — Investigate tomorrow
    lines.extend(["", "── Investigate tomorrow ──"])
    for item in _investigate_tomorrow(port, alloc, cq):
        lines.append(f"  · {item}")

    return lines, alloc, learning_summary


def format_process_metrics_below_fold(
    *,
    port: dict[str, Any],
    plan: dict[str, Any],
) -> list[str]:
    """IQ / process score — explicitly below the fold (Phase 6 rule 36)."""
    prox = port.get("process_proxies") if isinstance(port.get("process_proxies"), dict) else {}
    meta = port.get("meta_learning") if isinstance(port.get("meta_learning"), dict) else {}
    lines = [
        "",
        "── Process metrics (not edge — cold-start maturity) ──",
        f"  Process score: {prox.get('process_score', '—')}/10 · "
        f"Atlas IQ / System: {meta.get('intelligence_score', '—')}",
        "  IQ and process score describe machinery maturity — not risk-adjusted edge.",
    ]
    mat = port.get("maturity_split") if isinstance(port.get("maturity_split"), dict) else None
    if not mat:
        iq = port.get("atlas_iq") if isinstance(port.get("atlas_iq"), dict) else None
        mat = iq.get("maturity_split") if isinstance(iq, dict) else None
    if isinstance(mat, dict) and mat.get("trading_evidence_maturity") is not None:
        lines.append(
            f"  Trading Evidence Maturity: {mat.get('trading_evidence_maturity')} · "
            f"Attribution: {mat.get('attribution_maturity')} · "
            f"Strategy Evidence: {mat.get('strategy_evidence')} · "
            f"Data: {mat.get('data_readiness')}"
        )
    if str(plan.get("phase") or "") == "learning":
        lines.append("  phase=learning — ranking and IQ are provisional until closed outcomes")
    return lines
