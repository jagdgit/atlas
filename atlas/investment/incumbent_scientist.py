"""OI-ICR5 — Scientist notes on ACP / EXIT_REVIEW (advice-only).

Budgeted research-lane densify. Never places orders. Deterministic draft always;
optional LLM enrich when capacity allows (CU0 fail-fast).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

VERSION = "icr.5.scientist_notes.v1"
STORE_REL = Path("investment") / "scientist_notes"
_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.incumbent_scientist")

DEFAULT_ICR5_PASSES = 2
DEFAULT_ICR5_DAILY_LLM_CAP = 12
DEFAULT_ICR5_RTH_PASSES = 1
DEFAULT_ICR5_SCHEDULE_MAX_RTH = 2
DEFAULT_ICR5_SCHEDULE_MAX_NIGHT = 4
DEFAULT_ICR5_MAX_NOTE_ATTEMPTS = 3
STATUS_FAILED_PERMANENT = "failed_permanent"
_DECISIONS_NEED_NOTES = frozenset({"EXIT_REVIEW", "SWITCH_REVIEW", "HOLD"})
# Transient / first-attempt statuses only. Deterministic parse bugs and
# AttributeError leftovers promote to failed_permanent after max attempts.
_LLM_RETRIABLE = frozenset(
    {
        "pending",
        "deferred_lane_busy",
        "failed:AttributeError",
        "failed:failed:AttributeError",
        # CPU Ollama often exceeds wall-clock; keep draining off-market
        "failed:OllamaError",
        "failed:TimeoutError",
        "failed:failed:OllamaError",
        "failed_non_json",
        "failed:failed_non_json",
        "failed:non_json",
    }
)
# Bug-class / deterministic failures — short leash, then permanent
_LLM_DETERMINISTIC_FAIL = frozenset(
    {
        "failed:AttributeError",
        "failed:failed:AttributeError",
        "failed_non_json",
        "failed:failed_non_json",
        "failed:non_json",
    }
)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in (s or ""))


def _note_storage_key(acp: dict[str, Any]) -> str:
    """One scientist note per allocation state — not per ephemeral acp_id UUID."""
    sym = str((acp.get("incumbent") or {}).get("symbol") or "UNKNOWN").upper()
    sh = str(acp.get("state_hash") or "").strip()
    if sh:
        return _safe(f"{sym}_{sh}")
    acp_id = str(acp.get("acp_id") or "").strip()
    return _safe(acp_id or sym)


def _doc_storage_key(doc: dict[str, Any]) -> str:
    sym = str(doc.get("symbol") or "").upper()
    sh = str(doc.get("state_hash") or "").strip()
    if sym and sh:
        return _safe(f"{sym}_{sh}")
    acp_id = str(doc.get("acp_id") or "").strip()
    notes_id = str(doc.get("notes_id") or "").strip()
    return _safe(acp_id or notes_id or sym or "x")


def ist_today() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).astimezone(_IST).date().isoformat()


def _daily_budget_path(data_dir: str | Path, laboratory_id: str) -> Path:
    return store_dir(data_dir, laboratory_id=laboratory_id) / "llm_daily_budget.json"


def scientist_llm_attempts_today(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
) -> int:
    if not data_dir:
        return 0
    path = _daily_budget_path(data_dir, laboratory_id)
    if not path.is_file():
        return 0
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if str(doc.get("as_of_ist") or "") != ist_today():
        return 0
    return int(doc.get("attempts") or 0)


def record_scientist_llm_attempt(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    n: int = 1,
) -> int:
    """Increment IST-day LLM attempt counter; returns new total."""
    if not data_dir:
        return 0
    path = _daily_budget_path(data_dir, laboratory_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    today = ist_today()
    attempts = 0
    if path.is_file():
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if str(doc.get("as_of_ist") or "") == today:
                attempts = int(doc.get("attempts") or 0)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            attempts = 0
    attempts = max(0, attempts) + max(1, int(n))
    try:
        path.write_text(
            json.dumps(
                {
                    "version": VERSION,
                    "as_of_ist": today,
                    "laboratory_id": laboratory_id,
                    "attempts": attempts,
                    "cap": DEFAULT_ICR5_DAILY_LLM_CAP,
                    "honesty": (
                        "DP-LLM2 — scientist LLM daily attempt budget; "
                        "failures count so we cannot spin forever."
                    ),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError:
        _log.debug("scientist daily budget write failed", exc_info=True)
    return attempts


def scientist_drain_pass_budget(*, cfg: dict[str, Any] | None = None) -> int:
    """How many LLM enrich passes this drain tick may run."""
    cfg = cfg or {}
    try:
        from atlas.investment.llm_lanes import in_nse_rth, in_overnight_window

        if in_nse_rth():
            return max(1, int(cfg.get("icr5_rth_passes") or DEFAULT_ICR5_RTH_PASSES))
        if in_overnight_window():
            return max(1, int(cfg.get("icr5_drain_passes") or DEFAULT_ICR5_PASSES))
    except Exception:  # noqa: BLE001
        pass
    return max(1, int(cfg.get("icr5_drain_passes") or DEFAULT_ICR5_PASSES))


def scientist_schedule_max_n(*, cfg: dict[str, Any] | None = None) -> int:
    cfg = cfg or {}
    try:
        from atlas.investment.llm_lanes import in_nse_rth

        if in_nse_rth():
            return max(1, int(cfg.get("icr5_schedule_max_rth") or DEFAULT_ICR5_SCHEDULE_MAX_RTH))
    except Exception:  # noqa: BLE001
        pass
    return max(1, int(cfg.get("icr5_schedule_max_night") or DEFAULT_ICR5_SCHEDULE_MAX_NIGHT))


def store_dir(data_dir: str | Path, *, laboratory_id: str) -> Path:
    from atlas.investment.laboratory import normalize_laboratory_id

    lab = normalize_laboratory_id(laboratory_id=laboratory_id)
    return Path(data_dir) / STORE_REL / _safe(lab)


def _by_id_dir(data_dir: str | Path, laboratory_id: str) -> Path:
    d = store_dir(data_dir, laboratory_id=laboratory_id) / "by_id"
    d.mkdir(parents=True, exist_ok=True)
    return d


def icr5_enabled(cfg: dict[str, Any] | None) -> bool:
    cfg = cfg or {}
    if cfg.get("icr5_enabled") is False:
        return False
    return True  # default on; LLM enrich still optional


def _f(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def draft_scientist_notes(
    acp: dict[str, Any] | None,
    *,
    resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministic advice-only notes (no LLM). Always safe to attach."""
    acp = acp if isinstance(acp, dict) else {}
    res = resolution if isinstance(resolution, dict) else {}
    inc = acp.get("incumbent") if isinstance(acp.get("incumbent"), dict) else {}
    cash = acp.get("cash") if isinstance(acp.get("cash"), dict) else {}
    stance = str(inc.get("thesis_stance") or "").upper()
    identity = str(inc.get("identity") or "").upper()
    mos = _f(inc.get("mos_pct"))
    decision = str(acp.get("decision") or "")
    exit_action = str(res.get("action") or (acp.get("exit_resolution") or {}).get("action") or "")

    contradictions: list[str] = []
    # Technical / allocation vs research
    if stance in {"AVOID", "INVALID"} and decision in {"KEEP", "HOLD", "EXIT_REVIEW"}:
        contradictions.append(
            f"Thesis {stance} while capital still allocated (ACP={decision}"
            + (f", densify={exit_action}" if exit_action else "")
            + ") — research and book disagree"
        )
    if identity == "QUARANTINED":
        contradictions.append(
            "Identity QUARANTINED — business model may be contaminated; "
            "do not trust ADD/KEEP edge until identity repaired"
        )
    if mos is not None and mos < -25 and decision not in {"EXIT_REVIEW", "SWITCH_REVIEW"}:
        contradictions.append(
            f"MoS {mos:.1f}% deeply negative but ACP={decision} — valuation vs hold conflict"
        )
    tech_buy = False
    try:
        er = _f(inc.get("expected_return"))
        if er is not None and er > 0 and stance in {"AVOID", "INVALID"}:
            tech_buy = True
            contradictions.append(
                f"Prototype E[R]={er:+.4f} positive while thesis {stance} — "
                "technical/prototype edge ≠ fundamental permission"
            )
    except Exception:  # noqa: BLE001
        pass

    unknowns: list[str] = []
    for u in res.get("waiting_for") or acp.get("unknowns") or []:
        if u and str(u) not in unknowns:
            unknowns.append(str(u)[:120])
    missing = list(inc.get("missing_terms") or [])
    if missing:
        unknowns.append(f"er_missing_terms:{','.join(missing[:6])}")
    if identity == "QUARANTINED" and "identity_repair" not in unknowns:
        unknowns.append("identity_repair")
    if not unknowns:
        unknowns.append("challenger_evidence_density")

    # Which unknown flips ranking
    flip_hints: list[str] = []
    best = None
    for c in acp.get("challengers") or []:
        if isinstance(c, dict) and c.get("is_best"):
            best = c
            break
    if best:
        flip_hints.append(
            f"If challenger {best.get('symbol')} clears costs with honest E[R], "
            "SWITCH_REVIEW outranks KEEP"
        )
    if cash.get("expected_return") is not None:
        flip_hints.append(
            "If incumbent E[R] honesty falls to ≤ cash after costs, EXIT_TO_CASH "
            "outranks WAIT"
        )
    if identity == "QUARANTINED":
        flip_hints.append(
            "Clearing quarantine / re-establishing identity can flip EXIT_REVIEW → HOLD/KEEP"
        )
    if not flip_hints:
        flip_hints.append("Denser valuation MoS or RS vs benchmark can flip HOLD → KEEP/SWITCH")

    # Edge robustness
    completeness = _f(inc.get("er_completeness"))
    if completeness is not None and completeness < 0.45:
        edge = (
            f"Incumbent edge fragile — E[R] completeness {completeness:.2f} "
            "(thin evidence; not a robust edge)"
        )
    elif stance in {"AVOID", "INVALID"} or identity == "QUARANTINED":
        edge = "Incumbent edge not robust — thesis/identity veto outweighs technical score"
    elif decision == "KEEP":
        edge = "Incumbent edge tentatively robust vs best challenger after costs (KEEP)"
    else:
        edge = f"Incumbent edge unsettled under ACP={decision} — densify before ADD"

    summary = (
        f"{inc.get('symbol') or '?'}: scientist — "
        + (f"{len(contradictions)} contradiction(s); " if contradictions else "no hard contradiction; ")
        + f"flip via {flip_hints[0][:80]}; {edge[:100]}"
    )

    return {
        "version": VERSION,
        "advice_only": True,
        "never_orders": True,
        "source": "deterministic",
        "llm": False,
        "review_status": "DETERMINISTIC",
        "symbol": inc.get("symbol"),
        "acp_decision": decision,
        "exit_action": exit_action or None,
        "contradictions": contradictions[:6],
        "unknowns_that_flip_ranking": unknowns[:8],
        "flip_hints": flip_hints[:4],
        "incumbent_edge_robust": edge,
        "tech_vs_thesis_tension": tech_buy,
        "summary": summary[:400],
        "operator_line": summary[:220],
        "honesty": (
            "ICR.5 scientist notes — advice-only. Deterministic gates / ICR.0–2 "
            "own capital. Never places orders. LLM densify → REVIEWED; "
            "failure → UNREVIEWED (not silent success)."
        ),
    }


def schedule_scientist_notes(
    data_dir: str | Path | None,
    acp: dict[str, Any] | None,
    *,
    laboratory_id: str | None = None,
    resolution: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Persist draft notes + pending LLM enrich job. Idempotent per state_hash."""
    if not data_dir or not isinstance(acp, dict):
        return None
    if not icr5_enabled(cfg):
        return None
    decision = str(acp.get("decision") or "")
    if decision not in _DECISIONS_NEED_NOTES:
        return None
    # Prefer EXIT/SWITCH; HOLD only when advantage_unclear / thin
    reason = str(acp.get("reason_code") or "")
    if decision == "HOLD" and reason not in {
        "advantage_unclear",
        "hold_thin_evidence",
        "hold_default",
    }:
        return None

    lab = laboratory_id or str(acp.get("laboratory_id") or "india_equity_learner")
    acp_id = str(acp.get("acp_id") or "")
    sym = str((acp.get("incumbent") or {}).get("symbol") or "UNKNOWN").upper()
    key = _note_storage_key(acp)
    path = _by_id_dir(data_dir, lab) / f"{key}.json"
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                existing.setdefault("path", str(path))
                # Trace latest ACP id without spawning duplicate pending rows
                if acp_id and acp_id != str(existing.get("acp_id") or ""):
                    existing["acp_id"] = acp_id
                attach_scientist_notes_to_acp(
                    data_dir,
                    acp,
                    existing.get("notes") if isinstance(existing.get("notes"), dict) else {},
                )
                return existing
        except Exception:  # noqa: BLE001
            pass

    notes = draft_scientist_notes(acp, resolution=resolution)
    try:
        from atlas.investment.world_evidence import attach_world_evidence

        world = attach_world_evidence(
            data_dir,
            sym,
            laboratory_id=lab,
            sector=str((acp.get("incumbent") or {}).get("sector") or "") or None,
        )
        notes = dict(notes)
        notes["world_evidence"] = {
            "version": world.get("version"),
            "evidence_lines": list(world.get("evidence_lines") or [])[:12],
            "news_n": len(world.get("news") or []),
            "policy_n": len(world.get("policy") or []),
            "history": world.get("history"),
            "unknowns": list(world.get("unknowns") or [])[:8],
        }
        for u in world.get("unknowns") or []:
            tag = f"world_{u}"
            if tag not in (notes.get("unknowns_that_flip_ranking") or []):
                notes.setdefault("unknowns_that_flip_ranking", []).append(tag)
        notes["unknowns_that_flip_ranking"] = list(
            notes.get("unknowns_that_flip_ranking") or []
        )[:10]
    except Exception:  # noqa: BLE001
        _log.debug("NOW #7 world evidence on schedule skipped", exc_info=True)

    row: dict[str, Any] = {
        "version": VERSION,
        "notes_id": str(uuid4()),
        "acp_id": acp_id or None,
        "state_hash": acp.get("state_hash"),
        "symbol": sym,
        "laboratory_id": lab,
        "status": "draft",  # draft = deterministic done; pending_llm optional
        "created_at": _now(),
        "completed_at": _now(),
        "llm_status": "pending",
        "notes": notes,
        "acp_snapshot": {
            "decision": decision,
            "reason_code": acp.get("reason_code"),
            "operator_line": acp.get("operator_line"),
            "thesis_stance": (acp.get("incumbent") or {}).get("thesis_stance"),
            "identity": (acp.get("incumbent") or {}).get("identity"),
            "mos_pct": (acp.get("incumbent") or {}).get("mos_pct"),
            "best_challenger": next(
                (
                    c.get("symbol")
                    for c in (acp.get("challengers") or [])
                    if isinstance(c, dict) and c.get("is_best")
                ),
                None,
            ),
            "exit_resolution": acp.get("exit_resolution") or (
                {
                    "action": (resolution or {}).get("action"),
                    "reason_code": (resolution or {}).get("reason_code"),
                    "waiting_for": (resolution or {}).get("waiting_for"),
                }
                if resolution
                else None
            ),
        },
    }
    try:
        path.write_text(json.dumps(row, indent=2, default=str) + "\n", encoding="utf-8")
    except OSError:
        _log.debug("ICR.5 schedule write failed", exc_info=True)
        return None
    row["path"] = str(path)

    # Attach draft onto ACP immediately
    attach_scientist_notes_to_acp(data_dir, acp, notes)
    return row


def attach_scientist_notes_to_acp(
    data_dir: str | Path | None,
    acp: dict[str, Any],
    notes: dict[str, Any],
) -> None:
    if not isinstance(acp, dict) or not isinstance(notes, dict):
        return
    acp["scientist_notes"] = notes
    if isinstance(acp.get("provenance"), dict):
        acp["provenance"]["scientist_notes"] = {
            "summary": notes.get("summary"),
            "source": notes.get("source"),
            "llm": notes.get("llm"),
            "advice_only": True,
        }
    if data_dir:
        try:
            from atlas.investment.allocation_comparison import persist_acp

            persist_acp(data_dir, acp)
        except Exception:  # noqa: BLE001
            _log.debug("ICR.5 ACP attach persist skipped", exc_info=True)


def schedule_from_lab_acps(
    data_dir: str | Path | None,
    packets: list[dict[str, Any]] | None,
    *,
    laboratory_id: str,
    resolutions: list[dict[str, Any]] | None = None,
    cfg: dict[str, Any] | None = None,
    max_n: int | None = None,
) -> dict[str, Any]:
    res_by = {
        str(r.get("symbol") or "").upper(): r
        for r in (resolutions or [])
        if isinstance(r, dict)
    }
    cap = max_n if max_n is not None else scientist_schedule_max_n(cfg=cfg)
    scheduled: list[str] = []
    for acp in packets or []:
        if len(scheduled) >= max(1, int(cap)):
            break
        if not isinstance(acp, dict):
            continue
        sym = str((acp.get("incumbent") or {}).get("symbol") or "").upper()
        row = schedule_scientist_notes(
            data_dir,
            acp,
            laboratory_id=laboratory_id,
            resolution=res_by.get(sym),
            cfg=cfg,
        )
        if row:
            scheduled.append(str(row.get("notes_id") or row.get("acp_id") or sym))
    return {"version": VERSION, "count": len(scheduled), "ids": scheduled, "max_n": cap}


def _note_attempts(doc: dict[str, Any]) -> int:
    try:
        return max(0, int(doc.get("llm_attempts") or 0))
    except (TypeError, ValueError):
        return 0


def _max_note_attempts(cfg: dict[str, Any] | None = None) -> int:
    cfg = cfg or {}
    try:
        return max(1, int(cfg.get("icr5_max_note_attempts") or DEFAULT_ICR5_MAX_NOTE_ATTEMPTS))
    except (TypeError, ValueError):
        return DEFAULT_ICR5_MAX_NOTE_ATTEMPTS


def _is_retriable_status(st: str, *, attempts: int, max_attempts: int) -> bool:
    if not st or st.startswith(STATUS_FAILED_PERMANENT):
        return False
    if st not in _LLM_RETRIABLE:
        return False
    if st in _LLM_DETERMINISTIC_FAIL and attempts >= max_attempts:
        return False
    if ("Ollama" in st or "Timeout" in st) and attempts >= max_attempts:
        return False
    return True


def _mark_failed_permanent(
    doc: dict[str, Any],
    *,
    reason: str,
    data_dir: str | Path | None,
    laboratory_id: str,
) -> dict[str, Any]:
    doc["llm_status"] = STATUS_FAILED_PERMANENT
    doc["fail_reason"] = reason
    doc["failed_permanent_at"] = _now()
    doc["completed_at"] = _now()
    doc["honesty"] = (
        "FAILED_PERMANENT — bounded retries exhausted. "
        "Cognitive failure must not consume tick/LLM capacity. Advice-only."
    )
    _save(data_dir, laboratory_id, doc)
    return doc


def retire_exhausted_scientist_notes(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One-shot: promote attempt-exhausted / AttributeError leftovers to permanent."""
    if not data_dir:
        return {"ok": False, "retired_n": 0}
    max_attempts = _max_note_attempts(cfg)
    root = _by_id_dir(data_dir, laboratory_id)
    retired: list[str] = []
    if not root.is_dir():
        return {"ok": True, "retired_n": 0, "ids": []}
    for p in root.glob("*.json"):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(doc, dict):
            continue
        doc["path"] = str(p)
        st = str(doc.get("llm_status") or "")
        if st.startswith(STATUS_FAILED_PERMANENT):
            continue
        attempts = _note_attempts(doc)
        # AttributeError is a fixed bug class — retire without another LLM burn
        if "AttributeError" in st:
            doc["llm_attempts"] = max(attempts, max_attempts)
            _mark_failed_permanent(
                doc, reason=st, data_dir=data_dir, laboratory_id=laboratory_id
            )
            retired.append(str(doc.get("notes_id") or p.name))
            continue
        # Historical deterministic parse failures already burned an attempt on disk
        if st in _LLM_DETERMINISTIC_FAIL or "non_json" in st:
            if attempts >= max_attempts or "llm_attempts" not in doc:
                doc["llm_attempts"] = max(attempts, max_attempts)
                _mark_failed_permanent(
                    doc, reason=st, data_dir=data_dir, laboratory_id=laboratory_id
                )
                retired.append(str(doc.get("notes_id") or p.name))
                continue
    return {"ok": True, "retired_n": len(retired), "ids": retired[:20]}


def list_pending_llm(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    limit: int = 20,
    cfg: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not data_dir:
        return []
    root = _by_id_dir(data_dir, laboratory_id)
    rows: list[tuple[tuple[int, float], dict[str, Any]]] = []
    max_attempts = _max_note_attempts(cfg)

    def _prio(st: str) -> int:
        # Prefer fresh pending over deterministic failures that may go permanent
        if st in {"pending", "deferred_lane_busy"}:
            return 0
        if "Ollama" in st or "Timeout" in st:
            return 1
        if st == "failed_non_json" or "non_json" in st:
            return 2
        if "AttributeError" in st:
            return 3
        return 4

    for p in root.glob("*.json"):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(doc, dict):
            continue
        st = str(doc.get("llm_status") or "")
        attempts = _note_attempts(doc)
        if not _is_retriable_status(st, attempts=attempts, max_attempts=max_attempts):
            continue
        doc.setdefault("path", str(p))
        rows.append(((_prio(st), -p.stat().st_mtime), doc))
    rows.sort(key=lambda x: x[0])
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for _, doc in rows:
        sym = str(doc.get("symbol") or "").upper()
        sh = str(doc.get("state_hash") or "").strip()
        dedupe_key = (sym, sh) if sh else (sym, str(doc.get("notes_id") or doc.get("path") or ""))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        out.append(doc)
        if len(out) >= max(1, int(limit)):
            break
    return out


def enrich_with_llm(
    data_dir: str | Path | None,
    doc: dict[str, Any],
    *,
    laboratory_id: str,
    llm: Any | None = None,
    reasoning: Any | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Optional Cognitive Core enrich (NOW #5). Fail → UNREVIEWED; never orders."""
    if not isinstance(doc, dict):
        return doc
    max_attempts = _max_note_attempts(cfg)
    # Increment before call — failures count toward permanent retirement
    doc["llm_attempts"] = _note_attempts(doc) + 1
    notes = doc.get("notes") if isinstance(doc.get("notes"), dict) else {}
    snap = doc.get("acp_snapshot") if isinstance(doc.get("acp_snapshot"), dict) else {}

    from atlas.reasoning.cognitive_core import (
        REVIEWED,
        UNREVIEWED,
        evidence_packet_from_icr_notes,
        merge_advice_into_icr_notes,
        reason_as_scientist,
    )

    packet = evidence_packet_from_icr_notes(
        notes, acp_snapshot=snap, laboratory_id=laboratory_id
    )
    try:
        from atlas.investment.world_evidence import (
            apply_world_to_evidence_packet,
            attach_world_evidence,
        )

        world = attach_world_evidence(
            data_dir,
            str(doc.get("symbol") or notes.get("symbol") or ""),
            laboratory_id=laboratory_id,
        )
        packet = apply_world_to_evidence_packet(packet, world)
        doc["world_evidence"] = {
            "version": world.get("version"),
            "evidence_lines": list(world.get("evidence_lines") or [])[:12],
            "unknowns": list(world.get("unknowns") or [])[:8],
            "news_n": len(world.get("news") or []),
            "policy_n": len(world.get("policy") or []),
            "history": world.get("history"),
        }
    except Exception:  # noqa: BLE001
        _log.debug("NOW #7 ICR world evidence skipped", exc_info=True)

    if reasoning is None and llm is None:
        notes = dict(notes)
        notes["review_status"] = UNREVIEWED
        notes.setdefault("cognitive_core", {"review_status": UNREVIEWED, "skip_reason": "no_llm"})
        doc["notes"] = notes
        doc["llm_status"] = "skipped_no_llm"
        doc["completed_at"] = _now()
        _save(data_dir, laboratory_id, doc)
        return doc

    try:
        busy_src = reasoning if reasoning is not None else llm
        lane_llm = getattr(busy_src, "_llm", None) or busy_src
        if hasattr(lane_llm, "lane_busy") and lane_llm.lane_busy():
            notes = dict(notes)
            notes["review_status"] = UNREVIEWED
            doc["notes"] = notes
            doc["llm_status"] = "deferred_lane_busy"
            _save(data_dir, laboratory_id, doc)
            return doc
    except Exception:  # noqa: BLE001
        pass

    try:
        if reasoning is not None and hasattr(reasoning, "reason_scientist"):
            advice = reasoning.reason_scientist(
                packet=packet,
                laboratory_id=laboratory_id,
                purpose="icr5_scientist_notes",
            )
        else:
            advice = reason_as_scientist(
                packet=packet, llm=llm, purpose="icr5_scientist_notes"
            )
    except Exception as exc:  # noqa: BLE001
        name = type(exc).__name__
        notes = dict(notes)
        notes["review_status"] = UNREVIEWED
        notes["cognitive_core"] = {
            "review_status": UNREVIEWED,
            "skip_reason": f"failed:{name}",
        }
        doc["notes"] = notes
        doc["llm_status"] = f"failed:{name}"
        doc["completed_at"] = _now()
        if _note_attempts(doc) >= max_attempts or name == "AttributeError":
            return _mark_failed_permanent(
                doc,
                reason=doc["llm_status"],
                data_dir=data_dir,
                laboratory_id=laboratory_id,
            )
        _save(data_dir, laboratory_id, doc)
        _log.debug("ICR.5 enrich exception: %s", name, exc_info=True)
        return doc

    merged = merge_advice_into_icr_notes(notes, advice)
    doc["notes"] = merged
    status = str((advice or {}).get("review_status") or UNREVIEWED)
    skip = str((advice or {}).get("skip_reason") or "")
    # Phase 7 — LLM attribution (measurement only; never allocation authority)
    try:
        from atlas.investment.llm_attribution import record_consultation

        accepted = status == REVIEWED
        changed: list[str] = []
        if accepted:
            # Scientist notes may change research surface; never allocation here
            changed.append("research")
            det = str((notes or {}).get("decision") or packet.get("decision") or "")
            adv = str((advice or {}).get("recommended_action") or (advice or {}).get("action") or "")
            if adv and det and adv.upper() != det.upper():
                changed.append("ranking")
        else:
            changed.append("none")
        record_consultation(
            data_dir,
            laboratory_id=laboratory_id,
            purpose="icr5_scientist_notes",
            advice_summary=str((advice or {}).get("summary") or (advice or {}).get("note") or "")[
                :400
            ]
            or None,
            accepted=accepted if status in {REVIEWED, UNREVIEWED} else None,
            changed=changed,
            deterministic_action=str(
                (notes or {}).get("decision") or packet.get("decision") or ""
            )
            or None,
            advised_action=str(
                (advice or {}).get("recommended_action") or (advice or {}).get("action") or ""
            )
            or None,
            outcome_ref=str(doc.get("id") or doc.get("path") or "") or None,
        )
    except Exception:  # noqa: BLE001
        _log.debug("llm attribution skipped", exc_info=True)
    if status == REVIEWED:
        doc["llm_status"] = "done"
        doc["status"] = "done"
        doc["completed_at"] = _now()
    elif skip == "lane_busy" or "lane" in skip:
        doc["llm_status"] = "deferred_lane_busy"
    elif skip in {"no_llm", "empty_packet"}:
        doc["llm_status"] = f"skipped_{skip}" if skip != "no_llm" else "skipped_no_llm"
        doc["completed_at"] = _now()
    else:
        doc["llm_status"] = skip if skip.startswith("failed") else f"failed:{skip or 'unreviewed'}"
        doc["completed_at"] = _now()
        st_fail = str(doc["llm_status"])
        if (
            st_fail in _LLM_DETERMINISTIC_FAIL
            or "non_json" in st_fail
            or "AttributeError" in st_fail
        ) and _note_attempts(doc) >= max_attempts:
            return _mark_failed_permanent(
                doc,
                reason=st_fail,
                data_dir=data_dir,
                laboratory_id=laboratory_id,
            )
    _save(data_dir, laboratory_id, doc)

    # Re-attach enriched notes onto latest ACP if possible
    try:
        from atlas.investment.allocation_comparison import load_latest_acp_summary
        from atlas.investment.incumbent_capital import load_acp

        sym = str(doc.get("symbol") or "")
        summary = load_latest_acp_summary(data_dir, laboratory_id, sym)
        sh = str((summary or {}).get("state_hash") or doc.get("state_hash") or "")
        if sh:
            full = load_acp(
                data_dir, laboratory_id=laboratory_id, symbol=sym, state_hash=sh
            )
            if isinstance(full, dict):
                attach_scientist_notes_to_acp(data_dir, full, merged)
    except Exception:  # noqa: BLE001
        pass
    return doc


def _save(data_dir: str | Path | None, laboratory_id: str, doc: dict[str, Any]) -> None:
    if not data_dir or not isinstance(doc, dict):
        return
    path = doc.get("path")
    if not path:
        key = _doc_storage_key(doc)
        path = str(_by_id_dir(data_dir, laboratory_id) / f"{key}.json")
        doc["path"] = path
    try:
        Path(path).write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
    except OSError:
        _log.debug("ICR.5 save failed", exc_info=True)


def drain_pending_scientist_notes(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    llm: Any | None = None,
    reasoning: Any | None = None,
    max_passes: int | None = None,
    limit: int = 10,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = cfg or {}
    daily_cap = max(1, int(cfg.get("icr5_daily_llm_cap") or DEFAULT_ICR5_DAILY_LLM_CAP))
    used = scientist_llm_attempts_today(data_dir, laboratory_id=laboratory_id)
    if used >= daily_cap:
        return {
            "version": VERSION,
            "pending": 0,
            "done": 0,
            "deferred": 0,
            "skipped": 0,
            "reason": "daily_llm_cap",
            "attempts_today": used,
            "daily_cap": daily_cap,
        }
    passes = (
        max_passes
        if max_passes is not None
        else scientist_drain_pass_budget(cfg=cfg)
    )
    remaining = max(0, daily_cap - used)
    passes = max(1, min(int(passes), remaining))
    # Retire exhausted leftovers so they stop competing with fresh pending
    retired = retire_exhausted_scientist_notes(
        data_dir, laboratory_id=laboratory_id, cfg=cfg
    )
    pending = list_pending_llm(
        data_dir, laboratory_id=laboratory_id, limit=limit, cfg=cfg
    )
    done = deferred = skipped = permanent = 0
    for doc in pending[:passes]:
        record_scientist_llm_attempt(data_dir, laboratory_id=laboratory_id, n=1)
        out = enrich_with_llm(
            data_dir,
            doc,
            laboratory_id=laboratory_id,
            llm=llm,
            reasoning=reasoning,
            cfg=cfg,
        )
        st = str(out.get("llm_status") or "")
        if st == "done":
            done += 1
        elif st.startswith(STATUS_FAILED_PERMANENT):
            permanent += 1
        elif "deferred" in st:
            deferred += 1
        elif st.startswith("skipped"):
            skipped += 1
    return {
        "version": VERSION,
        "pending": len(pending),
        "done": done,
        "deferred": deferred,
        "skipped": skipped,
        "failed_permanent": permanent,
        "retired_exhausted_n": int(retired.get("retired_n") or 0),
        "passes": passes,
        "attempts_today": scientist_llm_attempts_today(
            data_dir, laboratory_id=laboratory_id
        ),
        "daily_cap": daily_cap,
    }


def _note_keep_rank(doc: dict[str, Any], mtime: float) -> tuple[int, float]:
    notes = doc.get("notes") if isinstance(doc.get("notes"), dict) else {}
    rs = str(notes.get("review_status") or "")
    st = str(doc.get("llm_status") or "")
    if rs == "REVIEWED" or st == "done":
        band = 0
    elif "non_json" in st:
        band = 1
    elif st in {"pending", "deferred_lane_busy"}:
        band = 2
    elif "Ollama" in st or "Timeout" in st:
        band = 3
    elif "AttributeError" in st:
        band = 4
    else:
        band = 5
    return (band, -mtime)


def compact_legacy_scientist_notes(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Archive duplicate uuid-keyed notes; keep one row per symbol+state_hash."""
    if not data_dir:
        return {"version": VERSION, "ok": False, "error": "no_data_dir"}
    root = _by_id_dir(data_dir, laboratory_id)
    if not root.is_dir():
        return {"version": VERSION, "ok": True, "groups": 0, "archived": 0}

    groups: dict[tuple[str, str], list[tuple[Path, dict[str, Any], float]]] = {}
    skipped = 0
    for p in root.glob("*.json"):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            skipped += 1
            continue
        if not isinstance(doc, dict):
            skipped += 1
            continue
        sym = str(doc.get("symbol") or "").upper()
        sh = str(doc.get("state_hash") or "").strip()
        if not sym or not sh:
            skipped += 1
            continue
        mtime = p.stat().st_mtime
        groups.setdefault((sym, sh), []).append((p, doc, mtime))

    archive_dir = root / "_archive_duplicates"
    archived = 0
    kept = 0
    migrated = 0
    for (_sym, sh), rows in groups.items():
        if len(rows) < 2:
            continue
        rows.sort(key=lambda x: _note_keep_rank(x[1], x[2]))
        winner_path, winner_doc, _ = rows[0]
        canonical = root / f"{_doc_storage_key(winner_doc)}.json"
        kept += 1
        if not dry_run:
            if canonical != winner_path and not canonical.is_file():
                try:
                    winner_doc["path"] = str(canonical)
                    canonical.write_text(
                        json.dumps(winner_doc, indent=2, default=str) + "\n",
                        encoding="utf-8",
                    )
                    if winner_path != canonical and winner_path.is_file():
                        winner_path.unlink(missing_ok=True)
                    migrated += 1
                except OSError:
                    _log.debug("ICR.5 compact migrate failed", exc_info=True)
        for path, _doc, mt in rows[1:]:
            if path == canonical:
                continue
            archived += 1
            if dry_run:
                continue
            try:
                archive_dir.mkdir(parents=True, exist_ok=True)
                dest = archive_dir / path.name
                if dest.is_file():
                    dest = archive_dir / f"{path.stem}_{int(mt)}.json"
                path.rename(dest)
            except OSError:
                _log.debug("ICR.5 compact archive failed", exc_info=True)

    return {
        "version": VERSION,
        "ok": True,
        "laboratory_id": laboratory_id,
        "dry_run": dry_run,
        "duplicate_groups": sum(1 for g in groups.values() if len(g) > 1),
        "kept": kept,
        "archived": archived,
        "migrated": migrated,
        "skipped_unkeyed": skipped,
    }


def format_scientist_evening_lines(
    data_dir: str | Path | None,
    laboratory_id: str,
    symbols: list[str] | None = None,
    *,
    limit: int = 4,
) -> list[str]:
    if not data_dir:
        return []
    lines = ["", "── Scientist notes (OI-ICR5 — advice-only) ──"]
    n = 0
    root = _by_id_dir(data_dir, laboratory_id)
    sym_filter = {str(s).upper() for s in (symbols or []) if s}
    for p in sorted(root.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        if n >= limit:
            break
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(doc, dict):
            continue
        sym = str(doc.get("symbol") or "")
        if sym_filter and sym not in sym_filter:
            continue
        notes = doc.get("notes") if isinstance(doc.get("notes"), dict) else {}
        line = notes.get("operator_line") or notes.get("summary")
        if not line:
            continue
        src = notes.get("source") or "deterministic"
        rev = notes.get("review_status") or ""
        tag = f"{src}" + (f"/{rev}" if rev else "")
        lines.append(f"  {line} [{tag}]")
        n += 1
    if n == 0:
        return []
    return lines
