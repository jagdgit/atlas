"""BRE.2 — budgeted LLM belief revision (semantic beliefs = LLM only).

Deterministic code may skip / store structure; only LLM may author thesis_text
and belief notes (§1.7). Citation validation drops uncited claims.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from atlas.investment.cognitive_budget import (
    DEFAULT_NIGHTLY_LLM_PASSES,
    budget_for_wso,
    pick_budgeted,
)
from atlas.investment.world_state import append_revision, save_wso

_log = logging.getLogger("atlas.investment.belief_revision")

VERSION = "bre2.revision.v1"

_JSON_RE = re.compile(r"\{[\s\S]*\}")


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


def _allowed_evidence_ids(wso: dict[str, Any], extra_ids: list[str] | None) -> set[str]:
    ids = {str(x) for x in (wso.get("evidence_ids") or []) if x}
    for x in extra_ids or []:
        if x:
            ids.add(str(x))
    return ids


def _filter_cited(
    claims: list[Any], allowed: set[str]
) -> tuple[list[Any], list[str]]:
    """Keep claim objects that cite at least one allowed id (or mark assumption)."""
    kept: list[Any] = []
    rejected: list[str] = []
    for c in claims or []:
        if isinstance(c, str):
            # bare string without citation → assumption tag
            kept.append({"text": c, "assumption": True, "evidence_ids": []})
            continue
        if not isinstance(c, dict):
            continue
        cites = [str(x) for x in (c.get("evidence_ids") or c.get("citations") or []) if x]
        if not cites:
            c2 = dict(c)
            c2["assumption"] = True
            kept.append(c2)
            continue
        if allowed and not any(x in allowed for x in cites):
            rejected.append(str(c.get("text") or c.get("claim") or cites)[:80])
            continue
        kept.append(c)
    return kept, rejected


def revise_one_wso(
    wso: dict[str, Any],
    *,
    llm: Any | None,
    evidence_delta: dict[str, Any] | None,
    extra_evidence_ids: list[str] | None = None,
    data_dir: str | None = None,
    skip_reason: str | None = None,
) -> dict[str, Any]:
    """Revise a single WSO. Mutates and optionally persists."""
    doc = dict(wso)
    delta = evidence_delta if isinstance(evidence_delta, dict) else {}
    material = bool(delta.get("material"))

    if skip_reason:
        append_revision(
            doc,
            status="unchanged",
            reason=skip_reason[:500],
            evidence_delta=delta,
            llm=False,
        )
        if data_dir:
            save_wso(data_dir, doc)
        return doc

    if not material:
        append_revision(
            doc,
            status="unchanged",
            reason="no material evidence delta — belief revision not expected",
            evidence_delta=delta,
            llm=False,
        )
        if data_dir:
            save_wso(data_dir, doc)
        return doc

    if llm is None:
        append_revision(
            doc,
            status="unreviewed",
            reason="LLM_UNAVAILABLE — BRE.2 not run (not belief unchanged)",
            evidence_delta=delta,
            llm=False,
        )
        if data_dir:
            save_wso(data_dir, doc)
        return doc

    # Lane busy → defer
    try:
        if hasattr(llm, "lane_busy") and llm.lane_busy():
            append_revision(
                doc,
                status="unreviewed",
                reason="LLM_UNAVAILABLE — lane busy; reschedule BRE.2",
                evidence_delta=delta,
                llm=False,
            )
            if data_dir:
                save_wso(data_dir, doc)
            return doc
    except Exception:  # noqa: BLE001
        pass

    allowed = _allowed_evidence_ids(doc, extra_evidence_ids)
    prompt = {
        "task": "belief_revision",
        "symbol": doc.get("symbol"),
        "prior_thesis": doc.get("thesis_text") or "",
        "prior_beliefs": doc.get("beliefs") or {},
        "unknowns": doc.get("unknowns") or [],
        "uncertainty": doc.get("uncertainty") or {},
        "evidence_delta": delta,
        "allowed_evidence_ids": sorted(allowed)[:40],
        "instructions": (
            "Return JSON only with keys: status "
            "(strengthened|weakened|unchanged|falsified|insufficient_evidence), "
            "thesis_text, thesis_strength (0-10 or null), "
            "beliefs (object name->{confidence:0-1, note, evidence_ids[]}), "
            "falsifiers (list), unknowns (list), reason, "
            "claims (list of {text, evidence_ids[]}). "
            "Every factual claim must cite allowed_evidence_ids or be marked assumption. "
            "Never invent PE/FCF/prices. Unknown stays unknown."
        ),
    }
    try:
        client = llm.for_role("researcher") if hasattr(llm, "for_role") else llm
        messages = [
            {
                "role": "system",
                "content": (
                    "You are Atlas's investment cortex. Revise beliefs only from evidence. "
                    "Respond with a single JSON object."
                ),
            },
            {"role": "user", "content": json.dumps(prompt, default=str)},
        ]
        resp = client.chat(messages)
        text = getattr(resp, "text", None) or getattr(resp, "content", None) or str(resp)
    except Exception as exc:  # noqa: BLE001
        append_revision(
            doc,
            status="unreviewed",
            reason=f"LLM_UNAVAILABLE — BRE.2 LLM failed: {type(exc).__name__}",
            evidence_delta=delta,
            llm=False,
        )
        if data_dir:
            save_wso(data_dir, doc)
        return doc

    parsed = _parse_json_blob(str(text))
    if not parsed:
        append_revision(
            doc,
            status="unreviewed",
            reason="LLM_UNAVAILABLE — BRE.2 returned non-JSON (not belief unchanged)",
            evidence_delta=delta,
            llm=True,
        )
        if data_dir:
            save_wso(data_dir, doc)
        return doc

    fund_row: dict[str, Any] | None = None
    if data_dir and doc.get("symbol"):
        try:
            from atlas.investment.fundamentals import get_symbol as fund_get

            fund_row = fund_get(data_dir, str(doc.get("symbol")), program_id="market_intelligence")
        except Exception:  # noqa: BLE001
            fund_row = None
    try:
        from atlas.investment.research_intelligence import gate_belief_revision_output

        gated = gate_belief_revision_output(
            parsed, allowed, fundamentals=fund_row if isinstance(fund_row, dict) else None
        )
        parsed = gated.get("parsed") or parsed
        if gated.get("rejected"):
            doc.setdefault("verification", {})["rejected_claims"] = list(gated.get("rejected") or [])[:12]
    except Exception:  # noqa: BLE001
        _log.debug("belief verify gate skipped", exc_info=True)

    claims, rejected = _filter_cited(list(parsed.get("claims") or []), allowed)
    status = str(parsed.get("status") or "unchanged").strip().lower()
    if status not in {
        "strengthened",
        "weakened",
        "unchanged",
        "falsified",
        "insufficient_evidence",
    }:
        status = "unchanged"

    # Apply semantic fields (LLM-authored)
    thesis = str(parsed.get("thesis_text") or "").strip()
    if thesis and str(parsed.get("status") or "") != "insufficient_evidence":
        doc["thesis_text"] = thesis[:2000]
    ts = parsed.get("thesis_strength")
    try:
        if ts is not None:
            doc["thesis_strength"] = max(0.0, min(10.0, float(ts)))
    except (TypeError, ValueError):
        pass

    beliefs_in = parsed.get("beliefs") if isinstance(parsed.get("beliefs"), dict) else {}
    beliefs_out: dict[str, Any] = dict(doc.get("beliefs") or {})
    for name, meta in beliefs_in.items():
        if not isinstance(meta, dict):
            continue
        cites = [str(x) for x in (meta.get("evidence_ids") or []) if x]
        if cites and allowed and not any(c in allowed for c in cites):
            rejected.append(f"belief:{name}")
            continue
        note = str(meta.get("note") or "").strip()
        conf = meta.get("confidence")
        try:
            conf_f = float(conf) if conf is not None else None
        except (TypeError, ValueError):
            conf_f = None
        beliefs_out[str(name)] = {
            "confidence": conf_f,
            "note": note[:500],
            "evidence_ids": cites[:8],
            "assumption": bool(meta.get("assumption")) or not cites,
        }
    doc["beliefs"] = beliefs_out

    if isinstance(parsed.get("falsifiers"), list):
        doc["falsifiers"] = [str(x)[:200] for x in parsed["falsifiers"] if x][:12]
    if isinstance(parsed.get("unknowns"), list):
        doc["unknowns"] = [str(x)[:80] for x in parsed["unknowns"] if x][:40]

    reason = str(parsed.get("reason") or status)[:500]
    if rejected:
        reason = f"{reason} (dropped {len(rejected)} uncited claims)"
    append_revision(
        doc,
        status=status,
        reason=reason,
        evidence_delta={
            **delta,
            "claims_kept": len(claims),
            "claims_rejected": len(rejected),
        },
        llm=True,
    )
    if data_dir:
        save_wso(data_dir, doc)
    return doc


def revise_beliefs_budgeted(
    wsos: list[dict[str, Any]] | None,
    *,
    evidence_delta: dict[str, Any] | None,
    llm: Any | None = None,
    data_dir: str | None = None,
    max_passes: int = DEFAULT_NIGHTLY_LLM_PASSES,
    extra_evidence_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """BRE.2 nightly: budgeted revise across open-book WSOs."""
    delta = evidence_delta if isinstance(evidence_delta, dict) else {}
    material = bool(delta.get("material"))
    prepared: list[dict[str, Any]] = []
    for w in wsos or []:
        if not isinstance(w, dict):
            continue
        bud = budget_for_wso(w, is_open_position=True, has_material_delta=material)
        item = {"wso": w, "llm_budget": int(bud.get("llm_budget") or 0), "budget": bud}
        prepared.append(item)

    if not material:
        out: list[dict[str, Any]] = []
        for it in prepared:
            out.append(
                revise_one_wso(
                    it["wso"],
                    llm=None,
                    evidence_delta=delta,
                    data_dir=data_dir,
                    skip_reason="no material evidence delta — belief revision not expected",
                )
            )
        return out

    # Always allow at least structural pass recording; LLM only for budgeted
    chosen = pick_budgeted(prepared, max_passes=max_passes)
    chosen_syms = {str((c.get("wso") or {}).get("symbol")) for c in chosen}
    out = []
    for it in prepared:
        w = it["wso"]
        sym = str(w.get("symbol") or "")
        if sym in chosen_syms and int(it.get("llm_budget") or 0) > 0 and llm is not None:
            out.append(
                revise_one_wso(
                    w,
                    llm=llm,
                    evidence_delta=delta,
                    extra_evidence_ids=extra_evidence_ids,
                    data_dir=data_dir,
                )
            )
        elif llm is None:
            out.append(
                revise_one_wso(
                    w,
                    llm=None,
                    evidence_delta=delta,
                    data_dir=data_dir,
                    skip_reason="BRE.2 skipped — no LLM (deterministic Represent only)",
                )
            )
        else:
            out.append(
                revise_one_wso(
                    w,
                    llm=None,
                    evidence_delta=delta,
                    data_dir=data_dir,
                    skip_reason="below cognitive budget tonight — no LLM pass",
                )
            )
    return out
