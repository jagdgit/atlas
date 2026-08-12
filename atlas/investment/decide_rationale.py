"""BRE.3 / OI-LLM-OS0 — Decide-time async LLM rationale (never blocks fills).

At material buy/sell freeze: mark ``meta.llm_pending`` and enqueue a sidecar job.
Drain under Cognitive Budget when the LLM lane is free. Packets stay immutable —
semantic rationale / falsifiers live only in the sidecar.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from atlas.investment.cognitive_budget import (
    DEFAULT_NIGHTLY_LLM_PASSES,
    pick_budgeted,
    score_dimensions,
)

_log = logging.getLogger("atlas.investment.decide_rationale")
VERSION = "bre3.decide_rationale.v1"
STORE_REL = Path("investment") / "decide_rationale"

# Decide-window slice (shares nightly spirit; leave headroom for BRE.2)
DEFAULT_DECIDE_LLM_PASSES = 2

_JSON_RE = re.compile(r"\{[\s\S]*\}")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_^." else "_" for c in (s or ""))


def store_dir(data_dir: str | Path, *, laboratory_id: str) -> Path:
    from atlas.investment.laboratory import normalize_laboratory_id

    lab = normalize_laboratory_id(laboratory_id=laboratory_id)
    return Path(data_dir) / STORE_REL / _safe(lab)


def _by_id_dir(data_dir: str | Path, laboratory_id: str) -> Path:
    d = store_dir(data_dir, laboratory_id=laboratory_id) / "by_id"
    d.mkdir(parents=True, exist_ok=True)
    return d


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


def budget_for_decision(
    *,
    action: str,
    unknowns: list[Any] | None = None,
    is_open_book: bool = True,
) -> dict[str, Any]:
    """Heuristic decide-time budget (buy/sell high; holds low)."""
    act = str(action or "").lower()
    unk = list(unknowns or [])
    if act in {"buy", "sell"}:
        importance = "high" if is_open_book or act == "buy" else "medium"
        novelty = "high" if unk else "medium"
        uncertainty = "high" if len(unk) >= 3 else ("medium" if unk else "low")
    else:
        importance = "low"
        novelty = "low"
        uncertainty = "medium" if unk else "low"
    return score_dimensions(
        importance=importance, novelty=novelty, uncertainty=uncertainty
    )


def packet_summary(packet: dict[str, Any] | None) -> dict[str, Any]:
    """Compact frozen facts for the LLM prompt (no rewrite of packet)."""
    p = packet if isinstance(packet, dict) else {}
    return {
        "decision_id": p.get("decision_id"),
        "symbol": p.get("symbol"),
        "action": p.get("action"),
        "strategy_tag": p.get("strategy_tag"),
        "reasons_for": list(p.get("reasons_for") or [])[:6],
        "reasons_against": list(p.get("reasons_against") or [])[:6],
        "unknowns": list(p.get("unknowns") or [])[:12],
        "observation_ids": list(p.get("observation_ids") or [])[:20],
        "evidence_refs": list(p.get("evidence_refs") or [])[:12],
        "prices": p.get("prices") if isinstance(p.get("prices"), dict) else {},
        "gates": {
            "research_ok": bool((p.get("gates") or {}).get("research")),
            "portfolio_ok": bool((p.get("gates") or {}).get("portfolio")),
        },
        "confidence": (p.get("confidence_breakdown") or {}).get("overall")
        if isinstance(p.get("confidence_breakdown"), dict)
        else None,
    }


def schedule_decide_rationale(
    data_dir: str | Path | None,
    *,
    decision_id: str | None,
    symbol: str,
    action: str,
    laboratory_id: str | None = None,
    portfolio_key: str | None = None,
    packet: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Enqueue async rationale job. Never calls LLM. Idempotent per decision_id."""
    if not data_dir:
        return None
    act = str(action or "").lower()
    if act not in {"buy", "sell"}:
        return None
    did = str(decision_id or "").strip()
    if not did:
        return None
    sym = str(symbol or "").strip()
    if not sym:
        return None
    lab = laboratory_id or portfolio_key or "india_equity_learner"
    path = _by_id_dir(data_dir, lab) / f"{_safe(did)}.json"
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                return existing
        except (OSError, json.JSONDecodeError):
            pass

    summary = packet_summary(packet)
    bud = budget_for_decision(
        action=act,
        unknowns=summary.get("unknowns") or [],
        is_open_book=True,
    )
    row: dict[str, Any] = {
        "version": VERSION,
        "rationale_id": str(uuid4()),
        "decision_id": did,
        "symbol": sym,
        "action": act,
        "laboratory_id": lab,
        "portfolio_key": portfolio_key or lab,
        "status": "pending",
        "created_at": _now(),
        "completed_at": None,
        "llm_budget": int(bud.get("llm_budget") or 0),
        "budget": bud,
        "packet_summary": summary,
        "rationale_text": None,
        "falsifiers": [],
        "expected_outcome": None,
        "evidence_ids": list(summary.get("observation_ids") or [])[:20],
        "skip_reason": None,
        "llm": False,
    }
    try:
        path.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        _log.debug("BRE.3 schedule write failed", exc_info=True)
        return None
    row["path"] = str(path)
    return row


def load_rationale(
    data_dir: str | Path | None,
    decision_id: str,
    *,
    laboratory_id: str,
) -> dict[str, Any] | None:
    if not data_dir or not decision_id:
        return None
    path = _by_id_dir(data_dir, laboratory_id) / f"{_safe(decision_id)}.json"
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def list_pending(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    if not data_dir:
        return []
    root = _by_id_dir(data_dir, laboratory_id)
    rows: list[dict[str, Any]] = []
    for p in sorted(root.glob("*.json"), key=lambda x: x.stat().st_mtime):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict):
            continue
        if doc.get("status") not in {"pending", "deferred_lane_busy"}:
            continue
        rows.append(doc)
        if len(rows) >= limit:
            break
    return rows


def _save(data_dir: str | Path, laboratory_id: str, row: dict[str, Any]) -> None:
    did = str(row.get("decision_id") or "")
    if not did:
        return
    path = _by_id_dir(data_dir, laboratory_id) / f"{_safe(did)}.json"
    path.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run_one(
    row: dict[str, Any],
    *,
    llm: Any | None,
    data_dir: str | Path,
    laboratory_id: str,
    skip_reason: str | None = None,
) -> dict[str, Any]:
    doc = dict(row)
    if skip_reason:
        doc["status"] = "skipped_no_budget" if "budget" in skip_reason else "skipped"
        doc["skip_reason"] = skip_reason[:500]
        doc["completed_at"] = _now()
        doc["llm"] = False
        _save(data_dir, laboratory_id, doc)
        return doc

    if llm is None:
        doc["status"] = "skipped"
        doc["skip_reason"] = "BRE.3 skipped — no LLM"
        doc["completed_at"] = _now()
        doc["llm"] = False
        _save(data_dir, laboratory_id, doc)
        return doc

    try:
        if hasattr(llm, "lane_busy") and llm.lane_busy():
            doc["status"] = "deferred_lane_busy"
            doc["skip_reason"] = "BRE.3 deferred — LLM lane busy"
            doc["llm"] = False
            _save(data_dir, laboratory_id, doc)
            return doc
    except Exception:  # noqa: BLE001
        pass

    allowed = {str(x) for x in (doc.get("evidence_ids") or []) if x}
    summary = doc.get("packet_summary") if isinstance(doc.get("packet_summary"), dict) else {}
    prompt = {
        "task": "decide_time_rationale",
        "decision": summary,
        "allowed_evidence_ids": sorted(allowed)[:40],
        "instructions": (
            "Return JSON only with keys: rationale_text (1-3 sentences), "
            "falsifiers (list of strings — what would prove this decision wrong), "
            "expected_outcome (short string or null), "
            "claims (list of {text, evidence_ids[]}). "
            "Do not invent PE/FCF/prices. Unknown stays unknown. "
            "Deterministic reasons_for already frozen — add judgment, do not contradict facts."
        ),
    }
    try:
        client = llm.for_role("researcher") if hasattr(llm, "for_role") else llm
        messages = [
            {
                "role": "system",
                "content": (
                    "You are Atlas's investment cortex at decide-time. "
                    "Write a concise rationale and falsifiers. Respond with one JSON object."
                ),
            },
            {"role": "user", "content": json.dumps(prompt, default=str)},
        ]
        resp = client.chat(messages)
        text = getattr(resp, "text", None) or getattr(resp, "content", None) or str(resp)
    except Exception as exc:  # noqa: BLE001
        doc["status"] = "failed"
        doc["skip_reason"] = f"BRE.3 LLM failed: {type(exc).__name__}"
        doc["completed_at"] = _now()
        doc["llm"] = False
        _save(data_dir, laboratory_id, doc)
        return doc

    parsed = _parse_json_blob(str(text))
    if not parsed:
        doc["status"] = "failed"
        doc["skip_reason"] = "BRE.3 LLM returned non-JSON"
        doc["completed_at"] = _now()
        doc["llm"] = True
        _save(data_dir, laboratory_id, doc)
        return doc

    # Citation filter: drop claims that cite unknown ids (keep assumptions)
    claims_in = list(parsed.get("claims") or [])
    rejected = 0
    for c in claims_in:
        if not isinstance(c, dict):
            continue
        cites = [str(x) for x in (c.get("evidence_ids") or c.get("citations") or []) if x]
        if cites and allowed and not any(x in allowed for x in cites):
            rejected += 1

    rationale = str(parsed.get("rationale_text") or "").strip()[:1200]
    falsifiers = [
        str(x)[:200] for x in (parsed.get("falsifiers") or []) if x
    ][:8]
    expected = parsed.get("expected_outcome")
    if expected is not None:
        expected = str(expected)[:300]

    doc["rationale_text"] = rationale or None
    doc["falsifiers"] = falsifiers
    doc["expected_outcome"] = expected
    doc["status"] = "done" if rationale or falsifiers else "failed"
    doc["skip_reason"] = (
        f"dropped {rejected} uncited claims" if rejected else None
    )
    if doc["status"] == "failed" and not rationale:
        doc["skip_reason"] = "empty rationale and falsifiers"
    doc["completed_at"] = _now()
    doc["llm"] = True
    _save(data_dir, laboratory_id, doc)
    return doc


def drain_pending_rationales(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    llm: Any | None = None,
    max_passes: int = DEFAULT_DECIDE_LLM_PASSES,
    limit: int = 20,
) -> dict[str, Any]:
    """Drain pending decide-time rationale jobs under Cognitive Budget."""
    pending = list_pending(data_dir, laboratory_id=laboratory_id, limit=limit)
    prepared: list[dict[str, Any]] = []
    for row in pending:
        prepared.append(
            {
                "row": row,
                "llm_budget": int(row.get("llm_budget") or 0),
            }
        )
    chosen = pick_budgeted(prepared, max_passes=max_passes)
    chosen_ids = {str((c.get("row") or {}).get("decision_id")) for c in chosen}

    done = 0
    deferred = 0
    skipped = 0
    failed = 0
    updated: list[dict[str, Any]] = []

    if not data_dir:
        return {
            "version": VERSION,
            "done": 0,
            "deferred": 0,
            "skipped": 0,
            "failed": 0,
            "pending": 0,
            "rows": [],
        }

    for it in prepared:
        row = it["row"]
        did = str(row.get("decision_id") or "")
        if did in chosen_ids and int(it.get("llm_budget") or 0) > 0 and llm is not None:
            out = _run_one(row, llm=llm, data_dir=data_dir, laboratory_id=laboratory_id)
        elif llm is None:
            out = _run_one(
                row,
                llm=None,
                data_dir=data_dir,
                laboratory_id=laboratory_id,
                skip_reason="BRE.3 skipped — no LLM",
            )
        else:
            out = _run_one(
                row,
                llm=None,
                data_dir=data_dir,
                laboratory_id=laboratory_id,
                skip_reason="below cognitive budget — no decide-time LLM pass",
            )
        st = str(out.get("status") or "")
        if st == "done":
            done += 1
        elif st == "deferred_lane_busy":
            deferred += 1
        elif st == "failed":
            failed += 1
        else:
            skipped += 1
        updated.append(out)

    return {
        "version": VERSION,
        "done": done,
        "deferred": deferred,
        "skipped": skipped,
        "failed": failed,
        "pending": len(list_pending(data_dir, laboratory_id=laboratory_id, limit=limit)),
        "max_passes": max_passes,
        "nightly_cap_reference": DEFAULT_NIGHTLY_LLM_PASSES,
        "rows": updated,
    }


def format_decide_rationale_lines(
    data_dir: str | Path | None,
    packets: list[dict[str, Any]] | None,
    *,
    laboratory_id: str,
) -> list[str]:
    """Evening join: show sidecar rationale next to material packets."""
    lines: list[str] = []
    material = [
        p
        for p in (packets or [])
        if isinstance(p, dict) and str(p.get("action") or "").lower() in {"buy", "sell"}
    ]
    if not material:
        return lines
    lines.append("")
    lines.append("Decide-time rationale (BRE.3):")
    shown = 0
    for p in material[:12]:
        did = str(p.get("decision_id") or "")
        sym = p.get("symbol") or "?"
        act = str(p.get("action") or "?").upper()
        meta = p.get("meta") if isinstance(p.get("meta"), dict) else {}
        row = load_rationale(data_dir, did, laboratory_id=laboratory_id) if did else None
        if row and row.get("status") == "done":
            text = str(row.get("rationale_text") or "").strip()
            bit = text[:140] + ("…" if len(text) > 140 else "") if text else "(empty)"
            lines.append(f"  · {act} {sym}: {bit}")
            fals = list(row.get("falsifiers") or [])[:3]
            if fals:
                lines.append(f"     falsifiers: {'; '.join(str(x) for x in fals)}")
            shown += 1
        elif row and row.get("status") in {"pending", "deferred_lane_busy"}:
            lines.append(f"  · {act} {sym}: llm_pending ({row.get('status')})")
            shown += 1
        elif meta.get("llm_pending"):
            lines.append(f"  · {act} {sym}: llm_pending (queued)")
            shown += 1
        elif row and row.get("skip_reason"):
            lines.append(
                f"  · {act} {sym}: skipped — {str(row.get('skip_reason'))[:80]}"
            )
            shown += 1
    if shown == 0:
        lines.append("  (no material decide-time rationale jobs)")
    return lines
