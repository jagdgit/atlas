"""BRE.3 / OI-LLM-OS0 — Decide-time async LLM rationale (never blocks fills).

At material buy/sell freeze: mark ``meta.llm_pending`` and enqueue a sidecar job.
Drain under Cognitive Budget when the LLM lane is free. Packets stay immutable —
semantic rationale / falsifiers live only in the sidecar.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from atlas.investment.cognitive_budget import (
    DEFAULT_NIGHTLY_LLM_PASSES,
    score_dimensions,
)

_log = logging.getLogger("atlas.investment.decide_rationale")
VERSION = "bre3.decide_rationale.v1"
STORE_REL = Path("investment") / "decide_rationale"

# Decide-window slice (shares nightly spirit; leave headroom for BRE.2)
DEFAULT_DECIDE_LLM_PASSES = 2
_IST = ZoneInfo("Asia/Kolkata")
STALE_STATUS = "skipped_stale"
STALE_REASON = (
    "CLC.R0 skipped_stale — backlog expired; drain today's material buys. "
    "Do not catch up CPU chats."
)
PRE_CLC_STATUS = "skipped_pre_clc"
PRE_CLC_REASON = (
    "CLC.R1 skipped_pre_clc — queued before lesson_refs/no_match stamp; "
    "do not catch up with LLM. Next proof is a new material buy."
)
R1_QUOTA_STATUS = "skipped_r1_quota"
R1_QUOTA_REASON = (
    "CLC.R1 skipped_r1_quota — this laboratory already spent today's "
    "decide-rationale LLM shot(s). Do not catch up wash fills."
)


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


def _ist_today() -> str:
    return datetime.now(_IST).date().isoformat()


def _created_ist_date(created_at: Any) -> str | None:
    raw = str(created_at or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_IST).date().isoformat()
    except (TypeError, ValueError):
        return raw[:10] if len(raw) >= 10 else None


def packet_summary(packet: dict[str, Any] | None) -> dict[str, Any]:
    """Compact frozen facts for the LLM prompt (no rewrite of packet)."""
    p = packet if isinstance(packet, dict) else {}
    bc = p.get("belief_context") if isinstance(p.get("belief_context"), dict) else {}
    lesson_refs = list(p.get("lesson_refs") or bc.get("lesson_refs") or [])[:12]
    experience_refs = list(p.get("experience_refs") or bc.get("experience_refs") or [])[:12]
    no_match = p.get("no_match")
    if no_match is None:
        no_match = bc.get("no_match")
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
        "lesson_refs": [str(x) for x in lesson_refs if x],
        "experience_refs": [str(x) for x in experience_refs if x],
        "no_match": no_match,
        "synthetic": bool(p.get("synthetic")),
        "influence": bc.get("influence") or p.get("influence"),
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
        "lesson_refs": list(summary.get("lesson_refs") or []),
        "experience_refs": list(summary.get("experience_refs") or []),
        "no_match": summary.get("no_match"),
        "synthetic": bool(summary.get("synthetic") or (packet or {}).get("synthetic")),
        "never_orders": True,
        "advice_only": True,
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
    for p in root.glob("*.json"):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict):
            continue
        if doc.get("status") not in {
            "pending",
            "deferred_lane_busy",
            "failed",
        }:
            continue
        if str(doc.get("status") or "") == "failed":
            skip = str(doc.get("skip_reason") or "")
            # Retry transient LLM exceptions only (not permanent empty-packet skips)
            if "AttributeError" not in skip and "failed:" not in skip:
                continue
        rows.append(doc)
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    rows.sort(
        key=lambda r: (
            0
            if str(r.get("action") or "").lower() == "buy"
            else 1
            if str(r.get("action") or "").lower() == "sell"
            else 2
        )
    )
    return rows[: max(0, int(limit))]


def _save(data_dir: str | Path, laboratory_id: str, row: dict[str, Any]) -> None:
    did = str(row.get("decision_id") or "")
    if not did:
        return
    path = _by_id_dir(data_dir, laboratory_id) / f"{_safe(did)}.json"
    try:
        path.write_text(
            json.dumps(row, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        _log.warning(
            "BRE.3 sidecar save failed decision_id=%s lab=%s",
            did,
            laboratory_id,
            exc_info=True,
        )
        raise


def _run_one(
    row: dict[str, Any],
    *,
    llm: Any | None,
    data_dir: str | Path,
    laboratory_id: str,
    skip_reason: str | None = None,
    reasoning: Any | None = None,
) -> dict[str, Any]:
    from atlas.reasoning.cognitive_core import (
        REVIEWED,
        UNREVIEWED,
        evidence_packet_from_decide,
        reason_decide_rationale,
    )

    doc = dict(row)
    if skip_reason:
        doc["status"] = "skipped_no_budget" if "budget" in skip_reason else "skipped"
        doc["skip_reason"] = skip_reason[:500]
        doc["review_status"] = UNREVIEWED
        doc["completed_at"] = _now()
        doc["llm"] = False
        _save(data_dir, laboratory_id, doc)
        return doc

    if reasoning is None and llm is None:
        doc["status"] = "skipped"
        doc["skip_reason"] = "BRE.3 skipped — no LLM"
        doc["review_status"] = UNREVIEWED
        doc["completed_at"] = _now()
        doc["llm"] = False
        _save(data_dir, laboratory_id, doc)
        return doc

    try:
        busy_src = reasoning if reasoning is not None else llm
        lane_llm = getattr(busy_src, "_llm", None) or busy_src
        if hasattr(lane_llm, "lane_busy") and lane_llm.lane_busy():
            doc["status"] = "deferred_lane_busy"
            doc["skip_reason"] = "BRE.3 deferred — LLM lane busy"
            doc["review_status"] = UNREVIEWED
            doc["llm"] = False
            _save(data_dir, laboratory_id, doc)
            return doc
    except Exception:  # noqa: BLE001
        pass

    allowed = {str(x) for x in (doc.get("evidence_ids") or []) if x}
    summary = doc.get("packet_summary") if isinstance(doc.get("packet_summary"), dict) else {}
    from atlas.investment.scientist_packet import build_scientist_packet

    lesson_exps: list[dict[str, Any]] = []
    for ref in list(summary.get("lesson_refs") or doc.get("lesson_refs") or [])[:8]:
        if isinstance(ref, dict):
            lesson_exps.append(
                {
                    "id": ref.get("id") or ref.get("lesson_id"),
                    "lesson": str(ref.get("lesson") or ref.get("id") or "")[:160],
                }
            )
        elif ref:
            lesson_exps.append({"id": str(ref), "lesson": str(ref)[:160]})
    scientist_packet = build_scientist_packet(
        laboratory_id=laboratory_id,
        decision_id=str(doc.get("decision_id") or ""),
        packet_summary=summary,
        evidence_ids=list(allowed),
        unknowns=list(summary.get("unknowns") or doc.get("unknowns") or []),
        experiences=lesson_exps
        or list(summary.get("experience_refs") or doc.get("experience_refs") or []),
    )
    world = None
    synthetic = bool(doc.get("synthetic") or summary.get("synthetic"))
    # NOW #7 — attach durable news/policy/history (empty → explicit unknowns)
    # CLC.R1 synthetic fixture skips live attach so the prompt stays the contract.
    if not synthetic:
        try:
            from atlas.investment.world_evidence import (
                apply_world_to_evidence_packet,
                apply_world_to_scientist_packet,
                attach_world_evidence,
            )

            world = attach_world_evidence(
                data_dir,
                str(doc.get("symbol") or summary.get("symbol") or ""),
                laboratory_id=laboratory_id,
                sector=str(summary.get("sector") or "") or None,
            )
            scientist_packet = apply_world_to_scientist_packet(scientist_packet, world)
            for eid in world.get("evidence_ids") or []:
                if eid:
                    allowed.add(str(eid))
            doc["world_evidence"] = scientist_packet.get("world_evidence")
        except Exception:  # noqa: BLE001
            _log.debug("NOW #7 world evidence attach skipped", exc_info=True)
            world = None

    doc["scientist_packet"] = scientist_packet
    evidence_packet = evidence_packet_from_decide(
        doc, laboratory_id=laboratory_id, scientist_packet=scientist_packet
    )
    if world is not None:
        try:
            evidence_packet = apply_world_to_evidence_packet(evidence_packet, world)
        except Exception:  # noqa: BLE001
            _log.debug("NOW #7 evidence packet world merge skipped", exc_info=True)
    # NOW #9 — belief/experience inheritance (advice-only)
    if not synthetic:
        try:
            from atlas.investment.self_worldview import (
                apply_worldview_to_evidence_packet,
                apply_worldview_to_scientist_packet,
                attach_self_worldview,
            )

            wv = attach_self_worldview(
                reasoning=reasoning,
                data_dir=data_dir,
                symbols=[str(doc.get("symbol") or summary.get("symbol") or "")],
                laboratory_id=laboratory_id,
                query=str(doc.get("action") or "") + " " + str(doc.get("symbol") or ""),
            )
            scientist_packet = apply_worldview_to_scientist_packet(scientist_packet, wv)
            evidence_packet = apply_worldview_to_evidence_packet(evidence_packet, wv)
            doc["scientist_packet"] = scientist_packet
            doc["self_worldview"] = scientist_packet.get("self_worldview")
        except Exception:  # noqa: BLE001
            _log.debug("NOW #9 self worldview skipped", exc_info=True)
    doc["evidence_packet"] = evidence_packet

    try:
        if reasoning is not None and hasattr(reasoning, "reason_decide_rationale"):
            advice = reasoning.reason_decide_rationale(
                packet=evidence_packet,
                doc=doc,
                laboratory_id=laboratory_id,
                allowed_evidence_ids=list(allowed),
                purpose="bre3_decide_rationale",
            )
        else:
            advice = reason_decide_rationale(
                packet=evidence_packet,
                llm=llm,
                allowed_evidence_ids=list(allowed),
                purpose="bre3_decide_rationale",
            )
    except Exception as exc:  # noqa: BLE001
        name = type(exc).__name__
        doc["cognitive_core"] = {
            "review_status": UNREVIEWED,
            "skip_reason": f"failed:{name}",
        }
        doc["review_status"] = UNREVIEWED
        doc["status"] = "failed"
        doc["skip_reason"] = f"BRE.3 UNREVIEWED: failed:{name}"[:500]
        doc["completed_at"] = _now()
        doc["llm"] = False
        _save(data_dir, laboratory_id, doc)
        _log.debug("BRE.3 enrich exception: %s", name, exc_info=True)
        return doc

    doc["cognitive_core"] = {
        "version": advice.get("version"),
        "review_status": advice.get("review_status"),
        "skip_reason": advice.get("skip_reason"),
        "kind": advice.get("kind"),
    }
    if advice.get("raw_llm_text"):
        raw = str(advice.get("raw_llm_text"))[:2000]
        doc["raw_llm_text"] = raw
        doc["cognitive_core"]["raw_snippet"] = raw[:240]
    if advice.get("confidence") is not None:
        doc["confidence"] = advice.get("confidence")
    status = str(advice.get("review_status") or UNREVIEWED)
    skip = str(advice.get("skip_reason") or "")
    doc["review_status"] = status

    if status != REVIEWED:
        if skip == "lane_busy" or "lane" in skip:
            doc["status"] = "deferred_lane_busy"
            doc["skip_reason"] = "BRE.3 deferred — LLM lane busy"
            doc["llm"] = False
        else:
            doc["status"] = "failed" if skip.startswith("failed") or "empty" in skip else "skipped"
            doc["skip_reason"] = (
                f"BRE.3 UNREVIEWED: {skip or 'cognitive_core'}"
            )[:500]
            doc["completed_at"] = _now()
            doc["llm"] = bool(advice.get("llm"))
        _save(data_dir, laboratory_id, doc)
        return doc

    doc["rationale_text"] = advice.get("rationale_text")
    doc["falsifiers"] = list(advice.get("falsifiers") or [])
    doc["expected_outcome"] = advice.get("expected_outcome")
    doc["claims"] = list(advice.get("claims") or [])
    doc["status"] = "done"
    doc["skip_reason"] = skip or None
    doc["completed_at"] = _now()
    doc["llm"] = True
    _save(data_dir, laboratory_id, doc)
    return doc


def expire_stale_rationales(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    keep_ist_date: str | None = None,
) -> int:
    """CLC.R0 — mark pre-today pending/deferred as skipped_stale (no CPU catch-up)."""
    if not data_dir:
        return 0
    keep = str(keep_ist_date or _ist_today())
    n = 0
    root = _by_id_dir(data_dir, laboratory_id)
    for p in root.glob("*.json"):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict):
            continue
        if str(doc.get("status") or "") not in {"pending", "deferred_lane_busy"}:
            continue
        created = _created_ist_date(doc.get("created_at"))
        if created is None or created >= keep:
            continue
        doc["status"] = STALE_STATUS
        doc["skip_reason"] = STALE_REASON
        doc["review_status"] = "UNREVIEWED"
        doc["completed_at"] = _now()
        doc["llm"] = False
        _save(data_dir, laboratory_id, doc)
        n += 1
    return n


def has_clc_r1_shape(row: dict[str, Any] | None) -> bool:
    """New sidecars stamp lesson_refs/no_match on packet_summary; old backlog does not."""
    doc = row if isinstance(row, dict) else {}
    summary = doc.get("packet_summary") if isinstance(doc.get("packet_summary"), dict) else {}
    return "lesson_refs" in summary or "no_match" in summary


def expire_pre_clc_rationales(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
) -> int:
    """CLC.R1 — mark pre-stamp pending as skipped_pre_clc (no CPU catch-up)."""
    if not data_dir:
        return 0
    n = 0
    root = _by_id_dir(data_dir, laboratory_id)
    for p in root.glob("*.json"):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict):
            continue
        if str(doc.get("status") or "") not in {"pending", "deferred_lane_busy"}:
            continue
        if has_clc_r1_shape(doc):
            continue
        doc["status"] = PRE_CLC_STATUS
        doc["skip_reason"] = PRE_CLC_REASON
        doc["review_status"] = "UNREVIEWED"
        doc["completed_at"] = _now()
        doc["llm"] = False
        _save(data_dir, laboratory_id, doc)
        n += 1
    return n


def symbols_llm_today(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    ist_date: str | None = None,
) -> set[str]:
    """Symbols that already got an LLM sidecar today (done or failed)."""
    if not data_dir:
        return set()
    keep = str(ist_date or _ist_today())
    found: set[str] = set()
    root = _by_id_dir(data_dir, laboratory_id)
    for p in root.glob("*.json"):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict) or not doc.get("llm"):
            continue
        created = _created_ist_date(doc.get("completed_at") or doc.get("created_at"))
        if created != keep:
            continue
        sym = str(doc.get("symbol") or "").strip()
        if sym:
            found.add(sym)
    return found


def expire_r1_quota_rationales(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    ist_date: str | None = None,
) -> int:
    """Do not catch up remaining same-day wash after today's LLM shot(s)."""
    if not data_dir:
        return 0
    if not symbols_llm_today(
        data_dir, laboratory_id=laboratory_id, ist_date=ist_date
    ):
        return 0
    n = 0
    root = _by_id_dir(data_dir, laboratory_id)
    for p in root.glob("*.json"):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict):
            continue
        if str(doc.get("status") or "") not in {"pending", "deferred_lane_busy"}:
            continue
        doc["status"] = R1_QUOTA_STATUS
        doc["skip_reason"] = R1_QUOTA_REASON
        doc["review_status"] = "UNREVIEWED"
        doc["completed_at"] = _now()
        doc["llm"] = False
        _save(data_dir, laboratory_id, doc)
        n += 1
    return n


def _pick_decide_passes(
    prepared: list[dict[str, Any]], *, max_passes: int
) -> list[dict[str, Any]]:
    """Each sidecar costs one pass. Rank: buy, then budget, then newest."""
    ranked = list(prepared)
    ranked.sort(key=lambda it: str((it.get("row") or {}).get("created_at") or ""), reverse=True)
    ranked.sort(key=lambda it: -int(it.get("llm_budget") or 0))

    def _pri(it: dict[str, Any]) -> int:
        act = str((it.get("row") or {}).get("action") or "").lower()
        if act == "buy":
            return 0
        if act == "sell":
            return 1
        return 2

    ranked.sort(key=_pri)
    cap = max(0, int(max_passes))
    out: list[dict[str, Any]] = []
    for it in ranked:
        if int(it.get("llm_budget") or 0) <= 0:
            continue
        if len(out) >= cap:
            break
        out.append(it)
    return out


def drain_pending_rationales(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    llm: Any | None = None,
    reasoning: Any | None = None,
    max_passes: int = DEFAULT_DECIDE_LLM_PASSES,
    limit: int = 20,
) -> dict[str, Any]:
    """Drain pending decide-time rationale jobs under Cognitive Budget.

    CLC.R0: each job costs **one** pass (buy llm_budget=3 used to exceed
    max_passes=2 so nothing was chosen). Unchosen rows stay ``pending`` —
    they are not permanently ``skipped_no_budget``. Stale backlog expires.
    CLC.R1: pending sidecars without ``lesson_refs``/``no_match`` keys are
    ``skipped_pre_clc`` — do not burn CPU on packets queued before the stamp.
    """
    stale_expired = expire_stale_rationales(
        data_dir, laboratory_id=laboratory_id
    )
    pre_clc_expired = expire_pre_clc_rationales(
        data_dir, laboratory_id=laboratory_id
    )
    r1_quota_expired = expire_r1_quota_rationales(
        data_dir, laboratory_id=laboratory_id
    )
    pending = list_pending(data_dir, laboratory_id=laboratory_id, limit=limit)
    prepared: list[dict[str, Any]] = []
    for row in pending:
        prepared.append(
            {
                "row": row,
                "llm_budget": int(row.get("llm_budget") or 0),
            }
        )
    chosen = _pick_decide_passes(prepared, max_passes=max_passes)
    chosen_ids = {str((c.get("row") or {}).get("decision_id")) for c in chosen}

    done = 0
    deferred = 0
    skipped = 0
    failed = 0
    left_pending = 0
    updated: list[dict[str, Any]] = []

    if not data_dir:
        return {
            "version": VERSION,
            "done": 0,
            "deferred": 0,
            "skipped": 0,
            "failed": 0,
            "pending": 0,
            "stale_expired": stale_expired,
            "pre_clc_expired": pre_clc_expired,
            "r1_quota_expired": r1_quota_expired,
            "rows": [],
        }

    has_brain = reasoning is not None or llm is not None
    r0_cause = None
    if not has_brain:
        r0_cause = "llm_unbound"
    for it in prepared:
        row = it["row"]
        did = str(row.get("decision_id") or "")
        if did in chosen_ids and int(it.get("llm_budget") or 0) > 0 and has_brain:
            out = _run_one(
                row,
                llm=llm,
                reasoning=reasoning,
                data_dir=data_dir,
                laboratory_id=laboratory_id,
            )
        elif not has_brain:
            out = _run_one(
                row,
                llm=None,
                reasoning=None,
                data_dir=data_dir,
                laboratory_id=laboratory_id,
                skip_reason="BRE.3 skipped — no LLM",
            )
        elif int(it.get("llm_budget") or 0) <= 0:
            out = _run_one(
                row,
                llm=None,
                reasoning=None,
                data_dir=data_dir,
                laboratory_id=laboratory_id,
                skip_reason="below cognitive budget — no decide-time LLM pass",
            )
        else:
            # CLC.R0 — leave for a later pass. Do not stamp skipped_no_budget.
            left_pending += 1
            if r0_cause is None:
                r0_cause = "pass_cap_left_pending"
            continue
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

    remaining = list_pending(data_dir, laboratory_id=laboratory_id, limit=limit)
    return {
        "version": VERSION,
        "done": done,
        "deferred": deferred,
        "skipped": skipped,
        "failed": failed,
        "pending": len(remaining),
        "stale_expired": stale_expired,
        "pre_clc_expired": pre_clc_expired,
        "r1_quota_expired": r1_quota_expired,
        "left_pending": left_pending,
        "chosen_n": len(chosen_ids),
        "llm_bound": llm is not None,
        "reasoning_bound": reasoning is not None,
        "r0_cause": r0_cause,
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
