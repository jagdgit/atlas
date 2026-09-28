"""M4 Step 4 — publish deterministic fundamental summaries as findings + embeddings.

Narrow slice: HBLPOWER + TATACHEM only until the bridge is proven.
Does not parse raw XBRL. Does not call the chat LLM. Does not dump trades.
When canonical state changes, the previous finding is superseded (new vector).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from atlas.investment.fundamental_summary import (
    CLAIM_TYPE,
    VERSION,
    build_fundamental_summary,
)
from atlas.investment.fundamentals import get_symbol, normalize_symbol
from atlas.knowledge.lifecycle import finding_identity_key

_log = logging.getLogger("atlas.investment.fundamental_knowledge")

DEFAULT_SLICE_SYMBOLS = ("HBLPOWER.NS", "TATACHEM.NS")


def _finding_id(row: dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return ""
    return str(row.get("id") or row.get("finding_id") or "")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _embed(knowledge: Any, emb: Any, row: dict[str, Any]) -> dict[str, Any]:
    statement = str(row.get("statement") or "")
    fid = _finding_id(row)
    model = getattr(knowledge, "_model", None) or "default"
    vector = None
    try:
        vector = knowledge._query_vector(statement)
    except Exception:  # noqa: BLE001
        vector = None
    if not vector:
        try:
            vector = list(knowledge._llm.embed([statement]).vectors[0])
        except Exception:  # noqa: BLE001
            vector = None
    if emb is None or not vector or not fid:
        return {"ok": False, "reason": "embed_unavailable", "model": model}
    try:
        if hasattr(emb, "meta") and isinstance(emb.meta, dict):
            emb.meta[fid] = {
                **row,
                "finding_id": fid,
                "status": row.get("status") or "active",
                "domain": row.get("domain") or "research",
                "statement": statement,
            }
        emb.upsert(fid, model, vector)
    except Exception as exc:  # noqa: BLE001
        _log.warning("fundamental summary embed failed for %s: %s", fid, exc)
        return {"ok": False, "reason": "embed_failed", "model": model}
    return {"ok": True, "model": model, "finding_id": fid}


def _mark_superseded(emb: Any, previous: dict[str, Any], successor_id: str) -> None:
    old_id = _finding_id(previous)
    if not old_id:
        return
    if hasattr(emb, "meta") and isinstance(emb.meta, dict) and old_id in emb.meta:
        meta = dict(emb.meta[old_id])
        meta["status"] = "superseded"
        meta["superseded_by"] = successor_id
        emb.meta[old_id] = meta


def publish_symbol(
    knowledge: Any,
    data_dir: str | None,
    symbol: str,
    *,
    findings: Any | None = None,
    finding_embeddings: Any | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Create or supersede one fundamental_summary finding from the store row."""
    findings = findings if findings is not None else getattr(knowledge, "_findings", None)
    emb = (
        finding_embeddings
        if finding_embeddings is not None
        else getattr(knowledge, "_finding_embeddings", None)
    )
    sym = normalize_symbol(symbol)
    row = get_symbol(data_dir, symbol) if data_dir else None
    if not row:
        return {"ok": False, "symbol": sym, "reason": "not_in_store"}
    summary = build_fundamental_summary(row, data_dir=data_dir)
    value = dict(summary["value"])
    stamp = generated_at or _now()
    identity = finding_identity_key(
        {
            "claim_type": CLAIM_TYPE,
            "domain": "research",
            "value": value,
            "statement": summary["statement"],
        }
    )
    provenance = {
        "kind": CLAIM_TYPE,
        "version": VERSION,
        "symbol": value.get("symbol"),
        "fundamental_as_of": value.get("fundamental_as_of"),
        "evidence_as_of": value.get("evidence_as_of"),
        "canonical_filing_id": value.get("canonical_filing_id"),
        "source": value.get("source"),
        "raw_evidence_id": [value.get("canonical_filing_id")]
        if value.get("canonical_filing_id")
        else [],
        "calculation_id": sorted(
            {
                m.get("calculation_id")
                for m in (value.get("metrics") or {}).values()
                if isinstance(m, dict) and m.get("calculation_id")
            }
        ),
        "generated_at": stamp,
        "knowledge_status": value.get("knowledge_status"),
        "conflicts": value.get("conflicts") or [],
        "snapshot_fingerprint": summary["fingerprint"],
        "llm_not_used": True,
        "not_a_trade": True,
        "not_raw_xbrl": True,
    }
    payload = {
        "statement": summary["statement"],
        "value": value,
        "claim_type": CLAIM_TYPE,
        "domain": "research",
        "status": "active",
        "confidence": "HIGH",
        "provenance": provenance,
        "identity_key": list(identity),
        "valid_from": value.get("evidence_as_of"),
    }
    existing = None
    if findings is not None and hasattr(findings, "find_active_by_identity"):
        try:
            existing = findings.find_active_by_identity(identity)
        except Exception:  # noqa: BLE001
            existing = None
    if isinstance(existing, dict):
        prev_fp = ((existing.get("provenance") or {}) if isinstance(existing.get("provenance"), dict) else {}).get(
            "snapshot_fingerprint"
        )
        if prev_fp == summary["fingerprint"]:
            embedded = _embed(knowledge, emb, existing)
            return {
                "ok": True,
                "symbol": sym,
                "action": "unchanged",
                "finding_id": _finding_id(existing),
                "canonical_id": existing.get("canonical_id"),
                "fingerprint": summary["fingerprint"],
                "embed": embedded,
                "plc_a_state": value.get("plc_a_state"),
                "knowledge_status": value.get("knowledge_status"),
            }
        if hasattr(findings, "append_revision"):
            created = findings.append_revision(existing, payload)
            _mark_superseded(emb, existing, _finding_id(created))
            embedded = _embed(knowledge, emb, created)
            return {
                "ok": True,
                "symbol": sym,
                "action": "superseded",
                "finding_id": _finding_id(created),
                "previous_id": _finding_id(existing),
                "canonical_id": created.get("canonical_id"),
                "fingerprint": summary["fingerprint"],
                "embed": embedded,
                "plc_a_state": value.get("plc_a_state"),
                "knowledge_status": value.get("knowledge_status"),
            }
    if findings is None or not hasattr(findings, "create"):
        return {"ok": False, "symbol": sym, "reason": "findings_unavailable"}
    created = findings.create(
        summary["statement"],
        value=value,
        claim_type=CLAIM_TYPE,
        domain="research",
        status="active",
        confidence="HIGH",
        maturity="verified",
        provenance=provenance,
        identity_key=list(identity),
        valid_from=value.get("evidence_as_of"),
    )
    embedded = _embed(knowledge, emb, created)
    return {
        "ok": True,
        "symbol": sym,
        "action": "created",
        "finding_id": _finding_id(created),
        "canonical_id": created.get("canonical_id") if isinstance(created, dict) else None,
        "fingerprint": summary["fingerprint"],
        "embed": embedded,
        "plc_a_state": value.get("plc_a_state"),
        "knowledge_status": value.get("knowledge_status"),
    }


def run_tick(
    knowledge: Any,
    data_dir: str | None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Scheduler entry: publish the locked two-symbol slice (or payload.symbols)."""
    raw = (payload or {}).get("symbols") if isinstance(payload, dict) else None
    symbols = tuple(raw) if isinstance(raw, (list, tuple)) and raw else DEFAULT_SLICE_SYMBOLS
    results = [
        publish_symbol(knowledge, data_dir, str(sym))
        for sym in symbols
        if str(sym).strip()
    ]
    return {
        "ok": all(r.get("ok") for r in results) if results else False,
        "version": VERSION,
        "symbols": list(symbols),
        "results": results,
        "llm_not_used": True,
        "ranking_unchanged": True,
    }
