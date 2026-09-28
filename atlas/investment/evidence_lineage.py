"""OI-MDPH0 Phase 6 — Evidence lineage stubs on decisions.

decision → prediction → ACP → evidence IDs → observations → source/as_of/provider

Does not invent evidence. Strengthens provenance before minting more L5s.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

VERSION = "learn.evidence_lineage.v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ref_id(ref: Any) -> str | None:
    if isinstance(ref, str) and ref.strip():
        return ref.strip()[:120]
    if isinstance(ref, dict):
        for k in ("id", "evidence_id", "observation_id", "uri", "path"):
            v = ref.get(k)
            if v:
                return str(v)[:120]
    return None


def _source_meta(ref: Any) -> dict[str, Any] | None:
    if not isinstance(ref, dict):
        return None
    out = {
        "source": ref.get("source") or ref.get("provider") or ref.get("kind"),
        "provider": ref.get("provider"),
        "as_of": ref.get("as_of") or ref.get("as_of_ist") or ref.get("ts"),
        "timestamp": ref.get("timestamp") or ref.get("received_at") or ref.get("ts"),
        "id": _ref_id(ref),
    }
    if not any(out.get(k) for k in ("source", "provider", "id")):
        return None
    return out


def build_evidence_lineage(
    *,
    decision_id: str | None = None,
    prediction: dict[str, Any] | None = None,
    acp_id: str | None = None,
    evidence_refs: list[Any] | None = None,
    observation_ids: list[str] | None = None,
    market_snapshot: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compact genealogy block for a decision packet / ACP."""
    refs = list(evidence_refs or [])
    obs = [str(x) for x in (observation_ids or []) if x]
    evidence_ids = [eid for eid in (_ref_id(r) for r in refs) if eid]
    sources = [s for s in (_source_meta(r) for r in refs) if s]
    snap = market_snapshot if isinstance(market_snapshot, dict) else {}
    prov = snap.get("observation_provenance") if isinstance(snap.get("observation_provenance"), dict) else {}
    if prov:
        sources.append(
            {
                "source": prov.get("source") or "market",
                "provider": prov.get("provider"),
                "as_of": prov.get("as_of") or snap.get("as_of"),
                "timestamp": prov.get("received_at") or prov.get("timestamp"),
                "id": prov.get("id"),
            }
        )
    pred = prediction if isinstance(prediction, dict) else None
    lineage = {
        "version": VERSION,
        "decision_id": decision_id,
        "prediction": {
            "status": (pred or {}).get("prediction_status") or (pred or {}).get("status"),
            "thesis_id": (pred or {}).get("thesis_id"),
            "return_band": (pred or {}).get("return_band"),
        }
        if pred
        else None,
        "acp_id": acp_id,
        "evidence_ids": evidence_ids[:40],
        "observation_ids": obs[:40],
        "sources": sources[:40],
        "recorded_at": _now_iso(),
        "completeness": (
            "strong"
            if (evidence_ids or obs) and sources
            else ("partial" if (evidence_ids or obs or sources) else "weak")
        ),
        "honesty": (
            "Lineage cites what was attached at decide-time. "
            "Missing IDs stay missing — never invent provenance."
        ),
    }
    if isinstance(extra, dict):
        for k, v in extra.items():
            if v is not None and k not in lineage:
                lineage[k] = v
    return lineage


def stamp_packet_lineage(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach ``evidence_lineage`` onto a decision-packet payload (in place)."""
    if not isinstance(payload, dict):
        return payload
    pred = payload.get("expected") if isinstance(payload.get("expected"), dict) else None
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    lineage = build_evidence_lineage(
        decision_id=str(payload.get("decision_id") or "") or None,
        prediction=pred,
        acp_id=(meta.get("acp_id") if isinstance(meta, dict) else None)
        or payload.get("acp_id"),
        evidence_refs=list(payload.get("evidence_refs") or []),
        observation_ids=list(payload.get("observation_ids") or []),
        market_snapshot=payload.get("market_snapshot")
        if isinstance(payload.get("market_snapshot"), dict)
        else None,
    )
    payload["evidence_lineage"] = lineage
    return payload
