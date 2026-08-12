"""META.1 / OI-META-COG0 — Reasoning-pattern ledger (meta-cognition).

Not trade attribution — **why** a belief formed (which reasoning pattern), and
whether that pattern has been historically reliable.

A8: free text + tags first; controlled vocab after 50+ revisions.
Batch-first; deterministic tagging + reliability math; optional LLM labels later.
Advice-only (A7).
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from atlas.investment.world_state import list_lab_wsos

_log = logging.getLogger("atlas.investment.meta_cognition")
VERSION = "meta1.reasoning_patterns.v1"
STORE_REL = Path("investment") / "meta_cognition"
VOCAB_GATE_N = 50  # A8 — controlled vocab only after this many tagged revisions

# Free-text tag seeds (heuristic; not a closed ontology yet)
_TAG_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("brand_moat", re.compile(r"\b(brand|moat|pricing.?power|franchise)\b", re.I)),
    ("valuation", re.compile(r"\b(pe|p/e|valuation|cheap|expensive|multiple|fcf)\b", re.I)),
    ("momentum_rs", re.compile(r"\b(rs|relative.?strength|momentum|trend|sma|breakout)\b", re.I)),
    ("fundamentals_gap", re.compile(r"\b(fcf|roe|d/?e|debt|fundamentals?|unknown)\b", re.I)),
    ("news_catalyst", re.compile(r"\b(news|headline|rss|catalyst|event)\b", re.I)),
    ("sector_theme", re.compile(r"\b(sector|theme|pli|policy|budget|defence|pharma)\b", re.I)),
    ("falsifier_check", re.compile(r"\b(falsif|invalidat|contradict|disprov)\b", re.I)),
    ("evidence_cite", re.compile(r"\b(evidence|cited|citation|obs-|observation)\b", re.I)),
    ("size_risk", re.compile(r"\b(size|sizing|notional|risk|stop.?loss)\b", re.I)),
    ("thesis_intact", re.compile(r"\b(thesis|belief|strengthen|intact)\b", re.I)),
)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in (s or ""))


def store_dir(data_dir: str | Path, *, laboratory_id: str) -> Path:
    from atlas.investment.laboratory import normalize_laboratory_id

    lab = normalize_laboratory_id(laboratory_id=laboratory_id)
    return Path(data_dir) / STORE_REL / _safe(lab)


def latest_path(data_dir: str | Path, *, laboratory_id: str) -> Path:
    d = store_dir(data_dir, laboratory_id=laboratory_id)
    d.mkdir(parents=True, exist_ok=True)
    return d / "latest.json"


def load_ledger(
    data_dir: str | Path | None, *, laboratory_id: str
) -> dict[str, Any] | None:
    if not data_dir:
        return None
    path = latest_path(data_dir, laboratory_id=laboratory_id)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def save_ledger(data_dir: str | Path | None, doc: dict[str, Any]) -> Path | None:
    if not data_dir or not isinstance(doc, dict):
        return None
    lab = str(doc.get("laboratory_id") or "india_equity_learner")
    path = latest_path(data_dir, laboratory_id=lab)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def tag_reason(text: str) -> list[str]:
    """Free-text → tags (A8). Always includes ``untagged`` if nothing matches."""
    raw = str(text or "").strip()
    if not raw:
        return ["untagged"]
    tags: list[str] = []
    for name, pat in _TAG_RULES:
        if pat.search(raw):
            tags.append(name)
    if not tags:
        tags.append("untagged")
    return tags


def collect_reasoning_events(
    wsos: list[dict[str, Any]] | None,
    *,
    max_n: int = 200,
) -> list[dict[str, Any]]:
    """One event per material WSO revision with pattern tags."""
    material = {"strengthened", "weakened", "falsified", "insufficient_evidence"}
    events: list[dict[str, Any]] = []
    for w in wsos or []:
        if not isinstance(w, dict) or w.get("kind") == "global":
            continue
        sym = str(w.get("symbol") or "").strip()
        if not sym or sym == "_GLOBAL":
            continue
        hist = [r for r in (w.get("revision_history") or []) if isinstance(r, dict)]
        prior_status = None
        for rec in hist:
            status = str(rec.get("status") or "").lower()
            if status not in material and not rec.get("llm"):
                prior_status = status
                continue
            reason = str(rec.get("reason") or "")
            tags = tag_reason(reason)
            flipped = bool(
                prior_status == "strengthened"
                and status in {"weakened", "falsified"}
            ) or bool(
                prior_status in {"weakened", "falsified"}
                and status == "strengthened"
            )
            events.append(
                {
                    "symbol": sym,
                    "status": status,
                    "reason": reason[:300],
                    "tags": tags,
                    "at": rec.get("at"),
                    "llm": bool(rec.get("llm")),
                    "flipped_from_prior": flipped,
                    "prior_status": prior_status,
                }
            )
            if status in material:
                prior_status = status
            if len(events) >= max_n:
                return events
    return events


def build_pattern_ledger(
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate tags → reliability (deterministic)."""
    by_tag: dict[str, dict[str, Any]] = {}
    for ev in events:
        for tag in ev.get("tags") or ["untagged"]:
            row = by_tag.setdefault(
                str(tag),
                {
                    "tag": str(tag),
                    "n": 0,
                    "strengthened": 0,
                    "weakened": 0,
                    "falsified": 0,
                    "insufficient_evidence": 0,
                    "flip_after": 0,
                    "examples": [],
                },
            )
            row["n"] = int(row["n"]) + 1
            st = str(ev.get("status") or "")
            if st in row:
                row[st] = int(row[st]) + 1
            if ev.get("flipped_from_prior"):
                row["flip_after"] = int(row["flip_after"]) + 1
            if len(row["examples"]) < 3:
                row["examples"].append(
                    {
                        "symbol": ev.get("symbol"),
                        "status": st,
                        "reason": ev.get("reason"),
                    }
                )

    patterns: list[dict[str, Any]] = []
    for tag, row in by_tag.items():
        n = max(1, int(row["n"]))
        good = int(row.get("strengthened") or 0)
        bad = int(row.get("weakened") or 0) + int(row.get("falsified") or 0)
        flips = int(row.get("flip_after") or 0)
        # reliability ∈ [0,1]: favors strengthen, penalizes weaken/falsify/flips
        raw = (good - 0.5 * bad - flips) / n
        reliability = round(max(0.0, min(1.0, 0.5 + 0.5 * raw)), 3)
        note = None
        if n >= 3 and reliability < 0.4:
            note = (
                f"Pattern '{tag}' historically weak "
                f"(reliability={reliability}) — reduce confidence when reused"
            )
        elif n >= 3 and reliability >= 0.7:
            note = f"Pattern '{tag}' historically steadier (reliability={reliability})"
        patterns.append(
            {
                **row,
                "reliability": reliability,
                "note": note,
                "advice_only": True,
            }
        )

    patterns.sort(key=lambda p: (-int(p.get("n") or 0), str(p.get("tag"))))
    total_n = sum(int(p.get("n") or 0) for p in patterns)
    return {
        "patterns": patterns,
        "tagged_revisions": total_n,
        "unique_tags": len(patterns),
        "vocab_mode": "free_text_tags"
        if total_n < VOCAB_GATE_N
        else "controlled_vocab_eligible",
        "vocab_gate_n": VOCAB_GATE_N,
    }


def run_meta_cognition(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    wsos: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build / persist reasoning-pattern ledger for a lab."""
    lab = laboratory_id or "india_equity_learner"
    rows = list(wsos) if wsos is not None else (
        list_lab_wsos(data_dir, lab) if data_dir else []
    )
    events = collect_reasoning_events(rows)
    built = build_pattern_ledger(events)
    status = "done" if events else "empty"
    skip = None if events else "META.1 empty — no material revisions to attribute yet"

    # Top advice bullets (deterministic)
    advice: list[str] = []
    for p in built.get("patterns") or []:
        if p.get("note") and p.get("tag") != "untagged":
            advice.append(str(p["note"]))
        if len(advice) >= 5:
            break
    if not advice and events:
        advice.append(
            "Reasoning patterns logged — need more revisions before reliability claims"
        )

    doc = {
        "version": VERSION,
        "laboratory_id": lab,
        "created_at": _now(),
        "status": status,
        "skip_reason": skip,
        "advice_only": True,
        "enable_soft_bias": False,
        "tagged_revisions": built.get("tagged_revisions") or 0,
        "unique_tags": built.get("unique_tags") or 0,
        "vocab_mode": built.get("vocab_mode"),
        "vocab_gate_n": VOCAB_GATE_N,
        "patterns": built.get("patterns") or [],
        "advice": advice,
        "events_sample": events[:20],
    }
    if data_dir:
        save_ledger(data_dir, doc)
    return doc


def format_meta_cognition_section(doc: dict[str, Any] | None) -> list[str]:
    """Evening: reasoning-pattern ledger (META.1)."""
    if not isinstance(doc, dict):
        return []
    lines = ["", "--- Reasoning patterns (META.1) ---"]
    n = int(doc.get("tagged_revisions") or 0)
    lines.append(
        f"tagged_revisions={n} · tags={doc.get('unique_tags')} · "
        f"vocab={doc.get('vocab_mode')} · advice_only="
        f"{bool(doc.get('advice_only', True))}"
    )
    if doc.get("skip_reason") and doc.get("status") == "empty":
        lines.append(f"  {doc.get('skip_reason')}")
        return lines
    for p in list(doc.get("patterns") or [])[:8]:
        if not isinstance(p, dict):
            continue
        tag = p.get("tag")
        if tag == "untagged" and int(p.get("n") or 0) < 2:
            continue
        lines.append(
            f"  · {tag}: n={p.get('n')} reliability={p.get('reliability')} "
            f"(↑{p.get('strengthened')} ↓{p.get('weakened')}+"
            f"{p.get('falsified')} flip={p.get('flip_after')})"
        )
        if p.get("note"):
            lines.append(f"     {p.get('note')}")
    for a in list(doc.get("advice") or [])[:3]:
        lines.append(f"  advice: {a}")
    if n < VOCAB_GATE_N:
        lines.append(
            f"  Honesty: free-text tags until ≥{VOCAB_GATE_N} tagged revisions "
            f"(have {n}) — not a closed ontology yet."
        )
    return lines
