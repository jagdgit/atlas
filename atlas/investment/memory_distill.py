"""MEM.1 / OI-MEM-LLM0 — Episodic → semantic / procedural memory distill.

Batch-first. Deterministic clustering + provenance; LLM may author concept/
procedure text under Cognitive Budget. Mentors/research read the durable
layers. Soft-bias stays off (A7) until calibration sample gate.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

from atlas.investment.cognitive_budget import DEFAULT_NIGHTLY_LLM_PASSES
from atlas.investment.world_state import list_lab_wsos, load_global_wso

_log = logging.getLogger("atlas.investment.memory_distill")
VERSION = "mem1.distill.v1"
STORE_REL = Path("investment") / "memory_distill"
DEFAULT_DISTILL_LLM_PASSES = 1

_JSON_RE = re.compile(r"\{[\s\S]*\}")


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


def load_distill(
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


def save_distill(data_dir: str | Path | None, doc: dict[str, Any]) -> Path | None:
    if not data_dir or not isinstance(doc, dict):
        return None
    lab = str(doc.get("laboratory_id") or "india_equity_learner")
    path = latest_path(data_dir, laboratory_id=lab)
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


def collect_episodic(
    *,
    wsos: list[dict[str, Any]] | None = None,
    experiences: list[dict[str, Any]] | None = None,
    global_wso: dict[str, Any] | None = None,
    max_n: int = 80,
) -> list[dict[str, Any]]:
    """Flatten episodic candidates with provenance (deterministic)."""
    rows: list[dict[str, Any]] = []
    for w in wsos or []:
        if not isinstance(w, dict) or w.get("kind") == "global":
            continue
        sym = str(w.get("symbol") or "").strip()
        if not sym or sym == "_GLOBAL":
            continue
        for rec in list(w.get("revision_history") or [])[-5:]:
            if not isinstance(rec, dict):
                continue
            status = str(rec.get("status") or "").lower()
            if status in {"unchanged", ""} and not rec.get("llm"):
                continue
            rows.append(
                {
                    "source": "wso_revision",
                    "symbol": sym,
                    "status": status,
                    "text": str(rec.get("reason") or "")[:300],
                    "at": rec.get("at"),
                    "llm": bool(rec.get("llm")),
                }
            )
    digest = (global_wso or {}).get("mentor_digest") if isinstance(global_wso, dict) else None
    if isinstance(digest, dict):
        for b in list(digest.get("bullets") or [])[:8]:
            rows.append(
                {
                    "source": "global_digest",
                    "symbol": None,
                    "status": "pattern",
                    "text": str(b)[:300],
                    "at": None,
                    "llm": False,
                }
            )
    for e in experiences or []:
        if not isinstance(e, dict):
            continue
        tags = {str(t).lower() for t in (e.get("tags") or [])}
        domain = str(e.get("domain") or "").lower()
        if domain and domain not in {"markets", "market", ""}:
            if "markets" not in tags and "paper_trading" not in tags:
                continue
        text = str(e.get("lessons") or e.get("lesson") or e.get("title") or "")[:300]
        if not text:
            continue
        rows.append(
            {
                "source": "experience",
                "symbol": None,
                "status": "lesson",
                "text": text,
                "at": e.get("created_at") or e.get("occurred_at"),
                "id": e.get("id") or e.get("ref_id"),
                "llm": False,
            }
        )
    return rows[:max_n]


def structure_layers(
    episodic: list[dict[str, Any]],
) -> dict[str, Any]:
    """Deterministic semantic concept stubs + procedural tip stubs (no invented prose)."""
    by_status = Counter(str(r.get("status") or "unknown") for r in episodic)
    by_symbol = Counter(
        str(r.get("symbol")) for r in episodic if r.get("symbol")
    )
    concepts: list[dict[str, Any]] = []
    for status, n in by_status.most_common(12):
        examples = [
            r for r in episodic if str(r.get("status") or "") == status
        ][:3]
        concepts.append(
            {
                "id": f"concept:{status}",
                "kind": "semantic",
                "label": status,
                "count": n,
                "statement": None,  # LLM may fill
                "examples": [
                    {
                        "symbol": e.get("symbol"),
                        "text": e.get("text"),
                        "source": e.get("source"),
                    }
                    for e in examples
                ],
                "provenance": [e.get("id") or e.get("source") for e in examples],
            }
        )
    for sym, n in by_symbol.most_common(10):
        examples = [r for r in episodic if r.get("symbol") == sym][:3]
        concepts.append(
            {
                "id": f"concept:symbol:{sym}",
                "kind": "semantic",
                "label": f"symbol:{sym}",
                "count": n,
                "statement": None,
                "examples": [
                    {"symbol": sym, "text": e.get("text"), "source": e.get("source")}
                    for e in examples
                ],
                "provenance": [e.get("source") for e in examples],
            }
        )

    procedures: list[dict[str, Any]] = []
    # Procedural tips from status patterns (structural only until LLM)
    if by_status.get("weakened") or by_status.get("falsified"):
        procedures.append(
            {
                "id": "proc:recheck_falsifiers",
                "kind": "procedural",
                "tip": None,
                "rule_stub": (
                    "When beliefs weaken or falsify, re-check falsifiers before adding size"
                ),
                "count": int(by_status.get("weakened") or 0)
                + int(by_status.get("falsified") or 0),
                "advice_only": True,
            }
        )
    if by_status.get("strengthened"):
        procedures.append(
            {
                "id": "proc:evidence_before_size",
                "kind": "procedural",
                "tip": None,
                "rule_stub": (
                    "Strengthened beliefs still need cited evidence before size-up "
                    "(advice-only)"
                ),
                "count": int(by_status.get("strengthened") or 0),
                "advice_only": True,
            }
        )
    if not procedures and episodic:
        procedures.append(
            {
                "id": "proc:keep_logging",
                "kind": "procedural",
                "tip": None,
                "rule_stub": "Keep logging revisions — distill needs sample growth",
                "count": len(episodic),
                "advice_only": True,
            }
        )

    return {
        "concepts": concepts[:24],
        "procedures": procedures[:12],
        "status_counts": dict(by_status),
        "symbol_counts": dict(by_symbol.most_common(20)),
        "episodic_n": len(episodic),
    }


def _apply_llm_text(
    layers: dict[str, Any],
    *,
    llm: Any | None,
) -> tuple[dict[str, Any], str | None]:
    """Optional budgeted LLM fill of concept statements / procedure tips."""
    if llm is None:
        return layers, "MEM.1 skipped LLM — structural layers only"
    try:
        if hasattr(llm, "lane_busy") and llm.lane_busy():
            return layers, "MEM.1 deferred — LLM lane busy"
    except Exception:  # noqa: BLE001
        pass

    prompt = {
        "task": "memory_distill",
        "concepts": [
            {
                "id": c.get("id"),
                "label": c.get("label"),
                "count": c.get("count"),
                "examples": c.get("examples"),
            }
            for c in (layers.get("concepts") or [])[:12]
        ],
        "procedures": [
            {
                "id": p.get("id"),
                "rule_stub": p.get("rule_stub"),
                "count": p.get("count"),
            }
            for p in (layers.get("procedures") or [])[:8]
        ],
        "instructions": (
            "Return JSON with keys: concepts (list of {id, statement}), "
            "procedures (list of {id, tip}). "
            "One short sentence each. Do not invent PE/FCF/prices. "
            "Advice-only — no auto size commands."
        ),
    }
    try:
        client = llm.for_role("researcher") if hasattr(llm, "for_role") else llm
        messages = [
            {
                "role": "system",
                "content": (
                    "You are Atlas's memory cortex. Distill episodic revisions into "
                    "semantic concepts and procedural tips. One JSON object only."
                ),
            },
            {"role": "user", "content": json.dumps(prompt, default=str)},
        ]
        resp = client.chat(messages)
        text = getattr(resp, "text", None) or getattr(resp, "content", None) or str(resp)
    except Exception as exc:  # noqa: BLE001
        return layers, f"MEM.1 LLM failed: {type(exc).__name__}"

    parsed = _parse_json_blob(str(text))
    if not parsed:
        return layers, "MEM.1 LLM returned non-JSON"

    by_c = {
        str(c.get("id")): str(c.get("statement") or "")[:400]
        for c in (parsed.get("concepts") or [])
        if isinstance(c, dict) and c.get("id")
    }
    by_p = {
        str(p.get("id")): str(p.get("tip") or "")[:400]
        for p in (parsed.get("procedures") or [])
        if isinstance(p, dict) and p.get("id")
    }
    out = dict(layers)
    concepts = []
    for c in layers.get("concepts") or []:
        c2 = dict(c)
        if c2.get("id") in by_c and by_c[c2["id"]]:
            c2["statement"] = by_c[c2["id"]]
        concepts.append(c2)
    procedures = []
    for p in layers.get("procedures") or []:
        p2 = dict(p)
        if p2.get("id") in by_p and by_p[p2["id"]]:
            p2["tip"] = by_p[p2["id"]]
        procedures.append(p2)
    out["concepts"] = concepts
    out["procedures"] = procedures
    return out, None


def run_memory_distill(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    wsos: list[dict[str, Any]] | None = None,
    experiences: list[dict[str, Any]] | None = None,
    llm: Any | None = None,
    allow_llm: bool = False,
) -> dict[str, Any]:
    """Batch distill episodic → semantic concepts + procedural tips."""
    lab = laboratory_id or "india_equity_learner"
    rows = list(wsos) if wsos is not None else (
        list_lab_wsos(data_dir, lab) if data_dir else []
    )
    gw = load_global_wso(data_dir, lab) if data_dir else None
    episodic = collect_episodic(wsos=rows, experiences=experiences, global_wso=gw)
    layers = structure_layers(episodic)
    skip = None
    llm_used = False
    if allow_llm and llm is not None and int(layers.get("episodic_n") or 0) > 0:
        layers, skip = _apply_llm_text(layers, llm=llm)
        llm_used = skip is None
    elif allow_llm and llm is None:
        skip = "MEM.1 skipped LLM — no LLM bound"
    elif int(layers.get("episodic_n") or 0) == 0:
        skip = "MEM.1 empty — no episodic revisions/experiences yet"

    doc = {
        "version": VERSION,
        "laboratory_id": lab,
        "created_at": _now(),
        "status": "done" if layers.get("episodic_n") else "empty",
        "skip_reason": skip,
        "llm": llm_used,
        "advice_only": True,
        "enable_soft_bias": False,
        "concepts": layers.get("concepts") or [],
        "procedures": layers.get("procedures") or [],
        "status_counts": layers.get("status_counts") or {},
        "symbol_counts": layers.get("symbol_counts") or {},
        "episodic_n": layers.get("episodic_n") or 0,
        "nightly_cap_reference": DEFAULT_NIGHTLY_LLM_PASSES,
        "distill_llm_passes": DEFAULT_DISTILL_LLM_PASSES,
    }
    if data_dir:
        save_distill(data_dir, doc)
    return doc


def format_memory_distill_section(doc: dict[str, Any] | None) -> list[str]:
    """Evening lines for MEM.1."""
    if not isinstance(doc, dict):
        return []
    lines = ["", "--- Memory distill (MEM.1) ---"]
    n = int(doc.get("episodic_n") or 0)
    lines.append(
        f"episodic={n} · concepts={len(doc.get('concepts') or [])} · "
        f"procedures={len(doc.get('procedures') or [])} · "
        f"advice_only={bool(doc.get('advice_only', True))}"
    )
    if doc.get("skip_reason") and doc.get("status") in {"empty", "skipped"}:
        lines.append(f"  {doc.get('skip_reason')}")
    # Prefer LLM statements; else show structural labels
    shown = 0
    for c in list(doc.get("concepts") or [])[:5]:
        if not isinstance(c, dict):
            continue
        stmt = str(c.get("statement") or "").strip()
        if stmt:
            lines.append(f"  concept · {c.get('label')}: {stmt[:140]}")
            shown += 1
        elif c.get("label") and int(c.get("count") or 0) >= 2:
            lines.append(
                f"  concept · {c.get('label')} ×{c.get('count')} "
                f"(structural — awaiting LLM statement)"
            )
            shown += 1
    for p in list(doc.get("procedures") or [])[:4]:
        if not isinstance(p, dict):
            continue
        tip = str(p.get("tip") or p.get("rule_stub") or "").strip()
        if tip:
            lines.append(f"  procedure · {tip[:160]}")
            shown += 1
    if shown == 0 and n == 0:
        lines.append("  No episodic material to distill yet.")
    return lines
