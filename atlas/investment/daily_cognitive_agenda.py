"""OI-DCA0 — Daily Cognitive Agenda (Judgment Pivot amendment C).

Morning publishes “today I intend to think about…” from open books,
curiosity queue, and prior ranking mistakes. CWS drains agenda items;
structural stubs alone do not clear them.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_log = logging.getLogger("atlas.investment.daily_cognitive_agenda")
_IST = ZoneInfo("Asia/Kolkata")

VERSION = "jdg.dca.v1"
STORE_REL = Path("investment") / "cognitive_agenda"
DEFAULT_MAX_ITEMS = 5


def _ist_today() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def _safe_lab(laboratory_id: str) -> str:
    return "".join(
        c if c.isalnum() or c in "-_" else "_" for c in (laboratory_id or "lab")
    )


def agenda_path(
    data_dir: str | Path | None,
    laboratory_id: str,
    *,
    ist_date: str | None = None,
) -> Path | None:
    if not data_dir:
        return None
    day = ist_date or _ist_today()
    d = Path(data_dir) / STORE_REL / _safe_lab(laboratory_id)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{day}.json"


def empty_agenda(
    laboratory_id: str,
    *,
    ist_date: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "version": VERSION,
        "laboratory_id": laboratory_id,
        "ist_date": ist_date or _ist_today(),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "items": [],
        "empty_reason": reason,
        "honesty": (
            "Agenda lists intentional thinking targets — not trading signals. "
            "Blocked items stay blocked until evidence exists (never invent)."
        ),
    }


def load_agenda(
    data_dir: str | Path | None,
    laboratory_id: str,
    *,
    ist_date: str | None = None,
) -> dict[str, Any]:
    path = agenda_path(data_dir, laboratory_id, ist_date=ist_date)
    if path is None or not path.is_file():
        return empty_agenda(laboratory_id, ist_date=ist_date, reason="not_published")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else empty_agenda(
            laboratory_id, ist_date=ist_date
        )
    except (OSError, json.JSONDecodeError):
        return empty_agenda(laboratory_id, ist_date=ist_date, reason="unreadable")


def save_agenda(data_dir: str | Path | None, doc: dict[str, Any]) -> Path | None:
    if not data_dir or not isinstance(doc, dict):
        return None
    lab = str(doc.get("laboratory_id") or "lab")
    path = agenda_path(
        data_dir, lab, ist_date=str(doc.get("ist_date") or _ist_today())
    )
    if path is None:
        return None
    doc = dict(doc)
    doc["version"] = VERSION
    doc["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _item(
    *,
    symbol: str | None,
    intent: str,
    kind: str,
    unknowns: list[str] | None = None,
    source: str = "open_book",
    priority: str = "medium",
) -> dict[str, Any]:
    return {
        "id": f"{kind}:{symbol or 'lab'}:{abs(hash(intent)) % 10_000_000}",
        "symbol": symbol,
        "intent": intent[:240],
        "kind": kind,
        "unknowns": list(unknowns or [])[:8],
        "source": source,
        "priority": priority,
        "status": "planned",
        "block_reason": None,
        "work_refs": [],
    }


def build_daily_agenda(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    wsos: list[dict[str, Any]] | None = None,
    open_symbols: set[str] | list[str] | None = None,
    curiosity: dict[str, Any] | None = None,
    ranked: list[dict[str, Any]] | None = None,
    ist_date: str | None = None,
    max_items: int = DEFAULT_MAX_ITEMS,
) -> dict[str, Any]:
    """Deterministic agenda from open books + curiosity + ranking honesty."""
    day = ist_date or _ist_today()
    open_set = {str(s).upper() for s in (open_symbols or []) if s}
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(it: dict[str, Any]) -> None:
        if len(items) >= max(1, int(max_items)):
            return
        key = f"{it.get('symbol')}|{it.get('kind')}|{it.get('intent')}"
        if key in seen:
            return
        seen.add(key)
        items.append(it)

    for w in wsos or []:
        if not isinstance(w, dict):
            continue
        sym = str(w.get("symbol") or "").strip()
        if not sym:
            continue
        if open_set and sym.upper() not in open_set:
            continue
        unk = [str(u) for u in (w.get("unknowns") or []) if u][:6]
        intent = (
            f"Review open thesis for {sym}"
            + (
                f" — resolve unknowns: {', '.join(unk[:4])}"
                if unk
                else " — check evidence vs thesis"
            )
        )
        _add(
            _item(
                symbol=sym,
                intent=intent,
                kind="open_book",
                unknowns=unk,
                source="wso",
                priority="high",
            )
        )

    cq = curiosity
    if cq is None and data_dir:
        try:
            from atlas.investment.curiosity import load_queue

            cq = load_queue(data_dir, day)
        except Exception:  # noqa: BLE001
            cq = None
    for it in (cq or {}).get("items") or []:
        if not isinstance(it, dict):
            continue
        if str(it.get("status") or "queued") not in {"queued", "ira_failed"}:
            continue
        sym = str(it.get("symbol") or "").strip() or None
        unk = str(it.get("unknown") or "").strip()
        if not unk:
            continue
        _add(
            _item(
                symbol=sym,
                intent=f"Pursue curiosity: {unk}" + (f" on {sym}" if sym else ""),
                kind="curiosity",
                unknowns=[unk],
                source="curiosity_queue",
                priority=str(it.get("priority") or "medium"),
            )
        )

    for r in list(ranked or [])[:8]:
        if not isinstance(r, dict):
            continue
        sym = str(r.get("symbol") or "").strip()
        if not sym:
            continue
        conf = r.get("confidence")
        try:
            conf_f = float(conf) if conf is not None else None
        except (TypeError, ValueError):
            conf_f = None
        if conf_f is not None and conf_f >= 0.7:
            continue
        _add(
            _item(
                symbol=sym,
                intent=(
                    f"Audit ranking for {sym}: what evidence supported rank="
                    f"{r.get('rank')}? (honesty pass — do not invent)"
                ),
                kind="mistake",
                unknowns=["ranking_evidence"],
                source="ranked",
                priority="low",
            )
        )
        break

    doc = empty_agenda(laboratory_id, ist_date=day)
    doc["items"] = items
    if not items:
        doc["empty_reason"] = (
            "No open-book unknowns, curiosity items, or weak ranks to agenda — "
            "idle thinking day (honest)."
        )
    else:
        doc["empty_reason"] = None
    if data_dir:
        save_agenda(data_dir, doc)
    return doc


def mark_agenda_progress(
    agenda: dict[str, Any],
    *,
    symbol: str | None = None,
    unknown: str | None = None,
    status: str = "done",
    block_reason: str | None = None,
    work_ref: str | None = None,
) -> dict[str, Any]:
    """Update matching agenda items after CWS/IRA/BRE work."""
    doc = dict(agenda or {})
    items = list(doc.get("items") or [])
    sym_u = (symbol or "").upper()
    unk_l = (unknown or "").lower()
    for it in items:
        if not isinstance(it, dict):
            continue
        cur = str(it.get("status") or "planned")
        if cur in {"done", "blocked"}:
            continue
        it_sym = str(it.get("symbol") or "").upper()
        it_unk = [str(u).lower() for u in (it.get("unknowns") or [])]
        if sym_u and it_sym and it_sym != sym_u:
            continue
        # Curiosity/mistake: prefer unknown match when provided
        if unk_l and it.get("kind") in {"curiosity", "mistake"} and unk_l not in it_unk:
            if unk_l not in str(it.get("intent") or "").lower():
                continue
        it["status"] = status
        if block_reason:
            it["block_reason"] = block_reason[:200]
        if work_ref:
            refs = list(it.get("work_refs") or [])
            refs.append(work_ref)
            it["work_refs"] = refs[-8:]
    doc["items"] = items
    return doc


def agenda_summary(agenda: dict[str, Any] | None) -> dict[str, int]:
    counts: dict[str, int] = {
        "planned": 0,
        "in_progress": 0,
        "done": 0,
        "deferred": 0,
        "blocked": 0,
    }
    for it in (agenda or {}).get("items") or []:
        if not isinstance(it, dict):
            continue
        st = str(it.get("status") or "planned")
        counts[st] = int(counts.get(st) or 0) + 1
    return counts


def format_agenda_section(
    agenda: dict[str, Any] | None,
    *,
    when: str = "morning",
) -> list[str]:
    """Morning intent list or evening done/deferred/blocked."""
    doc = agenda if isinstance(agenda, dict) else {}
    items = [i for i in (doc.get("items") or []) if isinstance(i, dict)]
    lines = ["", "--- Daily Cognitive Agenda (DCA) ---"]
    if when == "morning":
        lines.append("Today I intend to think about:")
    else:
        lines.append("Agenda progress (evening):")
    if not items:
        reason = doc.get("empty_reason") or "agenda empty"
        lines.append(f"  (empty) {reason}")
        return lines
    for i, it in enumerate(items, 1):
        sym = it.get("symbol") or "—"
        st = it.get("status") or "planned"
        if when == "morning":
            lines.append(f"  {i}. {sym}: {it.get('intent')}")
            unk = it.get("unknowns") or []
            if unk:
                lines.append(f"     unknowns: {', '.join(str(u) for u in unk[:5])}")
        else:
            block = f" — {it.get('block_reason')}" if it.get("block_reason") else ""
            lines.append(f"  {i}. [{st}] {sym}: {it.get('intent')}{block}")
    if when == "evening":
        summ = agenda_summary(doc)
        lines.append(
            "summary: " + " · ".join(f"{k}={v}" for k, v in summ.items() if v)
        )
    lines.append(
        "Honesty: agenda ≠ edge. Clearing an item requires real work or an explicit block."
    )
    return lines


def count_belief_revisions(
    data_dir: str | Path | None,
    laboratory_id: str,
    *,
    days: int = 7,
) -> dict[str, Any]:
    """Count material WSO revisions (strengthen/weaken/falsify) today and over N days."""
    from datetime import timedelta

    today = _ist_today()
    start = (
        datetime.now(_IST) - timedelta(days=max(0, int(days) - 1))
    ).strftime("%Y-%m-%d")
    today_n = 0
    week_n = 0
    by_status: dict[str, int] = {}
    if not data_dir:
        return {
            "today": 0,
            "days": int(days),
            "period": 0,
            "by_status": {},
            "honesty": "no data_dir",
        }
    root: Path | None = None
    try:
        from atlas.investment.world_state import lab_dir

        root = lab_dir(data_dir, laboratory_id)
    except Exception:  # noqa: BLE001
        root = Path(data_dir) / "investment" / "world_state" / _safe_lab(laboratory_id)
    if root is None or not Path(root).is_dir():
        return {
            "today": 0,
            "days": int(days),
            "period": 0,
            "by_status": {},
            "honesty": "no WSO directory",
        }
    material = {"strengthened", "weakened", "falsified"}
    for path in Path(root).glob("*.json"):
        if path.name.startswith("_"):
            continue
        try:
            w = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(w, dict):
            continue
        for rec in w.get("revision_history") or []:
            if not isinstance(rec, dict):
                continue
            st = str(rec.get("status") or "")
            if st not in material:
                continue
            ed = (
                rec.get("evidence_delta")
                if isinstance(rec.get("evidence_delta"), dict)
                else {}
            )
            if ed.get("structural") and not rec.get("llm"):
                continue
            at = str(rec.get("at") or "")
            day = at[:10] if len(at) >= 10 else ""
            if not day:
                continue
            by_status[st] = int(by_status.get(st) or 0) + 1
            if day >= start:
                week_n += 1
            if day == today:
                today_n += 1
    return {
        "today": today_n,
        "days": int(days),
        "period": week_n,
        "by_status": by_status,
        "honesty": (
            "Counts material strengthen/weaken/falsify with non-structural evidence. "
            "Structural WSO shells are excluded."
        ),
    }


def format_jis_revisions_section(stats: dict[str, Any] | None) -> list[str]:
    """Amendment C — Belief Revisions today/7d always visible (+ Belief Core / consultations)."""
    s = stats if isinstance(stats, dict) else {}
    lines = ["", "--- Judgment Improvement (JIS) — Belief Revisions ---"]
    lines.append(
        f"Belief Revisions: today={int(s.get('today') or 0)} · "
        f"{int(s.get('days') or 7)}d={int(s.get('period') or 0)}"
    )
    by = s.get("by_status") or {}
    if by:
        lines.append(
            "by_status: " + " · ".join(f"{k}={v}" for k, v in sorted(by.items()))
        )
    core = s.get("belief_core") if isinstance(s.get("belief_core"), dict) else {}
    if core:
        lines.append(
            f"Belief Core: today={int(core.get('today') or 0)} · "
            f"7d={int(core.get('period') or 0)} (source={core.get('source')})"
        )
    consults = s.get("consultations_today") or core.get("consultations_today") or {}
    if isinstance(consults, dict) and consults:
        byd = consults.get("by_domain") or {}
        lines.append(
            f"Belief Consultations Today: {int(consults.get('total') or 0)} "
            f"(market={int(byd.get('market') or 0)} · "
            f"engineering={int(byd.get('engineering') or 0)} · "
            f"personal={int(byd.get('personal') or 0)} · "
            f"cross={int(byd.get('cross') or 0)})"
        )
    lines.append(
        "Honesty: JIS ≠ P&L. 0 revisions is honest when evidence is thin — "
        "do not invent calibration yet. Consultations=0 means worldview is decorative."
    )
    if int(s.get("period") or 0) == 0:
        lines.append(
            "North star: raise Belief Revisions/week via evidence densify + "
            "Belief Core reflection — not via more HOLD emails."
        )
    return lines
