"""Template service (Phase A · §A.5) — seed built-ins + instantiate missions.

The instantiation orchestrator: it turns a **template** into a concrete **Mission + config v1 +
worker rows** in one call (Docker-Compose-like). Kept as its own kernel service rather than a
method on ``MissionService`` so the Mission Manager stays free of hard dependencies on the
Configuration Manager and Worker Manager (it composes them here instead).

Seeds the built-in templates by name on boot (B7: upsert, bump `template_version` in code;
existing operator missions keep the version they were instantiated with).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from atlas.exceptions.base import AtlasError
from atlas.missions.templates.builtins import BUILTIN_TEMPLATES
from atlas.models.template import MissionTemplate
from atlas.services.base import HealthStatus

if TYPE_CHECKING:
    from atlas.configuration.service import ConfigurationService
    from atlas.missions.service import MissionService
    from atlas.repositories.template_repo import TemplateRepository
    from atlas.workers.manager import WorkerManager


class TemplateError(AtlasError):
    """A template operation was invalid (unknown template)."""


class TemplateService:
    name = "templates"
    VERSION = "1"

    def __init__(
        self,
        template_repo: "TemplateRepository",
        mission_service: "MissionService",
        configuration_service: "ConfigurationService",
        worker_manager: "WorkerManager",
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repo = template_repo
        self._missions = mission_service
        self._configs = configuration_service
        self._workers = worker_manager
        self._logger = logger or logging.getLogger("atlas.missions.templates")

    # --- seeding --------------------------------------------------------

    def seed_builtins(self) -> int:
        """Upsert the built-in templates by name (idempotent). Returns the count."""
        n = 0
        for spec in BUILTIN_TEMPLATES:
            try:
                self._repo.upsert_by_name(**spec)
                n += 1
            except Exception:  # noqa: BLE001 - a bad built-in must not fail boot
                self._logger.exception("failed to seed template %s", spec.get("name"))
        self._logger.info("seeded %d built-in template(s)", n)
        return n

    # --- reads ----------------------------------------------------------

    def list_templates(self) -> list[MissionTemplate]:
        return self._repo.list()

    def get_template(self, name: str) -> MissionTemplate | None:
        return self._repo.get_by_name(name)

    # --- instantiation --------------------------------------------------

    def instantiate(
        self,
        template_name: str,
        *,
        title: str | None = None,
        objective: str = "",
        config_overrides: dict[str, Any] | None = None,
        labels: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        scheduling_policy: str = "background",
        priority: int = 0,
        criticality: str = "normal",
        budget: dict[str, Any] | None = None,
        activate: bool = True,
        autostart: bool = True,
    ) -> dict[str, Any]:
        """Create a Mission + config v1 (+ workers) from a template (Q2, B7).

        ``config_overrides`` customize the template's ``default_config`` at instantiation.
        Returns ``{"mission", "config", "workers"}``.
        """
        tmpl = self._repo.get_by_name(template_name)
        if tmpl is None:
            raise TemplateError(
                "unknown template", template=template_name,
                known=[t.name for t in self._repo.list()],
            )

        mission = self._missions.create_mission(
            title or tmpl.name,
            objective,
            scheduling_policy=scheduling_policy,
            priority=priority,
            criticality=criticality,
            budget=budget,
            labels=labels,
            metadata=metadata,
            knowledge_domains=list(tmpl.knowledge_domains),
            success_criteria=dict(tmpl.success_criteria),
            template_id=tmpl.id,
            template_version=tmpl.template_version,
        )

        document = {**dict(tmpl.default_config), **(config_overrides or {})}
        config = self._configs.create_config(
            mission.id,
            tmpl.config_schema_type,
            document,
            change_note=f"instantiated from template {tmpl.name} v{tmpl.template_version}",
        )

        if activate:
            mission = self._missions.activate(mission.id, f"instantiated from {tmpl.name}")

        workers = []
        for spec in tmpl.worker_specs:
            worker = self._workers.create_worker(
                mission.id,
                spec["type"],
                interval_seconds=int(spec.get("interval_seconds", 60)),
                autostart=autostart,
            )
            workers.append(worker)

        self._logger.info(
            "instantiated mission %s from template %s v%d (%d worker(s))",
            mission.id, tmpl.name, tmpl.template_version, len(workers),
        )
        return {"mission": mission, "config": config, "workers": workers}

    # --- lifecycle (kernel service) ------------------------------------

    def start(self) -> None:
        self.seed_builtins()

    def stop(self) -> None:
        return None

    def health_check(self) -> HealthStatus:
        try:
            count = len(self._repo.list())
        except Exception as exc:  # noqa: BLE001 - health probe must not raise
            return HealthStatus.fail(f"template repo unreachable: {exc}")
        return HealthStatus.ok(f"{count} template(s) available", templates=count)
