"""Scheduler hierarchy — Program → Mission → Worker tick (OI-PA-SCHED / SCHED.1).

Workers still fire via durable ``scheduler.schedules`` (Phase A). This service
makes the *intended* cadence hierarchy explicit for operators and for resolving
an effective ``interval_seconds`` when instantiating or aligning workers:

```
Program   (e.g. Market Intelligence runs 24×7 → default 300s)
  → Mission  (News Intelligence hourly → 3600s)
    → Worker (market_observer every 5m → 300s from template)
```

Cascade (most specific wins): worker_specs.interval → mission cadence → program default.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from atlas.missions.programs import BUILTIN_PROGRAMS, get_program, list_programs

# Operator shorthand → ProgramDefinition.id
_PROGRAM_ALIASES = {
    "market": "market_intelligence",
    "markets": "market_intelligence",
    "engineering": "engineering_intelligence",
    "personal": "personal_intelligence",
}


def _resolve_program_id(program_id: str | None) -> str | None:
    if not program_id:
        return None
    key = program_id.strip()
    return _PROGRAM_ALIASES.get(key.lower(), key)

# Program-level default when cadence is "always on"
PROGRAM_DEFAULT_INTERVAL = 300

# Human cadence strings from ProgramMember.cadence → seconds
_CADENCE_MAP: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"continuous|24\s*[×x]?\s*7|with\s+fills", re.I), 300),
    (re.compile(r"on\s+trigger", re.I), 3600),
    (re.compile(r"hourly", re.I), 3600),
    (re.compile(r"daily\s*/\s*weekly|daily", re.I), 86400),
    (re.compile(r"weekly", re.I), 604800),
]


def cadence_to_seconds(cadence: str | None, *, default: int = PROGRAM_DEFAULT_INTERVAL) -> int:
    """Map a Program/Mission cadence label to a tick interval in seconds."""
    text = (cadence or "").strip()
    if not text:
        return default
    # bare integer
    if text.isdigit():
        return max(1, int(text))
    for pattern, seconds in _CADENCE_MAP:
        if pattern.search(text):
            return seconds
    return default


class SchedulerHierarchyService:
    """Operator-facing Program → Mission → Worker schedule view + interval resolve."""

    name = "scheduler_hierarchy"
    VERSION = "sched.1"

    def __init__(
        self,
        *,
        programs: Any | None = None,
        templates: Any | None = None,
        workers: Any | None = None,
        schedules: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._programs = programs
        self._templates = templates
        self._workers = workers
        self._schedules = schedules
        self._logger = logger or logging.getLogger("atlas.scheduler.hierarchy")

    def resolve_interval(
        self,
        *,
        program_id: str | None = None,
        template: str | None = None,
        worker_type: str | None = None,
        cadence: str | None = None,
        worker_interval: int | None = None,
    ) -> dict[str, Any]:
        """Resolve effective interval with cascade explanation."""
        layers: list[dict[str, Any]] = []
        program_interval = PROGRAM_DEFAULT_INTERVAL
        program_id = _resolve_program_id(program_id)
        if program_id:
            prog = get_program(program_id)
            if prog is not None:
                program_interval = PROGRAM_DEFAULT_INTERVAL
                layers.append(
                    {
                        "layer": "program",
                        "id": prog.id,
                        "interval_seconds": program_interval,
                        "note": "Program default (24×7)",
                    }
                )

        mission_interval: int | None = None
        member_cadence = cadence
        if program_id and template:
            prog = get_program(program_id)
            if prog is not None:
                for m in prog.members:
                    if m.template == template or (
                        template == "paper_trading"
                        and m.template == "decision_simulation"
                    ):
                        member_cadence = member_cadence or m.cadence
                        break
        if member_cadence:
            mission_interval = cadence_to_seconds(member_cadence)
            layers.append(
                {
                    "layer": "mission",
                    "template": template,
                    "cadence": member_cadence,
                    "interval_seconds": mission_interval,
                }
            )

        tpl_worker_interval = worker_interval
        if tpl_worker_interval is None and template:
            tpl_worker_interval = self._template_worker_interval(
                template, worker_type=worker_type
            )
        if tpl_worker_interval is not None:
            layers.append(
                {
                    "layer": "worker",
                    "worker_type": worker_type or template,
                    "interval_seconds": int(tpl_worker_interval),
                    "note": "template worker_specs",
                }
            )

        # Most specific wins: worker > mission > program
        effective = program_interval
        source = "program"
        if mission_interval is not None:
            effective = mission_interval
            source = "mission"
        if tpl_worker_interval is not None:
            effective = int(tpl_worker_interval)
            source = "worker"

        return {
            "interval_seconds": effective,
            "source": source,
            "layers": layers,
            "program_id": program_id,
            "template": template,
            "worker_type": worker_type,
            "version": self.VERSION,
        }

    def view(self, program_id: str | None = None) -> dict[str, Any]:
        """Full hierarchy tree for one Program or all Programs."""
        programs = []
        program_id = _resolve_program_id(program_id)
        targets = [get_program(program_id)] if program_id else list_programs()
        for prog in targets:
            if prog is None:
                continue
            members_out: list[dict[str, Any]] = []
            for member in prog.members:
                resolved = self.resolve_interval(
                    program_id=prog.id,
                    template=member.template,
                    cadence=member.cadence,
                )
                workers_live = self._live_workers(prog.id, member.template)
                members_out.append(
                    {
                        "role": member.role,
                        "template": member.template,
                        "cadence": member.cadence,
                        "status": member.status,
                        "resolved": resolved,
                        "workers": workers_live,
                    }
                )
            programs.append(
                {
                    "id": prog.id,
                    "title": prog.title,
                    "default_interval_seconds": PROGRAM_DEFAULT_INTERVAL,
                    "members": members_out,
                }
            )
        return {
            "programs": programs,
            "cascade": "worker_specs > mission cadence > program default",
            "version": self.VERSION,
        }

    def suggest_for_template(
        self, template: str, *, program_id: str | None = None
    ) -> dict[str, Any]:
        """Interval suggestion when instantiating a mission template."""
        pid = program_id
        if pid is None:
            for p in BUILTIN_PROGRAMS:
                if template in p.member_templates() or (
                    template == "paper_trading" and "decision_simulation" in p.member_templates()
                ):
                    pid = p.id
                    break
        return self.resolve_interval(program_id=pid, template=template)

    def _template_worker_interval(
        self, template_name: str, *, worker_type: str | None = None
    ) -> int | None:
        if self._templates is None:
            return None
        try:
            rows = self._templates.list_templates()
        except Exception:  # noqa: BLE001
            return None
        for t in rows or []:
            name = getattr(t, "name", None) or (t.get("name") if isinstance(t, dict) else None)
            if name != template_name:
                continue
            specs = getattr(t, "worker_specs", None)
            if specs is None and isinstance(t, dict):
                specs = t.get("worker_specs")
            if not specs and hasattr(t, "to_dict"):
                specs = (t.to_dict() or {}).get("worker_specs")
            for spec in specs or []:
                if not isinstance(spec, dict):
                    continue
                if worker_type and spec.get("type") != worker_type:
                    continue
                iv = spec.get("interval_seconds")
                if iv is not None:
                    return int(iv)
            break
        return None

    def _live_workers(self, program_id: str, template: str) -> list[dict[str, Any]]:
        if self._workers is None:
            return []
        out: list[dict[str, Any]] = []
        try:
            rows = self._workers.list_workers() if hasattr(self._workers, "list_workers") else []
        except Exception:  # noqa: BLE001
            return []
        label = f"program:{program_id}"
        for w in rows or []:
            data = w.to_dict() if hasattr(w, "to_dict") else dict(w)
            wtype = str(data.get("type") or "")
            # Match by worker type ≈ template name (or paper_trading ↔ decision_simulation)
            match = wtype == template or (
                template == "decision_simulation" and wtype == "paper_trading"
            )
            if not match:
                continue
            # Prefer workers whose mission carries the program label when available
            mid = data.get("mission_id")
            out.append(
                {
                    "worker_id": str(data.get("id") or ""),
                    "type": wtype,
                    "status": data.get("status"),
                    "mission_id": str(mid) if mid else None,
                    "schedule_id": str(data.get("schedule_id") or "") or None,
                    "program_label": label,
                }
            )
        return out[:20]
