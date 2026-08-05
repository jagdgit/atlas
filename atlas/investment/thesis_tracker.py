"""IIP.8 — Thesis Tracker + outcome learning.

Tracks hypothesis → assumptions → decision → outcome → lessons.
Closed paper outcomes shift durable priors (discovery / theme / scoring).
Extends IRA outcomes — not a parallel system.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger("atlas.investment.thesis_tracker")

VERSION = "iip.8.thesis_tracker"
STORE_REL = Path("investment") / "thesis_tracker"
PRIORS_NAME = "priors.json"
DEFAULT_PROGRAM = "market_intelligence"

ASSUMPTION_KINDS = (
    "policy_support",
    "capex_delivery",
    "valuation_band",
    "management_execution",
    "leverage_ok",
    "growth_path",
    "theme_tailwind",
    "other",
)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def normalize_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if s and not s.endswith(".NS") and "." not in s:
        return f"{s}.NS"
    return s


def store_dir(data_dir: str | Path, program_id: str = DEFAULT_PROGRAM) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (program_id or DEFAULT_PROGRAM))
    return Path(data_dir) / STORE_REL / safe


def priors_path(data_dir: str | Path, program_id: str = DEFAULT_PROGRAM) -> Path:
    return store_dir(data_dir, program_id) / PRIORS_NAME


def tracker_path(
    data_dir: str | Path, symbol: str, program_id: str = DEFAULT_PROGRAM
) -> Path:
    return store_dir(data_dir, program_id) / f"{normalize_symbol(symbol)}.json"


def empty_priors() -> dict[str, Any]:
    return {
        "version": VERSION,
        "closed_outcomes": 0,
        "by_result": {},
        "assumption_hits": {},  # assumption_kind → {held, failed}
        "failure_lessons": [],  # mentor-facing strings
        "weight_deltas": {
            "discovery_theme_boost": {},  # theme_id → float
            "scoring_axis_penalty": {},  # axis → float
            "ranking_penalty_global": 0.0,
            "ranking_bonus_global": 0.0,
        },
        "updated_at": None,
        "note": (
            "Priors shift only from closed paper outcomes (held/weakened/falsified). "
            "N≥20 needed for meaningful weight moves."
        ),
    }


def load_priors(data_dir: str | Path | None, program_id: str = DEFAULT_PROGRAM) -> dict[str, Any]:
    if not data_dir:
        return empty_priors()
    path = priors_path(data_dir, program_id)
    if not path.is_file():
        return empty_priors()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            base = empty_priors()
            base.update(raw)
            base.setdefault("weight_deltas", empty_priors()["weight_deltas"])
            return base
    except Exception:  # noqa: BLE001
        _log.debug("priors load failed", exc_info=True)
    return empty_priors()


def save_priors(
    data_dir: str | Path | None,
    priors: dict[str, Any],
    program_id: str = DEFAULT_PROGRAM,
) -> Path | None:
    if not data_dir:
        return None
    path = priors_path(data_dir, program_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = dict(priors)
        doc["version"] = VERSION
        doc["updated_at"] = _utc()
        path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path
    except Exception:  # noqa: BLE001
        _log.debug("priors save failed", exc_info=True)
        return None


def empty_tracker(symbol: str) -> dict[str, Any]:
    return {
        "version": VERSION,
        "symbol": normalize_symbol(symbol),
        "status": "open",  # open | watching | closed
        "hypothesis": "",
        "theme_links": [],
        "assumptions": [],
        "horizon": "long_term",
        "research_confidence_at_entry": None,
        "investment_confidence_at_entry": None,
        "decision": None,  # buy | watch | avoid
        "decision_at": None,
        "size_note": "",
        "revisits": [],
        "attributions": [],
        "lessons": [],
        "opened_at": _utc(),
        "updated_at": _utc(),
        "closed_at": None,
        "outcome_summary": None,
    }


def load_tracker(
    data_dir: str | Path | None,
    symbol: str,
    program_id: str = DEFAULT_PROGRAM,
) -> dict[str, Any] | None:
    if not data_dir:
        return None
    path = tracker_path(data_dir, symbol, program_id)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except Exception:  # noqa: BLE001
        return None


def save_tracker(
    data_dir: str | Path | None,
    tracker: dict[str, Any],
    program_id: str = DEFAULT_PROGRAM,
) -> Path | None:
    if not data_dir:
        return None
    sym = normalize_symbol(str(tracker.get("symbol") or ""))
    if not sym:
        return None
    path = tracker_path(data_dir, sym, program_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = dict(tracker)
        doc["symbol"] = sym
        doc["version"] = VERSION
        doc["updated_at"] = _utc()
        path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path
    except Exception:  # noqa: BLE001
        _log.debug("tracker save failed", exc_info=True)
        return None


def open_tracker(
    data_dir: str | Path | None,
    symbol: str,
    *,
    program_id: str = DEFAULT_PROGRAM,
    hypothesis: str = "",
    theme_links: list[str] | None = None,
    assumptions: list[dict[str, Any]] | list[str] | None = None,
    horizon: str = "long_term",
    research_confidence: str | None = None,
    investment_confidence: str | None = None,
    decision: str = "watch",
    size_note: str = "",
    force: bool = False,
) -> dict[str, Any]:
    """Create or refresh an open thesis tracker at decision time."""
    existing = load_tracker(data_dir, symbol, program_id)
    if existing and existing.get("status") == "open" and not force:
        tracker = dict(existing)
    else:
        tracker = empty_tracker(symbol)

    tracker["hypothesis"] = (hypothesis or tracker.get("hypothesis") or "").strip()
    tracker["theme_links"] = list(theme_links or tracker.get("theme_links") or [])
    tracker["horizon"] = (horizon or tracker.get("horizon") or "long_term").strip().lower()
    tracker["research_confidence_at_entry"] = research_confidence or tracker.get(
        "research_confidence_at_entry"
    )
    tracker["investment_confidence_at_entry"] = investment_confidence or tracker.get(
        "investment_confidence_at_entry"
    )
    tracker["decision"] = (decision or tracker.get("decision") or "watch").strip().lower()
    tracker["decision_at"] = tracker.get("decision_at") or _utc()
    tracker["size_note"] = size_note or tracker.get("size_note") or ""
    tracker["status"] = "open" if tracker["decision"] != "avoid" else "watching"

    cleaned_assumptions: list[dict[str, Any]] = []
    for a in assumptions or tracker.get("assumptions") or []:
        if isinstance(a, str):
            cleaned_assumptions.append(
                {
                    "id": f"a{len(cleaned_assumptions)+1}",
                    "kind": "other",
                    "text": a.strip(),
                    "status": "open",  # open | held | failed | unknown
                }
            )
        elif isinstance(a, dict) and (a.get("text") or a.get("kind")):
            cleaned_assumptions.append(
                {
                    "id": str(a.get("id") or f"a{len(cleaned_assumptions)+1}"),
                    "kind": str(a.get("kind") or "other"),
                    "text": str(a.get("text") or a.get("kind")),
                    "status": str(a.get("status") or "open"),
                }
            )
    if not cleaned_assumptions and tracker["hypothesis"]:
        cleaned_assumptions = [
            {
                "id": "a1",
                "kind": "other",
                "text": "Core hypothesis remains intact",
                "status": "open",
            }
        ]
    tracker["assumptions"] = cleaned_assumptions
    save_tracker(data_dir, tracker, program_id)
    return tracker


def revisit_tracker(
    data_dir: str | Path | None,
    symbol: str,
    *,
    program_id: str = DEFAULT_PROGRAM,
    assumption_updates: list[dict[str, Any]] | None = None,
    note: str = "",
    evidence_note: str = "",
) -> dict[str, Any]:
    """Periodic assumption check vs new evidence."""
    tracker = load_tracker(data_dir, symbol, program_id) or empty_tracker(symbol)
    assumptions = list(tracker.get("assumptions") or [])
    by_id = {str(a.get("id")): a for a in assumptions if isinstance(a, dict)}
    changed: list[str] = []
    for upd in assumption_updates or []:
        if not isinstance(upd, dict):
            continue
        aid = str(upd.get("id") or "")
        status = str(upd.get("status") or "").lower()
        if aid in by_id and status in {"open", "held", "failed", "unknown"}:
            prev = by_id[aid].get("status")
            by_id[aid]["status"] = status
            if upd.get("note"):
                by_id[aid]["last_note"] = str(upd["note"])[:200]
            if prev != status:
                changed.append(f"{aid}:{prev}→{status}")
    tracker["assumptions"] = list(by_id.values()) or assumptions
    revisit = {
        "at": _utc(),
        "note": (note or "")[:300],
        "evidence_note": (evidence_note or "")[:300],
        "changes": changed,
    }
    revisits = list(tracker.get("revisits") or [])
    revisits.append(revisit)
    tracker["revisits"] = revisits[-40:]
    save_tracker(data_dir, tracker, program_id)
    return tracker


def close_with_attribution(
    data_dir: str | Path | None,
    symbol: str,
    *,
    program_id: str = DEFAULT_PROGRAM,
    result: str,
    pnl: float | None = None,
    note: str = "",
    trade: dict[str, Any] | None = None,
    di_grades: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Close tracker: attribute P&L to which assumptions held/failed; update priors.

    DI.Attr: when ``di_grades`` is provided and ``may_update_priors`` is False
    (market_quality=F + decision_quality A/B), weight deltas are skipped.
    """
    tracker = load_tracker(data_dir, symbol, program_id) or empty_tracker(symbol)
    res = str(result or "observed").strip().lower()
    assumptions = list(tracker.get("assumptions") or [])
    held = [a for a in assumptions if isinstance(a, dict) and a.get("status") == "held"]
    failed = [a for a in assumptions if isinstance(a, dict) and a.get("status") == "failed"]

    # Auto-tag if still open at close
    if res in {"held"} and not held and not failed:
        for a in assumptions:
            if isinstance(a, dict) and a.get("status") == "open":
                a["status"] = "held"
        held = [a for a in assumptions if isinstance(a, dict) and a.get("status") == "held"]
    if res in {"weakened", "falsified"} and not failed:
        for a in assumptions:
            if isinstance(a, dict) and a.get("status") == "open":
                a["status"] = "failed"
        failed = [a for a in assumptions if isinstance(a, dict) and a.get("status") == "failed"]

    attribution = {
        "at": _utc(),
        "result": res,
        "pnl": pnl,
        "note": (note or "")[:300],
        "assumptions_held": [
            {"id": a.get("id"), "kind": a.get("kind"), "text": a.get("text")} for a in held
        ],
        "assumptions_failed": [
            {"id": a.get("id"), "kind": a.get("kind"), "text": a.get("text")} for a in failed
        ],
        "trade": trade or {},
        "di_grades": di_grades or None,
    }
    attrs = list(tracker.get("attributions") or [])
    attrs.append(attribution)
    tracker["attributions"] = attrs[-20:]
    tracker["assumptions"] = assumptions
    tracker["outcome_summary"] = attribution
    tracker["status"] = "closed"
    tracker["closed_at"] = _utc()

    lessons = list(tracker.get("lessons") or [])
    if failed:
        for a in failed[:3]:
            kind = str(a.get("kind") or "other")
            text = str(a.get("text") or kind)
            lesson = _mentor_lesson(kind, text, res)
            lessons.append(lesson)
            attribution.setdefault("lessons", []).append(lesson)
    elif res == "held":
        lessons.append("Assumptions held — keep process, avoid overconfidence.")
    tracker["lessons"] = lessons[-20:]
    save_tracker(data_dir, tracker, program_id)

    allow_weights = True
    if isinstance(di_grades, dict) and di_grades.get("may_update_priors") is False:
        allow_weights = False
    priors = apply_outcome_to_priors(
        data_dir,
        program_id=program_id,
        result=res,
        theme_links=list(tracker.get("theme_links") or []),
        failed_kinds=[str(a.get("kind") or "other") for a in failed],
        held_kinds=[str(a.get("kind") or "other") for a in held],
        lessons=list(attribution.get("lessons") or lessons[-3:]),
        allow_weight_update=allow_weights,
        di_grades=di_grades,
    )
    return {
        "tracker": tracker,
        "attribution": attribution,
        "priors": priors_view(priors),
        "priors_weight_update": allow_weights,
    }


def _mentor_lesson(kind: str, text: str, result: str) -> str:
    kind_n = (kind or "other").lower()
    templates = {
        "leverage_ok": "Ignored / underweighted debt — re-check leverage before size.",
        "valuation_band": "Overpay risk — MoS band was breached or ignored.",
        "policy_support": "Policy tailwind assumed but did not hold.",
        "capex_delivery": "Capex / execution delivery lagged thesis.",
        "management_execution": "Management execution assumption failed.",
        "growth_path": "Growth path assumption failed.",
        "theme_tailwind": "Theme membership did not translate to results.",
    }
    base = templates.get(kind_n, f"Assumption failed ({kind_n}): {text[:80]}")
    return f"{base} [outcome={result}]"


def apply_outcome_to_priors(
    data_dir: str | Path | None,
    *,
    program_id: str = DEFAULT_PROGRAM,
    result: str,
    theme_links: list[str] | None = None,
    failed_kinds: list[str] | None = None,
    held_kinds: list[str] | None = None,
    lessons: list[str] | None = None,
    allow_weight_update: bool = True,
    di_grades: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Update durable priors; weight deltas unlock after N closed outcomes.

    DI.Attr hard rule: when ``allow_weight_update`` is False, still record the
    outcome count/lesson text but skip ranking/axis weight deltas.
    """
    priors = load_priors(data_dir, program_id)
    res = str(result or "").lower()
    if res not in {"held", "weakened", "falsified"}:
        # observed/fill don't count toward N for weight shifts
        by = dict(priors.get("by_result") or {})
        by[res] = int(by.get(res) or 0) + 1
        priors["by_result"] = by
        save_priors(data_dir, priors, program_id)
        return priors

    priors["closed_outcomes"] = int(priors.get("closed_outcomes") or 0) + 1
    by = dict(priors.get("by_result") or {})
    by[res] = int(by.get(res) or 0) + 1
    priors["by_result"] = by

    hits = dict(priors.get("assumption_hits") or {})
    for kind in failed_kinds or []:
        row = dict(hits.get(kind) or {"held": 0, "failed": 0})
        row["failed"] = int(row.get("failed") or 0) + 1
        hits[kind] = row
    for kind in held_kinds or []:
        row = dict(hits.get(kind) or {"held": 0, "failed": 0})
        row["held"] = int(row.get("held") or 0) + 1
        hits[kind] = row
    priors["assumption_hits"] = hits

    fl = list(priors.get("failure_lessons") or [])
    for lesson in lessons or []:
        if lesson and lesson not in fl:
            fl.insert(0, lesson)
    if not allow_weight_update:
        fl.insert(
            0,
            "DI.Attr: priors weight update skipped "
            f"(market_quality={((di_grades or {}).get('market_quality'))}, "
            f"decision_quality={((di_grades or {}).get('decision_quality'))})",
        )
    priors["failure_lessons"] = fl[:40]

    n = int(priors["closed_outcomes"])
    deltas = dict(priors.get("weight_deltas") or empty_priors()["weight_deltas"])
    # Soft updates always; meaningful unlock note at N>=20 — unless DI.Attr blocks.
    if allow_weight_update:
        if res == "falsified":
            deltas["ranking_penalty_global"] = round(
                float(deltas.get("ranking_penalty_global") or 0) + 0.02, 4
            )
            axis_pen = dict(deltas.get("scoring_axis_penalty") or {})
            for kind in failed_kinds or []:
                axis = {
                    "leverage_ok": "risk",
                    "valuation_band": "valuation",
                    "management_execution": "management",
                    "growth_path": "growth",
                    "theme_tailwind": "macro_theme",
                    "policy_support": "macro_theme",
                    "capex_delivery": "business",
                }.get(kind, "risk")
                axis_pen[axis] = round(float(axis_pen.get(axis) or 0) + 0.03, 4)
            deltas["scoring_axis_penalty"] = axis_pen
        elif res == "weakened":
            deltas["ranking_penalty_global"] = round(
                float(deltas.get("ranking_penalty_global") or 0) + 0.01, 4
            )
        elif res == "held":
            deltas["ranking_bonus_global"] = round(
                min(0.2, float(deltas.get("ranking_bonus_global") or 0) + 0.01), 4
            )
            boost = dict(deltas.get("discovery_theme_boost") or {})
            for tid in theme_links or []:
                key = str(tid).strip().lower()
                if key:
                    boost[key] = round(min(0.25, float(boost.get(key) or 0) + 0.02), 4)
            deltas["discovery_theme_boost"] = boost
    else:
        deltas["di_attr_skipped"] = int(deltas.get("di_attr_skipped") or 0) + 1

    deltas["unlocked"] = n >= 20
    deltas["unlock_note"] = (
        f"Weight shifts active (N={n}≥20)."
        if n >= 20
        else f"Soft priors updating; full unlock at N=20 (now {n})."
    )
    if not allow_weight_update:
        deltas["unlock_note"] = (
            "DI.Attr blocked weight update (market F + decision A/B). " + deltas["unlock_note"]
        )
    priors["weight_deltas"] = deltas
    save_priors(data_dir, priors, program_id)
    return priors


def priors_view(priors: dict[str, Any] | None) -> dict[str, Any]:
    p = priors or empty_priors()
    n = int(p.get("closed_outcomes") or 0)
    return {
        "closed_outcomes": n,
        "by_result": p.get("by_result") or {},
        "assumption_hits": p.get("assumption_hits") or {},
        "failure_lessons": list(p.get("failure_lessons") or [])[:12],
        "weight_deltas": p.get("weight_deltas") or {},
        "ready_for_weight_shift": n >= 20,
        "version": VERSION,
        "note": p.get("note"),
        "updated_at": p.get("updated_at"),
    }


def list_trackers(
    data_dir: str | Path | None,
    *,
    program_id: str = DEFAULT_PROGRAM,
    status: str | None = None,
    limit: int = 40,
) -> dict[str, Any]:
    if not data_dir:
        return {"trackers": [], "count": 0, "priors": priors_view(None)}
    root = store_dir(data_dir, program_id)
    rows: list[dict[str, Any]] = []
    if root.is_dir():
        for path in sorted(root.glob("*.json")):
            if path.name == PRIORS_NAME:
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(raw, dict):
                continue
            if status and str(raw.get("status")) != status:
                continue
            rows.append(
                {
                    "symbol": raw.get("symbol"),
                    "status": raw.get("status"),
                    "hypothesis": (raw.get("hypothesis") or "")[:120],
                    "decision": raw.get("decision"),
                    "horizon": raw.get("horizon"),
                    "research_confidence_at_entry": raw.get("research_confidence_at_entry"),
                    "investment_confidence_at_entry": raw.get("investment_confidence_at_entry"),
                    "assumptions_open": sum(
                        1
                        for a in (raw.get("assumptions") or [])
                        if isinstance(a, dict) and a.get("status") == "open"
                    ),
                    "updated_at": raw.get("updated_at"),
                }
            )
    return {
        "trackers": rows[: max(1, int(limit))],
        "count": len(rows),
        "priors": priors_view(load_priors(data_dir, program_id)),
        "version": VERSION,
    }


def tracker_from_awareness(
    data_dir: str | Path | None,
    awareness: dict[str, Any],
    *,
    program_id: str = DEFAULT_PROGRAM,
    decision: str | None = None,
) -> dict[str, Any]:
    """Open tracker from IRA awareness + score/MKG."""
    aw = awareness if isinstance(awareness, dict) else {}
    score = aw.get("investment_score") if isinstance(aw.get("investment_score"), dict) else {}
    thesis = aw.get("thesis") if isinstance(aw.get("thesis"), dict) else {}
    mkg = aw.get("mkg") if isinstance(aw.get("mkg"), dict) else {}
    why = mkg.get("why_own") if isinstance(mkg.get("why_own"), dict) else {}
    themes = [
        str(t.get("target_key") or t.get("label") or "")
        for t in (why.get("themes") or [])
        if isinstance(t, dict)
    ]
    assumptions: list[dict[str, Any]] = []
    for i, t in enumerate((why.get("themes") or [])[:3]):
        if isinstance(t, dict):
            assumptions.append(
                {
                    "id": f"theme{i+1}",
                    "kind": "theme_tailwind",
                    "text": f"Theme link: {t.get('label') or t.get('target_key')}",
                    "status": "open",
                }
            )
    for i, p in enumerate((why.get("policies") or [])[:2]):
        if isinstance(p, dict):
            assumptions.append(
                {
                    "id": f"pol{i+1}",
                    "kind": "policy_support",
                    "text": f"Policy: {(p.get('label') or '')[:80]}",
                    "status": "open",
                }
            )
    val = aw.get("valuation") if isinstance(aw.get("valuation"), dict) else {}
    if val.get("margin_of_safety_pct") is not None:
        assumptions.append(
            {
                "id": "mos1",
                "kind": "valuation_band",
                "text": f"MoS band around {val.get('margin_of_safety_pct')}%",
                "status": "open",
            }
        )
    path = score.get("path") or "watch"
    dec = decision or ("buy" if path == "buy_eligible" else path if path in {"watch", "avoid"} else "watch")
    return open_tracker(
        data_dir,
        str(aw.get("symbol") or ""),
        program_id=program_id,
        hypothesis=str(thesis.get("summary") or aw.get("doing_now") or why.get("summary") or "")[:400],
        theme_links=[t for t in themes if t],
        assumptions=assumptions,
        horizon=str(score.get("horizon") or "long_term"),
        research_confidence=score.get("research_confidence") or aw.get("confidence"),
        investment_confidence=score.get("investment_confidence"),
        decision=str(dec),
        size_note=f"score_path={path}; band={score.get('score_band')}",
        force=True,
    )
