"""PLC.F — deterministic Market Intelligence status for chat (no LLM)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_market_intelligence_status(
    *,
    data_dir: str | Path | None = None,
    goals: Any | None = None,
) -> dict[str, Any]:
    """Assemble an honest MI / lab status from durable stores (disk + optional goals)."""
    lines: list[str] = [
        "Market Intelligence — what Atlas has learned / can do so far:",
        "",
        "Shipped (lab architecture — not claiming a proven edge yet):",
        "· Programs → Missions → Workers pipeline (universe → rank → research → sim → journal → email)",
        "· Decision packets · timeline · observations · attribution (DI) — prep for learning",
        "· Multi-lab ledgers: swing / intraday / F&O (hermetic KPIs)",
        "· Tier-C Yahoo fundamentals enrich (paced) + Screener/filing outrank Yahoo",
        "· AtlasNet / live NN: prep-only until sample gates clear",
        "",
    ]

    root: Path | None = None
    if data_dir:
        root = Path(data_dir)
    else:
        try:
            from atlas.config import get_config

            root = Path(get_config().paths.data)
        except Exception:  # noqa: BLE001
            root = None

    labs: list[dict[str, Any]] = []
    if root:
        try:
            from atlas.investment import portfolios as vp

            labs = [p for p in (vp.list_portfolios() or []) if isinstance(p, dict)]
        except Exception:  # noqa: BLE001
            labs = []
        if not labs:
            try:
                path = root / "market" / "virtual_portfolios.json"
                if path.is_file():
                    doc = json.loads(path.read_text(encoding="utf-8"))
                    labs = [p for p in (doc.get("portfolios") or []) if isinstance(p, dict)]
            except Exception:  # noqa: BLE001
                labs = []

    if labs:
        lines.append(f"Laboratories registered: {len(labs)}")
        for row in labs[:6]:
            key = row.get("portfolio_key") or row.get("laboratory_id") or "?"
            ac = row.get("asset_class") or "?"
            cash = (row.get("persona") or {}).get("capital")
            mid = "mission✓" if row.get("mission_id") else "no mission"
            cash_s = f"₹{float(cash):,.0f}" if cash is not None else "?"
            lines.append(f"· {key} · {ac} · capital {cash_s} · {mid}")
    else:
        lines.append("Laboratories: none found in registry yet.")

    # Fundamentals
    fund_n = pe_n = 0
    fund_note = ""
    if root:
        try:
            from atlas.investment.fundamentals import fundamentals_view

            fv = fundamentals_view(root, program_id="market_intelligence", limit=40)
            cov = fv.get("coverage") or {}
            fund_n = int(fv.get("count") or cov.get("symbols") or 0)
            pe_n = int(cov.get("with_pe") or 0)
            gaps = fv.get("learner_gaps") or {}
            if gaps.get("symbols_with_gaps") is not None:
                fund_note = (
                    f"watchlist holes {gaps.get('symbols_with_gaps')}/"
                    f"{gaps.get('symbols_checked') or '?'}"
                )
        except Exception:  # noqa: BLE001
            try:
                p = root / "investment" / "fundamentals" / "market_intelligence.json"
                if p.is_file():
                    doc = json.loads(p.read_text(encoding="utf-8"))
                    syms = doc.get("symbols") or {}
                    fund_n = len(syms)
                    pe_n = sum(1 for r in syms.values() if isinstance(r, dict) and r.get("pe") is not None)
            except Exception:  # noqa: BLE001
                pass
    lines.append(
        f"Fundamentals store: {pe_n}/{fund_n} with PE"
        + (f" · {fund_note}" if fund_note else "")
        + " (store coverage ≠ full watchlist)"
    )

    # Yahoo enrich honesty — why chat may still show 3/3
    if root:
        try:
            from atlas.investment.yahoo_fundamentals import get_yahoo_rate_gate
            from atlas.investment.fundamentals import (
                learner_fundamentals_gaps,
                load_store,
                watchlist_symbols,
            )

            gate = get_yahoo_rate_gate(root)
            gst = gate.status()
            wl = watchlist_symbols("market_intelligence", limit=40)
            gaps = learner_fundamentals_gaps(root, wl, program_id="market_intelligence")
            hole_n = int(gaps.get("symbols_with_gaps") or 0)
            store = load_store(root, "market_intelligence")
            last = store.get("last_yahoo_enrich") if isinstance(store, dict) else {}
            lines.append("")
            lines.append("Yahoo Tier-C enrich status:")
            lines.append(
                f"· Watchlist PE/FCF holes: {hole_n}/{gaps.get('symbols_checked') or len(wl)}"
            )
            if last:
                lines.append(
                    f"· Last enrich: fetched={last.get('fetched')} remaining="
                    f"{last.get('remaining')} paused={last.get('paused')} "
                    f"as_of={last.get('as_of')}"
                )
            cool = float(gst.get("cooldown_remaining_s") or 0)
            if cool > 0:
                lines.append(
                    f"· Cooldown {cool:.0f}s (HTTP {gst.get('last_block_status')}) — "
                    "not stopped; slow-and-steady resume"
                )
            else:
                lines.append(
                    "· Rate gate ready — worker/UI batches of 3 resume gaps "
                    "(open books prioritized)"
                )
        except Exception:  # noqa: BLE001
            pass

    # Research dossiers
    research_n = 0
    if root:
        rd = root / "investment" / "research" / "market_intelligence"
        if rd.is_dir():
            research_n = len(list(rd.glob("*.json")))
    lines.append(
        f"Research dossiers on disk: {research_n} "
        "(coverage often ~20% — dossier ≠ deep evidence)"
    )

    # UTS.G — Did we scan the universe? / coverage KPIs
    coverage_kpis: dict[str, Any] | None = None
    if root:
        try:
            from atlas.investment.coverage_kpis import (
                build_coverage_kpis,
                format_coverage_kpi_evening_lines,
            )

            coverage_kpis = build_coverage_kpis(
                root,
                program_id="market_intelligence",
                laboratory_id="india_equity_learner",
            )
            lines.append("")
            lines.append("Universe triage & allocation coverage (UTS):")
            for ln in format_coverage_kpi_evening_lines(coverage_kpis):
                lines.append(ln[2:] if ln.startswith("  ") else ln)
        except Exception:  # noqa: BLE001
            lines.append("")
            lines.append("Universe triage coverage: (unavailable)")

    # Goals / learner narrative when available
    learner_answer = None
    if goals is not None:
        try:
            report = goals.learner_status(query="india learner")
            learner_answer = report.get("answer") or report.get("narrative")
            if learner_answer:
                lines.append("")
                lines.append("Learner progress (from Goals DB):")
                # keep short
                for ln in str(learner_answer).splitlines()[:12]:
                    lines.append(ln)
        except Exception as exc:  # noqa: BLE001
            lines.append(f"Learner progress unavailable: {type(exc).__name__}")

    lines.extend(
        [
            "",
            "Honest gaps right now (typical cold-start):",
            "· Control strategy is still SMA/RSI — research does not yet drive every buy",
            "· Yahoo enrich paused on 429 earlier — paced batches resume; store 3/3 ≠ watchlist filled",
            "· Open-book daily observation packs rolling out (PLC.C)",
            "· No strategy mutation / AtlasNet until attributable closed sample gates",
            "",
            "Next useful moves:",
            "· Market tab → Laboratory status · Enrich next 3 gaps (Yahoo)",
            "· Invest intel → Screener CSV for Tier B PE",
            "· GET /v1/learner/status · GET /v1/market/intelligence-catalog",
            "· Ask: “learner status”, “did we scan the universe?”, or “why not switch into RELIANCE.NS?”",
            "",
            "(Deterministic reply — no chat LLM — works when Ollama is busy.)",
        ]
    )

    return {
        "ok": True,
        "answer": "\n".join(lines),
        "labs": len(labs),
        "fundamentals_pe": pe_n,
        "fundamentals_n": fund_n,
        "research_n": research_n,
        "has_learner_narrative": bool(learner_answer),
        "coverage_kpis": coverage_kpis,
    }


def answer_market_allocation_question(
    message: str,
    *,
    data_dir: str | Path | None = None,
    laboratory_id: str = "india_equity_learner",
) -> dict[str, Any] | None:
    """Route UTS status questions (scan / why not switch) without LLM.

    Returns None when the message is not an allocation-coverage question.
    """
    import re

    text = (message or "").strip()
    if not text:
        return None
    low = text.lower()
    root = Path(data_dir) if data_dir else None
    if root is None:
        try:
            from atlas.config import get_config

            root = Path(get_config().paths.data)
        except Exception:  # noqa: BLE001
            root = None

    if any(
        p in low
        for p in (
            "did we scan",
            "scan the universe",
            "universe coverage",
            "coverage kpi",
            "did atlas look",
        )
    ):
        from atlas.investment.coverage_kpis import (
            build_coverage_kpis,
            format_coverage_kpi_evening_lines,
        )

        kpis = build_coverage_kpis(
            root,
            program_id="market_intelligence",
            laboratory_id=laboratory_id,
        )
        lines = [
            "Did we scan the universe today?",
            "",
        ] + format_coverage_kpi_evening_lines(kpis)
        return {
            "ok": True,
            "kind": "coverage_kpis",
            "answer": "\n".join(lines),
            "coverage_kpis": kpis,
        }

    m = re.search(
        r"why\s+not\s+switch\s+into\s+([A-Za-z0-9._-]+)",
        text,
        flags=re.IGNORECASE,
    )
    if not m:
        m = re.search(
            r"why\s+(?:didn'?t|did\s+not)\s+we\s+switch\s+(?:into\s+)?([A-Za-z0-9._-]+)",
            text,
            flags=re.IGNORECASE,
        )
    if m:
        from atlas.investment.coverage_kpis import why_not_switch_into

        sym = m.group(1).strip().upper()
        if not sym.endswith(".NS") and sym.replace(".", "").isalnum():
            if "." not in sym:
                sym = f"{sym}.NS"
        out = why_not_switch_into(root, sym, laboratory_id=laboratory_id)
        return {"ok": True, "kind": "why_not_switch", **out}

    return None
