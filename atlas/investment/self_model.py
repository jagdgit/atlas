"""OI-CU0 CU.D — global daily self-model (deterministic, not consciousness theater).

One file: ``investment/self_model/{day}.json``
Sections: identity · system/lanes · knowledge · cognitive work · laboratories.

Chat answers who / what-doing / what-know from this snapshot (<2s, no Ollama).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "cu0.self_model.v1"
STORE_REL = Path("investment") / "self_model"
_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.self_model")

_WHO_RE = re.compile(
    r"\b("
    r"who\s+are\s+you|"
    r"what\s+are\s+you(?!\s+doing|\s+working|\s+uncertain)|"
    r"introduce\s+yourself|"
    r"your\s+identity|"
    r"tell\s+me\s+about\s+yourself"
    r")\b",
    re.I,
)
_DOING_RE = re.compile(
    r"\b("
    r"what\s+are\s+you\s+doing|"
    r"what\s+are\s+you\s+working\s+on|"
    r"what(?:'s|\s+is)\s+your\s+(?:focus|status|state)|"
    r"how\s+are\s+you\s+(?:doing|running)|"
    r"self[\s_-]?model|"
    r"system\s+state"
    r")\b",
    re.I,
)
_KNOW_RE = re.compile(
    r"\b("
    r"what\s+do\s+you\s+know|"
    r"what\s+don'?t\s+you\s+know|"
    r"what\s+are\s+your\s+unknowns|"
    r"what\s+are\s+you\s+uncertain|"
    r"what\s+(?:have\s+you\s+|did\s+you\s+)?learn(?:ed|t)?|"
    r"what\s+have\s+you\s+learned|"
    r"what\s+did\s+you\s+learn|"
    r"learn(?:ed|t)?\s+so\s+far|"
    r"open\s+unknowns|"
    r"knowledge\s+gaps?"
    r")\b",
    re.I,
)

_IDENTITY = {
    "name": "Atlas",
    "mission": (
        "Build an increasingly capable autonomous investment intelligence that "
        "learns from evidence and experience, allocates capital under risk "
        "constraints, and improves expected risk-adjusted return over time — "
        "in paper laboratories first."
    ),
    "mode": "paper laboratories · advice-only influence · simulation not broker orders",
    "not": (
        "Not a generic chatbot. Not phenomenal self-awareness. "
        "This snapshot is durable state for the operator — not consciousness theater."
    ),
}


def ist_today() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def day_path(data_dir: str | Path | None, as_of_ist: str | None = None) -> Path | None:
    if not data_dir:
        return None
    day = as_of_ist or ist_today()
    return Path(data_dir) / STORE_REL / f"{day}.json"


def detect_self_model_query(query: str) -> str | None:
    """Return 'who' | 'doing' | 'know' | 'learned' | None."""
    q = (query or "").strip()
    if not q:
        return None
    # Order matters: "what are you doing" must not match bare "what are you".
    if _DOING_RE.search(q):
        return "doing"
    # "what did you learn" before generic "what do you know"
    if re.search(
        r"\b(?:what\s+(?:have\s+you\s+|did\s+you\s+)?learn(?:ed|t)?|"
        r"learn(?:ed|t)?\s+so\s+far|"
        r"learning\s+(?:so\s+far|to\s+date|today))\b",
        q,
        re.I,
    ):
        return "learned"
    if _KNOW_RE.search(q):
        return "know"
    if _WHO_RE.search(q):
        return "who"
    return None


def _safe_lab(lab: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in (lab or "lab"))


def _lab_ids() -> tuple[str, ...]:
    try:
        from atlas.investment.laboratory import MAIL_SNAPSHOT_LABS

        return tuple(MAIL_SNAPSHOT_LABS)
    except Exception:  # noqa: BLE001
        return (
            "india_equity_learner",
            "india_fno_learner",
            "equity_intraday_learner",
        )


def _lab_title(lab: str) -> str:
    try:
        from atlas.investment.laboratory import MAIL_LAB_TITLES

        return MAIL_LAB_TITLES.get(lab) or lab
    except Exception:  # noqa: BLE001
        return lab


def _load_lab_books(
    data_dir: str | Path | None,
    *,
    as_of_ist: str,
    lab_books: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if lab_books:
        return [b for b in lab_books if isinstance(b, dict)]
    # Prefer caller-supplied books (evening). Registry fallback is persona-only.
    out: list[dict[str, Any]] = []
    try:
        from atlas.investment import portfolios as pf

        for lab in _lab_ids():
            meta = pf.get(lab)
            if not isinstance(meta, dict):
                continue
            persona = meta.get("persona") if isinstance(meta.get("persona"), dict) else {}
            out.append(
                {
                    "portfolio_key": lab,
                    "laboratory_id": lab,
                    "cash": persona.get("capital"),
                    "equity": persona.get("capital"),
                    "positions": [],
                    "valuation_basis": "registry_persona_only",
                    "as_of_ist": as_of_ist,
                    "data_dir_hint": str(data_dir) if data_dir else None,
                }
            )
    except Exception:  # noqa: BLE001
        pass
    return out


def _lab_section(
    data_dir: str | Path | None,
    lab: str,
    *,
    as_of_ist: str,
    book: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from atlas.investment.capital_allocation import load_allocation_table
    from atlas.investment.daily_cognitive_agenda import load_agenda
    from atlas.investment.learning_objects import (
        load_learning_events,
        summarize_learning_day,
    )
    from atlas.investment.learning_story import summarize_learning_stories

    alloc = load_allocation_table(data_dir, lab, as_of_ist=as_of_ist)
    agenda = load_agenda(data_dir, lab, ist_date=as_of_ist)
    events = load_learning_events(data_dir, lab, as_of_ist=as_of_ist)
    learn = summarize_learning_day(events)
    stories = summarize_learning_stories(events)
    kinds = learn.get("by_kind") if isinstance(learn.get("by_kind"), dict) else {}

    positions: list[str] = []
    if isinstance(book, dict):
        pos = book.get("positions") or book.get("holdings") or []
        if isinstance(pos, dict):
            positions = [str(k) for k in pos.keys()]
        elif isinstance(pos, list):
            for p in pos:
                if isinstance(p, dict) and p.get("symbol"):
                    positions.append(str(p["symbol"]))

    best = None
    if isinstance(alloc, dict):
        best = alloc.get("best_deploy") or alloc.get("summary")

    agenda_items = list(agenda.get("items") or []) if isinstance(agenda, dict) else []
    open_unknowns: list[str] = []
    for it in agenda_items[:8]:
        if not isinstance(it, dict):
            continue
        topic = it.get("topic") or it.get("title") or it.get("unknown") or it.get("symbol")
        if topic:
            open_unknowns.append(str(topic)[:120])

    return {
        "laboratory_id": lab,
        "title": _lab_title(lab),
        "book": {
            "cash": (book or {}).get("cash") if isinstance(book, dict) else None,
            "equity": (
                (book or {}).get("equity") or (book or {}).get("equity_value")
                if isinstance(book, dict)
                else None
            ),
            "positions": positions[:12],
            "valuation_basis": (book or {}).get("valuation_basis")
            if isinstance(book, dict)
            else None,
        },
        "allocation": {
            "best_deploy": best,
            "rows": len(list((alloc or {}).get("rows") or []))
            if isinstance(alloc, dict)
            else 0,
        },
        "learning": {
            "experiences": int(learn.get("experiences") or 0),
            "prediction_errors_computed": int(learn.get("prediction_errors_computed") or 0),
            "attribution_satisfied": int(learn.get("attribution_satisfied") or 0),
            "attribution_required": int(learn.get("attribution_required") or 0),
            "learning_stories": int(stories.get("stories") or 0),
            "llm_failures": int(kinds.get("llm_failure") or 0),
        },
        "agenda": {
            "items": len(agenda_items),
            "sample": open_unknowns[:5],
            "empty_reason": (agenda or {}).get("empty_reason")
            if isinstance(agenda, dict)
            else None,
        },
    }


def _system_state(*, llm_status: dict[str, Any] | None = None) -> dict[str, Any]:
    from atlas.investment.llm_lanes import LANE_PRIORITY, in_overnight_window

    status = dict(llm_status) if isinstance(llm_status, dict) else {}
    if not status:
        status = {
            "busy": None,
            "max_concurrency": None,
            "honesty": "LLM lane status not attached at snapshot time",
        }
    return {
        "inference_lanes": {
            "priority": dict(LANE_PRIORITY),
            "policy": (
                "chat/market may wait; research/background fail-fast when saturated; "
                "no blind concurrency raise (CU.A2)"
            ),
            "status": status,
        },
        "overnight_window_active": in_overnight_window(),
        "overnight_window": "18:30–07:30 IST",
    }


def _knowledge_rollup(labs: dict[str, Any]) -> dict[str, Any]:
    unknowns: list[str] = []
    for lab, sec in labs.items():
        if not isinstance(sec, dict):
            continue
        for u in list((sec.get("agenda") or {}).get("sample") or [])[:3]:
            unknowns.append(f"{lab}: {u}")
    return {
        "open_unknowns_sample": unknowns[:12],
        "note": (
            "Unknowns come from cognitive agenda / allocation gaps — "
            "never invent PE/FCF/news to fill them."
        ),
        "beliefs": (
            "Belief Core / WSO remain the durable belief store; "
            "this snapshot only points at today's open work."
        ),
    }


def _cognitive_rollup(labs: dict[str, Any]) -> dict[str, Any]:
    exp = stories = llm_f = agenda_n = 0
    for sec in labs.values():
        if not isinstance(sec, dict):
            continue
        learn = sec.get("learning") if isinstance(sec.get("learning"), dict) else {}
        ag = sec.get("agenda") if isinstance(sec.get("agenda"), dict) else {}
        exp += int(learn.get("experiences") or 0)
        stories += int(learn.get("learning_stories") or 0)
        llm_f += int(learn.get("llm_failures") or 0)
        agenda_n += int(ag.get("items") or 0)
    return {
        "experiences_today": exp,
        "learning_stories_today": stories,
        "llm_failures_today": llm_f,
        "agenda_items_open": agenda_n,
        "honesty": (
            "learned = prediction + outcome + error + attribution — not activity. "
            "No vanity learning story without a qualifying close."
        ),
    }


def assemble_self_model(
    data_dir: str | Path | None,
    *,
    as_of_ist: str | None = None,
    lab_books: list[dict[str, Any]] | None = None,
    llm_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """D1 — assemble one global snapshot from existing stores."""
    day = as_of_ist or ist_today()
    books = _load_lab_books(data_dir, as_of_ist=day, lab_books=lab_books)
    by_key = {
        str(b.get("portfolio_key") or b.get("laboratory_id") or ""): b for b in books
    }
    labs: dict[str, Any] = {}
    for lab in _lab_ids():
        labs[lab] = _lab_section(data_dir, lab, as_of_ist=day, book=by_key.get(lab))
    return {
        "version": VERSION,
        "kind": "SELF_MODEL",
        "as_of_ist": day,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "identity": dict(_IDENTITY),
        "system": _system_state(llm_status=llm_status),
        "laboratories": labs,
        "knowledge": _knowledge_rollup(labs),
        "cognitive_work": _cognitive_rollup(labs),
        "honesty": (
            "Global self-model — one file, per-lab sections. "
            "Read-only / advice-only. Not consciousness theater."
        ),
    }


def save_self_model(
    data_dir: str | Path | None, doc: dict[str, Any]
) -> dict[str, Any]:
    path = day_path(data_dir, str(doc.get("as_of_ist") or ist_today()))
    if path is None:
        return {"ok": False, "reason": "no_data_dir"}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
        return {"ok": True, "path": str(path)}
    except OSError as exc:
        _log.debug("self_model save failed", exc_info=True)
        return {"ok": False, "reason": type(exc).__name__}


def load_self_model(
    data_dir: str | Path | None, *, as_of_ist: str | None = None
) -> dict[str, Any] | None:
    path = day_path(data_dir, as_of_ist)
    if path is None or not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def ensure_self_model(
    data_dir: str | Path | None,
    *,
    as_of_ist: str | None = None,
    lab_books: list[dict[str, Any]] | None = None,
    llm_status: dict[str, Any] | None = None,
    refresh: bool = True,
) -> dict[str, Any]:
    """Assemble (+ optionally persist). Refresh default True for evening/chat honesty."""
    if not refresh:
        existing = load_self_model(data_dir, as_of_ist=as_of_ist)
        if existing:
            return existing
    doc = assemble_self_model(
        data_dir,
        as_of_ist=as_of_ist,
        lab_books=lab_books,
        llm_status=llm_status,
    )
    save_self_model(data_dir, doc)
    return doc


def format_self_model_answer(doc: dict[str, Any] | None, kind: str) -> str:
    """D2 — deterministic chat answers from snapshot."""
    snap = doc if isinstance(doc, dict) else {}
    ident = snap.get("identity") if isinstance(snap.get("identity"), dict) else _IDENTITY
    cog = snap.get("cognitive_work") if isinstance(snap.get("cognitive_work"), dict) else {}
    know = snap.get("knowledge") if isinstance(snap.get("knowledge"), dict) else {}
    system = snap.get("system") if isinstance(snap.get("system"), dict) else {}
    labs = snap.get("laboratories") if isinstance(snap.get("laboratories"), dict) else {}
    day = snap.get("as_of_ist") or ist_today()

    if kind == "who":
        return (
            f"I am {ident.get('name', 'Atlas')} — investment laboratory intelligence.\n"
            f"Mission: {ident.get('mission')}\n"
            f"Mode: {ident.get('mode')}\n"
            f"{ident.get('not')}\n"
            f"(self-model {day} · {VERSION})"
        )

    if kind == "know":
        lines = [
            f"What I track as open unknowns today ({day}):",
        ]
        sample = list(know.get("open_unknowns_sample") or [])
        if not sample:
            lines.append(
                "  · No agenda unknowns published yet — or books idle. "
                "Missing evidence stays unknown_explicit (not invented)."
            )
        else:
            for u in sample[:8]:
                lines.append(f"  · {u}")
        lines.append(str(know.get("note") or ""))
        lines.append(str(know.get("beliefs") or ""))
        lines.append(f"(self-model {day} · deterministic · no Ollama · {VERSION})")
        return "\n".join(lines).strip()

    if kind == "learned":
        lines = [
            f"What Atlas has recorded as learning so far ({day}):",
            f"  Cognitive today: experiences={cog.get('experiences_today', 0)} · "
            f"learning_stories={cog.get('learning_stories_today', 0)} · "
            f"agenda_open={cog.get('agenda_items_open', 0)} · "
            f"llm_failures={cog.get('llm_failures_today', 0)}",
            "  Per laboratory:",
        ]
        any_lab = False
        for lab, sec in labs.items():
            if not isinstance(sec, dict):
                continue
            any_lab = True
            learn = sec.get("learning") if isinstance(sec.get("learning"), dict) else {}
            lines.append(
                f"    · {sec.get('title') or lab}: "
                f"stories={learn.get('learning_stories', 0)}; "
                f"experiences={learn.get('experiences', 0)}; "
                f"prediction_errors={learn.get('prediction_errors_computed', 0)}; "
                f"attribution={learn.get('attribution_satisfied', 0)}/"
                f"{learn.get('attribution_required', 0)}"
            )
        if not any_lab:
            lines.append("    · (no lab sections in snapshot yet)")
        lines.append(
            str(
                cog.get("honesty")
                or (
                    "learned = prediction + outcome + error + attribution — "
                    "not chat activity or Ollama prose."
                )
            )
        )
        unk = list(know.get("open_unknowns_sample") or [])
        if unk:
            lines.append("  Still open (not invented):")
            for u in unk[:5]:
                lines.append(f"    · {u}")
        lines.append(
            "Ask “market intelligence status” for live books; "
            "“what is F&O?” for glossary. "
            f"(self-model {day} · deterministic · no Ollama · {VERSION})"
        )
        return "\n".join(lines).strip()

    lanes = system.get("inference_lanes") if isinstance(system.get("inference_lanes"), dict) else {}
    overnight = system.get("overnight_window_active")
    lines = [
        f"Atlas self-model status ({day}):",
        f"  Cognitive: experiences={cog.get('experiences_today', 0)} · "
        f"learning_stories={cog.get('learning_stories_today', 0)} · "
        f"agenda_items={cog.get('agenda_items_open', 0)} · "
        f"llm_failures={cog.get('llm_failures_today', 0)}",
        f"  Inference: {lanes.get('policy', 'CU.A lanes')}",
        f"  Overnight window active: {bool(overnight)} "
        f"({system.get('overnight_window', '18:30–07:30 IST')})",
        "  Laboratories:",
    ]
    for lab, sec in labs.items():
        if not isinstance(sec, dict):
            continue
        book = sec.get("book") if isinstance(sec.get("book"), dict) else {}
        pos = book.get("positions") or []
        pos_s = ", ".join(str(p) for p in pos[:4]) if pos else "(flat/none)"
        learn = sec.get("learning") if isinstance(sec.get("learning"), dict) else {}
        lines.append(
            f"    · {sec.get('title') or lab}: positions={pos_s}; "
            f"stories={learn.get('learning_stories', 0)}; "
            f"exp={learn.get('experiences', 0)}"
        )
    lines.append(str(cog.get("honesty") or ""))
    lines.append(str(snap.get("honesty") or ""))
    return "\n".join(lines).strip()


def answer_self_model_query(
    data_dir: str | Path | None,
    query: str,
    *,
    lab_books: list[dict[str, Any]] | None = None,
    llm_status: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    kind = detect_self_model_query(query)
    if kind is None:
        return None
    doc = ensure_self_model(
        data_dir, lab_books=lab_books, llm_status=llm_status, refresh=True
    )
    return {
        "version": VERSION,
        "ok": True,
        "mode": "self_model_deterministic",
        "kind": kind,
        "as_of_ist": doc.get("as_of_ist"),
        "answer": format_self_model_answer(doc, kind),
        "path": str(day_path(data_dir, str(doc.get("as_of_ist") or "")) or ""),
    }


def format_self_model_evening_lines(doc: dict[str, Any] | None) -> list[str]:
    """D3 — evening digest aligned with snapshot file."""
    snap = doc if isinstance(doc, dict) else {}
    cog = snap.get("cognitive_work") if isinstance(snap.get("cognitive_work"), dict) else {}
    lines = [
        "",
        "── Atlas self-model (OI-CU0 CU.D) ──",
        f"  day={snap.get('as_of_ist') or '—'} · file=investment/self_model/{{day}}.json",
        f"  experiences={cog.get('experiences_today', 0)} · "
        f"learning_stories={cog.get('learning_stories_today', 0)} · "
        f"agenda={cog.get('agenda_items_open', 0)} · "
        f"llm_failures={cog.get('llm_failures_today', 0)}",
    ]
    labs = snap.get("laboratories") if isinstance(snap.get("laboratories"), dict) else {}
    for lab, sec in labs.items():
        if not isinstance(sec, dict):
            continue
        book = sec.get("book") if isinstance(sec.get("book"), dict) else {}
        pos = book.get("positions") or []
        npos = len(pos) if isinstance(pos, list) else 0
        ag = sec.get("agenda") if isinstance(sec.get("agenda"), dict) else {}
        lines.append(
            f"  · {_safe_lab(lab)}: positions={npos} · agenda={ag.get('items', 0)}"
        )
    lines.append(
        "  Honesty: global snapshot with per-lab sections — not consciousness theater."
    )
    return lines
