"""OI-LEARN-AUDIT0 LA.0–LA.4 — Learning Auditor (instrument, not destination).

Proves whether Atlas is becoming a better Next-₹1 investor.
Hard law: Stored ≠ observed ≠ understood ≠ predicted ≠ learned ≠ improved.

LA.1: daily JSON from existing stores + evening lines.
LA.2: weekly Learning Report (≠ EOD fills) rolled from daily audits.
LA.3: LLM contribution join (fitness ↔ advice ↔ outcomes) — not call counts.
LA.4: rolling improvement + sample gates + LOOKAHEAD integrity scan.
LA.5: chat inherit — “what did you learn?” reads this instrument, not activity counts.
Does not invent Learning Records from row counts.
Does not place orders or increase capital.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "learn_audit.la4.v1"
VERSION_WEEKLY = "learn_audit.la2.weekly.v1"
KIND = "LEARNING_AUDIT"
KIND_WEEKLY = "WEEKLY_LEARNING_REPORT"
STORE_REL = Path("investment") / "learning_audit"
SAMPLE_GATE_N = 5  # LA.4 — do not claim IMPROVING/WORSE below this n
_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.learning_audit")

# Activity that is explicitly NOT learning (denylist for Auditor honesty)
NOT_LEARNING = frozenset(
    {
        "llm_call_count",
        "embedding_count",
        "consultation_count",
        "row_count",
        "tick_count",
        "research_job_count",
        "experience_row_without_chain",
        "database_size",
    }
)

CHAIN_STAGES = (
    "data",
    "evidence",
    "hypothesis",
    "prediction",
    "decision",
    "outcome",
    "attribution",
    "learning",
    "belief_update",
)


def ist_today() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in (s or ""))[:80]


def day_path(
    data_dir: str | Path | None,
    laboratory_id: str,
    as_of_ist: str | None = None,
) -> Path | None:
    if not data_dir:
        return None
    day = as_of_ist or ist_today()
    return Path(data_dir) / STORE_REL / _safe(laboratory_id) / f"{day}.json"


def latest_path(data_dir: str | Path | None, laboratory_id: str) -> Path | None:
    if not data_dir:
        return None
    return Path(data_dir) / STORE_REL / _safe(laboratory_id) / "_latest.json"


def empty_audit(
    *,
    laboratory_id: str,
    as_of_ist: str | None = None,
    reason: str = "no_data_dir",
) -> dict[str, Any]:
    day = as_of_ist or ist_today()
    return {
        "version": VERSION,
        "kind": KIND,
        "laboratory_id": laboratory_id,
        "as_of_ist": day,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "instrument_not_destination": True,
        "destination": "better_next_rupee_investor",
        "hard_principle": (
            "stored_neq_observed_neq_understood_neq_predicted_neq_learned_neq_improved"
        ),
        "not_learning": sorted(NOT_LEARNING),
        "chain_stages": list(CHAIN_STAGES),
        "learning_records": [],
        "learning_record_n": 0,
        "failure_patterns": [],
        "improvement": {
            "status": "unknown",
            "honesty": "LA.4 rolling windows + sample gates",
        },
        "data_quality": {},
        "llm_contribution": {
            "status": "unknown",
            "honesty": "Call counts are not contribution — LA.3 joins outcomes",
        },
        "throughput_not_learning": {},
        "overall_state": "UNKNOWN",
        "milestone": (
            "Five genuine learnings with evidence — not more trades "
            "(OI-LEARN-AUDIT0 Amendment A)"
        ),
        "skipped": True,
        "skip_reason": reason,
        "honesty": (
            "Learning Auditor is an instrument. Empty learning_records with "
            "explicit honesty is success; inventing learnings from row counts is failure."
        ),
        "advice_only": True,
        "never_orders": True,
        "no_capital_increase": True,
    }


def _scientist_status_counts(
    data_dir: str | Path | None, laboratory_id: str
) -> dict[str, int]:
    if not data_dir:
        return {}
    root = (
        Path(data_dir)
        / "investment"
        / "scientist_notes"
        / _safe(laboratory_id)
        / "by_id"
    )
    if not root.is_dir():
        return {}
    counts: dict[str, int] = {}
    reviewed = 0
    for p in root.glob("*.json"):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict):
            continue
        st = str(doc.get("llm_status") or "?")
        counts[st] = counts.get(st, 0) + 1
        notes = doc.get("notes") if isinstance(doc.get("notes"), dict) else {}
        if str(notes.get("review_status") or "") == "REVIEWED":
            reviewed += 1
    counts["REVIEWED_notes"] = reviewed
    return counts


def _fitness_summary(data_dir: str | Path | None, as_of_ist: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "n": 0,
        "ok": 0,
        "error": 0,
        "timeout": 0,
        "scientist_purposes": 0,
        "top_errors": [],
    }
    if not data_dir:
        return out
    try:
        from collections import Counter

        from atlas.llm.fitness_ledger import load_day, summarize_day

        rows = load_day(data_dir, as_of_ist=as_of_ist)
        summary = summarize_day(rows) if rows else {}
        out["n"] = int(summary.get("n") or len(rows) or 0)
        by = summary.get("by_outcome") if isinstance(summary.get("by_outcome"), dict) else {}
        if not by and rows:
            by = dict(
                Counter(str(r.get("outcome") or "?") for r in rows if isinstance(r, dict))
            )
        out["ok"] = int(by.get("ok") or 0)
        out["error"] = int(by.get("error") or 0)
        out["timeout"] = int(by.get("timeout") or 0)
        err_c: dict[str, int] = {}
        sci = 0
        for r in rows or []:
            if not isinstance(r, dict):
                continue
            purpose = str(r.get("purpose") or "")
            if "scientist" in purpose or "icr5" in purpose or "bre3" in purpose:
                sci += 1
            if str(r.get("outcome") or "") == "error":
                key = str(r.get("error") or r.get("reason") or "error")[:120]
                err_c[key] = err_c.get(key, 0) + 1
        out["scientist_purposes"] = sci
        out["top_errors"] = sorted(err_c.items(), key=lambda x: -x[1])[:5]
        out["ok_rate"] = round(out["ok"] / out["n"], 4) if out["n"] else None
        out["_rows"] = rows  # LA.3 join — stripped before persist
    except Exception:  # noqa: BLE001
        _log.debug("fitness summary skipped", exc_info=True)
    return out


_RELEVANT_PURPOSE_MARKERS = (
    "scientist",
    "icr5",
    "bre3",
    "decide_rationale",
    "cognitive_core",
    "belief_revision",
)


def _purpose_relevant(purpose: str) -> bool:
    p = (purpose or "").lower()
    return any(m in p for m in _RELEVANT_PURPOSE_MARKERS)


def _bre_rationale_counts(
    data_dir: str | Path | None, laboratory_id: str
) -> dict[str, int]:
    out = {"n": 0, "REVIEWED": 0, "UNREVIEWED": 0, "with_text": 0, "pending": 0}
    if not data_dir:
        return out
    root = (
        Path(data_dir)
        / "investment"
        / "decide_rationale"
        / _safe(laboratory_id)
        / "by_id"
    )
    if not root.is_dir():
        return out
    for p in root.glob("*.json"):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict):
            continue
        out["n"] += 1
        st = str(doc.get("review_status") or doc.get("status") or "")
        if st == "REVIEWED":
            out["REVIEWED"] += 1
        elif st == "UNREVIEWED":
            out["UNREVIEWED"] += 1
        elif st in {"pending", "scheduled"} or not st:
            out["pending"] += 1
        if doc.get("rationale_text"):
            out["with_text"] += 1
    return out


def build_llm_contribution_scorecard(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    as_of_ist: str,
    fitness: dict[str, Any] | None = None,
    learning_records: list[dict[str, Any]] | None = None,
    scientist: dict[str, int] | None = None,
) -> dict[str, Any]:
    """LA.3 — join fitness ↔ advice artifacts ↔ learning outcomes (honest).

    Does not invent economic contribution. Call counts alone never set status=measured.
    """
    fit = fitness if isinstance(fitness, dict) else {}
    sci = scientist if isinstance(scientist, dict) else {}
    records = learning_records if isinstance(learning_records, list) else []

    relevant_ok = relevant_err = relevant_to = noise = 0
    by_purpose: dict[str, int] = {}
    for r in fit.get("_rows") or []:
        if not isinstance(r, dict):
            continue
        purpose = str(r.get("purpose") or "unknown")
        outcome = str(r.get("outcome") or "")
        if _purpose_relevant(purpose):
            by_purpose[purpose] = by_purpose.get(purpose, 0) + 1
            if outcome == "ok":
                relevant_ok += 1
            elif outcome == "timeout":
                relevant_to += 1
            elif outcome in {"error", "busy", "lane_busy"}:
                relevant_err += 1
        else:
            noise += 1

    # Advice artifacts (scientist notes)
    advice_produced = int(sci.get("REVIEWED_notes") or 0)
    advice_done = int(sci.get("done") or 0)
    advice_pending = int(sci.get("pending") or 0) + int(
        sci.get("deferred_lane_busy") or 0
    )
    advice_failed = sum(
        int(v)
        for k, v in sci.items()
        if str(k).startswith("failed") and isinstance(v, int)
    )
    # Prefer REVIEWED; done without REVIEWED still counts as produced candidate
    produced = max(advice_produced, advice_done)

    reviewed_symbols: set[str] = set()
    if data_dir:
        root = (
            Path(data_dir)
            / "investment"
            / "scientist_notes"
            / _safe(laboratory_id)
            / "by_id"
        )
        if root.is_dir():
            for p in root.glob("*.json"):
                try:
                    doc = json.loads(p.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(doc, dict):
                    continue
                notes = doc.get("notes") if isinstance(doc.get("notes"), dict) else {}
                if str(notes.get("review_status") or "") != "REVIEWED" and str(
                    doc.get("llm_status") or ""
                ) != "done":
                    continue
                sym = str(doc.get("symbol") or notes.get("symbol") or "").upper()
                if sym:
                    reviewed_symbols.add(sym)
                # recount produced from scan when REVIEWED_notes lag
                if str(notes.get("review_status") or "") == "REVIEWED":
                    produced = max(produced, advice_produced)

    bre = _bre_rationale_counts(data_dir, laboratory_id)
    produced += int(bre.get("REVIEWED") or 0)

    # Outcome join — Learning Records on symbols that received LLM advice
    validated = 0
    rejected_hyp = 0
    for rec in records:
        if not isinstance(rec, dict):
            continue
        sym = str(rec.get("symbol") or "").upper()
        if reviewed_symbols and sym not in reviewed_symbols:
            continue
        if not reviewed_symbols:
            # No REVIEWED advice yet — cannot validate LLM-induced learning
            continue
        if rec.get("chain_complete"):
            pe = rec.get("error") if isinstance(rec.get("error"), dict) else {}
            direction = str(pe.get("direction_match") or "").lower()
            if direction in {"missed", "wrong", "false"}:
                rejected_hyp += 1
            else:
                validated += 1
        elif str(rec.get("status") or "") == "PROVISIONAL":
            # provisional without chain — useful candidate, not validated
            pass

    useful = produced  # emitted advice that entered the research surface
    # LLM-induced *decision* changes: research attach only; never claim fills
    llm_induced_changes = produced
    llm_induced_correct = validated  # only when outcome join exists

    relevant_n = relevant_ok + relevant_err + relevant_to
    contribution_rate = None
    if relevant_ok > 0 and validated > 0:
        contribution_rate = round(validated / relevant_ok, 4)

    if produced == 0 and relevant_n == 0:
        status = "unmeasured_economic"
    elif produced == 0:
        status = "joined_throughput_no_advice"
    elif validated == 0:
        status = "joined_advice_unvalidated"
    else:
        status = "partial_economic"

    return {
        "version": "learn_audit.la3.contribution.v1",
        "status": status,
        "calls_today": fit.get("n"),
        "ok": fit.get("ok"),
        "error": fit.get("error"),
        "timeout": fit.get("timeout"),
        "scientist_related": fit.get("scientist_purposes"),
        "ok_rate": fit.get("ok_rate"),
        "relevant_calls": relevant_n,
        "relevant_ok": relevant_ok,
        "relevant_error": relevant_err,
        "relevant_timeout": relevant_to,
        "noise_calls": noise,
        "relevant_by_purpose": dict(
            sorted(by_purpose.items(), key=lambda x: -x[1])[:8]
        ),
        "useful_hypotheses": useful,
        "validated_hypotheses": validated,
        "rejected_hypotheses": rejected_hyp,
        "llm_induced_decision_changes": llm_induced_changes,
        "llm_induced_correct_changes": llm_induced_correct if validated else None,
        "contribution_rate": contribution_rate,
        "advice": {
            "scientist_REVIEWED": advice_produced,
            "scientist_done": advice_done,
            "scientist_pending": advice_pending,
            "scientist_failed": advice_failed,
            "bre_REVIEWED": bre.get("REVIEWED"),
            "bre_with_text": bre.get("with_text"),
            "reviewed_symbols_n": len(reviewed_symbols),
        },
        "chain": (
            "hypothesis → accepted/rejected → future observation → "
            "correct/incorrect → economic contribution"
        ),
        "honesty": (
            "LA.3 joins fitness↔advice↔Learning Records. "
            "Call counts are not contribution. "
            "llm_induced_decision_changes counts research-surface advice only — "
            "never fills/orders. "
            "Economic contribution stays null until validated Learning Records exist "
            "on REVIEWED advice symbols. "
            "One useful hypothesis can beat hundreds of empty calls."
        ),
    }


def _load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _next_rupee_snapshot(
    data_dir: str | Path | None, laboratory_id: str, day: str
) -> dict[str, Any]:
    if not data_dir:
        return {}
    base = Path(data_dir) / "investment" / "next_rupee" / _safe(laboratory_id)
    doc = _load_json(base / f"{day}.json") or _load_json(base / "_latest.json") or {}
    return {
        "destination": doc.get("destination"),
        "destination_action": doc.get("destination_action"),
        "destination_er": doc.get("destination_er"),
        "operator_answer": (doc.get("operator_answer") or "")[:220],
        "blocking_unknowns_n": len(doc.get("blocking_unknowns") or []),
        "advice_only": doc.get("advice_only", True),
        "never_orders": doc.get("never_orders", True),
    }


def _kpi_snapshot(
    data_dir: str | Path | None, laboratory_id: str, day: str
) -> dict[str, Any]:
    if not data_dir:
        return {}
    path = (
        Path(data_dir) / "market" / "trading_kpis" / _safe(laboratory_id) / f"{day}.json"
    )
    doc = _load_json(path) or {}
    k = doc.get("kpis") if isinstance(doc.get("kpis"), dict) else doc
    if not isinstance(k, dict):
        return {}
    return {
        "buys_today": k.get("buys_today"),
        "sells_today": k.get("sells_today"),
        "fills_today": k.get("fills_today"),
        "open_positions": k.get("open_positions"),
        "top_no_fill_reasons": list(k.get("top_no_fill_reasons") or [])[:6],
        "planned_symbols": list(k.get("planned_symbols") or [])[:8],
        "equity": k.get("equity"),
        "cash": k.get("cash"),
    }


def _failure_patterns(
    *,
    scientist: dict[str, int],
    fitness: dict[str, Any],
    kpi: dict[str, Any],
    learning_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    patterns: list[dict[str, Any]] = []

    failed_attr = int(scientist.get("failed:AttributeError") or 0)
    pending = int(scientist.get("pending") or 0)
    reviewed = int(scientist.get("REVIEWED_notes") or 0)
    if failed_attr or (pending and reviewed == 0):
        status = "NOT_SOLVED"
        if failed_attr == 0 and reviewed > 0:
            status = "PARTIALLY_SOLVED"
        patterns.append(
            {
                "id": "scientist_llm_drain",
                "label": "Scientist notes LLM drain (REVIEWED backlog)",
                "occurrences": pending + failed_attr,
                "detail": {
                    "pending": pending,
                    "failed_AttributeError": failed_attr,
                    "reviewed": reviewed,
                },
                "status": status,
                "honesty": (
                    "ChatMessage/as_dict fix landed 2026-08-23 — bounce required; "
                    "counts alone are not learning."
                ),
            }
        )

    err_n = int(fitness.get("error") or 0) + int(fitness.get("timeout") or 0)
    if err_n:
        top = fitness.get("top_errors") or []
        top0 = top[0][0] if top and isinstance(top[0], (list, tuple)) else ""
        status = "PARTIALLY_SOLVED" if "as_dict" in str(top0) else "NOT_SOLVED"
        patterns.append(
            {
                "id": "llm_fitness_errors",
                "label": "LLM fitness errors / timeouts (research lane)",
                "occurrences": err_n,
                "detail": {
                    "top_errors": top[:3],
                    "ok": fitness.get("ok"),
                    "n": fitness.get("n"),
                },
                "status": status,
            }
        )

    for row in kpi.get("top_no_fill_reasons") or []:
        if not isinstance(row, dict):
            continue
        reason = str(row.get("reason") or "")
        count = int(row.get("count") or 0)
        if reason == "switch_blocked" and count:
            patterns.append(
                {
                    "id": "switch_blocked_plc_a",
                    "label": "Opportunity switch blocked (PLC.A / advantage unclear)",
                    "occurrences": count,
                    "status": "NOT_SOLVED",
                    "honesty": (
                        "Incumbent capital may stay trapped — opp-cost densify ongoing"
                    ),
                }
            )
        if reason == "session_closed" and count:
            patterns.append(
                {
                    "id": "session_closed",
                    "label": "Session closed (weekend / after hours) — expected idle",
                    "occurrences": count,
                    "status": "EXPECTED",
                }
            )

    by_kind = (
        learning_summary.get("by_kind") if isinstance(learning_summary, dict) else {}
    )
    if isinstance(by_kind, dict):
        oc = int(by_kind.get("opportunity_cost_resolved") or 0)
        ocs = int(by_kind.get("opportunity_cost_scheduled") or 0)
        if oc or ocs:
            patterns.append(
                {
                    "id": "opportunity_cost_loop",
                    "label": "Opportunity-cost scheduled/resolved events",
                    "occurrences": oc + ocs,
                    "detail": {"resolved": oc, "scheduled": ocs},
                    "status": "IMPROVING" if oc else "NOT_SOLVED",
                    "honesty": (
                        "Event rows are not Learning Records until chain completes"
                    ),
                }
            )

    return patterns


def _lesson_text_from_event(ev: dict[str, Any]) -> str | None:
    """Prefer explicit lesson string; else first non-empty lessons.* track."""
    for key in ("lesson", "update", "summary"):
        val = ev.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:500]
    lessons = ev.get("lessons")
    if isinstance(lessons, dict):
        for track in (
            "atlas",
            "strategy",
            "thesis",
            "market",
            "relative_opportunity",
        ):
            val = lessons.get(track)
            if isinstance(val, str) and val.strip():
                return f"[{track}] {val.strip()}"[:500]
        for track, val in lessons.items():
            if isinstance(val, str) and val.strip():
                return f"[{track}] {val.strip()}"[:500]
    return None


def _derive_candidate_lesson(
    ev: dict[str, Any], pe: dict[str, Any], attr: dict[str, Any]
) -> str | None:
    """Deterministic L3 candidate when no lesson tracks exist — never invents success."""
    existing = _lesson_text_from_event(ev)
    if existing:
        return existing
    err = pe.get("error_pct")
    unknowns: list[str] = []
    causal = attr.get("causal_factors") if isinstance(attr.get("causal_factors"), dict) else {}
    if isinstance(causal.get("unknown"), list):
        unknowns = [str(u) for u in causal["unknown"][:4]]
    if isinstance(attr.get("unknown"), list):
        unknowns = unknowns or [str(u) for u in attr["unknown"][:4]]
    bits: list[str] = []
    if pe.get("status") == "computed" and err is not None:
        bits.append(f"prediction_error={err}%")
    if unknowns:
        bits.append("unknowns=" + ",".join(unknowns))
    elif str(attr.get("status") or "") == "unknown_explicit":
        bits.append("attribution=unknown_explicit")
    sym = str(ev.get("symbol") or "").upper()
    if not bits:
        return None
    return (
        f"[atlas] {sym or 'name'}: provisional lesson from computed error — "
        + "; ".join(bits)
        + ". Not validated; belief unchanged until subsequent test."
    )[:500]


def classify_learning_category(rec: dict[str, Any]) -> str:
    """investment | system — MDPH operational rows never count toward L5 investment."""
    explicit = str(rec.get("category") or rec.get("learning_class") or "").lower()
    if explicit in {"investment", "system"}:
        return explicit
    src = str(rec.get("source") or "").lower()
    if "mdph" in src or "provider" in src or "silent_yahoo" in src:
        return "system"
    if str(rec.get("decision_status") or "") == "NOT_EVALUABLE":
        return "system"
    if src in {"experience_event", "opportunity_cost_resolved"}:
        return "investment"
    return "investment"


def classify_learning_level(rec: dict[str, Any]) -> str:
    """L0–L5 per MDPH learning contract."""
    pe = rec.get("prediction") if isinstance(rec.get("prediction"), dict) else {}
    attr = rec.get("attribution") if isinstance(rec.get("attribution"), dict) else {}
    lesson = rec.get("update") or rec.get("lesson")
    belief = str(rec.get("belief_update") or "").lower()
    has_pred_out = pe.get("status") == "computed" or (
        rec.get("outcome") is not None and bool(pe)
    )
    if not has_pred_out and not rec.get("outcome"):
        return "L0"
    level = "L1"
    if attr.get("satisfied") or str(attr.get("status") or "") in {
        "unknown_explicit",
        "attributed",
        "partial",
    }:
        level = "L2"
    if lesson:
        level = "L3"
    if belief in {"candidate", "weaken", "strengthen"} or rec.get("belief_candidate"):
        level = "L4"
    if (
        rec.get("subsequent_test")
        or rec.get("validation")
        or str(rec.get("level") or "").upper() in {"L5", "5"}
    ):
        level = "L5"
    # CLC.4 — a cited loop is not L5 without subsequent validation.
    if rec.get("loop_closed_cite") and not rec.get("subsequent_test") and not rec.get(
        "validation"
    ):
        if level == "L5":
            level = "L4"
    return level


def _provisional_learning_from_events(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Promote only chain-complete-ish experiences; never invent from throughput."""
    records: list[dict[str, Any]] = []
    for i, ev in enumerate(events):
        if not isinstance(ev, dict):
            continue
        kind = str(ev.get("kind") or "")
        event_kind = str(ev.get("event_kind") or "")
        if kind == "EXPERIENCE":
            pe = (
                ev.get("prediction_error")
                if isinstance(ev.get("prediction_error"), dict)
                else {}
            )
            attr = (
                ev.get("attribution") if isinstance(ev.get("attribution"), dict) else {}
            )
            if pe.get("status") != "computed":
                continue
            lesson = _derive_candidate_lesson(ev, pe, attr)
            if not lesson and not attr.get("satisfied"):
                continue
            belief_update = ev.get("belief_update")
            rec = {
                "id": f"L-{str(ev.get('experience_id') or ev.get('id') or i)[:12]}",
                "status": "PROVISIONAL",
                "symbol": ev.get("symbol"),
                "before": ev.get("before") or ev.get("prior_belief") or ev.get("predicted"),
                "evidence": ev.get("evidence") or ev.get("evidence_refs"),
                "prediction": pe,
                "decision": ev.get("decision") or ev.get("action"),
                "outcome": ev.get("outcome") or pe.get("observed"),
                "error": pe,
                "attribution": attr,
                "update": lesson,
                "lesson": lesson,
                "lessons": ev.get("lessons"),
                "belief_update": belief_update,
                "confidence": ev.get("confidence"),
                "chain_complete": bool(attr.get("satisfied") and lesson),
                "source": "experience_event",
                "experience_id": ev.get("experience_id"),
                "category": "investment",
                "learning_class": "investment",
                "honesty": (
                    "PROVISIONAL — experience with computed error; "
                    "L5 requires subsequent validation of any belief candidate"
                ),
            }
            rec["level"] = classify_learning_level(rec)
            if rec.get("experience_refs") or rec.get("lesson_refs") or ev.get("experience_refs"):
                rec["loop_closed_cite"] = True
                rec["honesty"] = (
                    "loop_closed_cite — lesson retrieved and applied; "
                    "L5 requires subsequent validation of any belief candidate"
                )
                rec["level"] = classify_learning_level(rec)
            records.append(rec)
        elif event_kind == "opportunity_cost_resolved":
            records.append(
                {
                    "id": f"L-oc-{str(ev.get('id') or i)[:10]}",
                    "status": "PROVISIONAL",
                    "symbol": ev.get("symbol"),
                    "before": "Incumbent capital vs challenger E[R] unresolved",
                    "evidence": ev.get("detail") or ev.get("payload"),
                    "prediction": None,
                    "decision": ev.get("decision") or "HOLD/EXIT_REVIEW",
                    "outcome": ev.get("outcome") or ev.get("resolved"),
                    "error": ev.get("opportunity_cost") or ev.get("delta"),
                    "attribution": {"hints": ["incumbent_bias", "relative_ranking"]},
                    "update": (
                        "Existing ownership must not block relative advantage review"
                    ),
                    "lesson": (
                        "Existing ownership must not block relative advantage review"
                    ),
                    "confidence": None,
                    "chain_complete": False,
                    "source": "opportunity_cost_resolved",
                    "category": "investment",
                    "learning_class": "investment",
                    "level": "L3",
                    "honesty": (
                        "PROVISIONAL from opp-cost event — not a full Learning Record "
                        "(missing explicit before-belief + matured prediction)"
                    ),
                }
            )
        if len(records) >= 8:
            break
    return records


def _overall_state(
    *,
    learning_n: int,
    patterns: list[dict[str, Any]],
    fitness: dict[str, Any],
) -> str:
    not_solved = sum(1 for p in patterns if p.get("status") == "NOT_SOLVED")
    if learning_n >= 5 and not_solved == 0:
        return "IMPROVING"
    if learning_n >= 1 or any(p.get("status") == "IMPROVING" for p in patterns):
        return "DEVELOPING"
    if int(fitness.get("error") or 0) > int(fitness.get("ok") or 0):
        return "DEVELOPING"
    if learning_n == 0:
        return "UNPROVEN"
    return "DEVELOPING"


def build_learning_audit(
    data_dir: str | Path | None,
    *,
    laboratory_id: str = "india_equity_learner",
    as_of_ist: str | None = None,
) -> dict[str, Any]:
    """LA.1 — assemble daily Learning Audit from existing stores (read-only)."""
    day = as_of_ist or ist_today()
    lab = str(laboratory_id or "india_equity_learner")
    if not data_dir:
        return empty_audit(laboratory_id=lab, as_of_ist=day, reason="no_data_dir")

    learning_summary: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    try:
        from atlas.investment.learning_objects import (
            load_learning_events,
            summarize_learning_day,
        )

        events = load_learning_events(data_dir, lab, as_of_ist=day, limit=300)
        learning_summary = summarize_learning_day(events)
    except Exception:  # noqa: BLE001
        _log.debug("learning events load skipped", exc_info=True)

    scientist = _scientist_status_counts(data_dir, lab)
    fitness = _fitness_summary(data_dir, day)
    kpi = _kpi_snapshot(data_dir, lab, day)
    next_r = _next_rupee_snapshot(data_dir, lab, day)
    records = _provisional_learning_from_events(events)
    patterns = _failure_patterns(
        scientist=scientist,
        fitness=fitness,
        kpi=kpi,
        learning_summary=learning_summary,
    )

    data_quality = {
        "learning_events_n": int(learning_summary.get("events") or 0),
        "experiences_n": int(learning_summary.get("experiences") or 0),
        "prediction_errors_computed": int(
            learning_summary.get("prediction_errors_computed") or 0
        ),
        "attribution_satisfied": int(learning_summary.get("attribution_satisfied") or 0),
        "decision_time_integrity": scan_lookahead_integrity(
            data_dir,
            laboratory_id=lab,
            as_of_ist=day,
            events=events,
        ),
    }

    llm_contribution = build_llm_contribution_scorecard(
        data_dir,
        laboratory_id=lab,
        as_of_ist=day,
        fitness=fitness,
        learning_records=records,
        scientist=scientist,
    )
    # Never persist raw fitness rows inside the audit JSON
    fitness.pop("_rows", None)

    throughput = {
        "warning": "These are NOT learning metrics",
        "kpi_fills_today": kpi.get("fills_today"),
        "kpi_buys_today": kpi.get("buys_today"),
        "learning_event_rows": learning_summary.get("events"),
        "scientist_pending": scientist.get("pending"),
        "llm_calls": fitness.get("n"),
        "not_learning_labels": sorted(NOT_LEARNING),
    }

    overall = _overall_state(
        learning_n=len(records), patterns=patterns, fitness=fitness
    )
    chain_complete_n = len([r for r in records if r.get("chain_complete")])
    investment_l5_n = len(
        [
            r
            for r in records
            if r.get("chain_complete")
            and classify_learning_category(r) == "investment"
            and str(r.get("level") or "") == "L5"
        ]
    )
    improvement = build_rolling_improvement(
        data_dir,
        laboratory_id=lab,
        as_of_ist=day,
        next_rupee=next_r,
    )

    return {
        "version": VERSION,
        "kind": KIND,
        "laboratory_id": lab,
        "as_of_ist": day,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "instrument_not_destination": True,
        "destination": "better_next_rupee_investor",
        "hard_principle": (
            "stored_neq_observed_neq_understood_neq_predicted_neq_learned_neq_improved"
        ),
        "not_learning": sorted(NOT_LEARNING),
        "chain_stages": list(CHAIN_STAGES),
        "learning_records": records,
        "learning_record_n": len(records),
        "genuine_learning_milestone": {
            "target": 5,
            "have": investment_l5_n,
            "chain_complete_n": chain_complete_n,
            "investment_l5_n": investment_l5_n,
            "provisional": len(records),
            "met": investment_l5_n >= 5,
            "unit": "independent_investment_L5",
            "honesty": (
                "Headline is investment L5 (prediction→outcome→attribution→lesson→"
                "belief candidate→subsequent validation). chain_complete alone is not L5; "
                "provisional candidates do not count as met."
            ),
        },
        "failure_patterns": patterns,
        "improvement": improvement,
        "data_quality": data_quality,
        "llm_contribution": llm_contribution,
        "scientist_notes": scientist,
        "throughput_not_learning": throughput,
        "kpi": kpi,
        "overall_state": overall,
        "milestone": (
            "Five genuine learnings with evidence — not more trades "
            "(OI-LEARN-AUDIT0 Amendment A)"
        ),
        "skipped": False,
        "honesty": (
            "Learning Auditor instrument — empty or provisional learnings with "
            "explicit honesty beat invented success from row counts."
        ),
        "advice_only": True,
        "never_orders": True,
        "no_capital_increase": True,
    }


def persist_learning_audit(
    data_dir: str | Path | None,
    doc: dict[str, Any],
) -> dict[str, Any]:
    if not data_dir or not isinstance(doc, dict):
        return doc
    lab = str(doc.get("laboratory_id") or "india_equity_learner")
    day = str(doc.get("as_of_ist") or ist_today())
    path = day_path(data_dir, lab, day)
    latest = latest_path(data_dir, lab)
    if path is None:
        return doc
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(doc, indent=2, default=str) + "\n"
        path.write_text(text, encoding="utf-8")
        doc["path"] = str(path)
        if latest is not None:
            latest.write_text(text, encoding="utf-8")
            doc["latest_path"] = str(latest)
    except OSError:
        _log.debug("learning audit persist failed", exc_info=True)
    return doc


def build_and_persist_learning_audit(
    data_dir: str | Path | None,
    *,
    laboratory_id: str = "india_equity_learner",
    as_of_ist: str | None = None,
) -> dict[str, Any]:
    doc = build_learning_audit(
        data_dir, laboratory_id=laboratory_id, as_of_ist=as_of_ist
    )
    return persist_learning_audit(data_dir, doc)


def load_learning_audit(
    data_dir: str | Path | None,
    *,
    laboratory_id: str = "india_equity_learner",
    as_of_ist: str | None = None,
) -> dict[str, Any] | None:
    path = day_path(data_dir, laboratory_id, as_of_ist)
    doc = _load_json(path)
    if doc is None:
        doc = _load_json(latest_path(data_dir, laboratory_id))
    return doc


def format_learning_audit_evening_lines(
    doc: dict[str, Any] | None,
    *,
    limit_patterns: int = 5,
) -> list[str]:
    lines = ["", "── Learning Audit (OI-LEARN-AUDIT0 — instrument) ──"]
    if not isinstance(doc, dict) or doc.get("skipped"):
        reason = (doc or {}).get("skip_reason") if isinstance(doc, dict) else "missing"
        lines.append(f"  no audit yet (reason={reason})")
        lines.append(
            "  Honesty: stored≠learned — empty audit beats invented learning."
        )
        return lines

    n = int(doc.get("learning_record_n") or 0)
    mile = doc.get("genuine_learning_milestone") or {}
    llm = doc.get("llm_contribution") or {}
    lines.append(
        f"  state={doc.get('overall_state')} · learning_records={n} "
        f"(chain_complete={mile.get('have')}/{mile.get('target')}) · "
        f"instrument_not_destination=true"
    )
    lines.append(
        f"  LLM today: calls={llm.get('calls_today')} ok={llm.get('ok')} "
        f"err={llm.get('error')} · contribution={llm.get('status')}"
    )
    if llm.get("relevant_calls") is not None:
        lines.append(
            f"  LA.3 join: relevant={llm.get('relevant_calls')} "
            f"(ok={llm.get('relevant_ok')} err={llm.get('relevant_error')} "
            f"timeout={llm.get('relevant_timeout')}) · "
            f"advice_useful={llm.get('useful_hypotheses')} · "
            f"validated={llm.get('validated_hypotheses')} · "
            f"rate={llm.get('contribution_rate')}"
        )
    sci = doc.get("scientist_notes") or {}
    if sci:
        lines.append(
            f"  scientist notes: pending={sci.get('pending')} "
            f"failed:AttributeError={sci.get('failed:AttributeError')} "
            f"REVIEWED={sci.get('REVIEWED_notes')}"
        )
    nr = (doc.get("improvement") or {}).get("next_rupee") or {}
    if nr.get("destination"):
        lines.append(
            f"  Next-₹1: {nr.get('destination')} {nr.get('destination_action')} "
            f"(advice-only)"
        )
    imp = doc.get("improvement") or {}
    if imp.get("version"):
        cur = imp.get("current") or {}
        lines.append(
            f"  LA.4 rolling: status={imp.get('status')} · "
            f"gate=n≥{imp.get('sample_gate')} · "
            f"cur_dir_n={cur.get('direction_n')} "
            f"hit={cur.get('direction_hit_rate')} · "
            f"delta_hit={((imp.get('delta') or {}).get('direction_hit_rate'))}"
        )
    dqi = (doc.get("data_quality") or {}).get("decision_time_integrity") or {}
    if dqi.get("status"):
        lines.append(
            f"  LOOKAHEAD: status={dqi.get('status')} · "
            f"scanned={dqi.get('scanned')} · flags={dqi.get('lookahead_flags')}"
        )
    patterns = list(doc.get("failure_patterns") or [])[: max(1, int(limit_patterns))]
    if patterns:
        lines.append("  Failure patterns:")
        for p in patterns:
            lines.append(
                f"    · {p.get('label')}: n={p.get('occurrences')} "
                f"status={p.get('status')}"
            )
    if n == 0:
        lines.append(
            "  Learning records: 0 — experiences/events without chain completion "
            "are not counted as learning."
        )
    else:
        for r in list(doc.get("learning_records") or [])[:3]:
            lines.append(
                f"    · {r.get('id')} [{r.get('status')}] {r.get('symbol')} — "
                f"{str(r.get('update') or '')[:80]}"
            )
    lines.append(
        "  Milestone: five genuine learnings with evidence — not more trades."
    )
    lines.append(f"  Honesty: {str(doc.get('honesty') or '')[:160]}")
    return lines


def detect_learning_audit_query(message: str) -> str | None:
    """LA.5 — return ``daily`` | ``weekly`` when chat asks about learning health."""
    low = (message or "").lower().strip()
    if not low:
        return None
    weekly_markers = (
        "this week",
        "weekly learning",
        "week's learning",
        "last week",
        "learning report",
    )
    learn_markers = (
        "what did you learn",
        "what have you learned",
        "what have we learned",
        "did you learn",
        "learning audit",
        "learning health",
        "genuine learning",
        "learning record",
        "learning milestone",
        "chain complete",
        "chain-complete",
    )
    if not any(m in low for m in learn_markers) and "learning report" not in low:
        return None
    if any(m in low for m in weekly_markers):
        return "weekly"
    return "daily"


def answer_learning_audit_chat(
    message: str,
    *,
    data_dir: str | Path | None = None,
    laboratory_id: str = "india_equity_learner",
) -> dict[str, Any] | None:
    """LA.5 — chat inherits Learning Auditor (instrument), not throughput counts."""
    mode = detect_learning_audit_query(message)
    if not mode:
        return None

    if mode == "weekly":
        doc = load_weekly_learning_report(data_dir, laboratory_id=laboratory_id)
        title = "Weekly Learning Report (OI-LEARN-AUDIT0 — instrument)"
        if not isinstance(doc, dict) or doc.get("skipped"):
            return {
                "ok": True,
                "kind": "learning_audit_weekly",
                "answer": (
                    "No weekly Learning Report is persisted yet for "
                    f"{laboratory_id}. After daily audits accumulate, Atlas "
                    "rolls an honest weekly instrument — not fill counts or "
                    "LLM call totals."
                ),
                "advice_only": True,
                "never_orders": True,
            }
        mile = doc.get("genuine_learning_milestone") or {}
        llm = doc.get("llm_contribution") or {}
        lines = [
            title,
            "",
            f"week={doc.get('week')} · state={doc.get('overall_state')} · "
            f"days_with_audit={doc.get('days_with_audit')}",
            f"Learning Records: {doc.get('learning_record_n')} "
            f"(chain-complete {mile.get('have')}/{mile.get('target')})",
            f"LLM week: calls={llm.get('calls_week')} ok={llm.get('ok')} · "
            f"contribution={llm.get('status')}",
        ]
        learned = list(doc.get("what_we_learned") or [])[:5]
        lines.append("")
        lines.append("What we learned (Learning Records only):")
        if not learned:
            lines.append(
                "  · (none yet — tick counts, fills, and LLM calls are not learning)"
            )
        for r in learned:
            lines.append(
                f"  · {r.get('as_of_ist')} [{r.get('status')}] {r.get('symbol')}: "
                f"{str(r.get('update') or '')[:120]}"
            )
        not_l = list(doc.get("what_we_did_not_learn") or [])[:4]
        if not_l:
            lines.append("")
            lines.append("What we did not learn (open patterns):")
            for p in not_l:
                lines.append(
                    f"  · {p.get('label')}: n={p.get('occurrences')} "
                    f"status={p.get('status')}"
                )
        lines.append("")
        lines.append(
            "Honesty: Learning Auditor is an instrument — destination is a better "
            "Next-₹1 investor. Chat does not place orders."
        )
        return {
            "ok": True,
            "kind": "learning_audit_weekly",
            "answer": "\n".join(lines),
            "week": doc.get("week"),
            "learning_record_n": doc.get("learning_record_n"),
            "chain_complete": mile.get("have"),
            "advice_only": True,
            "never_orders": True,
        }

    doc = load_learning_audit(data_dir, laboratory_id=laboratory_id)
    if not isinstance(doc, dict) or doc.get("skipped"):
        return {
            "ok": True,
            "kind": "learning_audit_daily",
            "answer": (
                "Learning Audit is not persisted yet for this lab. After a paper "
                "tick Atlas writes an honest daily instrument: Learning Records, "
                "failure patterns, and LLM contribution — not activity counts."
            ),
            "advice_only": True,
            "never_orders": True,
        }

    mile = doc.get("genuine_learning_milestone") or {}
    llm = doc.get("llm_contribution") or {}
    imp = doc.get("improvement") or {}
    sci = doc.get("scientist_notes") or {}
    lines = [
        "Learning Audit (OI-LEARN-AUDIT0 — instrument, not destination)",
        "",
        f"as_of={doc.get('as_of_ist')} · state={doc.get('overall_state')}",
        f"Learning Records: {doc.get('learning_record_n')} "
        f"(chain-complete {mile.get('have')}/{mile.get('target')})",
        f"LLM today: relevant={llm.get('relevant_calls')} ok={llm.get('relevant_ok')} · "
        f"advice_useful={llm.get('useful_hypotheses')} validated={llm.get('validated_hypotheses')}",
    ]
    if imp.get("status"):
        cur = imp.get("current") or {}
        lines.append(
            f"Improvement signal: {imp.get('status')} "
            f"(directional n={cur.get('direction_n')}, gate≥{imp.get('sample_gate')})"
        )
    nr = imp.get("next_rupee") or {}
    if nr.get("destination"):
        lines.append(
            f"Next-₹1 trail: {nr.get('destination')} {nr.get('destination_action')} "
            "(advice-only)"
        )
    if sci:
        lines.append(
            f"Scientist drain: REVIEWED={sci.get('REVIEWED_notes')} · "
            f"pending={sci.get('pending')} · "
            f"failed:AttributeError={sci.get('failed:AttributeError')}"
        )
    records = list(doc.get("learning_records") or [])[:4]
    lines.append("")
    lines.append("Learning Records (provisional or chain-complete):")
    if not records:
        lines.append("  · (none — experiences without full chain are not counted)")
    for r in records:
        chain = "complete" if r.get("chain_complete") else "provisional"
        lines.append(
            f"  · [{r.get('status')}/{chain}] {r.get('symbol')}: "
            f"{str(r.get('update') or '')[:120]}"
        )
    patterns = [
        p
        for p in (doc.get("failure_patterns") or [])
        if str(p.get("status") or "") not in {"EXPECTED"}
    ][:4]
    if patterns:
        lines.append("")
        lines.append("Open failure patterns (not learning):")
        for p in patterns:
            lines.append(
                f"  · {p.get('label')}: n={p.get('occurrences')} status={p.get('status')}"
            )
    tp = doc.get("throughput_not_learning") or {}
    if tp.get("warning"):
        lines.append("")
        lines.append(
            f"Not learning today: fills={tp.get('kpi_fills_today')} · "
            f"llm_calls={tp.get('llm_calls')} · scientist_pending={tp.get('scientist_pending')}"
        )
    lines.append("")
    lines.append(
        "Honesty: stored≠learned. Chat inherits the Auditor — not consultation counts "
        "or self-model activity. No orders from chat."
    )
    return {
        "ok": True,
        "kind": "learning_audit_daily",
        "answer": "\n".join(lines),
        "as_of_ist": doc.get("as_of_ist"),
        "learning_record_n": doc.get("learning_record_n"),
        "chain_complete": mile.get("have"),
        "overall_state": doc.get("overall_state"),
        "advice_only": True,
        "never_orders": True,
    }


def iso_week_key(as_of_ist: str | None = None) -> str:
    day = as_of_ist or ist_today()
    d = date.fromisoformat(str(day)[:10])
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def weekly_path(
    data_dir: str | Path | None,
    laboratory_id: str,
    week_key: str | None = None,
    *,
    as_of_ist: str | None = None,
) -> Path | None:
    if not data_dir:
        return None
    wk = week_key or iso_week_key(as_of_ist)
    return (
        Path(data_dir)
        / STORE_REL
        / _safe(laboratory_id)
        / "weekly"
        / f"{_safe(wk)}.json"
    )


def weekly_latest_path(data_dir: str | Path | None, laboratory_id: str) -> Path | None:
    if not data_dir:
        return None
    return Path(data_dir) / STORE_REL / _safe(laboratory_id) / "weekly" / "_latest.json"


def _day_window(end_day: str, days: int = 7) -> list[str]:
    end = date.fromisoformat(str(end_day)[:10])
    n = max(1, min(int(days), 31))
    return [(end - timedelta(days=i)).isoformat() for i in range(n - 1, -1, -1)]


def _iso_day(val: Any) -> str | None:
    s = str(val or "").strip()
    if not s:
        return None
    day = s[:10]
    if len(day) == 10 and day[4] == "-" and day[7] == "-":
        try:
            date.fromisoformat(day)
            return day
        except ValueError:
            return None
    return None


_ASOF_KEYS = frozenset(
    {
        "as_of",
        "as_of_ist",
        "bar_as_of",
        "fundamentals_as_of",
        "price_as_of",
        "observed_at",
        "evidence_as_of",
        "quote_as_of",
        "filing_as_of",
    }
)


def _collect_dated_fields(
    obj: Any,
    *,
    path: str = "",
    depth: int = 0,
    out: list[tuple[str, str]] | None = None,
) -> list[tuple[str, str]]:
    if out is None:
        out = []
    if depth > 5 or len(out) >= 40:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = str(k)
            p = f"{path}.{key}" if path else key
            if key in _ASOF_KEYS or key.endswith("_as_of"):
                day = _iso_day(v)
                if day:
                    out.append((p, day))
            else:
                _collect_dated_fields(v, path=p, depth=depth + 1, out=out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:12]):
            _collect_dated_fields(v, path=f"{path}[{i}]", depth=depth + 1, out=out)
    return out


def scan_lookahead_integrity(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    as_of_ist: str,
    events: list[dict[str, Any]] | None = None,
    limit_packets: int = 80,
) -> dict[str, Any]:
    """LA.4 — flag evidence dated after decide_ts (LOOKAHEAD)."""
    lab = _safe(laboratory_id)
    day = str(as_of_ist)[:10]
    flags: list[dict[str, Any]] = []
    scanned = 0
    if not data_dir:
        return {
            "status": "unknown",
            "scanned": 0,
            "lookahead_flags": 0,
            "flags": [],
            "honesty": "no_data_dir",
        }

    day_file = (
        Path(data_dir)
        / "investment"
        / "decisions"
        / "by_day"
        / lab
        / f"{day}.jsonl"
    )
    if day_file.is_file():
        try:
            for line in day_file.read_text(encoding="utf-8").splitlines():
                if scanned >= limit_packets:
                    break
                if not line.strip():
                    continue
                try:
                    pkt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(pkt, dict):
                    continue
                scanned += 1
                decide = _iso_day(pkt.get("ts_ist") or pkt.get("as_of_ist") or day)
                for fpath, evid in _collect_dated_fields(pkt):
                    if decide and evid > decide:
                        flags.append(
                            {
                                "kind": "LOOKAHEAD",
                                "source": "decision_packet",
                                "decision_id": pkt.get("decision_id"),
                                "symbol": pkt.get("symbol"),
                                "decide_ts": decide,
                                "evidence_as_of": evid,
                                "field": fpath,
                            }
                        )
        except OSError:
            _log.debug("lookahead packet scan skipped", exc_info=True)

    for ev in events or []:
        if not isinstance(ev, dict) or str(ev.get("kind") or "") != "EXPERIENCE":
            continue
        scanned += 1
        decide = None
        if isinstance(ev.get("decision"), dict):
            decide = _iso_day(ev["decision"].get("ts_ist"))
        decide = decide or _iso_day(ev.get("as_of_ist"))
        for fpath, evid in _collect_dated_fields(ev.get("evidence") or {}):
            if decide and evid > decide:
                flags.append(
                    {
                        "kind": "LOOKAHEAD",
                        "source": "experience",
                        "experience_id": ev.get("experience_id"),
                        "symbol": ev.get("symbol"),
                        "decide_ts": decide,
                        "evidence_as_of": evid,
                        "field": fpath,
                    }
                )

    if flags:
        status = "LOOKAHEAD_FLAGS"
    elif scanned:
        status = "CLEAN_SAMPLED"
    else:
        status = "UNKNOWN_NO_SAMPLE"

    return {
        "version": "learn_audit.la4.lookahead.v1",
        "status": status,
        "scanned": scanned,
        "lookahead_flags": len(flags),
        "flags": flags[:12],
        "sample_gate": SAMPLE_GATE_N,
        "honesty": (
            "LOOKAHEAD = evidence as_of > decide_ts. "
            "CLEAN_SAMPLED means no flags in scanned rows — not proof of global purity. "
            "UNKNOWN_NO_SAMPLE means nothing to scan yet."
        ),
    }


def _window_prediction_metrics(
    data_dir: str | Path | None,
    laboratory_id: str,
    days: list[str],
) -> dict[str, Any]:
    """Aggregate directional accuracy + Next-₹1 trail over a day window."""
    matched = missed = computed = experiences = 0
    destinations: list[str] = []
    learning_n = chain_n = 0
    empty = {
        "days": days,
        "experiences": 0,
        "direction_n": 0,
        "direction_matched": 0,
        "direction_missed": 0,
        "direction_hit_rate": None,
        "learning_record_n": 0,
        "chain_complete_n": 0,
        "next_rupee_destinations": [],
        "sample_ok": False,
    }
    if not data_dir:
        return empty

    try:
        from atlas.investment.learning_objects import load_learning_events
    except Exception:  # noqa: BLE001
        load_learning_events = None  # type: ignore[assignment]

    for d in days:
        if load_learning_events is not None:
            try:
                rows = load_learning_events(
                    data_dir, laboratory_id, as_of_ist=d, limit=300
                )
            except Exception:  # noqa: BLE001
                rows = []
            for ev in rows or []:
                if not isinstance(ev, dict) or str(ev.get("kind") or "") != "EXPERIENCE":
                    continue
                experiences += 1
                pe = (
                    ev.get("prediction_error")
                    if isinstance(ev.get("prediction_error"), dict)
                    else {}
                )
                dm = str(pe.get("direction_match") or "")
                if pe.get("status") in {"computed", "direction_only"} or dm:
                    computed += 1
                    if dm == "matched":
                        matched += 1
                    elif dm == "missed":
                        missed += 1
        aud = _load_json(day_path(data_dir, laboratory_id, d))
        if isinstance(aud, dict):
            learning_n += int(aud.get("learning_record_n") or 0)
            mile = aud.get("genuine_learning_milestone") or {}
            chain_n += int(mile.get("have") or 0)
        nr = _next_rupee_snapshot(data_dir, laboratory_id, d)
        if nr.get("destination"):
            destinations.append(str(nr.get("destination")))

    hit = round(matched / computed, 4) if computed else None
    return {
        "days": days,
        "experiences": experiences,
        "direction_n": computed,
        "direction_matched": matched,
        "direction_missed": missed,
        "direction_hit_rate": hit,
        "learning_record_n": learning_n,
        "chain_complete_n": chain_n,
        "next_rupee_destinations": destinations[-8:],
        "sample_ok": computed >= SAMPLE_GATE_N,
    }


def build_rolling_improvement(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    as_of_ist: str,
    next_rupee: dict[str, Any] | None = None,
    window_days: int = 7,
) -> dict[str, Any]:
    """LA.4 — prev vs current window; refuse IMPROVING/WORSE under sample gate."""
    day = str(as_of_ist)[:10]
    cur_days = _day_window(day, days=window_days)
    try:
        prev_end = (date.fromisoformat(cur_days[0]) - timedelta(days=1)).isoformat()
    except ValueError:
        prev_end = day
    prev_days = _day_window(prev_end, days=window_days)

    current = _window_prediction_metrics(data_dir, laboratory_id, cur_days)
    previous = _window_prediction_metrics(data_dir, laboratory_id, prev_days)

    cur_n = int(current.get("direction_n") or 0)
    prev_n = int(previous.get("direction_n") or 0)
    cur_hit = current.get("direction_hit_rate")
    prev_hit = previous.get("direction_hit_rate")

    delta: dict[str, Any] = {
        "direction_hit_rate": None,
        "direction_n": cur_n - prev_n,
        "learning_record_n": int(current.get("learning_record_n") or 0)
        - int(previous.get("learning_record_n") or 0),
    }
    if cur_hit is not None and prev_hit is not None:
        delta["direction_hit_rate"] = round(float(cur_hit) - float(prev_hit), 4)

    if cur_n < SAMPLE_GATE_N and prev_n < SAMPLE_GATE_N:
        status = "INSUFFICIENT_SAMPLE"
    elif cur_n < SAMPLE_GATE_N:
        status = "INSUFFICIENT_SAMPLE_CURRENT"
    elif prev_n < SAMPLE_GATE_N:
        status = "BASELINE_THIN"
    elif cur_hit is None or prev_hit is None:
        status = "UNKNOWN"
    else:
        d = float(delta["direction_hit_rate"] or 0)
        if d > 0.05:
            status = "IMPROVING"
        elif d < -0.05:
            status = "WORSE"
        else:
            status = "FLAT"

    return {
        "version": "learn_audit.la4.rolling.v1",
        "status": status,
        "sample_gate": SAMPLE_GATE_N,
        "window_days": window_days,
        "current": current,
        "previous": previous,
        "delta": delta,
        "next_rupee": next_rupee or {},
        "honesty": (
            f"Sample gate n≥{SAMPLE_GATE_N} directional predictions before "
            "IMPROVING/WORSE. Thin samples stay INSUFFICIENT_SAMPLE — not failure. "
            "Next-₹1 trail is exposed but not scored as P&L."
        ),
    }


def build_weekly_learning_report(
    data_dir: str | Path | None,
    *,
    laboratory_id: str = "india_equity_learner",
    as_of_ist: str | None = None,
    days: int = 7,
    ensure_dailies: bool = True,
) -> dict[str, Any]:
    """LA.2 — weekly Learning Report from daily audits (instrument, ≠ EOD fills)."""
    day = as_of_ist or ist_today()
    lab = str(laboratory_id or "india_equity_learner")
    week = iso_week_key(day)
    if not data_dir:
        return {
            "version": VERSION_WEEKLY,
            "kind": KIND_WEEKLY,
            "laboratory_id": lab,
            "week": week,
            "as_of_ist": day,
            "skipped": True,
            "skip_reason": "no_data_dir",
            "instrument_not_destination": True,
            "destination": "better_next_rupee_investor",
            "advice_only": True,
            "never_orders": True,
            "no_capital_increase": True,
        }

    window = _day_window(day, days=days)
    dailies: list[dict[str, Any]] = []
    for d in window:
        # Day-specific only — never fall back to _latest (would duplicate one day ×7)
        doc = _load_json(day_path(data_dir, lab, d))
        if doc is None and ensure_dailies:
            try:
                doc = build_and_persist_learning_audit(
                    data_dir, laboratory_id=lab, as_of_ist=d
                )
            except Exception:  # noqa: BLE001
                _log.debug("weekly daily ensure failed for %s", d, exc_info=True)
                doc = None
        if isinstance(doc, dict) and not doc.get("skipped"):
            dailies.append(doc)

    learning_records: list[dict[str, Any]] = []
    pattern_agg: dict[str, dict[str, Any]] = {}
    llm_calls = llm_ok = llm_err = llm_to = 0
    rel_ok = rel_err = rel_to = useful_sum = validated_sum = 0
    sci_pending_max = 0
    sci_reviewed_max = 0
    sci_attr_max = 0
    states: list[str] = []
    next_rupee_trail: list[dict[str, Any]] = []
    fills_sum = 0
    contrib_statuses: list[str] = []

    for aud in dailies:
        states.append(str(aud.get("overall_state") or "?"))
        for r in aud.get("learning_records") or []:
            if isinstance(r, dict):
                learning_records.append({**r, "as_of_ist": aud.get("as_of_ist")})
        for p in aud.get("failure_patterns") or []:
            if not isinstance(p, dict):
                continue
            pid = str(p.get("id") or p.get("label") or "pattern")
            cur = pattern_agg.get(pid) or {
                "id": pid,
                "label": p.get("label"),
                "occurrences": 0,
                "status": p.get("status"),
                "days_seen": 0,
            }
            cur["occurrences"] = int(cur["occurrences"] or 0) + int(
                p.get("occurrences") or 0
            )
            cur["days_seen"] = int(cur["days_seen"] or 0) + 1
            # Prefer worst status if mixed
            st = str(p.get("status") or "")
            if st == "NOT_SOLVED" or cur.get("status") != "NOT_SOLVED":
                if st:
                    cur["status"] = st
            pattern_agg[pid] = cur
        llm = aud.get("llm_contribution") or {}
        llm_calls += int(llm.get("calls_today") or 0)
        llm_ok += int(llm.get("ok") or 0)
        llm_err += int(llm.get("error") or 0)
        llm_to += int(llm.get("timeout") or 0)
        rel_ok += int(llm.get("relevant_ok") or 0)
        rel_err += int(llm.get("relevant_error") or 0)
        rel_to += int(llm.get("relevant_timeout") or 0)
        useful_sum += int(llm.get("useful_hypotheses") or 0)
        validated_sum += int(llm.get("validated_hypotheses") or 0)
        if llm.get("status"):
            contrib_statuses.append(str(llm.get("status")))
        sci = aud.get("scientist_notes") or {}
        sci_pending_max = max(sci_pending_max, int(sci.get("pending") or 0))
        sci_reviewed_max = max(sci_reviewed_max, int(sci.get("REVIEWED_notes") or 0))
        sci_attr_max = max(sci_attr_max, int(sci.get("failed:AttributeError") or 0))
        nr = (aud.get("improvement") or {}).get("next_rupee") or {}
        if nr.get("destination"):
            next_rupee_trail.append(
                {
                    "as_of_ist": aud.get("as_of_ist"),
                    "destination": nr.get("destination"),
                    "destination_action": nr.get("destination_action"),
                }
            )
        kpi = aud.get("kpi") or {}
        fills_sum += int(kpi.get("fills_today") or 0)

    chain_complete = [r for r in learning_records if r.get("chain_complete")]
    patterns = sorted(
        pattern_agg.values(), key=lambda x: -int(x.get("occurrences") or 0)
    )
    not_solved = [p for p in patterns if p.get("status") == "NOT_SOLVED"]

    # Honest overall: do not claim IMPROVING from throughput
    if len(chain_complete) >= 5 and not not_solved:
        overall = "IMPROVING"
    elif learning_records or any(p.get("status") == "IMPROVING" for p in patterns):
        overall = "DEVELOPING"
    elif dailies:
        overall = "UNPROVEN"
    else:
        overall = "UNKNOWN"

    what_learned = [
        {
            "id": r.get("id"),
            "symbol": r.get("symbol"),
            "status": r.get("status"),
            "update": r.get("update"),
            "as_of_ist": r.get("as_of_ist"),
            "chain_complete": r.get("chain_complete"),
        }
        for r in learning_records[:12]
    ]
    what_not = [
        {
            "id": p.get("id"),
            "label": p.get("label"),
            "status": p.get("status"),
            "occurrences": p.get("occurrences"),
        }
        for p in not_solved[:8]
    ]

    return {
        "version": VERSION_WEEKLY,
        "kind": KIND_WEEKLY,
        "laboratory_id": lab,
        "week": week,
        "as_of_ist": day,
        "window_days": window,
        "days_with_audit": len(dailies),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "instrument_not_destination": True,
        "destination": "better_next_rupee_investor",
        "hard_principle": (
            "stored_neq_observed_neq_understood_neq_predicted_neq_learned_neq_improved"
        ),
        "not_eod_fills_report": True,
        "overall_state": overall,
        "daily_states": states,
        "learning_records": learning_records[:20],
        "learning_record_n": len(learning_records),
        "genuine_learning_milestone": {
            "target": 5,
            "have": len(chain_complete),
            "provisional": len(learning_records),
            "met": False,
            "honesty": (
                "Weekly rollup — milestone unmet until five chain-complete "
                "Learning Records exist across the window."
            ),
        },
        "what_we_learned": what_learned,
        "what_we_did_not_learn": what_not,
        "failure_patterns": patterns[:12],
        "scientist_notes": {
            "pending_max": sci_pending_max,
            "REVIEWED_notes_max": sci_reviewed_max,
            "failed_AttributeError_max": sci_attr_max,
        },
        "llm_contribution": {
            "status": (
                "partial_economic"
                if validated_sum
                else (
                    "joined_advice_unvalidated"
                    if useful_sum
                    else (
                        "joined_throughput_no_advice"
                        if (rel_ok + rel_err + rel_to)
                        else "unmeasured_economic"
                    )
                )
            ),
            "calls_week": llm_calls,
            "ok": llm_ok,
            "error": llm_err,
            "timeout": llm_to,
            "relevant_ok": rel_ok,
            "relevant_error": rel_err,
            "relevant_timeout": rel_to,
            "useful_hypotheses": useful_sum,
            "validated_hypotheses": validated_sum,
            "contribution_rate": (
                round(validated_sum / rel_ok, 4) if rel_ok and validated_sum else None
            ),
            "daily_statuses": contrib_statuses[-7:],
            "honesty": (
                "Weekly LA.3 rollup — call counts are not contribution. "
                "Fills this window are throughput only."
            ),
        },
        "throughput_not_learning": {
            "warning": "These are NOT learning metrics",
            "kpi_fills_sum": fills_sum,
            "llm_calls_week": llm_calls,
            "days_with_audit": len(dailies),
        },
        "next_rupee_trail": next_rupee_trail[-7:],
        "milestone": (
            "Five genuine learnings with evidence — not more trades "
            "(OI-LEARN-AUDIT0 Amendment A)"
        ),
        "skipped": False,
        "honesty": (
            "Weekly Learning Report is an instrument section — empty what_we_learned "
            "with explicit honesty beats inventing lessons from fills or LLM calls."
        ),
        "advice_only": True,
        "never_orders": True,
        "no_capital_increase": True,
    }


def persist_weekly_learning_report(
    data_dir: str | Path | None,
    doc: dict[str, Any],
) -> dict[str, Any]:
    if not data_dir or not isinstance(doc, dict):
        return doc
    lab = str(doc.get("laboratory_id") or "india_equity_learner")
    week = str(doc.get("week") or iso_week_key(str(doc.get("as_of_ist") or "")))
    path = weekly_path(data_dir, lab, week)
    latest = weekly_latest_path(data_dir, lab)
    if path is None:
        return doc
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(doc, indent=2, default=str) + "\n"
        path.write_text(text, encoding="utf-8")
        doc["path"] = str(path)
        if latest is not None:
            latest.write_text(text, encoding="utf-8")
            doc["latest_path"] = str(latest)
    except OSError:
        _log.debug("weekly learning report persist failed", exc_info=True)
    return doc


def build_and_persist_weekly_learning_report(
    data_dir: str | Path | None,
    *,
    laboratory_id: str = "india_equity_learner",
    as_of_ist: str | None = None,
    days: int = 7,
    ensure_dailies: bool = True,
) -> dict[str, Any]:
    doc = build_weekly_learning_report(
        data_dir,
        laboratory_id=laboratory_id,
        as_of_ist=as_of_ist,
        days=days,
        ensure_dailies=ensure_dailies,
    )
    return persist_weekly_learning_report(data_dir, doc)


def load_weekly_learning_report(
    data_dir: str | Path | None,
    *,
    laboratory_id: str = "india_equity_learner",
    as_of_ist: str | None = None,
    week_key: str | None = None,
) -> dict[str, Any] | None:
    path = weekly_path(
        data_dir, laboratory_id, week_key=week_key, as_of_ist=as_of_ist
    )
    doc = _load_json(path)
    if doc is None:
        doc = _load_json(weekly_latest_path(data_dir, laboratory_id))
    return doc


def format_weekly_learning_report_lines(
    doc: dict[str, Any] | None,
    *,
    limit_learned: int = 5,
    limit_patterns: int = 5,
) -> list[str]:
    lines = ["", "── Weekly Learning Report (OI-LEARN-AUDIT0 LA.2 — instrument) ──"]
    if not isinstance(doc, dict) or doc.get("skipped"):
        reason = (doc or {}).get("skip_reason") if isinstance(doc, dict) else "missing"
        lines.append(f"  no weekly report yet (reason={reason})")
        lines.append(
            "  Honesty: this is not an EOD fills digest — empty beats invented learning."
        )
        return lines

    mile = doc.get("genuine_learning_milestone") or {}
    llm = doc.get("llm_contribution") or {}
    lines.append(
        f"  week={doc.get('week')} · state={doc.get('overall_state')} · "
        f"days_with_audit={doc.get('days_with_audit')} · "
        f"learning_records={doc.get('learning_record_n')} "
        f"(chain_complete={mile.get('have')}/{mile.get('target')})"
    )
    lines.append(
        f"  LLM week: calls={llm.get('calls_week')} ok={llm.get('ok')} "
        f"err={llm.get('error')} timeout={llm.get('timeout')} · "
        f"contribution={llm.get('status')}"
    )
    if llm.get("relevant_ok") is not None or llm.get("useful_hypotheses") is not None:
        lines.append(
            f"  LA.3 week: relevant_ok={llm.get('relevant_ok')} · "
            f"useful={llm.get('useful_hypotheses')} · "
            f"validated={llm.get('validated_hypotheses')} · "
            f"rate={llm.get('contribution_rate')}"
        )
    sci = doc.get("scientist_notes") or {}
    if sci:
        lines.append(
            f"  scientist (window max): pending={sci.get('pending_max')} "
            f"failed:AttributeError={sci.get('failed_AttributeError_max')} "
            f"REVIEWED={sci.get('REVIEWED_notes_max')}"
        )
    learned = list(doc.get("what_we_learned") or [])[: max(0, int(limit_learned))]
    lines.append("  What we learned (Learning Records only):")
    if not learned:
        lines.append(
            "    · (none yet — throughput/fills/LLM calls are not listed here)"
        )
    for r in learned:
        lines.append(
            f"    · {r.get('as_of_ist')} {r.get('id')} [{r.get('status')}] "
            f"{r.get('symbol')} — {str(r.get('update') or '')[:72]}"
        )
    not_l = list(doc.get("what_we_did_not_learn") or [])[: max(0, int(limit_patterns))]
    if not_l:
        lines.append("  What we did not learn (open failure patterns):")
        for p in not_l:
            lines.append(
                f"    · {p.get('label')}: n={p.get('occurrences')} "
                f"status={p.get('status')}"
            )
    trail = list(doc.get("next_rupee_trail") or [])[-3:]
    if trail:
        lines.append("  Next-₹1 trail (advice-only):")
        for t in trail:
            lines.append(
                f"    · {t.get('as_of_ist')}: {t.get('destination')} "
                f"{t.get('destination_action')}"
            )
    thr = doc.get("throughput_not_learning") or {}
    lines.append(
        f"  Throughput (NOT learning): fills_sum={thr.get('kpi_fills_sum')} · "
        f"llm_calls={thr.get('llm_calls_week')}"
    )
    lines.append(
        "  Milestone: five genuine learnings with evidence — not more trades."
    )
    lines.append(f"  Honesty: {str(doc.get('honesty') or '')[:160]}")
    return lines
