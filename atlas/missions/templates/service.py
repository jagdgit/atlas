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
from atlas.missions.templates.resources import profile_from_template_criteria
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
        scheduling_policy: str | None = None,
        priority: int = 0,
        criticality: str | None = None,
        budget: dict[str, Any] | None = None,
        activate: bool = True,
        autostart: bool = True,
    ) -> dict[str, Any]:
        """Create a Mission + config v1 (+ workers) from a template (Q2, B7).

        ``config_overrides`` customize the template's ``default_config`` at instantiation.
        IR-RO3: template ``success_criteria.resources`` supplies service class, criticality,
        scheduling policy, and budget defaults when callers omit them.
        Returns ``{"mission", "config", "workers", "resources"}``.
        """
        tmpl = self._repo.get_by_name(template_name)
        if tmpl is None:
            raise TemplateError(
                "unknown template", template=template_name,
                known=[t.name for t in self._repo.list()],
            )

        profile = profile_from_template_criteria(
            tmpl.success_criteria, template_name=tmpl.name
        )
        effective_policy = scheduling_policy or profile.scheduling_policy
        effective_criticality = criticality or profile.criticality
        effective_budget = {**profile.budget_defaults(), **(budget or {})}

        mission_meta = dict(metadata or {})
        for key, value in profile.metadata_fields().items():
            if key not in mission_meta or mission_meta.get(key) is None:
                mission_meta[key] = value
        if "queue" not in mission_meta:
            from atlas.core.resources.mission_queue import QUEUE_READY, queue_block

            if mission_meta.get("queued_for_capacity"):
                from atlas.core.resources.mission_queue import QUEUE_WAITING_HOST

                mission_meta["queue"] = queue_block(
                    state=QUEUE_WAITING_HOST,
                    reason=str(mission_meta.get("queue_reason") or "queued_for_capacity"),
                    owner={
                        "program": mission_meta.get("program_id"),
                        "operator": mission_meta.get("operator") or "operator",
                    },
                )
            else:
                mission_meta["queue"] = queue_block(
                    state=QUEUE_READY,
                    reason="admitted",
                    owner={
                        "program": mission_meta.get("program_id"),
                        "operator": mission_meta.get("operator") or "operator",
                    },
                )

        mission = self._missions.create_mission(
            title or tmpl.name,
            objective,
            scheduling_policy=effective_policy,
            priority=priority,
            criticality=effective_criticality,
            budget=effective_budget,
            labels=labels,
            metadata=mission_meta,
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
            cron = spec.get("cron") or spec.get("cron_expr")
            worker_meta: dict[str, Any] = {
                "service_class": profile.service_class,
                "program_id": mission_meta.get("program_id"),
                "ops": {
                    "expected_tick_ms": profile.expected_tick_ms,
                    "service_class": profile.service_class,
                },
            }
            if mission_meta.get("queued_for_capacity"):
                worker_meta["queued_for_capacity"] = True
                worker_meta["queue_reason"] = mission_meta.get("queue_reason")
            worker = self._workers.create_worker(
                mission.id,
                spec["type"],
                interval_seconds=int(spec.get("interval_seconds", 60)),
                cron_expr=str(cron) if cron else None,
                metadata=worker_meta,
                autostart=autostart,
            )
            workers.append(worker)

        self._logger.info(
            "instantiated mission %s from template %s v%d (%d worker(s), class=%s)",
            mission.id, tmpl.name, tmpl.template_version, len(workers),
            profile.service_class,
        )
        return {
            "mission": mission,
            "config": config,
            "workers": workers,
            "resources": profile.as_dict(),
        }

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
