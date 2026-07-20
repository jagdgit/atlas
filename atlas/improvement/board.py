"""ImprovementBoard — durable surface for self-improvement findings (Phase D · §D.10).

The Operations Dashboard reads this board. The SelfImprovementWatcher writes findings /
recommendations after each eval tick; the ApprovalService applier records operator-approved
intents. Survives reboot via a small JSON file under the data directory.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ImprovementBoard:
    name = "improvement_board"
    VERSION = "1.0.0"

    def __init__(
        self,
        data_dir: str | Path,
        *,
        max_items: int = 50,
        logger: logging.Logger | None = None,
    ) -> None:
        self._path = Path(data_dir) / "improvement" / "board.json"
        self._max = max_items
        self._logger = logger or logging.getLogger("atlas.improvement.board")
        self._data = self._load()

    def snapshot(self) -> dict[str, Any]:
        return {
            "last_run": self._data.get("last_run"),
            "findings": list(self._data.get("findings") or []),
            "recommendations": list(self._data.get("recommendations") or []),
            "approved": list(self._data.get("approved") or []),
            "finding_count": len(self._data.get("findings") or []),
            "open_recommendations": len(self._data.get("recommendations") or []),
        }

    def record_run(
        self,
        *,
        metrics: dict[str, float],
        findings: list[dict[str, Any]],
        decision_id: str | None = None,
        recommendation: dict[str, Any] | None = None,
        milestone: str | None = None,
    ) -> None:
        self._data["last_run"] = {
            "at": _now(),
            "milestone": milestone,
            "decision_id": decision_id,
            "metric_count": len(metrics),
            "finding_count": len(findings),
            "metrics": metrics,
        }
        for finding in findings:
            self._push("findings", {**finding, "recorded_at": _now()})
        if recommendation:
            self._push("recommendations", {
                **recommendation,
                "decision_id": decision_id,
                "recorded_at": _now(),
                "status": "proposed",
            })
        self._save()

    def record_approved(self, action: dict[str, Any], *, decision_id: Any = None) -> dict[str, Any]:
        row = {
            "action": action,
            "decision_id": str(decision_id) if decision_id else None,
            "approved_at": _now(),
            "status": "approved",
        }
        self._push("approved", row)
        # Mark matching open recommendation as approved when possible.
        rid = (action.get("finding_id") or action.get("id") or "")
        for rec in self._data.get("recommendations") or []:
            if rid and (
                rec.get("finding_id") == rid
                or (rec.get("payload") or {}).get("finding_id") == rid
                or str(rec.get("decision_id")) == str(decision_id)
            ):
                rec["status"] = "approved"
        self._save()
        return row

    def revert_approved(self, decision_id: Any) -> None:
        approved = [
            a for a in (self._data.get("approved") or [])
            if str(a.get("decision_id")) != str(decision_id)
        ]
        self._data["approved"] = approved[-self._max :]
        self._save()

    def _push(self, key: str, item: dict[str, Any]) -> None:
        items = list(self._data.get(key) or [])
        items.insert(0, item)
        self._data[key] = items[: self._max]

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"findings": [], "recommendations": [], "approved": [], "last_run": None}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {
                "findings": [], "recommendations": [], "approved": [], "last_run": None
            }
        except Exception:  # noqa: BLE001
            self._logger.warning("improvement board unreadable; starting fresh")
            return {"findings": [], "recommendations": [], "approved": [], "last_run": None}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            self._logger.exception("failed to persist improvement board")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
