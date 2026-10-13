"""Learning quarantine — keep process-invalid closes out of training.

The ledger is never rewritten. A quarantined experience stays on disk for
audit, but every learning consumer (FEL datasets, hypothesis verdicts, any
future policy learner) must skip it. Entries are append-only; a later row
with ``action="release"`` lifts the quarantine.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_log = logging.getLogger("atlas.investment.learning_quarantine")

VERSION = "deli.learning_quarantine.v1"
QUARANTINE_REL = Path("investment") / "integrity" / "learning_quarantine"


def quarantine_path(data_dir: str | Path | None, laboratory_id: str) -> Path | None:
    if not data_dir or not laboratory_id:
        return None
    return Path(data_dir) / QUARANTINE_REL / f"{laboratory_id}.jsonl"


def quarantined_ids(data_dir: str | Path | None, laboratory_id: str) -> set[str]:
    path = quarantine_path(data_dir, laboratory_id)
    if path is None or not path.is_file():
        return set()
    held: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        eid = str(row.get("experience_id") or "").strip()
        if not eid:
            continue
        if str(row.get("action") or "quarantine") == "release":
            held.discard(eid)
        else:
            held.add(eid)
    return held


def quarantine_experiences(
    data_dir: str | Path | None,
    laboratory_id: str,
    *,
    experience_ids: Iterable[str],
    reasons: list[str],
    note: str,
    by: str = "operator",
) -> dict[str, Any]:
    path = quarantine_path(data_dir, laboratory_id)
    if path is None:
        return {"ok": False, "reason": "no_path"}
    already = quarantined_ids(data_dir, laboratory_id)
    now = datetime.now(timezone.utc).isoformat()
    added: list[str] = []
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for eid in experience_ids:
            eid_s = str(eid or "").strip()
            if not eid_s or eid_s in already:
                continue
            fh.write(
                json.dumps(
                    {
                        "version": VERSION,
                        "action": "quarantine",
                        "experience_id": eid_s,
                        "laboratory_id": laboratory_id,
                        "reasons": list(reasons),
                        "note": note,
                        "by": by,
                        "at": now,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
            added.append(eid_s)
    return {"ok": True, "path": str(path), "added": added, "already": sorted(already)}


def is_learning_eligible(
    exp: dict[str, Any] | None,
    *,
    quarantined: set[str] | None = None,
) -> bool:
    """False when the close is quarantined or stamped ineligible at close time."""
    if not isinstance(exp, dict):
        return False
    elig = exp.get("learning_eligibility")
    if isinstance(elig, dict) and elig.get("eligible") is False:
        return False
    if quarantined and str(exp.get("experience_id") or "") in quarantined:
        return False
    return True
