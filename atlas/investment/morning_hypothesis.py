"""BRE.4 / OI-LLM-OS0 — Morning hypothesis / evidence-needed BATCH.

Batch-first (never real-time). Cognitive Budget gates LLM passes.
Only LLM authors semantic hypothesis prose; deterministic path lists
structural unknowns / curiosity evidence asks honestly when LLM is absent.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from atlas.investment.cognitive_budget import (
    DEFAULT_NIGHTLY_LLM_PASSES,
    budget_for_wso,
    pick_budgeted,
    score_dimensions,
)
from atlas.investment.curiosity import load_queue

_log = logging.getLogger("atlas.investment.morning_hypothesis")
_IST = ZoneInfo("Asia/Kolkata")

VERSION = "bre4.morning_hypothesis.v1"
STORE_REL = Path("investment") / "morning_hypothesis"
DEFAULT_MORNING_LLM_PASSES = 2

_JSON_RE = re.compile(r"\{[\s\S]*\}")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_^." else "_" for c in (s or ""))


def ist_today() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def store_dir(data_dir: str | Path, *, laboratory_id: str) -> Path:
    from atlas.investment.laboratory import normalize_laboratory_id

    lab = normalize_laboratory_id(laboratory_id=laboratory_id)
    return Path(data_dir) / STORE_REL / _safe(lab)


def batch_path(
    data_dir: str | Path, *, laboratory_id: str, ist_date: str | None = None
) -> Path:
    day = ist_date or ist_today()
    d = store_dir(data_dir, laboratory_id=laboratory_id)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{day}.json"


def load_batch(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    ist_date: str | None = None,
) -> dict[str, Any] | None:
    if not data_dir:
        return None
    path = batch_path(data_dir, laboratory_id=laboratory_id, ist_date=ist_date)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def save_batch(data_dir: str | Path | None, doc: dict[str, Any]) -> Path | None:
    if not data_dir or not isinstance(doc, dict):
        return None
    lab = str(doc.get("laboratory_id") or "india_equity_learner")
    path = batch_path(
        data_dir, laboratory_id=lab, ist_date=str(doc.get("ist_date") or None)
    )
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _parse_json_blob(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        m = _JSON_RE.search(raw)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None


def _evidence_asks(unknown: str) -> list[str]:
    """Deterministic evidence asks (mirror curiosity; never invent values)."""
    u = str(unknown or "").lower()
    if u in {"fcf", "free_cash_flow"}:
        return ["cashflow statement", "screener FCF", "annual report"]
    if u in {"debt_equity", "d_e", "debt"}:
        return ["balance sheet", "screener D/E"]
    if u in {"pe", "roe"}:
        return ["fundamentals store", "screener ratios"]
    if u in {"occupancy", "arpob"}:
        return ["quarterly presentation", "management commentary"]
    if u in {"company", "sector", "macro", "gov", "news"}:
        return ["real RSS/news", "filings", "not seed stubs"]
    return [f"evidence for unknown:{unknown}"]


def budget_for_morning_target(
    *,
    kind: str,
    unknowns: list[Any] | None = None,
    is_open_book: bool = False,
) -> dict[str, Any]:
    unk = list(unknowns or [])
    if kind == "open_book":
        importance = "high"
        novelty = "high" if unk else "medium"
        uncertainty = "high" if len(unk) >= 2 else ("medium" if unk else "low")
    elif kind == "candidate":
        importance = "medium"
        novelty = "medium" if unk else "low"
        uncertainty = "medium" if unk else "low"
    else:
        importance = "low"
        novelty = "low"
        uncertainty = "medium" if unk else "low"
    return score_dimensions(
        importance=importance, novelty=novelty, uncertainty=uncertainty
    )


def collect_morning_targets(
    *,
    wsos: list[dict[str, Any]] | None = None,
    plan: dict[str, Any] | None = None,
    curiosity: dict[str, Any] | None = None,
    open_symbols: set[str] | None = None,
    max_candidates: int = 5,
) -> list[dict[str, Any]]:
    """Build budgeted morning targets from open WSOs + plan candidates + curiosity."""
    open_set = {str(s).upper() for s in (open_symbols or set())}
    by_sym: dict[str, dict[str, Any]] = {}

    for w in wsos or []:
        if not isinstance(w, dict):
            continue
        sym = str(w.get("symbol") or "").strip()
        if not sym:
            continue
        is_open = (not open_set) or sym.upper() in open_set
        if open_set and not is_open:
            continue
        unk = [str(u) for u in (w.get("unknowns") or []) if u][:12]
        bud = budget_for_wso(w, is_open_position=True) if is_open else budget_for_morning_target(
            kind="open_book", unknowns=unk, is_open_book=True
        )
        asks: list[str] = []
        for u in unk:
            asks.extend(_evidence_asks(u))
        # de-dupe asks
        seen_a: set[str] = set()
        asks_u: list[str] = []
        for a in asks:
            if a not in seen_a:
                seen_a.add(a)
                asks_u.append(a)
        by_sym[sym.upper()] = {
            "symbol": sym,
            "kind": "open_book",
            "unknowns": unk,
            "evidence_needed": asks_u[:8],
            "prior_thesis": str(w.get("thesis_text") or "")[:400],
            "llm_budget": int(bud.get("llm_budget") or 0),
            "budget": bud,
        }

    # Curiosity overlays (prefer queued evidence_needed lists)
    for item in (curiosity or {}).get("items") or []:
        if not isinstance(item, dict):
            continue
        sym = str(item.get("symbol") or "").strip()
        if not sym:
            continue
        key = sym.upper()
        row = by_sym.get(key) or {
            "symbol": sym,
            "kind": "open_book" if (not open_set or key in open_set) else "curiosity",
            "unknowns": [],
            "evidence_needed": [],
            "prior_thesis": "",
            "llm_budget": int(item.get("llm_budget") or 0),
            "budget": item.get("budget"),
        }
        unk = str(item.get("unknown") or "").strip()
        if unk and unk not in row["unknowns"]:
            row["unknowns"].append(unk)
        for a in list(item.get("evidence_needed") or [])[:6]:
            if a and a not in row["evidence_needed"]:
                row["evidence_needed"].append(str(a))
        row["llm_budget"] = max(int(row.get("llm_budget") or 0), int(item.get("llm_budget") or 0))
        by_sym[key] = row

    # Plan candidates (Tier-A deploy set)
    for c in list((plan or {}).get("candidates") or [])[: max(1, int(max_candidates))]:
        if not isinstance(c, dict):
            continue
        sym = str(c.get("symbol") or "").strip()
        if not sym:
            continue
        key = sym.upper()
        if key in by_sym:
            # Already open-book — keep open_book kind, bump budget slightly
            by_sym[key]["llm_budget"] = max(int(by_sym[key].get("llm_budget") or 0), 1)
            by_sym[key]["plan_rank"] = c.get("rank")
            continue
        bud = budget_for_morning_target(kind="candidate", unknowns=[], is_open_book=False)
        by_sym[key] = {
            "symbol": sym,
            "kind": "candidate",
            "unknowns": [],
            "evidence_needed": ["confirm PE/FCF coverage", "real news vs seed"],
            "prior_thesis": str(c.get("why") or "")[:300],
            "plan_rank": c.get("rank"),
            "llm_budget": int(bud.get("llm_budget") or 0),
            "budget": bud,
        }

    return list(by_sym.values())


def _deterministic_batch(
    targets: list[dict[str, Any]],
    *,
    laboratory_id: str,
    ist_date: str,
    skip_reason: str,
) -> dict[str, Any]:
    hyps: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for t in targets:
        sym = t.get("symbol")
        unk = list(t.get("unknowns") or [])
        # No semantic hypothesis prose without LLM
        if unk:
            hyps.append(
                {
                    "symbol": sym,
                    "kind": t.get("kind"),
                    "statement": None,
                    "unknowns": unk[:6],
                    "assumption": True,
                }
            )
        for u in unk[:4]:
            evidence.append(
                {
                    "symbol": sym,
                    "unknown": u,
                    "asks": list(t.get("evidence_needed") or _evidence_asks(str(u)))[:6],
                }
            )
        if not unk and t.get("evidence_needed"):
            evidence.append(
                {
                    "symbol": sym,
                    "unknown": "coverage",
                    "asks": list(t.get("evidence_needed"))[:6],
                }
            )
    return {
        "version": VERSION,
        "laboratory_id": laboratory_id,
        "ist_date": ist_date,
        "created_at": _now(),
        "status": "skipped" if skip_reason else "deterministic",
        "skip_reason": skip_reason,
        "llm": False,
        "hypotheses": hyps[:20],
        "evidence_needed": evidence[:30],
        "targets_considered": len(targets),
        "targets_budgeted": 0,
    }


def run_morning_hypothesis_batch(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    llm: Any | None = None,
    wsos: list[dict[str, Any]] | None = None,
    plan: dict[str, Any] | None = None,
    curiosity: dict[str, Any] | None = None,
    open_symbols: set[str] | None = None,
    ist_date: str | None = None,
    max_passes: int = DEFAULT_MORNING_LLM_PASSES,
    max_candidates: int = 5,
) -> dict[str, Any]:
    """Morning BATCH: budgeted LLM hypotheses + evidence-needed list."""
    day = ist_date or ist_today()
    lab = laboratory_id or "india_equity_learner"
    cq = curiosity
    if cq is None and data_dir:
        # Prefer today's queue; fall back to yesterday is not required for BRE.4
        cq = load_queue(data_dir, day)

    targets = collect_morning_targets(
        wsos=wsos,
        plan=plan,
        curiosity=cq,
        open_symbols=open_symbols,
        max_candidates=max_candidates,
    )
    if not targets:
        doc = {
            "version": VERSION,
            "laboratory_id": lab,
            "ist_date": day,
            "created_at": _now(),
            "status": "empty",
            "skip_reason": "No open books or plan candidates — nothing to hypothesize",
            "llm": False,
            "hypotheses": [],
            "evidence_needed": [],
            "targets_considered": 0,
            "targets_budgeted": 0,
            "nightly_cap_reference": DEFAULT_NIGHTLY_LLM_PASSES,
        }
        if data_dir:
            save_batch(data_dir, doc)
        return doc

    prepared = [{"target": t, "llm_budget": int(t.get("llm_budget") or 0)} for t in targets]
    chosen = pick_budgeted(prepared, max_passes=max_passes)
    chosen_syms = {str((c.get("target") or {}).get("symbol") or "").upper() for c in chosen}

    if llm is None:
        doc = _deterministic_batch(
            targets,
            laboratory_id=lab,
            ist_date=day,
            skip_reason="BRE.4 skipped — no LLM (deterministic Represent only)",
        )
        doc["targets_considered"] = len(targets)
        if data_dir:
            save_batch(data_dir, doc)
        return doc

    try:
        if hasattr(llm, "lane_busy") and llm.lane_busy():
            doc = _deterministic_batch(
                targets,
                laboratory_id=lab,
                ist_date=day,
                skip_reason="BRE.4 deferred — LLM lane busy",
            )
            doc["status"] = "deferred_lane_busy"
            doc["targets_considered"] = len(targets)
            if data_dir:
                save_batch(data_dir, doc)
            return doc
    except Exception:  # noqa: BLE001
        pass

    if not chosen:
        doc = _deterministic_batch(
            targets,
            laboratory_id=lab,
            ist_date=day,
            skip_reason="BRE.4 skipped — cognitive budget 0 / no budgeted targets",
        )
        doc["targets_considered"] = len(targets)
        if data_dir:
            save_batch(data_dir, doc)
        return doc

    # One batched LLM call for all budgeted targets (batch-first)
    prompt_targets = [
        {
            "symbol": (c.get("target") or {}).get("symbol"),
            "kind": (c.get("target") or {}).get("kind"),
            "unknowns": (c.get("target") or {}).get("unknowns") or [],
            "evidence_needed": (c.get("target") or {}).get("evidence_needed") or [],
            "prior_thesis": (c.get("target") or {}).get("prior_thesis") or "",
            "plan_rank": (c.get("target") or {}).get("plan_rank"),
        }
        for c in chosen
    ]
    prompt = {
        "task": "morning_hypothesis_batch",
        "ist_date": day,
        "laboratory_id": lab,
        "targets": prompt_targets,
        "instructions": (
            "Return JSON only with keys: "
            "hypotheses (list of {symbol, kind, statement, falsifiers[]}), "
            "evidence_needed (list of {symbol, unknown, asks[]}), "
            "notes (short string). "
            "One hypothesis statement per budgeted symbol (1 sentence). "
            "Do not invent PE/FCF/prices. Prefer concrete evidence asks. "
            "Unknown stays unknown."
        ),
    }
    try:
        from atlas.llm.provider import ChatMessage

        client = llm.for_role("researcher") if hasattr(llm, "for_role") else llm
        messages = [
            ChatMessage(
                "system",
                (
                    "You are Atlas's investment cortex for the morning window. "
                    "Propose hypotheses and evidence needed. One JSON object only."
                ),
            ),
            ChatMessage("user", json.dumps(prompt, default=str)),
        ]
        resp = client.chat(messages)
        text = getattr(resp, "text", None) or getattr(resp, "content", None) or str(resp)
    except Exception as exc:  # noqa: BLE001
        doc = _deterministic_batch(
            targets,
            laboratory_id=lab,
            ist_date=day,
            skip_reason=f"BRE.4 LLM failed: {type(exc).__name__}: {exc}",
        )
        doc["status"] = "failed"
        doc["targets_considered"] = len(targets)
        if data_dir:
            save_batch(data_dir, doc)
        return doc

    parsed = _parse_json_blob(str(text))
    if not parsed:
        doc = _deterministic_batch(
            targets,
            laboratory_id=lab,
            ist_date=day,
            skip_reason="BRE.4 LLM returned non-JSON — no semantic hypotheses",
        )
        doc["status"] = "failed"
        doc["llm"] = True
        doc["targets_considered"] = len(targets)
        if data_dir:
            save_batch(data_dir, doc)
        return doc

    hyps_out: list[dict[str, Any]] = []
    for h in list(parsed.get("hypotheses") or [])[:20]:
        if not isinstance(h, dict):
            continue
        sym = str(h.get("symbol") or "").strip()
        if not sym or sym.upper() not in chosen_syms:
            continue
        statement = str(h.get("statement") or "").strip()[:500]
        if not statement:
            continue
        hyps_out.append(
            {
                "symbol": sym,
                "kind": h.get("kind") or "open_book",
                "statement": statement,
                "falsifiers": [str(x)[:200] for x in (h.get("falsifiers") or []) if x][:6],
            }
        )

    evid_out: list[dict[str, Any]] = []
    for e in list(parsed.get("evidence_needed") or [])[:30]:
        if not isinstance(e, dict):
            continue
        sym = str(e.get("symbol") or "").strip()
        if not sym:
            continue
        asks = [str(a)[:120] for a in (e.get("asks") or []) if a][:6]
        if not asks:
            continue
        evid_out.append(
            {
                "symbol": sym,
                "unknown": str(e.get("unknown") or "unknown")[:80],
                "asks": asks,
            }
        )
    # Fill structural evidence for targets LLM omitted
    have = {(str(e["symbol"]).upper(), str(e.get("unknown"))) for e in evid_out}
    for t in targets:
        for u in list(t.get("unknowns") or [])[:4]:
            key = (str(t.get("symbol") or "").upper(), str(u))
            if key in have:
                continue
            evid_out.append(
                {
                    "symbol": t.get("symbol"),
                    "unknown": u,
                    "asks": list(t.get("evidence_needed") or _evidence_asks(str(u)))[:6],
                }
            )
            have.add(key)

    doc = {
        "version": VERSION,
        "laboratory_id": lab,
        "ist_date": day,
        "created_at": _now(),
        "status": "done",
        "skip_reason": None,
        "llm": True,
        "notes": str(parsed.get("notes") or "")[:400] or None,
        "hypotheses": hyps_out,
        "evidence_needed": evid_out[:30],
        "targets_considered": len(targets),
        "targets_budgeted": len(chosen),
        "max_passes": max_passes,
        "nightly_cap_reference": DEFAULT_NIGHTLY_LLM_PASSES,
    }
    if data_dir:
        save_batch(data_dir, doc)
    return doc


def format_morning_hypothesis_section(doc: dict[str, Any] | None) -> list[str]:
    """Morning-mail lines for BRE.4."""
    if not isinstance(doc, dict):
        return []
    lines = ["", "Morning hypotheses / evidence needed (BRE.4):"]
    status = str(doc.get("status") or "")
    skip = doc.get("skip_reason")
    if status in {"empty", "skipped", "deferred_lane_busy", "failed", "deterministic"}:
        if skip:
            lines.append(f"  {skip}")
        elif status == "empty":
            lines.append("  (nothing to hypothesize today)")
        # Still show structural evidence when present
    hyps = [h for h in (doc.get("hypotheses") or []) if isinstance(h, dict)]
    open_h = [h for h in hyps if h.get("kind") == "open_book" and h.get("statement")]
    cand_h = [h for h in hyps if h.get("kind") == "candidate" and h.get("statement")]
    if open_h:
        lines.append("  Open books:")
        for h in open_h[:8]:
            lines.append(f"    · {h.get('symbol')}: {h.get('statement')}")
            fals = list(h.get("falsifiers") or [])[:2]
            if fals:
                lines.append(f"       falsifiers: {'; '.join(str(x) for x in fals)}")
    if cand_h:
        lines.append("  Ranked candidates:")
        for h in cand_h[:5]:
            lines.append(f"    · {h.get('symbol')}: {h.get('statement')}")
    evid = [e for e in (doc.get("evidence_needed") or []) if isinstance(e, dict)]
    if evid:
        lines.append("  Evidence needed:")
        for e in evid[:10]:
            asks = ", ".join(str(a) for a in (e.get("asks") or [])[:3])
            lines.append(
                f"    · {e.get('symbol')} / {e.get('unknown')} → {asks or '—'}"
            )
    if not open_h and not cand_h and not evid and not skip:
        lines.append("  (no hypotheses or evidence asks)")
    return lines
