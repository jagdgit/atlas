"""Career mission wiring helpers — single-step LinkedIn export → Observer (CI.1+)."""

from __future__ import annotations

import logging
from typing import Any

from atlas.missions.programs import program_label

_LOG = logging.getLogger("atlas.career.wiring")

_PROGRAM = "personal_intelligence"
_OBSERVER_TEMPLATE = "career_observer"
_OBSERVER_TITLE = "Personal Intelligence · Career Observer"
_ADVISOR_TEMPLATE = "job_hunting"


def ensure_career_observer_with_export(
    *,
    path: str,
    missions: Any | None = None,
    configuration: Any | None = None,
    templates: Any | None = None,
    also_wire_advisor_jobs_asset: bool = True,
    jobs_asset_name: str = "linkedin_export_jobs",
) -> dict[str, Any]:
    """Idempotently ensure Career Observer knows this export path (one-step ingest).

    Creates the Observer mission if missing; otherwise appends ``path`` to
    ``linkedin_export_paths``. Optionally wires the Advisor to the Observer's
    ``linkedin_export_jobs`` asset name (Advisor still ranks; Observer discovers).
    """
    path_s = (path or "").strip()
    if not path_s:
        return {"ok": False, "reason": "empty export path"}

    out: dict[str, Any] = {"ok": True, "path": path_s, "observer": None, "advisor": None}

    if missions is None or configuration is None:
        out["ok"] = False
        out["reason"] = "missions/configuration unavailable — paste path into Observer config later"
        return out

    mission = _find_mission(missions, template=_OBSERVER_TEMPLATE, title_substr="Career Observer")
    created = False
    if mission is None and templates is not None:
        try:
            result = templates.instantiate(
                _OBSERVER_TEMPLATE,
                title=_OBSERVER_TITLE,
                objective="Discover career knowledge from LinkedIn export / job feeds (never recommend)",
                config_overrides={
                    "linkedin_export_paths": [path_s],
                    "register_job_assets": True,
                    "wire_advisor_sources": False,
                    "seed_watchlist": True,
                },
                labels=[program_label(_PROGRAM), f"role:{_OBSERVER_TEMPLATE}"],
                metadata={
                    "program_id": _PROGRAM,
                    "template": _OBSERVER_TEMPLATE,
                    "role": "Career Observer",
                    "ci": "CI.1",
                },
                activate=True,
                autostart=True,
            )
            mission = result.get("mission")
            created = True
            out["observer"] = {
                "ok": True,
                "created": True,
                "mission_id": str(getattr(mission, "id", None) or (mission or {}).get("id") or ""),
                "linkedin_export_paths": [path_s],
            }
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("career_observer instantiate failed: %s", exc)
            out["observer"] = {"ok": False, "reason": str(exc)[:240]}
            return out

    if mission is None:
        out["observer"] = {
            "ok": False,
            "reason": (
                "no Career Observer mission and templates unavailable — "
                "start Personal Intelligence program or instantiate career_observer"
            ),
        }
        return out

    if not created:
        mid = getattr(mission, "id", None) or mission.get("id")
        active = configuration.get_active(mid)
        if active is None:
            out["observer"] = {"ok": False, "reason": "Career Observer has no active config", "mission_id": str(mid)}
            return out
        doc = dict(getattr(active, "document", None) or active.get("document") or {})
        paths = [str(p) for p in (doc.get("linkedin_export_paths") or []) if str(p).strip()]
        if path_s not in paths:
            paths.append(path_s)
        doc["linkedin_export_paths"] = paths
        doc.setdefault("register_job_assets", True)
        doc.setdefault("seed_watchlist", True)
        cfg = configuration.update_config(
            mid,
            doc,
            change_note=f"CI.1 wire LinkedIn export path {path_s}",
            activate=True,
        )
        out["observer"] = {
            "ok": True,
            "created": False,
            "mission_id": str(mid),
            "linkedin_export_paths": paths,
            "config_version": getattr(cfg, "version", None),
        }

    if also_wire_advisor_jobs_asset and missions is not None and configuration is not None:
        try:
            from atlas.career.feeds import wire_source_to_career_advisor

            out["advisor"] = wire_source_to_career_advisor(
                missions=missions,
                configuration=configuration,
                source_name=jobs_asset_name,
            )
        except Exception as exc:  # noqa: BLE001
            out["advisor"] = {"ok": False, "reason": str(exc)[:200]}

    return out


def _find_mission(missions: Any, *, template: str, title_substr: str) -> Any | None:
    rows: list[Any] = []
    if hasattr(missions, "list_missions"):
        try:
            rows = list(missions.list_missions(limit=200) or [])
        except TypeError:
            try:
                rows = list(missions.list_missions(status="active", limit=200) or [])
            except TypeError:
                rows = []
    elif hasattr(missions, "list"):
        try:
            rows = list(missions.list() or [])
        except TypeError:
            rows = []

    for m in rows:
        status = str(getattr(m, "status", None) or (m.get("status") if isinstance(m, dict) else "") or "")
        if status in {"archived", "completed", "failed"}:
            continue
        title = str(getattr(m, "title", None) or (m.get("title") if isinstance(m, dict) else "") or "")
        labels = getattr(m, "labels", None) or (m.get("labels") if isinstance(m, dict) else None) or []
        label_s = " ".join(str(x) for x in labels) if not isinstance(labels, str) else labels
        meta = getattr(m, "metadata", None) or (m.get("metadata") if isinstance(m, dict) else None) or {}
        tmpl = str(meta.get("template") or "")
        if tmpl == template or f"role:{template}" in label_s or title_substr in title:
            return m
    return None
