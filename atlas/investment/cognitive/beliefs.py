"""Cognitive Loop C7/C8 — versioned belief revision and its behavioural proof.

A belief that changes nothing is not a learning, and a belief with no evidence chain
is not a belief. So every revision here is a numbered version carrying the experiment
ids and learning ids behind it, and it is PROPOSED until a validated learning backs it.

Hard boundary: an accepted belief changes decision *context* only. It never touches
order authority, position sizing, capital allocation, SMA/RSI, or PLC.A. If a belief
could size a trade, the cognitive loop would be a strategy — it is not.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "cognitive.belief.v1"
KIND = "BELIEF_REVISION"
STORE_REL = Path("investment") / "cognitive" / "beliefs"

STATUS_PROPOSED = "PROPOSED"
STATUS_ACCEPTED = "ACCEPTED"
STATUS_REJECTED = "REJECTED"

_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.cognitive.beliefs")


def belief_id_for(laboratory_id: str, dimension: str) -> str:
    return f"B-{laboratory_id}-{dimension}".replace(" ", "_")[:80]


def _path(data_dir: str | Path, laboratory_id: str, belief_id: str) -> Path:
    return Path(data_dir) / STORE_REL / str(laboratory_id) / f"{belief_id}.jsonl"


def load_versions(
    data_dir: str | Path | None, *, laboratory_id: str, belief_id: str
) -> list[dict[str, Any]]:
    if not data_dir:
        return []
    path = _path(data_dir, laboratory_id, belief_id)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(doc, dict):
            rows.append(doc)
    return rows


def current_version(
    data_dir: str | Path | None, *, laboratory_id: str, belief_id: str
) -> dict[str, Any] | None:
    versions = load_versions(data_dir, laboratory_id=laboratory_id, belief_id=belief_id)
    accepted = [v for v in versions if v.get("status") == STATUS_ACCEPTED]
    return (accepted or versions or [None])[-1]


def propose_revision(
    data_dir: str | Path | None,
    candidate: dict[str, Any] | None,
    *,
    laboratory_id: str,
) -> dict[str, Any]:
    """Propose belief version N+1 from a learning candidate that earned one."""
    cand = candidate if isinstance(candidate, dict) else {}
    if not cand.get("writes_belief"):
        return {
            "ok": True,
            "proposed": False,
            "reason": "candidate did not earn a belief write",
            "detail": cand.get("experiment_result"),
        }
    dimension = str(cand.get("dimension") or "")
    belief_id = belief_id_for(laboratory_id, dimension)
    prior = current_version(data_dir, laboratory_id=laboratory_id, belief_id=belief_id)
    version = int((prior or {}).get("version_n") or 0) + 1

    row = {
        "version": VERSION,
        "kind": KIND,
        "belief_id": belief_id,
        "version_n": version,
        "previous_version": (prior or {}).get("version_n"),
        "laboratory_id": str(laboratory_id or ""),
        "dimension": dimension,
        "statement": cand.get("statement"),
        "confidence": "low",
        "status": STATUS_PROPOSED,
        "evidence": {
            "experiment_ids": [cand.get("experiment_id")],
            "learning_ids": [cand.get("hypothesis_id")],
            "baseline": cand.get("baseline"),
            "gap": cand.get("gap"),
        },
        "reason": (
            f"experiment {cand.get('experiment_id')} returned "
            f"{cand.get('experiment_result')} on {dimension}"
        ),
        "validated_learning": bool(cand.get("validated")),
        "affects": "decision_context_only",
        "does_not_affect": [
            "order_authority",
            "position_sizing",
            "capital_allocation",
            "sma_rsi_v1",
            "plc_a",
        ],
        "at": datetime.now(_IST).isoformat(),
        "honesty": (
            "PROPOSED. Acceptance requires a VALIDATED learning behind it, not a "
            "single supported pass. An accepted belief changes what a decision knows, "
            "never what it is allowed to do."
        ),
    }
    out = _append(data_dir, laboratory_id=laboratory_id, belief_id=belief_id, row=row)
    return {"ok": out.get("ok", False), "proposed": True, "belief": row}


def accept_revision(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    belief_id: str,
    validated_learning_id: str | None,
) -> dict[str, Any]:
    """Accept only with a validated learning behind it. Otherwise refuse, loudly."""
    versions = load_versions(data_dir, laboratory_id=laboratory_id, belief_id=belief_id)
    proposed = [v for v in versions if v.get("status") == STATUS_PROPOSED]
    if not proposed:
        return {"ok": False, "reason": "no_proposed_version"}
    if not validated_learning_id:
        return {
            "ok": False,
            "reason": "no_validated_learning",
            "detail": (
                "belief acceptance requires a learning that passed its pre-declared "
                "independent test"
            ),
        }
    row = dict(proposed[-1])
    row["status"] = STATUS_ACCEPTED
    row["validated_learning"] = True
    row["accepted_at"] = datetime.now(_IST).isoformat()
    row["evidence"] = {
        **(row.get("evidence") or {}),
        "validated_learning_id": str(validated_learning_id),
    }
    out = _append(data_dir, laboratory_id=laboratory_id, belief_id=belief_id, row=row)
    return {"ok": out.get("ok", False), "belief": row}


def _append(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    belief_id: str,
    row: dict[str, Any],
) -> dict[str, Any]:
    if not data_dir:
        return {"ok": False, "reason": "missing_data_dir"}
    try:
        path = _path(data_dir, laboratory_id, belief_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return {"ok": True, "path": str(path)}
    except Exception as exc:  # noqa: BLE001
        _log.debug("belief append failed", exc_info=True)
        return {"ok": False, "reason": type(exc).__name__}


def belief_context_for_decision(
    data_dir: str | Path | None, *, laboratory_id: str
) -> dict[str, Any]:
    """C8 — what a decision packet should cite. Advice-level, read-only."""
    root = (
        Path(data_dir) / STORE_REL / str(laboratory_id)
        if data_dir
        else None
    )
    beliefs: list[dict[str, Any]] = []
    if root is not None and root.is_dir():
        for path in sorted(root.glob("B-*.jsonl")):
            versions = load_versions(
                data_dir, laboratory_id=laboratory_id, belief_id=path.stem
            )
            accepted = [v for v in versions if v.get("status") == STATUS_ACCEPTED]
            if accepted:
                latest = accepted[-1]
                beliefs.append(
                    {
                        "belief_id": latest.get("belief_id"),
                        "version_n": latest.get("version_n"),
                        "dimension": latest.get("dimension"),
                        "statement": latest.get("statement"),
                        "confidence": latest.get("confidence"),
                    }
                )
    return {
        "version": VERSION,
        "beliefs": beliefs,
        "n_accepted": len(beliefs),
        "affects": "decision_context_only",
        "honesty": (
            "Accepted beliefs cited by this decision. They inform what the decision "
            "knows; they do not change order authority or sizing. An empty list means "
            "nothing has been validated yet, which is the current honest state."
        ),
    }


def behavioural_delta(
    before: dict[str, Any] | None, after: dict[str, Any] | None
) -> dict[str, Any]:
    """C8 — did the belief change actually change the decision's context?"""
    b = before if isinstance(before, dict) else {}
    a = after if isinstance(after, dict) else {}
    b_ids = {
        (x.get("belief_id"), x.get("version_n")) for x in (b.get("beliefs") or [])
    }
    a_ids = {
        (x.get("belief_id"), x.get("version_n")) for x in (a.get("beliefs") or [])
    }
    added = sorted(f"{bid}@v{v}" for bid, v in (a_ids - b_ids))
    removed = sorted(f"{bid}@v{v}" for bid, v in (b_ids - a_ids))
    return {
        "version": VERSION,
        "changed": bool(added or removed),
        "added": added,
        "removed": removed,
        "paper_only": True,
        "honesty": (
            "Context-level comparison on paper. changed=false means the belief has not "
            "yet altered any decision, so no behavioural change may be claimed."
        ),
    }
