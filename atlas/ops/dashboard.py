"""Operations Dashboard aggregator (Phase 0 · ATLAS_OS_ROADMAP §5.11, A4).

Assembles the **single-screen** operator snapshot: Atlas status, live counts, host
metrics (CPU/RAM/disk/internet, temp/UPS best-effort), last backup, capability
inventory, and SSE subscriber count. Every section is guarded so one broken source
degrades to an empty/absent value rather than failing the whole dashboard.

Counts for workers/missions are 0 until Phase A introduces them; ``recovery`` reports the
last startup-recovery pass and ``last_checkpoint`` the most recent resume point (both from
§2.8). The design leaves keys in place so the UI doesn't change when values start flowing.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable, TypeVar

if TYPE_CHECKING:
    from atlas.kernel.application import Application
    from atlas.system.host import HostMetrics
    from atlas.system.time import ClockService

T = TypeVar("T")


class OperationsDashboard:
    name = "ops_dashboard"

    def __init__(
        self,
        app: "Application",
        host: "HostMetrics",
        *,
        clock: "ClockService | None" = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._app = app
        self._host = host
        self._clock = clock
        self._logger = logger or logging.getLogger("atlas.ops.dashboard")

    def snapshot(self) -> dict[str, Any]:
        worker_states = self._guard(self._worker_states, {})
        mission_queue = self._guard(self._mission_queue, {})
        host_guard = self._guard(self._host_guard, {})
        program_health = self._guard(
            lambda: self._program_health(worker_states, mission_queue, host_guard),
            {},
        )
        capacity_signal = self._guard(
            lambda: self._capacity_signal(worker_states, mission_queue, host_guard),
            {},
        )
        next_tick = self._guard(
            lambda: self._next_tick_preview(worker_states, host_guard),
            {},
        )
        research_progress = self._guard(self._research_progress, {})
        research_velocity = self._guard(self._research_velocity, {})
        archive_lane = self._guard(lambda: self._archive_lane(host_guard), {})
        # Drop full classified rows from the wire payload (used only for rollups).
        if isinstance(worker_states, dict) and "rows" in worker_states:
            worker_states = {k: v for k, v in worker_states.items() if k != "rows"}
        atlas = self._guard(self._atlas, {})
        return {
            "atlas": atlas,
            "counts": self._guard(self._counts, {}),
            "worker_states": worker_states,
            "mission_queue": mission_queue,
            "program_health": program_health,
            "capacity_signal": capacity_signal,
            "next_tick": next_tick,
            "archive_lane": archive_lane,
            "research_progress": research_progress,
            "research_velocity": research_velocity,
            "glossary": self._guard(self._glossary, {}),
            "reservations": self._guard(self._reservations, {}),
            "storage_pressure": self._guard(self._storage_pressure, {}),
            "budgets": self._guard(self._budgets, {}),
            "machine_profile": self._guard(self._machine_profile, {}),
            "work_admission": self._guard(self._work_admission, {}),
            "power": self._guard(self._power, {}),
            "host": self._guard(self._host.snapshot, {}),
            "host_guard": host_guard,
            "backup": self._guard(self._backup, {}),
            "storage": self._guard(self._storage, {}),
            "capabilities": self._guard(self._capabilities, []),
            "sse_subscribers": self._guard(self._sse_subscribers, 0),
            "recovery": self._guard(self._recovery, {}),
            "last_checkpoint": self._guard(self._last_checkpoint, None),
            "self_improvement": self._guard(self._self_improvement, {}),
            "startup": self._startup_banner(atlas),
            "generated_at": self._now(),
        }

    def summary(self) -> dict[str, Any]:
        """ARMF Phase E — lightweight first paint for Ops UI (fast path)."""
        worker_states = self._guard(self._worker_states, {})
        mission_queue = self._guard(self._mission_queue, {})
        host_guard = self._guard(self._host_guard, {})
        atlas = self._guard(self._atlas, {})
        program_health = self._guard(
            lambda: self._program_health(worker_states, mission_queue, host_guard),
            {},
        )
        capacity_signal = self._guard(
            lambda: self._capacity_signal(worker_states, mission_queue, host_guard),
            {},
        )
        archive_lane = self._guard(lambda: self._archive_lane(host_guard), {})
        # Compact worker counts only (no row dump)
        ws_counts = {}
        if isinstance(worker_states, dict):
            ws_counts = worker_states.get("counts") or {}
        return {
            "version": "armf.e1",
            "atlas": {
                "healthy": atlas.get("healthy"),
                "degraded": atlas.get("degraded"),
                "version": atlas.get("version"),
                "uptime_seconds": atlas.get("uptime_seconds"),
                "subsystem_counts": atlas.get("subsystem_counts"),
            },
            "program_health": program_health,
            "capacity_signal": capacity_signal,
            "archive_lane": archive_lane,
            "host_guard": {
                "max_concurrent_ticks": host_guard.get("max_concurrent_ticks"),
                "max_archive_workers": host_guard.get("max_archive_workers"),
                "archive_workers_running": host_guard.get("archive_workers_running"),
                "running_workers": host_guard.get("running_workers"),
                "capacity_queued_workers": host_guard.get("capacity_queued_workers"),
            },
            "worker_counts": ws_counts,
            "startup": self._startup_banner(atlas),
            "leave_running": {
                "ok_to_leave": bool(atlas.get("healthy")),
                "reminders": [
                    "Paper learner may show 0 buys until MA/RSI fires — strategy_hold is normal.",
                    "Cleanup Apply is idempotent on already-archived zombies.",
                    "Archive stays at 1 slot unless ATLAS_RESOURCES_MAX_ARCHIVE_WORKERS≥2.",
                    "Evening investor email uses session notes for zero-fill honesty.",
                ],
            },
            "generated_at": self._now(),
        }

    def _startup_banner(self, atlas: dict[str, Any] | None) -> dict[str, Any]:
        """Show a warm-up banner for the first minutes after restart."""
        a = atlas if isinstance(atlas, dict) else {}
        up = a.get("uptime_seconds")
        try:
            up_f = float(up) if up is not None else None
        except (TypeError, ValueError):
            up_f = None
        warming = up_f is not None and up_f < 180.0
        return {
            "warming": warming,
            "uptime_seconds": up_f,
            "message": (
                "Atlas recently started — workers and paper ticks are warming up. "
                "Starved chips may clear after a few cycles."
                if warming
                else None
            ),
        }

    # --- sections -------------------------------------------------------

    def _atlas(self) -> dict[str, Any]:
        return self._app.status()

    def _counts(self) -> dict[str, Any]:
        counts: dict[str, Any] = {
            "jobs_total": 0,
            "jobs_active": 0,
            "jobs_queued": 0,
            "workers": 0,     # Phase A
            "missions": 0,    # Phase A
        }
        jobs = self._resolve("jobs")
        if jobs is not None and hasattr(jobs, "list_jobs"):
            rows = jobs.list_jobs(limit=500)
            counts["jobs_total"] = len(rows)
            active = queued = 0
            for j in rows:
                status = getattr(j, "status", None) or (
                    j.get("status") if isinstance(j, dict) else None
                )
                if status in ("queued", "running", "planning", "planning_queued"):
                    active += 1
                if status == "queued":
                    queued += 1
            counts["jobs_active"] = active
            counts["jobs_queued"] = queued

        missions = self._resolve("missions")
        if missions is not None and hasattr(missions, "list_missions"):
            rows = missions.list_missions(limit=500)
            counts["missions"] = len(rows)
            counts["missions_active"] = sum(1 for m in rows if getattr(m, "status", None) == "active")

        workers = self._resolve("workers")
        if workers is not None and hasattr(workers, "health_check"):
            wc = (workers.health_check().data or {}).get("counts", {})
            counts["workers"] = wc.get("running", 0) + wc.get("recovering", 0)
            counts["workers_total"] = sum(wc.values()) if wc else 0
        return counts

    def _worker_states(self) -> dict[str, Any]:
        """IR-OPS1 — Running ticks / Ready / Waiting Host / Starved / Slow / …"""
        workers = self._resolve("workers")
        if workers is None or not hasattr(workers, "ops_state_snapshot"):
            return {}
        return workers.ops_state_snapshot()

    def _mission_queue(self) -> dict[str, Any]:
        """IR-RO2 — Mission Queue states + owners."""
        queue = self._resolve("mission_queue")
        if queue is None or not hasattr(queue, "snapshot"):
            return {}
        return queue.snapshot()

    def _glossary(self) -> dict[str, Any]:
        from atlas.ops.glossary import glossary_snapshot

        return glossary_snapshot()

    def _program_health(
        self,
        worker_states: dict[str, Any],
        mission_queue: dict[str, Any],
        host_guard: dict[str, Any],
    ) -> dict[str, Any]:
        from atlas.ops.program_health import summarize_program_health

        rows = list(worker_states.get("rows") or [])
        if not rows:
            # Fallback: flatten by_program notable + reconstruct thin rows from notable.
            rows = list(worker_states.get("notable") or [])
        items = list(mission_queue.get("items") or mission_queue.get("notable") or [])
        return summarize_program_health(
            rows,
            items,
            host_guard=host_guard,
            hide_types=frozenset({"hello_watcher"}),
        )

    def _capacity_signal(
        self,
        worker_states: dict[str, Any],
        mission_queue: dict[str, Any],
        host_guard: dict[str, Any],
    ) -> dict[str, Any]:
        from atlas.ops.program_health import capacity_idle_signal

        wcounts = worker_states.get("counts") or {}
        qcounts = mission_queue.get("counts") or {}
        arb = (host_guard.get("arbiter") or {}) if isinstance(host_guard, dict) else {}
        tick_in = arb.get("total_inflight")
        if tick_in is None:
            tick_in = wcounts.get("running_ticks") or 0
        res = host_guard.get("resources") or {}
        deferring = res.get("tick_would_admit")
        host_deferring = False if deferring is True else (True if deferring is False else None)
        return capacity_idle_signal(
            tick_inflight=int(tick_in or 0),
            waiting_host_missions=int(qcounts.get("WAITING_HOST") or 0),
            waiting_host_workers=int(wcounts.get("waiting_host") or 0),
            host_deferring=host_deferring,
        )

    def _archive_lane(self, host_guard: dict[str, Any]) -> dict[str, Any]:
        """ARMF Phase D — archive clarity (CPU idle ≠ archive free)."""
        hg = host_guard if isinstance(host_guard, dict) else {}
        max_slots = int(hg.get("max_archive_workers") or 1)
        running = int(hg.get("archive_workers_running") or 0)
        free = max(0, max_slots - running)
        queued = int(hg.get("capacity_queued_workers") or 0)
        opt_in = max_slots >= 2
        return {
            "version": "armf.d1",
            "max_slots": max_slots,
            "running": running,
            "free": free,
            "capacity_queued": queued,
            "opt_in_second_slot": opt_in,
            "note": (
                "CPU idle ≠ archive free. Archive lane is capped separately from "
                "Market tick slots. A free CPU does not mean archive can start."
            ),
            "second_slot_note": (
                f"2nd archive slot opt-in ON (max={max_slots}) via "
                "ATLAS_RESOURCES_MAX_ARCHIVE_WORKERS."
                if opt_in
                else (
                    "2nd archive slot gated off — set ATLAS_RESOURCES_MAX_ARCHIVE_WORKERS=2 "
                    "and restart to opt in (keep 1 during market hours)."
                )
            ),
        }

    def _next_tick_preview(
        self,
        worker_states: dict[str, Any],
        host_guard: dict[str, Any],
    ) -> dict[str, Any]:
        from atlas.ops.research_signals import next_tick_preview

        rows = list(worker_states.get("rows") or worker_states.get("notable") or [])
        arb = {}
        if isinstance(host_guard, dict):
            arb = host_guard.get("arbiter") or {}
        # Prefer live arbiter if resolved
        try:
            live = self._resolve("mission_arbiter")
            if live is not None and hasattr(live, "snapshot"):
                arb = live.snapshot() or arb
        except Exception:  # noqa: BLE001
            pass
        return next_tick_preview(rows, arbiter_snap=arb)

    def _research_progress(self) -> dict[str, Any]:
        from atlas.ops.research_signals import research_progress_snapshot

        data_dir = self._data_dir()
        return research_progress_snapshot(data_dir)

    def _research_velocity(self) -> dict[str, Any]:
        from atlas.ops.research_signals import research_velocity_snapshot

        return research_velocity_snapshot(self._data_dir())

    def _data_dir(self) -> str | None:
        try:
            from atlas.config import get_config

            return str(get_config().paths.data)
        except Exception:  # noqa: BLE001
            return None

    def _reservations(self) -> dict[str, Any]:
        """IR-RO7 — active resource leases."""
        mgr = self._resolve("reservation_manager")
        if mgr is None or not hasattr(mgr, "snapshot"):
            return {}
        return mgr.snapshot()

    def _storage_pressure(self) -> dict[str, Any]:
        """IR-RO6 — disk watermarks."""
        svc = self._resolve("storage_pressure")
        if svc is None or not hasattr(svc, "snapshot"):
            return {}
        return svc.snapshot()

    def _budgets(self) -> dict[str, Any]:
        """IR-RO4 — dynamic effective tick slots + hysteresis."""
        ctrl = self._resolve("budget_controller")
        if ctrl is None or not hasattr(ctrl, "snapshot"):
            return {}
        return ctrl.snapshot()

    def _machine_profile(self) -> dict[str, Any]:
        """IR-RO8 — suggested host profile + preferred tick slots."""
        from atlas.core.resources.machine_profile import detect_machine_profile, profile_catalog

        hard = None
        guard = self._resolve("host_guard")
        if guard is not None and hasattr(guard, "status"):
            try:
                hard = (guard.status() or {}).get("max_concurrent_ticks")
            except Exception:  # noqa: BLE001
                hard = None
        suggestion = detect_machine_profile(hard_tick_ceiling=hard)
        configured = None
        try:
            from atlas.config import get_config

            configured = get_config().resources.profile
        except Exception:  # noqa: BLE001
            configured = None
        cached = self._resolve("machine_profile")
        boot = cached.as_dict() if cached is not None and hasattr(cached, "as_dict") else {}
        return {
            **suggestion.as_dict(),
            "configured_profile": configured,
            "boot_suggestion": boot,
            "catalog": profile_catalog(),
        }

    def _work_admission(self) -> dict[str, Any]:
        """IR-RO10 — should-run-now / BATCH quiet window."""
        policy = self._resolve("work_admission")
        if policy is None or not hasattr(policy, "snapshot"):
            return {}
        return policy.snapshot()

    def _power(self) -> dict[str, Any]:
        """IR-RO9 — power/UPS posture (honest when unmonitored)."""
        from atlas.core.resources.power import probe_power, read_thermal_zones

        power = probe_power()
        zones = [z.as_dict() for z in read_thermal_zones()]
        return {
            **power.as_dict(),
            "thermal": {
                "monitored": bool(zones),
                "hottest_c": max((z["celsius"] for z in zones), default=None),
                "zones": zones,
            },
        }

    def _host_guard(self) -> dict[str, Any]:
        guard = self._resolve("host_guard")
        if guard is None or not hasattr(guard, "status"):
            return {}
        return guard.status()

    def _backup(self) -> dict[str, Any]:
        backup = self._resolve("backup")
        if backup is None or not hasattr(backup, "list_backups"):
            return {"last": None, "count": 0}
        dumps = backup.list_backups()
        return {
            "last": dumps[0].name if dumps else None,
            "count": len(dumps),
        }

    def _storage(self) -> dict[str, Any]:
        storage = self._resolve("storage")
        if storage is None:
            return {}
        health = storage.health_check()
        return {"detail": health.detail, **(health.data or {})}

    def _capabilities(self) -> list[dict[str, Any]]:
        registry = getattr(self._app, "capabilities", None)
        if registry is None or not hasattr(registry, "describe"):
            return []
        out: list[dict[str, Any]] = []
        for name, meta in registry.describe().items():
            out.append(
                {
                    "name": name,
                    "kind": meta.get("kind"),
                    "version": meta.get("version"),
                    "enabled": meta.get("enabled", True),
                }
            )
        return out

    def _recovery(self) -> dict[str, Any]:
        rec = self._resolve("recovery")
        if rec is None or not hasattr(rec, "last_report"):
            return {}
        report = rec.last_report()
        if not report:
            return {"status": None}
        return {
            "status": report.get("status"),
            "ok": report.get("ok"),
            "run_id": report.get("run_id"),
            "steps": [
                {"name": s.get("name"), "ok": s.get("ok"), "detail": s.get("detail")}
                for s in report.get("steps", [])
            ],
        }

    def _last_checkpoint(self) -> dict[str, Any] | None:
        cp = self._resolve("checkpoints")
        if cp is None or not hasattr(cp, "most_recent"):
            return None
        row = cp.most_recent()
        if not row:
            return None
        updated = row.get("updated_at")
        return {
            "owner_type": row.get("owner_type"),
            "owner_id": row.get("owner_id"),
            "label": row.get("label"),
            "updated_at": updated.isoformat() if hasattr(updated, "isoformat") else updated,
        }

    def _self_improvement(self) -> dict[str, Any]:
        """Phase D · §D.10: eval findings + gated recommendations for the operator."""
        board = self._resolve("improvement_board")
        if board is None or not hasattr(board, "snapshot"):
            return {}
        return board.snapshot()

    def _sse_subscribers(self) -> int:
        notifier = self._resolve("notifier")
        if notifier is not None and hasattr(notifier, "broker"):
            return int(notifier.broker.subscriber_count())
        return 0

    # --- helpers --------------------------------------------------------

    def _now(self) -> str | None:
        if self._clock is not None:
            return self._clock.iso()
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()

    def _resolve(self, key: str):
        container = getattr(self._app, "container", None)
        if container is None:
            return None
        try:
            return container.resolve(key)
        except Exception:  # noqa: BLE001 - a missing/unregistered service is not fatal
            return None

    def _guard(self, fn: Callable[[], T], default: T) -> T:
        try:
            return fn()
        except Exception:  # noqa: BLE001 - one broken section must not break the dashboard
            self._logger.exception("dashboard section %s failed", getattr(fn, "__name__", "?"))
            return default
