"""Preflight checks (S22) — validate config + probe dependencies without starting.

``atlas doctor`` runs these to answer "will this box actually run Atlas?" *before*
spinning up worker threads or binding the API. Checks are split in two:

- **config checks** — pure, offline, deterministic (paths writable, API keys set,
  worker/job sizing, sandbox backend valid, backup tooling present);
- **dependency probes** — hit the real datastore + LLM provider (skippable with
  ``--offline``) by calling the already-wired services' ``health_check`` (no start).

Each check is a ``Check(name, status, detail)`` where status is ok / warn / fail.
``worst_status`` folds them so the CLI can exit non-zero only on a real failure.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from atlas.config import AtlasConfig
    from atlas.kernel.application import Application

CHECK_OK = "ok"
CHECK_WARN = "warn"
CHECK_FAIL = "fail"

_ORDER = {CHECK_OK: 0, CHECK_WARN: 1, CHECK_FAIL: 2}


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def worst_status(checks: list[Check]) -> str:
    return max((c.status for c in checks), key=lambda s: _ORDER.get(s, 0), default=CHECK_OK)


def check_config(cfg: "AtlasConfig") -> list[Check]:
    checks: list[Check] = []

    # API keys — the API fails closed (all /v1 routes 401) with none set.
    if cfg.api.keys:
        checks.append(Check("api.keys", CHECK_OK, f"{len(cfg.api.keys)} key(s) configured"))
    else:
        checks.append(Check(
            "api.keys", CHECK_WARN,
            "no API keys set — every /v1 route returns 401 (set ATLAS_API_KEYS)",
        ))

    # Worker/job sizing — jobs interleave on the worker pool; too few workers queues them.
    if cfg.scheduler.workers >= cfg.jobs.max_concurrent:
        checks.append(Check(
            "scheduler.workers", CHECK_OK,
            f"{cfg.scheduler.workers} worker(s) for up to {cfg.jobs.max_concurrent} concurrent job(s)",
        ))
    else:
        checks.append(Check(
            "scheduler.workers", CHECK_WARN,
            f"workers ({cfg.scheduler.workers}) < jobs.max_concurrent "
            f"({cfg.jobs.max_concurrent}): jobs will queue rather than interleave",
        ))

    # Writable data paths.
    for name in ("data", "documents", "logs", "backups"):
        path = Path(getattr(cfg.paths, name))
        checks.append(_check_writable(f"paths.{name}", path))

    # Sandbox backend must be a known value.
    if cfg.sandbox.backend in ("subprocess", "docker"):
        checks.append(Check("sandbox.backend", CHECK_OK, cfg.sandbox.backend))
    else:
        checks.append(Check(
            "sandbox.backend", CHECK_FAIL,
            f"unknown backend '{cfg.sandbox.backend}' (expected subprocess|docker)",
        ))

    # Backup tooling present when scheduled backups are enabled.
    if cfg.backup.enabled:
        if shutil.which(cfg.backup.pg_dump_path):
            checks.append(Check("backup.pg_dump", CHECK_OK, cfg.backup.pg_dump_path))
        else:
            checks.append(Check(
                "backup.pg_dump", CHECK_WARN,
                f"'{cfg.backup.pg_dump_path}' not found on PATH — scheduled backups will fail",
            ))

    return checks


def probe_dependencies(app: "Application") -> list[Check]:
    """Probe the real datastore + LLM by calling their health checks (no start)."""
    checks: list[Check] = []
    for name in ("database", "llm"):
        checks.append(_probe_service(app, name))
    return checks


def run_preflight(cfg: "AtlasConfig", app: "Application | None" = None) -> list[Check]:
    checks = check_config(cfg)
    if app is not None:
        checks.extend(probe_dependencies(app))
    return checks


def _check_writable(name: str, path: Path) -> Check:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return Check(name, CHECK_FAIL, f"cannot create {path}: {exc}")
    if os.access(path, os.W_OK):
        return Check(name, CHECK_OK, str(path))
    return Check(name, CHECK_FAIL, f"not writable: {path}")


def _probe_service(app: "Application", name: str) -> Check:
    try:
        service = app.registry.get(name)
    except Exception:  # noqa: BLE001 - service not registered
        return Check(name, CHECK_WARN, "service not registered")
    try:
        status = service.health_check()
    except Exception as exc:  # noqa: BLE001 - a probe must never raise
        return Check(name, CHECK_FAIL, f"health check raised: {exc}")
    level = getattr(status, "level", CHECK_OK if status.healthy else CHECK_FAIL)
    mapped = {"ok": CHECK_OK, "degraded": CHECK_WARN, "failed": CHECK_FAIL}.get(
        level, CHECK_OK if status.healthy else CHECK_FAIL
    )
    return Check(name, mapped, status.detail)
