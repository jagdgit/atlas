"""LI.5b / LI.0a.9 — Hypothesis Learning (scientific beliefs, not P&L alone).

Distinct from IIP.8 ``thesis_tracker`` (per-symbol company theses). Hypotheses
are world/lab beliefs such as “Lower PE stocks outperform in rate-cut regimes.”

Verdicts are gated — never invent support from thin samples.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from atlas.investment.laboratory import (
    LaboratoryContaminationError,
    normalize_laboratory_id,
    transfer_allowed,
)

_log = logging.getLogger("atlas.investment.hypothesis_learning")

VERSION = "li.5b.hypothesis_learning"
STORE_REL = Path("investment") / "hypotheses"
WORLD_DIR = "_world"

HYPOTHESIS_STATUSES = frozenset(
    {"open", "supported", "partially_supported", "rejected", "inconclusive", "expired"}
)
VERDICT_MIN_LINKS = 3  # gated: need linked decisions/attrs before non-inconclusive


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)


def store_dir(
    data_dir: str | Path,
    *,
    laboratory_id: str | None = None,
) -> Path:
    """Lab-scoped dir, or ``_world`` when laboratory_id is null (world hypotheses)."""
    if laboratory_id:
        lab = normalize_laboratory_id(laboratory_id=laboratory_id)
        return Path(data_dir) / STORE_REL / _safe(lab)
    return Path(data_dir) / STORE_REL / WORLD_DIR


def create_hypothesis(
    data_dir: str | Path | None,
    *,
    statement: str,
    domain_tags: list[str] | None = None,
    laboratory_id: str | None = None,
    transfer_class: str = "world",
    linked_decision_ids: list[str] | None = None,
    linked_experiment_ids: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stmt = (statement or "").strip()
    if not stmt:
        raise ValueError("statement is required")
    tc = str(transfer_class or "world").strip().lower()
    if laboratory_id and tc == "strategy" and not transfer_allowed("strategy"):
        # strategy hypotheses must stay lab-scoped — already true via path
        pass
    if not laboratory_id and tc == "strategy":
        raise ValueError("strategy hypotheses require laboratory_id (cannot be world)")
    lab = normalize_laboratory_id(laboratory_id=laboratory_id) if laboratory_id else None
    row: dict[str, Any] = {
        "hypothesis_id": str(uuid4()),
        "created_at": _now(),
        "statement": stmt[:500],
        "domain_tags": [str(t)[:40] for t in (domain_tags or [])][:12],
        "laboratory_id": lab,
        "transfer_class": tc if tc in {"world", "strategy"} else "world",
        "status": "open",
        "linked_decision_ids": [str(x) for x in (linked_decision_ids or [])][:40],
        "linked_experiment_ids": [str(x) for x in (linked_experiment_ids or [])][:20],
        "verdict": None,
        "extra": dict(extra or {}),
        "version": VERSION,
    }
    if data_dir:
        try:
            root = store_dir(data_dir, laboratory_id=lab)
            root.mkdir(parents=True, exist_ok=True)
            path = root / "by_id" / f"{row['hypothesis_id']}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
            with (root / "index.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"hypothesis_id": row["hypothesis_id"], "at": row["created_at"]}) + "\n")
        except Exception:  # noqa: BLE001
            _log.debug("hypothesis persist failed", exc_info=True)
    return {"hypothesis": row, "version": VERSION}


def get_hypothesis(
    data_dir: str | Path | None,
    hypothesis_id: str,
    *,
    laboratory_id: str | None = None,
) -> dict[str, Any] | None:
    if not data_dir or not hypothesis_id:
        return None
    candidates: list[Path] = []
    if laboratory_id:
        candidates.append(
            store_dir(data_dir, laboratory_id=laboratory_id)
            / "by_id"
            / f"{hypothesis_id}.json"
        )
    # Always allow discovery across labs for hermeticity checks
    root = Path(data_dir) / STORE_REL
    if root.is_dir():
        for lab_dir in root.iterdir():
            p = lab_dir / "by_id" / f"{hypothesis_id}.json"
            if p not in candidates:
                candidates.append(p)
    for path in candidates:
        if path.is_file():
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
                return doc if isinstance(doc, dict) else None
            except Exception:  # noqa: BLE001
                continue
    return None


def list_hypotheses(
    data_dir: str | Path | None,
    *,
    laboratory_id: str | None = None,
    include_world: bool = True,
    status: str | None = None,
    limit: int = 40,
) -> list[dict[str, Any]]:
    if not data_dir:
        return []
    roots: list[Path] = []
    if laboratory_id:
        roots.append(store_dir(data_dir, laboratory_id=laboratory_id))
        if include_world:
            roots.append(store_dir(data_dir, laboratory_id=None))
    else:
        roots.append(store_dir(data_dir, laboratory_id=None))
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in roots:
        by_id = root / "by_id"
        if not by_id.is_dir():
            continue
        for path in sorted(by_id.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(doc, dict):
                continue
            hid = str(doc.get("hypothesis_id") or "")
            if not hid or hid in seen:
                continue
            if status and str(doc.get("status") or "") != status:
                continue
            # Hermeticity: strategy hypotheses from other labs never leak in
            if laboratory_id and doc.get("laboratory_id"):
                if doc.get("laboratory_id") != normalize_laboratory_id(
                    laboratory_id=laboratory_id
                ):
                    continue
            seen.add(hid)
            rows.append(doc)
            if len(rows) >= limit:
                return rows
    return rows


def link_decision(
    data_dir: str | Path | None,
    *,
    hypothesis_id: str,
    decision_id: str,
    laboratory_id: str | None = None,
) -> dict[str, Any] | None:
    row = get_hypothesis(data_dir, hypothesis_id, laboratory_id=laboratory_id)
    if not row or not data_dir:
        return None
    lab = row.get("laboratory_id")
    if laboratory_id and lab and lab != normalize_laboratory_id(laboratory_id=laboratory_id):
        raise LaboratoryContaminationError(
            f"hypothesis {hypothesis_id} belongs to {lab}, not {laboratory_id}"
        )
    ids = list(row.get("linked_decision_ids") or [])
    did = str(decision_id)
    if did and did not in ids:
        ids.append(did)
    row["linked_decision_ids"] = ids[-40:]
    row["updated_at"] = _now()
    root = store_dir(data_dir, laboratory_id=lab)
    path = root / "by_id" / f"{hypothesis_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
    return row


def record_verdict(
    data_dir: str | Path | None,
    *,
    hypothesis_id: str,
    verdict: str,
    laboratory_id: str | None = None,
    evidence_n: int | None = None,
    note: str = "",
    force: bool = False,
) -> dict[str, Any]:
    """Apply a gated verdict. Thin evidence → inconclusive unless force."""
    v = str(verdict or "").strip().lower()
    if v not in HYPOTHESIS_STATUSES - {"open"}:
        raise ValueError(
            f"invalid verdict {verdict!r}; expected one of "
            f"{sorted(HYPOTHESIS_STATUSES - {'open'})}"
        )
    row = get_hypothesis(data_dir, hypothesis_id, laboratory_id=laboratory_id)
    if not row:
        raise ValueError(f"hypothesis {hypothesis_id} not found")
    lab = row.get("laboratory_id")
    if laboratory_id and lab and lab != normalize_laboratory_id(laboratory_id=laboratory_id):
        raise LaboratoryContaminationError(
            f"hypothesis {hypothesis_id} belongs to {lab}, not {laboratory_id}"
        )
    n_links = evidence_n
    if n_links is None:
        n_links = len(row.get("linked_decision_ids") or []) + len(
            row.get("linked_experiment_ids") or []
        )
    gated = v
    gate_note = None
    if not force and n_links < VERDICT_MIN_LINKS and v not in {"inconclusive", "expired"}:
        gated = "inconclusive"
        gate_note = (
            f"evidence thin (links={n_links} < {VERDICT_MIN_LINKS}) — "
            f"requested {v!r}, recorded inconclusive"
        )
    row["status"] = gated
    row["verdict"] = {
        "at": _now(),
        "verdict": gated,
        "requested": v,
        "evidence_n": n_links,
        "note": (note or gate_note or "")[:400],
        "force": bool(force),
        "version": VERSION,
    }
    row["updated_at"] = _now()
    if data_dir:
        root = store_dir(data_dir, laboratory_id=lab)
        path = root / "by_id" / f"{hypothesis_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
    return {"hypothesis": row, "version": VERSION}


def hypothesis_link_count(
    packets: list[dict[str, Any]] | None,
    attributions: list[dict[str, Any]] | None = None,
) -> int:
    """Count rows with LI.0a.9 hypothesis_id (not merely prior_thesis_id)."""
    n = 0
    for p in packets or []:
        if isinstance(p, dict) and p.get("hypothesis_id"):
            n += 1
    for a in attributions or []:
        if not isinstance(a, dict):
            continue
        payload = a.get("payload") if isinstance(a.get("payload"), dict) else {}
        extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
        if a.get("hypothesis_id") or payload.get("hypothesis_id") or extra.get("hypothesis_id"):
            n += 1
    return n
