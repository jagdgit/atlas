"""NOW #9 — SELF0 densify: beliefs + experiences into Next-₹1 / scientist context.

Advice-only inheritance of updated worldview. Never changes E[R], ranking,
ACP decisions, or capital size. Empty → explicit unknowns.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

VERSION = "now.self_worldview.v1"
_log = logging.getLogger("atlas.investment.self_worldview")


def _normalize_lesson_text(value: Any) -> str:
    """Coerce lesson payloads (str / dict / list) into a short readable line."""
    if value is None:
        return ""
    if isinstance(value, dict):
        parts = []
        for k in ("strategy", "thesis", "market", "atlas", "relative_opportunity", "text", "lesson"):
            v = value.get(k)
            if v:
                parts.append(f"{k}: {str(v)[:80]}")
        if not parts:
            parts = [f"{k}: {str(v)[:60]}" for k, v in list(value.items())[:4] if v]
        return "; ".join(parts)[:200]
    if isinstance(value, list):
        return "; ".join(_normalize_lesson_text(x) for x in value if x)[:200]
    text = str(value).strip()
    if text.startswith("{") and ("strategy" in text or "thesis" in text):
        try:
            import ast

            obj = ast.literal_eval(text)
            if isinstance(obj, dict):
                return _normalize_lesson_text(obj)
        except Exception:  # noqa: BLE001
            pass
    return text[:200]


def _claim_text(belief: dict[str, Any]) -> str:
    """Belief Core stores ``statement``; Cognitive Core historically expected ``claim``."""
    return str(
        belief.get("statement")
        or belief.get("claim")
        or belief.get("belief_key")
        or ""
    ).strip()


def lessons_from_learning_disk(
    data_dir: str | Path | None,
    laboratory_id: str | None,
    *,
    symbols: list[str] | None = None,
    limit: int = 4,
    lookback_days: int = 7,
) -> list[dict[str, Any]]:
    """Pull recent experience / learning-story lessons from durable learning jsonl.

    Empty → []. Never invents lessons.
    """
    if not data_dir or not laboratory_id:
        return []
    try:
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        from atlas.investment.learning_objects import load_learning_events
        from atlas.investment.learning_story import STORY_KIND
    except Exception:  # noqa: BLE001
        return []

    sym_set = {str(s).upper() for s in (symbols or []) if s}
    ist = ZoneInfo("Asia/Kolkata")
    today = datetime.now(ist).date()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    for offset in range(max(1, int(lookback_days))):
        day = (today - timedelta(days=offset)).isoformat()
        try:
            events = load_learning_events(
                data_dir, laboratory_id, as_of_ist=day, limit=200
            )
        except Exception:  # noqa: BLE001
            continue
        # Prefer symbol-matching rows first
        ordered = sorted(
            [e for e in events if isinstance(e, dict)],
            key=lambda e: (
                0 if str(e.get("symbol") or "").upper() in sym_set else 1,
                str(e.get("recorded_at") or e.get("as_of_ist") or ""),
            ),
            reverse=False,
        )
        # newest first within day
        ordered = list(reversed(ordered))
        for ev in ordered:
            kind = str(ev.get("kind") or "")
            texts: list[str] = []
            if kind == STORY_KIND or kind == "LEARNING_STORY":
                lessons = ev.get("lessons")
                if isinstance(lessons, list):
                    texts.extend(lessons)
                elif lessons:
                    texts.append(lessons)
                if ev.get("belief_note"):
                    texts.append(ev.get("belief_note"))
                cause = ev.get("cause") if isinstance(ev.get("cause"), dict) else {}
                if cause.get("narrative"):
                    texts.append(cause.get("narrative"))
                # Compact honest fallback from story fields
                if not texts:
                    bu = str(ev.get("belief_update") or "unchanged")
                    cs = str(cause.get("status") or "unknown_explicit")
                    sym = str(ev.get("symbol") or "?")
                    texts.append(
                        f"{sym} close story: belief_update={bu}; cause={cs}"
                    )
            elif kind == "EXPERIENCE":
                lessons = ev.get("lessons")
                if isinstance(lessons, list):
                    texts.extend(lessons)
                elif lessons:
                    texts.append(lessons)
                if ev.get("lesson"):
                    texts.append(ev.get("lesson"))
            for t in texts:
                lesson = _normalize_lesson_text(t)
                if not lesson or lesson in seen:
                    continue
                seen.add(lesson)
                out.append(
                    {
                        "id": ev.get("story_id") or ev.get("experience_id") or ev.get("id"),
                        "lesson": lesson,
                        "symbol": ev.get("symbol"),
                        "source": kind or "learning_event",
                        "as_of_ist": ev.get("as_of_ist") or day,
                    }
                )
                if len(out) >= max(1, int(limit)):
                    return out
    return out


def attach_self_worldview(
    *,
    reasoning: Any | None = None,
    experience_os: Any | None = None,
    data_dir: str | Path | None = None,
    symbols: list[str] | None = None,
    laboratory_id: str | None = None,
    query: str | None = None,
    beliefs: list[dict[str, Any]] | None = None,
    experiences: list[dict[str, Any]] | None = None,
    limit_beliefs: int = 4,
    limit_lessons: int = 4,
) -> dict[str, Any]:
    """Pull active beliefs + recent experience lessons for allocation context.

    Pass ``beliefs`` / ``experiences`` for hermetic tests; otherwise consult
    ReasoningService + ExperienceOS when bound. Falls back to durable
    ``investment/learning/{lab}/{day}.jsonl`` lessons when OS recall is empty.
    """
    syms = [str(s).upper() for s in (symbols or []) if s]
    q = (query or " ".join(syms[:6]) or "market capital allocation").strip()[:160]
    out: dict[str, Any] = {
        "version": VERSION,
        "kind": "SELF_WORLDVIEW",
        "laboratory_id": laboratory_id,
        "query": q,
        "symbols": syms[:12],
        "belief_claims": [],
        "experience_lessons": [],
        "unknowns": [],
        "advice_only": True,
        "never_orders": True,
        "no_capital_influence": True,
        "honesty": (
            "SELF worldview — advice-only context for Next-₹1 / scientist. "
            "Does not change E[R], ACP, or capital. Empty → unknown_explicit."
        ),
    }

    belief_rows: list[dict[str, Any]] = list(beliefs or [])
    if not belief_rows and reasoning is not None and hasattr(reasoning, "consult"):
        try:
            bundle = reasoning.consult(
                domain="market",
                query=q or None,
                limit=max(6, int(limit_beliefs) * 2),
                purpose="next_rupee_worldview",
                record_mode="once",
            )
            belief_rows = list((bundle or {}).get("beliefs") or [])
        except Exception:  # noqa: BLE001
            _log.debug("self_worldview belief consult failed", exc_info=True)

    claims: list[dict[str, Any]] = []
    for b in belief_rows:
        if not isinstance(b, dict):
            continue
        text = _claim_text(b)
        if not text:
            continue
        claims.append(
            {
                "id": b.get("id"),
                "claim": text[:200],
                "statement": text[:200],
                "status": b.get("status"),
                "confidence": b.get("effective_confidence", b.get("confidence")),
                "domain": b.get("domain"),
                "theme": b.get("theme"),
            }
        )
        if len(claims) >= max(1, int(limit_beliefs)):
            break
    out["belief_claims"] = claims
    if not claims:
        out["unknowns"].append("beliefs")

    exp_rows: list[dict[str, Any]] = list(experiences or [])
    if not exp_rows and experience_os is not None:
        try:
            if hasattr(experience_os, "recall"):
                exp_rows = list(experience_os.recall(q, limit=max(8, int(limit_lessons) * 2)) or [])
            elif hasattr(experience_os, "list_journals"):
                exp_rows = list(experience_os.list_journals(limit=max(8, int(limit_lessons) * 2)) or [])
        except Exception:  # noqa: BLE001
            _log.debug("self_worldview experience recall failed", exc_info=True)

    lessons: list[dict[str, Any]] = []
    for raw in exp_rows:
        if not isinstance(raw, dict):
            continue
        journal = raw.get("journal") if isinstance(raw.get("journal"), dict) else raw
        lesson = str(
            journal.get("lesson")
            or raw.get("lesson")
            or journal.get("title")
            or raw.get("title")
            or ""
        ).strip()
        if not lesson:
            continue
        lessons.append(
            {
                "id": raw.get("id") or journal.get("id"),
                "lesson": lesson[:200],
            }
        )
        if len(lessons) >= max(1, int(limit_lessons)):
            break

    # Disk densify when OS recall empty
    if len(lessons) < max(1, int(limit_lessons)) and data_dir and laboratory_id:
        try:
            disk = lessons_from_learning_disk(
                data_dir,
                laboratory_id,
                symbols=syms,
                limit=max(1, int(limit_lessons) - len(lessons)),
            )
            for row in disk:
                if any(row.get("lesson") == x.get("lesson") for x in lessons):
                    continue
                lessons.append(row)
                if len(lessons) >= max(1, int(limit_lessons)):
                    break
            if disk:
                out["lesson_source"] = "learning_disk"
        except Exception:  # noqa: BLE001
            _log.debug("self_worldview disk lessons failed", exc_info=True)

    out["experience_lessons"] = lessons
    if not lessons:
        out["unknowns"].append("experience_lessons")

    return out


def apply_worldview_to_next_rupee(
    doc: dict[str, Any] | None,
    worldview: dict[str, Any] | None,
) -> dict[str, Any]:
    """Fold SELF worldview into Next-₹1 packet (text/context only — no math)."""
    out = dict(doc) if isinstance(doc, dict) else {}
    wv = worldview if isinstance(worldview, dict) else {}
    claims = list(wv.get("belief_claims") or [])[:4]
    lessons = list(wv.get("experience_lessons") or [])[:4]
    unknowns = list(wv.get("unknowns") or [])[:8]

    out["worldview"] = {
        "version": wv.get("version") or VERSION,
        "belief_n": len(claims),
        "lesson_n": len(lessons),
        "belief_claims": claims,
        "experience_lessons": lessons,
        "unknowns": unknowns,
        "advice_only": True,
        "no_capital_influence": True,
    }

    bits: list[str] = []
    if claims:
        bits.append(
            "Belief context: "
            + "; ".join(f"«{(c.get('claim') or '')[:80]}»" for c in claims[:2])
        )
    if lessons:
        bits.append(
            "Experience: "
            + "; ".join(f"«{(x.get('lesson') or '')[:80]}»" for x in lessons[:2])
        )
    if unknowns and not claims and not lessons:
        bits.append(f"Worldview unknowns: {', '.join(unknowns)}")

    if bits:
        answer = str(out.get("operator_answer") or "").rstrip()
        extra = " | ".join(bits)
        if extra and extra not in answer:
            out["operator_answer"] = (answer + " — " + extra)[:700]

    # Surface belief/experience blockers honestly when still unknown
    blocking = list(out.get("blocking_unknowns") or [])
    for u in unknowns:
        tag = f"worldview:{u}"
        if tag not in blocking:
            blocking.append(tag)
    out["blocking_unknowns"] = blocking[:12]
    return out


def apply_worldview_to_evidence_packet(
    packet: dict[str, Any] | None,
    worldview: dict[str, Any] | None,
) -> dict[str, Any]:
    """Fold beliefs/lessons into Cognitive Core evidence packet."""
    pkt = dict(packet) if isinstance(packet, dict) else {}
    wv = worldview if isinstance(worldview, dict) else {}
    claims = list(wv.get("belief_claims") or [])[:4]
    lessons = list(wv.get("experience_lessons") or [])[:4]

    if claims and not pkt.get("prior_belief"):
        pkt["prior_belief"] = [
            {
                "id": c.get("id"),
                "claim": c.get("claim") or c.get("statement"),
                "confidence": c.get("confidence"),
                "status": c.get("status"),
            }
            for c in claims
        ]
    evid = [str(x) for x in (pkt.get("evidence") or []) if x]
    for c in claims:
        line = f"belief:{(c.get('claim') or '')[:160]}"
        if line not in evid:
            evid.append(line)
    for x in lessons:
        line = f"experience:{(x.get('lesson') or '')[:160]}"
        if line not in evid:
            evid.append(line)
    pkt["evidence"] = evid[:40]

    exps = list(pkt.get("experiences") or [])
    for x in lessons:
        if x not in exps:
            exps.append(x)
    pkt["experiences"] = exps[:8]

    unk = [str(u) for u in (pkt.get("unknowns") or []) if u]
    for u in wv.get("unknowns") or []:
        tag = f"worldview_{u}"
        if tag not in unk and str(u) not in unk:
            unk.append(tag)
    pkt["unknowns"] = unk[:20]
    pkt["self_worldview"] = {
        "version": wv.get("version") or VERSION,
        "belief_n": len(claims),
        "lesson_n": len(lessons),
        "unknowns": list(wv.get("unknowns") or [])[:8],
    }
    return pkt


def apply_worldview_to_scientist_packet(
    packet: dict[str, Any] | None,
    worldview: dict[str, Any] | None,
) -> dict[str, Any]:
    """Fold into Stage-3 scientist packet."""
    pkt = dict(packet) if isinstance(packet, dict) else {}
    wv = worldview if isinstance(worldview, dict) else {}
    lessons = list(wv.get("experience_lessons") or [])[:4]
    claims = list(wv.get("belief_claims") or [])[:4]
    exps = list(pkt.get("experiences") or [])
    for x in lessons:
        if isinstance(x, dict) and x not in exps:
            exps.append({"id": x.get("id"), "lesson": x.get("lesson")})
    pkt["experiences"] = exps[:8]
    unk = [str(u) for u in (pkt.get("unknowns") or []) if u]
    for u in wv.get("unknowns") or []:
        tag = f"worldview_{u}"
        if tag not in unk:
            unk.append(tag)
    pkt["unknowns"] = unk[:20]
    pkt["self_worldview"] = {
        "version": wv.get("version") or VERSION,
        "belief_n": len(claims),
        "lesson_n": len(lessons),
        "belief_claims": claims,
        "unknowns": list(wv.get("unknowns") or [])[:8],
    }
    return pkt
