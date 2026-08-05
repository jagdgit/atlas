"""Career Memory v0 — operator watchlist + status (CI.1.4).

Persists under ``data/career/watchlist.json`` (or ``ATLAS_CAREER_DIR``). Discover-only
workers may seed companies/jobs; the operator owns ``operator_status``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()
_LOG = logging.getLogger("atlas.career.watchlist")

VALID_STATUS = frozenset(
    {"watching", "interested", "applied", "passed", "hired", "archived"}
)
VALID_KIND = frozenset({"company", "job", "skill", "role"})


def persist_dir() -> Path:
    env = (os.environ.get("ATLAS_CAREER_DIR") or "").strip()
    if env:
        return Path(env)
    data = (os.environ.get("ATLAS_DATA_DIR") or "").strip()
    if data:
        return Path(data) / "career"
    return Path("data") / "career"


def _path() -> Path:
    return persist_dir() / "watchlist.json"


def _load() -> dict[str, Any]:
    path = _path()
    if not path.is_file():
        return {"items": [], "updated_at": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            items = data.get("items")
            if not isinstance(items, list):
                data["items"] = []
            return data
    except Exception as exc:  # noqa: BLE001
        _LOG.debug("career watchlist load skipped: %s", exc)
    return {"items": [], "updated_at": None}


def _save(payload: dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["updated_at"] = time.time()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, default=str, indent=2), encoding="utf-8")
    tmp.replace(path)


def list_items(*, status: str | None = None, kind: str | None = None) -> dict[str, Any]:
    with _LOCK:
        data = _load()
        items = [x for x in (data.get("items") or []) if isinstance(x, dict)]
        if status:
            items = [x for x in items if str(x.get("operator_status") or "") == status]
        if kind:
            items = [x for x in items if str(x.get("kind") or "") == kind]
        return {
            "ok": True,
            "items": items,
            "count": len(items),
            "updated_at": data.get("updated_at"),
            "path": str(_path()),
            "policy": "operator_owned",
        }


def upsert(
    *,
    label: str,
    kind: str = "company",
    operator_status: str = "watching",
    notes: str | None = None,
    external_id: str | None = None,
    url: str | None = None,
    item_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    label_s = (label or "").strip()
    if not label_s:
        raise ValueError("label is required")
    kind_s = (kind or "company").strip().lower()
    if kind_s not in VALID_KIND:
        raise ValueError(f"kind must be one of {sorted(VALID_KIND)}")
    status_s = (operator_status or "watching").strip().lower()
    if status_s not in VALID_STATUS:
        raise ValueError(f"operator_status must be one of {sorted(VALID_STATUS)}")

    with _LOCK:
        data = _load()
        items: list[dict[str, Any]] = [
            x for x in (data.get("items") or []) if isinstance(x, dict)
        ]
        target: dict[str, Any] | None = None
        if item_id:
            for row in items:
                if str(row.get("id")) == item_id:
                    target = row
                    break
        if target is None and external_id:
            for row in items:
                if str(row.get("external_id") or "") == external_id:
                    target = row
                    break
        if target is None:
            key = _norm_key(kind_s, label_s)
            for row in items:
                if _norm_key(str(row.get("kind") or ""), str(row.get("label") or "")) == key:
                    target = row
                    break

        now = time.time()
        if target is None:
            target = {
                "id": str(uuid.uuid4()),
                "kind": kind_s,
                "label": label_s,
                "operator_status": status_s,
                "notes": (notes or "").strip() or None,
                "external_id": (external_id or "").strip() or None,
                "url": (url or "").strip() or None,
                "meta": dict(meta or {}),
                "created_at": now,
                "updated_at": now,
            }
            items.append(target)
        else:
            target["kind"] = kind_s
            target["label"] = label_s
            target["operator_status"] = status_s
            if notes is not None:
                target["notes"] = notes.strip() or None
            if external_id is not None:
                target["external_id"] = external_id.strip() or None
            if url is not None:
                target["url"] = url.strip() or None
            if meta:
                merged = dict(target.get("meta") or {})
                merged.update(meta)
                target["meta"] = merged
            target["updated_at"] = now

        data["items"] = items
        _save(data)
        return {"ok": True, "item": target, "count": len(items)}


def seed_companies(
    names: list[str],
    *,
    operator_status: str = "watching",
    source: str = "career_observer",
    limit: int = 40,
) -> dict[str, Any]:
    """Idempotent seed from Observer discoveries — does not overwrite richer statuses."""
    added = 0
    skipped = 0
    for name in names[: max(0, limit)]:
        label = (name or "").strip()
        if not label:
            continue
        with _LOCK:
            data = _load()
            items = [x for x in (data.get("items") or []) if isinstance(x, dict)]
            key = _norm_key("company", label)
            existing = next(
                (
                    x
                    for x in items
                    if _norm_key(str(x.get("kind") or ""), str(x.get("label") or "")) == key
                ),
                None,
            )
            if existing:
                skipped += 1
                continue
        upsert(
            label=label,
            kind="company",
            operator_status=operator_status,
            meta={"seeded_by": source},
        )
        added += 1
    return {"ok": True, "added": added, "skipped": skipped}


def companies_for_filter(*, statuses: list[str] | None = None) -> list[str]:
    want = set(statuses or ["watching", "interested", "applied"])
    out = list_items()
    names: list[str] = []
    for row in out.get("items") or []:
        if str(row.get("kind") or "") != "company":
            continue
        if str(row.get("operator_status") or "") not in want:
            continue
        label = str(row.get("label") or "").strip()
        if label and label not in names:
            names.append(label)
    return names


def _norm_key(kind: str, label: str) -> str:
    raw = f"{kind}:{label}".strip().lower()
    return re.sub(r"\s+", " ", raw)
