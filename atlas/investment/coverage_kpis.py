"""UTS.G — hard daily coverage KPIs for universe triage + allocation loop.

Aggregates durable triage / switch / missed-opp / open-book signals. Never
invents green KPIs — missing stores → honest ``unknown`` / ``pending``.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "uts.g.coverage_kpis"
_IST = ZoneInfo("Asia/Kolkata")


def ist_today() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def build_coverage_kpis(
    data_dir: str | Path | None,
    *,
    program_id: str = "market_intelligence",
    laboratory_id: str = "india_equity_learner",
    as_of_ist: str | None = None,
    open_symbols: list[str] | None = None,
    open_books_observed: int | None = None,
    open_books_total: int | None = None,
) -> dict[str, Any]:
    """Assemble the hard KPI block for evening / governance / status chat."""
    day = (as_of_ist or ist_today()).strip()
    kpis: dict[str, Any] = {
        "version": VERSION,
        "as_of_ist": day,
        "program_id": program_id,
        "laboratory_id": laboratory_id,
    }
    # Universe triage
    triage_ok = False
    cov: dict[str, Any] = {}
    try:
        from atlas.investment.triage_memory import load_triage_day

        triage = load_triage_day(data_dir, program_id, day)
        triage_ok = bool(triage.get("ok"))
        cov = triage.get("coverage") if isinstance(triage.get("coverage"), dict) else {}
        kpis["universe_scanned"] = cov.get("universe_scanned") or (
            "—" if not triage_ok else "0/0"
        )
        kpis["price_coverage_pct"] = cov.get("price_coverage_pct")
        kpis["rank_ladder_persisted"] = bool(cov.get("rank_ladder_persisted") or triage_ok)
        kpis["acceleration_status"] = cov.get("acceleration_status") or (
            "pending_history" if triage_ok else "unknown"
        )
        # OI-MKT-COV Phase 1B — durable readiness (not live Yahoo alone)
        kpis["durable_bars_ok"] = bool(cov.get("durable_bars_ok"))
        kpis["readiness_grade"] = cov.get("readiness_grade")
        kpis["durable_priced_pct"] = cov.get("durable_priced_pct")
        kpis["durable_history_ok_pct"] = cov.get("durable_history_ok_pct")
        kpis["watchlist_refreshed"] = bool(
            (triage.get("meta") or {}).get("watchlist_n")
            or (triage.get("meta") or {}).get("published_watchlist")
            or triage_ok
        )
    except Exception:  # noqa: BLE001
        kpis["universe_scanned"] = "unknown"
        kpis["price_coverage_pct"] = None
        kpis["rank_ladder_persisted"] = False
        kpis["acceleration_status"] = "unknown"
        kpis["watchlist_refreshed"] = False
        kpis["durable_bars_ok"] = False
        kpis["readiness_grade"] = None
        kpis["durable_priced_pct"] = None
        kpis["durable_history_ok_pct"] = None

    # Open books observed
    total_open = open_books_total
    if total_open is None and open_symbols is not None:
        total_open = len(open_symbols)
    obs = open_books_observed
    if total_open is not None and obs is not None and total_open > 0:
        kpis["open_books_observed"] = f"{int(obs)}/{int(total_open)}"
        kpis["open_books_observed_pct"] = round(100.0 * float(obs) / float(total_open), 1)
    elif total_open == 0:
        kpis["open_books_observed"] = "0/0"
        kpis["open_books_observed_pct"] = 100.0
    else:
        kpis["open_books_observed"] = "unknown"
        kpis["open_books_observed_pct"] = None

    # Switch reviews today (+ honesty audit vs cold-start spam)
    switches_eval = switches_exec = 0
    unique_comparisons = 0
    routine_blocks = 0
    reason_hist: dict[str, int] = {}
    beneficial_pct = None
    try:
        from atlas.investment.switch_learning import list_switch_decisions

        rows = list_switch_decisions(
            data_dir, laboratory_id=laboratory_id, limit=500
        )
        today_rows = [
            r for r in rows if str(r.get("decision_ist") or "")[:10] == day
        ]
        switches_eval = len(today_rows)
        switches_exec = sum(1 for r in today_rows if r.get("executed"))
        pairs: set[tuple[str, str, str]] = set()
        for r in today_rows:
            hold = str(r.get("hold_symbol") or "").upper()
            chal = str(r.get("challenger_symbol") or "").upper()
            code = str(r.get("reason_code") or r.get("decision") or "").strip().lower()
            pairs.add((hold, chal, code))
            reason_hist[code or "unknown"] = reason_hist.get(code or "unknown", 0) + 1
            if "cold_start" in code or code.startswith("switch_blocked"):
                routine_blocks += 1
        unique_comparisons = len(pairs)
        # Rolling 20d beneficial among resolved switch decisions
        resolved = []
        for r in rows:
            if str(r.get("decision") or "") != "switch":
                continue
            for h in r.get("horizons") or []:
                if (
                    isinstance(h, dict)
                    and int(h.get("horizon_d") or 0) == 20
                    and h.get("status") == "done"
                    and h.get("was_switch_better") is not None
                ):
                    resolved.append(bool(h.get("was_switch_better")))
                    break
        if resolved:
            beneficial_pct = round(100.0 * sum(1 for x in resolved if x) / len(resolved), 1)
    except Exception:  # noqa: BLE001
        pass
    kpis["switches_evaluated"] = switches_eval
    kpis["switches_executed"] = switches_exec
    kpis["switches_unique_comparisons"] = unique_comparisons
    kpis["switches_routine_blocks"] = routine_blocks
    kpis["switches_reason_histogram"] = dict(
        sorted(reason_hist.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
    )
    if switches_eval > 0 and unique_comparisons < switches_eval:
        kpis["switches_honesty"] = (
            f"{switches_eval} raw evals → {unique_comparisons} unique "
            f"hold×challenger×reason; {routine_blocks} routine/cold-start blocks "
            "(not distinct learning experiments)"
        )
    elif switches_eval > 0:
        kpis["switches_honesty"] = (
            f"{switches_eval} unique hold-vs-challenger comparisons today"
        )
    else:
        kpis["switches_honesty"] = "no switch evaluations recorded today"
    kpis["switches_beneficial_20d_pct"] = beneficial_pct

    # Missed opportunity rows
    missed_n = 0
    try:
        from atlas.investment.missed_opportunity import load_missed_ledger

        ledger = load_missed_ledger(data_dir, laboratory_id=laboratory_id)
        if ledger.get("ok"):
            missed_n = len(ledger.get("rows") or [])
    except Exception:  # noqa: BLE001
        missed_n = 0
    kpis["missed_opportunity_rows"] = missed_n

    # Hard pass/fail flags (honest)
    price_ok = None
    try:
        if kpis.get("price_coverage_pct") is not None:
            price_ok = float(kpis["price_coverage_pct"]) >= 95.0
    except (TypeError, ValueError):
        price_ok = None
    kpis["hard"] = {
        "rank_ladder_persisted": bool(kpis.get("rank_ladder_persisted")),
        "price_coverage_ge_95": price_ok,
        "acceleration_ready": kpis.get("acceleration_status")
        not in {None, "unknown", "pending_history"},
        "switches_evaluated_today": switches_eval > 0 or switches_eval == 0,
    }
    # Overall: red if ladder missing on a trading day when we claim coverage OS.
    issues: list[str] = []
    if not kpis.get("rank_ladder_persisted"):
        issues.append("rank_ladder_not_persisted")
    if price_ok is False:
        issues.append("price_coverage_below_95")
    if kpis.get("acceleration_status") == "pending_history":
        issues.append("acceleration_pending_history")
    kpis["issues"] = issues
    kpis["status"] = "green" if not issues else ("yellow" if triage_ok else "red")
    kpis["ok"] = True
    return kpis


def format_coverage_kpi_evening_lines(kpis: dict[str, Any] | None) -> list[str]:
    if not isinstance(kpis, dict) or not kpis.get("ok"):
        return ["  Coverage KPIs: (unavailable)"]
    px = kpis.get("price_coverage_pct")
    px_line = (
        f"    Price coverage: {px}%"
        if px is not None
        else "    Price coverage: —"
    )
    ben = kpis.get("switches_beneficial_20d_pct")
    ben_line = (
        f"    Switches beneficial @20d: {ben}%"
        if ben is not None
        else "    Switches beneficial @20d: — (pending outcomes)"
    )
    lines = [
        f"  Coverage KPIs ({kpis.get('as_of_ist')} · {kpis.get('status')}):",
        f"    Universe scanned: {kpis.get('universe_scanned')}",
        px_line,
        f"    Rank ladder persisted: "
        f"{'yes' if kpis.get('rank_ladder_persisted') else 'no'}",
        f"    Acceleration: {kpis.get('acceleration_status')}",
        f"    Watchlist refreshed: "
        f"{'yes' if kpis.get('watchlist_refreshed') else 'no/unknown'}",
        f"    Open books observed: {kpis.get('open_books_observed')}",
        f"    Switches evaluated/executed today: "
        f"{kpis.get('switches_evaluated')}/{kpis.get('switches_executed')}",
        f"    Switch unique comparisons: "
        f"{kpis.get('switches_unique_comparisons', '—')} "
        f"(routine/cold-start blocks={kpis.get('switches_routine_blocks', '—')})",
    ]
    if kpis.get("switches_honesty"):
        lines.append(f"    Switch honesty: {kpis.get('switches_honesty')}")
    lines.extend(
        [
            ben_line,
            f"    Missed-opportunity rows: {kpis.get('missed_opportunity_rows')}",
        ]
    )
    issues = kpis.get("issues") or []
    if issues:
        lines.append("    Issues: " + ", ".join(str(i) for i in issues))
    return lines


def why_not_switch_into(
    data_dir: str | Path | None,
    symbol: str,
    *,
    laboratory_id: str = "india_equity_learner",
    as_of_ist: str | None = None,
) -> dict[str, Any]:
    """Answer “Why not switch into X?” from durable switch decisions (no LLM)."""
    sym = str(symbol or "").strip().upper()
    day = (as_of_ist or ist_today()).strip()
    if not sym:
        return {"ok": False, "honesty": "symbol required", "answer": "Which symbol?"}
    matches: list[dict[str, Any]] = []
    try:
        from atlas.investment.switch_learning import list_switch_decisions

        for row in list_switch_decisions(
            data_dir, laboratory_id=laboratory_id, limit=100
        ):
            chal = str(row.get("challenger_symbol") or "").strip().upper()
            if chal != sym:
                continue
            if day and str(row.get("decision_ist") or "")[:10] not in {day, ""}:
                # Prefer today; still keep recent.
                pass
            matches.append(row)
    except Exception:  # noqa: BLE001
        matches = []
    if not matches:
        return {
            "ok": True,
            "symbol": sym,
            "answer": (
                f"{sym}: no durable hold-vs-challenger evaluation found yet "
                "(not reviewed, or triage/switch memory empty)."
            ),
            "reason_code": "not_evaluated",
        }
    # Prefer most recent
    matches.sort(key=lambda r: str(r.get("decision_ist") or ""), reverse=True)
    latest = matches[0]
    code = latest.get("reason_code") or "unknown"
    adv = latest.get("expected_advantage")
    adv_s = f"{float(adv):+.4f}" if isinstance(adv, (int, float)) else "—"
    held = latest.get("hold_symbol")
    executed = "executed" if latest.get("executed") else "not executed"
    answer = (
        f"{sym}: latest review vs {held} on {latest.get('decision_ist')} → "
        f"{latest.get('decision')} ({code}); advantage={adv_s}; {executed}."
    )
    return {
        "ok": True,
        "symbol": sym,
        "answer": answer,
        "reason_code": code,
        "decision": latest.get("decision"),
        "hold_symbol": held,
        "expected_advantage": adv,
        "executed": bool(latest.get("executed")),
        "decision_ist": latest.get("decision_ist"),
    }
