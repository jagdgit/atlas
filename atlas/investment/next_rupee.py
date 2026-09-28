"""NOW #8 — Next-₹1 as economic center.

Answers: *Why is the next ₹1 going into this asset rather than my existing
holdings or cash?* Deterministic from challenger table + ACP summaries.
Does not place orders; does not increase capital.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from atlas.investment.capital_allocation import (
    CASH_SYMBOL,
    VERSION as ALLOC_VERSION,
    allocation_blocking_unknowns,
    ist_today,
)

VERSION = "now.next_rupee.v1"
STORE_REL = Path("investment") / "next_rupee"
_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.next_rupee")


def _f(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _er_s(value: Any) -> str:
    v = _f(value)
    if v is None:
        return "unknown"
    return f"{v:+.4f}"


def build_next_rupee_center(
    table: dict[str, Any] | None,
    *,
    acp_summaries: list[dict[str, Any]] | None = None,
    laboratory_id: str | None = None,
    as_of_ist: str | None = None,
) -> dict[str, Any]:
    """Durable economic-center packet — destination + rejected alternatives."""
    table = table if isinstance(table, dict) else {}
    day = (as_of_ist or table.get("as_of_ist") or ist_today()).strip()
    lab = laboratory_id or str(table.get("laboratory_id") or "india_equity_learner")
    rows = [r for r in (table.get("rows") or []) if isinstance(r, dict)]
    bd = table.get("best_deploy") if isinstance(table.get("best_deploy"), dict) else {}

    cash_row = next((r for r in rows if str(r.get("symbol")) == CASH_SYMBOL), None)
    cash_er = _f((cash_row or {}).get("expected_return"))
    if cash_er is None:
        cash_er = 0.0

    dest = str(bd.get("symbol") or CASH_SYMBOL).upper() or CASH_SYMBOL
    dest_er = _f(bd.get("expected_return"))
    if dest == CASH_SYMBOL:
        dest_er = cash_er
        dest_action = "HOLD_CASH"
    else:
        dest_action = "DEPLOY"

    acp_by = {
        str(a.get("symbol") or "").upper(): a
        for a in (acp_summaries or [])
        if isinstance(a, dict) and a.get("symbol")
    }

    rejected: list[dict[str, Any]] = []
    # Cash as rejected when deploying elsewhere
    if dest != CASH_SYMBOL:
        rejected.append(
            {
                "symbol": CASH_SYMBOL,
                "role": "cash",
                "expected_return": cash_er,
                "why_not": (
                    f"Cash E[R]={_er_s(cash_er)} below deploy target "
                    f"{dest} E[R]={_er_s(dest_er)}"
                ),
            }
        )

    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        if not sym or sym == CASH_SYMBOL:
            continue
        if row.get("role") != "holding":
            continue
        act = str(row.get("allocation_action") or "HOLD")
        er = _f(row.get("expected_return"))
        acp = acp_by.get(sym) or {}
        acp_dec = str(acp.get("decision") or "")
        if acp_dec in {"EXIT_REVIEW", "SWITCH_REVIEW"}:
            why = (
                f"Incumbent ACP={acp_dec} — capital trapped pending densify; "
                f"own E[R]={_er_s(er)} vs next ₹1 → {dest}"
            )
        elif act == "KEEP":
            why = (
                f"KEEP after costs — challenger not sufficiently better; "
                f"still not where *new* ₹1 goes (destination={dest})"
            )
        elif act == "ROTATE":
            why = (
                f"ROTATE signaled toward {row.get('best_challenger')} — "
                f"fresh ₹1 still ranks {dest} first among deploy pool"
            )
        else:
            why = (
                f"HOLD ({act}) — E[R]={_er_s(er)} does not win the next-₹1 "
                f"deploy race vs {dest}"
            )
        rejected.append(
            {
                "symbol": sym,
                "role": "incumbent",
                "allocation_action": act,
                "acp_decision": acp_dec or None,
                "expected_return": er,
                "er_completeness": row.get("er_completeness"),
                "why_not": why[:280],
            }
        )

    # Other challengers in table that lost to dest (optional thin)
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        if not sym or sym in {CASH_SYMBOL, dest} or row.get("role") == "holding":
            continue

    blockers = allocation_blocking_unknowns(table) if table else []
    blocker_syms = [
        f"{b.get('symbol')}:{b.get('unknown')}"
        for b in (blockers or [])[:8]
        if isinstance(b, dict)
    ]

    if dest == CASH_SYMBOL:
        if not any(r.get("role") == "holding" for r in rows) and not bd:
            answer = (
                "Next ₹1 → CASH — no legal deploy target and no open book "
                "(empty challenger/deploy pool)."
            )
        elif not any(r.get("role") == "holding" for r in rows):
            answer = (
                f"Next ₹1 → CASH rather than thin deploy pool "
                f"(best_deploy E[R]={_er_s(dest_er)} not clearing cash)."
            )
        else:
            hold_bits = ", ".join(
                f"{r['symbol']}({r.get('allocation_action')}/{_er_s(r.get('expected_return'))})"
                for r in rejected
                if r.get("role") == "incumbent"
            )[:180]
            answer = (
                f"Next ₹1 → CASH rather than adding to [{hold_bits or 'incumbents'}] "
                f"— cash E[R]={_er_s(cash_er)} wins deploy race (or no clearer "
                f"challenger after costs)."
            )
    else:
        vs_cash = f"cash E[R]={_er_s(cash_er)}"
        vs_holds = []
        for r in rejected:
            if r.get("role") != "incumbent":
                continue
            tag = r.get("acp_decision") or r.get("allocation_action")
            vs_holds.append(f"{r['symbol']}[{tag} E[R]={_er_s(r.get('expected_return'))}]")
        holds_s = ", ".join(vs_holds[:4]) or "no incumbents"
        answer = (
            f"Next ₹1 → {dest} (DEPLOY, E[R]={_er_s(dest_er)}) rather than "
            f"{vs_cash} or incumbents [{holds_s}] — highest risk-adjusted "
            f"deploy after switch costs / completeness."
        )

    if blocker_syms:
        answer += f" Blocking unknowns: {', '.join(blocker_syms[:4])}."

    return {
        "version": VERSION,
        "kind": "NEXT_RUPEE_CENTER",
        "laboratory_id": lab,
        "as_of_ist": day,
        "recorded_at": datetime.now(_IST).isoformat(),
        "destination": dest,
        "destination_action": dest_action,
        "destination_er": dest_er,
        "destination_score": bd.get("opportunity_score"),
        "destination_er_completeness": bd.get("er_completeness"),
        "cash_er": cash_er,
        "cash": table.get("cash"),
        "rejected": rejected[:12],
        "blocking_unknowns": blocker_syms,
        "operator_answer": answer[:600],
        "alloc_table_version": table.get("version") or ALLOC_VERSION,
        "best_deploy": {
            "symbol": bd.get("symbol"),
            "expected_return": bd.get("expected_return"),
            "opportunity_score": bd.get("opportunity_score"),
            "er_completeness": bd.get("er_completeness"),
        }
        if bd
        else None,
        "advice_only": True,
        "never_orders": True,
        "no_capital_increase": True,
        "honesty": (
            "Next-₹1 economic center — deterministic from challenger table + ACP. "
            "Does not place orders or increase capital. Missing E[R] stays unknown."
        ),
    }


def store_dir(data_dir: str | Path, laboratory_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in laboratory_id)[:80]
    return Path(data_dir) / STORE_REL / (safe or "lab")


def persist_next_rupee(
    data_dir: str | Path | None,
    doc: dict[str, Any],
) -> dict[str, Any] | None:
    if not data_dir or not isinstance(doc, dict):
        return None
    lab = str(doc.get("laboratory_id") or "lab")
    day = str(doc.get("as_of_ist") or ist_today())
    root = store_dir(data_dir, lab)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{day}.json"
    latest = root / "_latest.json"
    # Phase 5 — competition snapshot from Next-₹1 candidate table
    try:
        from atlas.investment.competition_snapshot import (
            build_competition_snapshot,
            persist_competition,
        )

        table_rows = []
        bd = doc.get("best_deploy") if isinstance(doc.get("best_deploy"), dict) else {}
        if bd.get("symbol"):
            table_rows.append(
                {
                    "symbol": bd.get("symbol"),
                    "expected_return": bd.get("expected_return"),
                    "opportunity_score": bd.get("opportunity_score"),
                }
            )
        for r in doc.get("rejected") or []:
            if not isinstance(r, dict) or not r.get("symbol"):
                continue
            table_rows.append(
                {
                    "symbol": r.get("symbol"),
                    "expected_return": r.get("expected_return"),
                    "opportunity_score": r.get("opportunity_score"),
                }
            )
        if doc.get("cash_er") is not None:
            table_rows.append(
                {"symbol": CASH_SYMBOL, "expected_return": doc.get("cash_er")}
            )
        if table_rows:
            snap = build_competition_snapshot(
                laboratory_id=lab,
                candidates=table_rows,
                decision=str(doc.get("destination_action") or "") or None,
                incumbent=str(doc.get("destination") or "") or None,
                as_of_ist=day,
            )
            persist_competition(data_dir, snap)
            doc["competition"] = {
                "winner": snap.get("winner"),
                "candidate_set": snap.get("candidate_set"),
                "line": None,
            }
            try:
                from atlas.investment.competition_snapshot import format_competition_line

                doc["competition"]["line"] = format_competition_line(snap)
            except Exception:  # noqa: BLE001
                pass
            # Feed OPEN subsequent tests (L3→L5) with today's winner observation
            try:
                from atlas.investment.l5_validation import (
                    observe_candidates_from_competition,
                )

                observe_candidates_from_competition(
                    data_dir, laboratory_id=lab, snap=snap, as_of_ist=day
                )
            except Exception:  # noqa: BLE001
                _log.debug("l5 competition observe skipped", exc_info=True)
    except Exception:  # noqa: BLE001
        _log.debug("next_rupee competition skipped", exc_info=True)
    try:
        text = json.dumps(doc, indent=2, default=str) + "\n"
        path.write_text(text, encoding="utf-8")
        latest.write_text(text, encoding="utf-8")
    except OSError:
        _log.debug("next_rupee persist failed", exc_info=True)
        return None
    out = dict(doc)
    out["path"] = str(path)
    return out


def load_next_rupee(
    data_dir: str | Path | None,
    laboratory_id: str,
    *,
    as_of_ist: str | None = None,
) -> dict[str, Any] | None:
    if not data_dir:
        return None
    root = store_dir(data_dir, laboratory_id)
    path = root / f"{(as_of_ist or ist_today()).strip()}.json"
    if not path.is_file():
        path = root / "_latest.json"
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except Exception:  # noqa: BLE001
        return None


def build_and_persist_next_rupee(
    data_dir: str | Path | None,
    table: dict[str, Any] | None,
    *,
    laboratory_id: str | None = None,
    acp_summaries: list[dict[str, Any]] | None = None,
    worldview: dict[str, Any] | None = None,
    reasoning: Any | None = None,
    experience_os: Any | None = None,
) -> dict[str, Any]:
    doc = build_next_rupee_center(
        table,
        acp_summaries=acp_summaries,
        laboratory_id=laboratory_id,
    )
    # NOW #9 — inherit Belief Core + experiences (advice-only; no math change)
    try:
        from atlas.investment.self_worldview import (
            apply_worldview_to_next_rupee,
            attach_self_worldview,
        )

        wv = worldview
        if wv is None:
            syms = [str(doc.get("destination") or "")]
            for r in doc.get("rejected") or []:
                if isinstance(r, dict) and r.get("symbol"):
                    syms.append(str(r["symbol"]))
            wv = attach_self_worldview(
                reasoning=reasoning,
                experience_os=experience_os,
                data_dir=data_dir,
                symbols=syms,
                laboratory_id=laboratory_id or doc.get("laboratory_id"),
                query=f"next rupee {doc.get('destination')} capital allocation",
            )
        doc = apply_worldview_to_next_rupee(doc, wv)
    except Exception:  # noqa: BLE001
        _log.debug("NOW #9 worldview attach skipped", exc_info=True)

    if data_dir:
        persisted = persist_next_rupee(data_dir, doc)
        if persisted:
            return persisted
    return doc


def format_next_rupee_evening_lines(
    doc: dict[str, Any] | None,
    *,
    limit_rejected: int = 4,
) -> list[str]:
    """Above-the-fold evening answer for Next-₹1."""
    if not isinstance(doc, dict) or not doc.get("operator_answer"):
        return [
            "",
            "── Next ₹1 (economic center) ──",
            "  (unavailable — no next-rupee packet today)",
        ]
    lines = [
        "",
        "── Next ₹1 (economic center — why this rupee) ──",
        f"  {doc.get('operator_answer')}",
        f"  destination={doc.get('destination')} action={doc.get('destination_action')} "
        f"E[R]={_er_s(doc.get('destination_er'))} · cash_E[R]={_er_s(doc.get('cash_er'))}",
    ]
    for r in (doc.get("rejected") or [])[: max(1, int(limit_rejected))]:
        if not isinstance(r, dict):
            continue
        lines.append(
            f"  · not {r.get('symbol')}: {(r.get('why_not') or '')[:160]}"
        )
    if doc.get("blocking_unknowns"):
        lines.append(
            f"  blocking: {', '.join(str(x) for x in doc['blocking_unknowns'][:6])}"
        )
    wv = doc.get("worldview") if isinstance(doc.get("worldview"), dict) else None
    if wv:
        bn = int(wv.get("belief_n") or 0)
        ln = int(wv.get("lesson_n") or 0)
        lines.append(f"  worldview: beliefs={bn} lessons={ln} (advice-only)")
        for c in (wv.get("belief_claims") or [])[:2]:
            if isinstance(c, dict) and c.get("claim"):
                lines.append(f"    · belief: {str(c['claim'])[:120]}")
        for x in (wv.get("experience_lessons") or [])[:2]:
            if isinstance(x, dict) and x.get("lesson"):
                lines.append(f"    · lesson: {str(x['lesson'])[:120]}")
    lines.append(f"  Honesty: {doc.get('honesty')}")
    return lines


def acp_summaries_from_disk(
    data_dir: str | Path | None,
    laboratory_id: str,
    symbols: list[str] | None,
) -> list[dict[str, Any]]:
    if not data_dir:
        return []
    out: list[dict[str, Any]] = []
    try:
        from atlas.investment.allocation_comparison import load_latest_acp_summary
    except Exception:  # noqa: BLE001
        return []
    for sym in symbols or []:
        s = str(sym or "").strip().upper()
        if not s:
            continue
        try:
            summary = load_latest_acp_summary(data_dir, laboratory_id, s)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(summary, dict):
            out.append(
                {
                    "symbol": s,
                    "decision": summary.get("decision"),
                    "operator_line": summary.get("operator_line"),
                    "reason_code": summary.get("reason_code"),
                }
            )
    return out
