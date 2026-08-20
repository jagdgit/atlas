"""OI-SELF-ID — deterministic “what did you do today?” day brief (no LLM).

Atlas is not phenomenally self-aware. This module is inheritance: read durable
artifacts Atlas already wrote today and speak them in first person.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "self0.day_activity.v1"

_DAY_RE = re.compile(
    r"\b("
    r"what\s+did\s+you\s+do\s+today|"
    r"what\s+have\s+you\s+done\s+today|"
    r"what(?:'s|\s+is)\s+your\s+(?:day|activity)\s+today|"
    r"how\s+was\s+your\s+day|"
    r"today'?s\s+activity|"
    r"summarize\s+(?:your\s+)?(?:day|today)|"
    r"what\s+happened\s+today|"
    r"day\s+brief|"
    r"activity\s+(?:report|brief)\s+today"
    r")\b",
    re.I,
)

_IST = ZoneInfo("Asia/Kolkata")


def detect_day_activity(query: str) -> bool:
    return bool(_DAY_RE.search((query or "").strip()))


def _today_ist() -> str:
    return datetime.now(_IST).date().isoformat()


def _data_root(data_dir: str | Path | None = None) -> Path | None:
    if data_dir:
        return Path(data_dir)
    try:
        from atlas.config import get_config

        return Path(get_config().paths.data)
    except Exception:  # noqa: BLE001
        return None


def _load_json(path: Path) -> Any | None:
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return None


def _count_research_mtime(root: Path, day: str) -> int:
    base = root / "investment" / "research" / "market_intelligence"
    if not base.is_dir():
        return 0
    try:
        target = date.fromisoformat(day)
    except ValueError:
        return 0
    n = 0
    for p in base.rglob("*.json"):
        try:
            if date.fromtimestamp(p.stat().st_mtime) == target:
                n += 1
        except Exception:  # noqa: BLE001
            continue
    return n


def _email_lines(root: Path, day: str) -> list[str]:
    doc = _load_json(root / "market" / "investor_reports_sent.json") or {}
    lines: list[str] = []
    morning = doc.get("morning") or []
    evening = doc.get("evening") or []
    hourly = doc.get("hourly") or []
    if any(day in str(x) for x in morning):
        lines.append("Morning investment plan email — marked sent")
    hourlies = sorted(
        str(x).split("|")[-1]
        for x in hourly
        if day in str(x) and "|" in str(x)
    )
    if hourlies:
        lines.append(f"Hourly digests marked sent for hours: {', '.join(hourlies)} IST")
    if any(day in str(x) for x in evening):
        lines.append("Evening EOD digest email — marked sent")
    if not lines:
        lines.append("No investor-report send markers found for today yet")
    return lines


def _lab_line(root: Path, lab: str, day: str) -> str:
    kpi_doc = _load_json(root / "market" / "trading_kpis" / lab / f"{day}.json") or {}
    note = _load_json(root / "market" / "session_notes" / lab / f"{day}.json") or {}
    kpis = kpi_doc.get("kpis") if isinstance(kpi_doc.get("kpis"), dict) else kpi_doc
    buys = kpis.get("buys_today")
    fills = kpis.get("fills_today")
    planned = kpis.get("planned_symbols") or []
    gap = note.get("feed_gap_days")
    reasons = note.get("reason_counts") or {}
    top = ""
    if isinstance(reasons, dict) and reasons:
        top_key = max(reasons.items(), key=lambda kv: int(kv[1] or 0))[0]
        top = f" · top idle={top_key}"
    gap_s = f" · feed_gap={gap}d" if gap is not None else ""
    plan_s = f" · planned={len(planned)}" if planned else ""
    return (
        f"{lab}: buys={buys if buys is not None else '?'} "
        f"fills={fills if fills is not None else '?'}{plan_s}{gap_s}{top}"
    )


def _hypothesis_line(root: Path, day: str) -> str | None:
    doc = _load_json(
        root
        / "investment"
        / "morning_hypothesis"
        / "india_equity_learner"
        / f"{day}.json"
    )
    if not isinstance(doc, dict):
        return None
    status = doc.get("status") or "?"
    skip = doc.get("skip_reason") or doc.get("reason") or ""
    if status == "skipped":
        return f"Morning hypothesis: skipped ({skip or 'no reason'})"
    return f"Morning hypothesis: {status}"


def _belief_lines(reasoning: Any | None) -> list[str]:
    if reasoning is None:
        return ["Belief Core: not bound on this process"]
    try:
        m = reasoning.consultation_metrics()
    except Exception:  # noqa: BLE001
        return ["Belief Core: metrics unavailable"]
    consults = m.get("consultations_today") or m
    total = consults.get("total") if isinstance(consults, dict) else None
    by = (consults.get("by_domain") if isinstance(consults, dict) else None) or {}
    counts = m.get("belief_counts") or {}
    revs = m.get("revisions") or {}
    return [
        f"Belief consultations today: {total if total is not None else '?'}"
        + (f" (market={by.get('market', 0)}, eng={by.get('engineering', 0)})" if by else ""),
        f"Active beliefs: {counts.get('active', '?')} · material revisions/7d: "
        f"{revs.get('material_total', '?')}",
    ]


def _why_idle_lines(root: Path, day: str) -> list[str]:
    """OI-STAB0 D4 — why I did / did not act (session notes + valuation)."""
    from atlas.investment.session_notes import (
        REASON_LABELS,
        format_no_fill_reasons,
        load_day_notes,
    )

    lines: list[str] = ["", "Why I did / did not act (equity)"]
    notes = load_day_notes(root, portfolio_key="india_equity_learner", ist_date=day)
    if not notes:
        lines.append("· No india_equity_learner session notes yet for this day.")
        return lines
    if notes.get("session_open") is False:
        lines.append("· Session closed for part of the day — expected idle, not a failed day.")
    basis = notes.get("valuation_basis")
    if basis:
        marks = notes.get("marks_pct")
        marks_bit = f" (marks {marks}%)" if marks is not None else ""
        lines.append(f"· Valuation basis: {basis}{marks_bit}")
    gap = notes.get("feed_gap_days")
    if gap is not None:
        lines.append(f"· Feed gap (max observed): {gap} day(s)")
    for row in format_no_fill_reasons(notes)[:6]:
        # format_no_fill_reasons already humanizes; keep bullet form
        text = row.strip()
        if text.startswith("- ") or text.startswith("·"):
            lines.append(text if text.startswith("·") else "· " + text[2:])
        else:
            lines.append(f"· {text}")
    # Top bucket with label when counts exist
    counts = notes.get("reason_counts") or {}
    if counts:
        top = max(counts.items(), key=lambda kv: int(kv[1] or 0))
        label = REASON_LABELS.get(str(top[0]), str(top[0]))
        lines.append(f"· Dominant idle bucket: {label} ×{top[1]}")
    return lines


def build_day_activity_brief(
    *,
    data_dir: str | Path | None = None,
    reasoning: Any | None = None,
    day: str | None = None,
    journal: Any | None = None,
) -> dict[str, Any]:
    """Return first-person day brief — journal first, artifact fallback (no LLM)."""
    day_ist = day or _today_ist()

    # P0.0 — prefer live activity_events work journal
    j = journal
    if j is None:
        try:
            from atlas.activity import get_journal

            j = get_journal()
        except Exception:  # noqa: BLE001
            j = None
    if j is not None:
        try:
            brief = j.format_day_brief(day_ist)
            if brief.get("ok") and int(brief.get("count") or 0) > 0:
                # Append honesty footer: why idle + beliefs + KPI cross-check
                root = _data_root(data_dir)
                extra: list[str] = []
                if root is not None:
                    extra.extend(_why_idle_lines(root, day_ist))
                    research_n = _count_research_mtime(root, day_ist)
                    extra.append("")
                    extra.append("Artifact cross-check")
                    extra.append(f"· Research dossiers mtime today: {research_n}")
                    for lab in ("india_equity_learner", "equity_intraday_learner"):
                        kpi_path = root / "market" / "trading_kpis" / lab / f"{day_ist}.json"
                        if kpi_path.is_file():
                            extra.append(f"· {_lab_line(root, lab, day_ist)}")
                extra.append("")
                extra.append("Belief Core")
                for row in _belief_lines(reasoning):
                    extra.append(f"· {row}")
                try:
                    from atlas.investment.session_readiness import evaluate_equity_session

                    card = evaluate_equity_session(root, day=day_ist)
                    extra.append("")
                    extra.append(
                        f"Session readiness: {card.get('status')} "
                        f"({card.get('counts', {}).get('required_ok')}/"
                        f"{card.get('counts', {}).get('required')} required gates)"
                    )
                except Exception:  # noqa: BLE001
                    pass
                answer = str(brief.get("answer") or "")
                if extra:
                    answer = answer.rstrip() + "\n" + "\n".join(extra)
                return {
                    **brief,
                    "answer": answer,
                    "mode": "day_activity_journal",
                    "source": "activity_events",
                }
        except Exception:  # noqa: BLE001
            pass

    root = _data_root(data_dir)
    lines: list[str] = [
        f"Here is what I can verify I did on {day_ist} (IST) from durable artifact "
        "files (activity journal empty or unbound) — not introspection:",
        "",
    ]
    citations: list[dict[str, Any]] = []

    if root is None:
        lines.append("Data directory unavailable — cannot read today's artifacts.")
        return {
            "ok": False,
            "version": VERSION,
            "mode": "day_activity",
            "day_ist": day_ist,
            "answer": "\n".join(lines),
            "citations": [],
        }

    lines.append("Mail / investor reports")
    for row in _email_lines(root, day_ist):
        lines.append(f"· {row}")
    citations.append(
        {
            "type": "artifact",
            "document_id": "market/investor_reports_sent.json",
            "snippet": f"send markers for {day_ist}",
        }
    )

    lines.append("")
    lines.append("Paper labs (ticks ≠ fills)")
    for lab in (
        "india_equity_learner",
        "equity_intraday_learner",
        "india_fno_learner",
    ):
        kpi_path = root / "market" / "trading_kpis" / lab / f"{day_ist}.json"
        if kpi_path.is_file() or (
            root / "market" / "session_notes" / lab / f"{day_ist}.json"
        ).is_file():
            lines.append(f"· {_lab_line(root, lab, day_ist)}")
            citations.append(
                {
                    "type": "artifact",
                    "document_id": f"market/trading_kpis/{lab}/{day_ist}.json",
                    "snippet": lab,
                }
            )
        else:
            lines.append(f"· {lab}: no KPI/session artifact for {day_ist} yet")

    research_n = _count_research_mtime(root, day_ist)
    lines.append("")
    lines.append("Research / cognition")
    lines.append(f"· Market dossiers with today's mtime: {research_n}")
    hyp = _hypothesis_line(root, day_ist)
    if hyp:
        lines.append(f"· {hyp}")

    lines.append("")
    lines.append("Belief Core")
    for row in _belief_lines(reasoning):
        lines.append(f"· {row}")

    lines.append("")
    lines.append(
        "Honest limits: I do not feel a day. Journal emitters may still be warming up — "
        "ask again after workers tick, or “market intelligence status” for lab KPIs."
    )

    return {
        "ok": True,
        "version": VERSION,
        "mode": "day_activity",
        "day_ist": day_ist,
        "answer": "\n".join(lines),
        "citations": citations,
        "research_dossiers_mtime": research_n,
        "source": "artifacts",
    }
