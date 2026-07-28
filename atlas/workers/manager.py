"""Worker Manager (Phase A · PHASE_A_PLAN §A.4) — supervises Persistent Workers.

Owns all worker durability so concrete workers stay trivial (see ``base.py``):

    worker_tick  →  skip unless tickable + past backoff
                 →  upgrade to running code version (B8)
                 →  drain operator inputs (Q4)
                 →  load active config version + checkpoint
                 →  worker.do_tick(ctx)  (one bounded unit)
                 →  save checkpoint + reset crash state   (success)
                 →  recovering + exponential backoff, pause on the 5th failure (B4, failure)

Ticks are driven by the schedule table (A.3); the manager never holds a worker in memory. A
tick failure is the *worker's* failure (tracked on the worker row) — it never propagates out of
the handler, so the scheduler keeps the recurrence alive and recovering ticks self-skip until
their ``next_retry_at``. Every notable action is journaled on the owning mission (P9).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from atlas.core.resources.arbiter import MissionArbiter, MissionDemand, demand_from_mission
from atlas.exceptions.base import AtlasError
from atlas.models.worker import (
    CRASH_PAUSE_AFTER,
    HEALTH_BLOCKED,
    HEALTH_HEALTHY,
    HEALTH_RECOVERING,
    WORKER_PAUSED,
    WORKER_RECOVERING,
    WORKER_RUNNING,
    WORKER_STATUSES,
    WORKER_STOPPED,
    WORKER_TICKABLE,
    Worker,
    backoff_for,
)
from atlas.ops.worker_states import (
    expected_tick_ms,
    ops_meta,
    summarize_workers,
    update_timing_ops,
    update_wait_ops,
)
from atlas.services.base import HealthStatus
from atlas.workers.base import PersistentWorker, TickContext

if TYPE_CHECKING:
    from atlas.events.dispatcher import EventDispatcher
    from atlas.recovery.checkpoints import CheckpointStore
    from atlas.repositories.worker_repo import WorkerRepository

_CHECKPOINT_OWNER = "worker"


def _llm_pair_from_profile(raw: Any) -> tuple[bool, int]:
    text = str(raw or "").strip().lower()
    if text in ("", "no", "false", "0", "none"):
        return False, 0
    if text in ("yes", "true", "light", "1"):
        return True, 1
    if text in ("heavy", "2"):
        return True, 2
    try:
        w = int(raw)
        return (w > 0), max(0, min(2, w))
    except (TypeError, ValueError):
        return True, 1


class WorkerError(AtlasError):
    """A worker operation was invalid (unknown type/worker)."""


class WorkerManager:
    name = "workers"
    VERSION = "1"

    def __init__(
        self,
        worker_repo: "WorkerRepository",
        checkpoint_store: "CheckpointStore",
        *,
        schedule_service: Any | None = None,
        config_repo: Any | None = None,
        mission_repo: Any | None = None,
        arbiter: MissionArbiter | None = None,
        resources: Any | None = None,
        host_guard: Any | None = None,
        reservations: Any | None = None,
        work_admission: Any | None = None,
        memory_watchdog: Any | None = None,
        events: "EventDispatcher | None" = None,
        clock: Any | None = None,
        logger: logging.Logger | None = None,
        default_tick_ram_mb: int = 512,
    ) -> None:
        self._repo = worker_repo
        self._checkpoints = checkpoint_store
        self._schedules = schedule_service
        self._config_repo = config_repo
        self._missions = mission_repo
        self._resources = resources  # OI-A3: optional machine RM for host RAM snapshot
        self._host_guard = host_guard  # slow-but-reliable host admission
        self._reservations = reservations  # IR-RO7 leases
        self._work_admission = work_admission  # IR-RO10 should-run-now
        self._memory_watchdog = memory_watchdog  # IR-RO11 runtime memory
        self._events = events
        self._clock = clock
        self._logger = logger or logging.getLogger("atlas.workers")
        self._types: dict[str, PersistentWorker] = {}
        self._default_tick_ram_mb = max(64, int(default_tick_ram_mb or 512))
        # Cross-mission admission (A7/§D.4 / OI-A3): the arbiter weighs effective_priority + deadline
        # urgency + importance and enforces hard per-mission concurrency + llm_units_per_window /
        # ram_mb caps (and optional global concurrency), with anti-starvation aging.
        self._arbiter = arbiter or MissionArbiter(clock=clock)

    # --- worker-type registry -------------------------------------------

    def register_worker_type(self, worker: PersistentWorker) -> None:
        self._types[worker.type] = worker

    def known_types(self) -> list[str]:
        return sorted(self._types)

    # --- lifecycle management -------------------------------------------

    def create_worker(
        self,
        mission_id: str,
        worker_type: str,
        *,
        interval_seconds: int = 60,
        cron_expr: str | None = None,
        metadata: dict[str, Any] | None = None,
        autostart: bool = True,
    ) -> Worker:
        impl = self._require_type(worker_type)
        config_version = self._active_config_version(mission_id)
        # Queued/deferred starts: create paused with a schedule registered but disabled
        # so HostGuard / operator resume can enable ticks later (slow-but-reliable).
        initial_status = WORKER_RUNNING if autostart else WORKER_PAUSED
        worker = self._repo.create(
            mission_id=mission_id,
            type=worker_type,
            worker_version=impl.VERSION,
            config_version=config_version,
            status=initial_status,
            metadata=metadata,
        )
        if self._schedules is not None:
            if cron_expr:
                schedule = self._schedules.register_schedule(
                    "worker_tick",
                    interval_seconds=max(1, int(interval_seconds or 60)),
                    payload={"worker_id": worker.id},
                    mission_id=mission_id,
                    worker_id=worker.id,
                    first_run_delay=0.0,
                    kind="cron",
                    cron_expr=cron_expr,
                    enabled=bool(autostart),
                )
            else:
                schedule = self._schedules.register_schedule(
                    "worker_tick",
                    interval_seconds,
                    payload={"worker_id": worker.id},
                    mission_id=mission_id,
                    worker_id=worker.id,
                    first_run_delay=0.0,
                    enabled=bool(autostart),
                )
            self._repo.set_schedule(worker.id, schedule.id)
            worker = self._repo.get(worker.id) or worker
        self._journal(
            mission_id,
            "worker_created",
            f"{worker_type} worker created"
            + ("" if autostart else " (queued for capacity)"),
            {
                "worker_id": worker.id,
                "type": worker_type,
                "worker_version": impl.VERSION,
                "autostart": bool(autostart),
            },
        )
        self._emit("WorkerCreated", worker)
        self._logger.info("created %s worker %s (mission %s)", worker_type, worker.id, mission_id)
        return worker

    def pause(self, worker_id: UUID | str, reason: str = "") -> Worker:
        worker = self._require(worker_id)
        self._release_arbiter_slot(worker)
        self._repo.set_status(worker.id, WORKER_PAUSED)
        self._toggle_schedule(worker, enabled=False)
        self._journal(worker.mission_id, "worker_paused", reason, {"worker_id": worker.id})
        updated = self._require(worker.id)
        self._emit("WorkerPaused", updated, reason=reason)
        return updated

    def resume(self, worker_id: UUID | str, reason: str = "") -> Worker:
        worker = self._require(worker_id)
        # Fresh start: clear crash backoff so it ticks on the next schedule fire.
        self._repo.record_success(worker.id)
        self._repo.set_status(worker.id, WORKER_RUNNING, health=HEALTH_HEALTHY)
        # Clear capacity-queue flag so HostGuard does not auto-resume an operator pause later.
        meta = dict(worker.metadata or {})
        if meta.pop("queued_for_capacity", None) is not None or "queue_reason" in meta:
            meta.pop("queue_reason", None)
            try:
                self._repo.update_metadata(worker.id, meta)
            except Exception:  # noqa: BLE001
                pass
        self._toggle_schedule(worker, enabled=True)
        self._journal(worker.mission_id, "worker_resumed", reason, {"worker_id": worker.id})
        updated = self._require(worker.id)
        self._emit("WorkerResumed", updated, reason=reason)
        return updated

    def stop_worker(self, worker_id: UUID | str, reason: str = "") -> Worker:
        """Operator stop of a worker (distinct from the service-lifecycle ``stop``)."""
        worker = self._require(worker_id)
        self._release_arbiter_slot(worker)
        self._repo.set_status(worker.id, WORKER_STOPPED)
        self._toggle_schedule(worker, enabled=False)
        self._journal(worker.mission_id, "worker_stopped", reason, {"worker_id": worker.id})
        updated = self._require(worker.id)
        self._emit("WorkerStopped", updated, reason=reason)
        return updated

    def _release_arbiter_slot(self, worker: Worker) -> None:
        """Free a leaked / mid-tick admission slot when operator stops or pauses."""
        if self._arbiter is None:
            return
        try:
            meta = worker.metadata if isinstance(worker.metadata, dict) else {}
            prog = meta.get("program_id") or meta.get("program")
            self._arbiter.release(str(worker.mission_id), program_id=str(prog) if prog else None)
        except Exception:  # noqa: BLE001 - lifecycle must not fail on arbiter bugs
            self._logger.debug("arbiter release on stop/pause failed", exc_info=True)

    def enqueue_input(self, worker_id: UUID | str, payload: dict[str, Any]) -> None:
        """Queue a live operator input the worker drains at the top of its next tick (Q4)."""
        worker = self._require(worker_id)
        self._repo.enqueue_input(worker.id, payload)
        self._emit("WorkerInputQueued", worker)

    # --- reads ----------------------------------------------------------

    def get_worker(self, worker_id: UUID | str) -> Worker | None:
        return self._repo.get(worker_id)

    def list_workers(
        self,
        *,
        mission_id: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[Worker]:
        return self._repo.list(mission_id=mission_id, status=status, limit=limit)

    def checkpoint_state(self, worker_id: UUID | str) -> dict[str, Any]:
        """Durable tick checkpoint for a worker (progress / files_done / etc.)."""
        worker = self._repo.get(worker_id)
        if worker is None:
            return {}
        try:
            return dict(self._checkpoints.load(_CHECKPOINT_OWNER, worker.id) or {})
        except Exception:  # noqa: BLE001
            return {}

    def enrich_worker(self, worker: Worker | dict[str, Any]) -> dict[str, Any]:
        """Worker row + checkpoint progress summary (for Archive / Missions UI)."""
        if hasattr(worker, "to_dict"):
            data = worker.to_dict()
            wid = worker.id
            wtype = worker.type
        else:
            data = dict(worker)
            wid = data.get("id")
            wtype = data.get("type")
        state = self.checkpoint_state(wid) if wid else {}
        progress = state.get("progress") if isinstance(state, dict) else None
        roots = (state or {}).get("roots") if isinstance(state, dict) else None
        root_progress: list[dict[str, Any]] = []
        if isinstance(roots, dict):
            for path, entry in roots.items():
                if not isinstance(entry, dict):
                    continue
                prog = entry.get("progress") or {}
                root_progress.append(
                    {
                        "path": path,
                        "name": Path(str(path)).name,
                        "complete": bool(entry.get("complete")),
                        "done": prog.get("done"),
                        "total": prog.get("total"),
                        "pending": prog.get("pending"),
                        "last_file": prog.get("last_file"),
                        "kind": entry.get("kind"),
                        "scanning": bool(prog.get("scanning")),
                        "walked": prog.get("walked"),
                    }
                )
        data["checkpoint"] = {
            "progress": progress,
            "roots": root_progress,
            "ticks": (state or {}).get("ticks"),
            "last_totals": (state or {}).get("last_totals"),
            "ingest_complete": bool((state or {}).get("ingest_complete")),
            "phase": (state or {}).get("phase"),
            "phase_detail": (state or {}).get("phase_detail"),
            "phase_updated_at": (state or {}).get("phase_updated_at"),
        }
        all_roots_done = bool(root_progress) and all(r.get("complete") for r in root_progress)
        data["has_progress"] = bool(root_progress) or bool(progress) or bool(
            (state or {}).get("phase")
        )
        data["is_archive"] = wtype == "owner_knowledge"
        data["archive_ingest_complete"] = all_roots_done or bool((state or {}).get("ingest_complete"))
        # Operator visibility: configured roots + schedule timing even before first checkpoint.
        cfg_doc: dict[str, Any] = {}
        mission_id = data.get("mission_id")
        if mission_id and self._config_repo is not None:
            try:
                active = self._config_repo.get_active(mission_id)
                if active is not None and isinstance(getattr(active, "document", None), dict):
                    cfg_doc = dict(active.document)
            except Exception:  # noqa: BLE001
                cfg_doc = {}
        cfg_roots: list[dict[str, Any]] = []
        for r in cfg_doc.get("archive_roots") or []:
            if isinstance(r, dict) and r.get("path"):
                cfg_roots.append(
                    {
                        "path": r.get("path"),
                        "name": Path(str(r.get("path"))).name,
                        "kind": r.get("kind") or "document",
                    }
                )
        data["configured_roots"] = cfg_roots
        data["archive_mode"] = cfg_doc.get("archive_mode") or (data.get("metadata") or {}).get(
            "archive_mode"
        )
        meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        data["queue_reason"] = meta.get("queue_reason")
        data["queued_for_capacity"] = bool(meta.get("queued_for_capacity"))
        next_run = None
        sid = data.get("schedule_id")
        if sid and self._schedules is not None and hasattr(self._schedules, "get"):
            try:
                sched = self._schedules.get(sid)
                nr = getattr(sched, "next_run_at", None) if sched is not None else None
                if nr is not None and hasattr(nr, "isoformat"):
                    next_run = nr.isoformat()
                elif nr is not None:
                    next_run = str(nr)
            except Exception:  # noqa: BLE001
                next_run = None
        data["next_run_at"] = next_run
        lt = data.get("last_tick_at")
        if hasattr(lt, "isoformat"):
            data["last_tick_at"] = lt.isoformat()
        ops = ops_meta(worker if not isinstance(worker, dict) else data)
        if ops:
            data["ops"] = ops
        return data

    def list_workers_enriched(
        self,
        *,
        mission_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows = self.list_workers(mission_id=mission_id, status=status, limit=limit)
        out = [self.enrich_worker(w) for w in rows[: max(1, limit)]]
        return out

    def ops_state_snapshot(self, *, limit: int = 500) -> dict[str, Any]:
        """IR-OPS1: Linux-style worker state breakdown for the Ops dashboard."""
        rows = self.list_workers(limit=max(1, limit))
        inflight: set[str] = set()
        try:
            snap = self._arbiter.snapshot()
            for mid, n in (snap.get("inflight") or {}).items():
                if int(n or 0) > 0:
                    inflight.add(str(mid))
        except Exception:  # noqa: BLE001
            pass
        holding: set[str] = set()
        if self._reservations is not None and hasattr(self._reservations, "holding_worker_ids"):
            try:
                holding = set(self._reservations.holding_worker_ids())
            except Exception:  # noqa: BLE001
                holding = set()
        now = None
        if self._clock is not None and hasattr(self._clock, "now"):
            try:
                now = self._clock.now()
            except Exception:  # noqa: BLE001
                now = None
        summary = summarize_workers(
            rows,
            now=now,
            inflight_mission_ids=inflight,
            holding_reservation_ids=holding,
        )
        if self._missions is not None and summary.get("notable"):
            for row in summary["notable"]:
                mid = row.get("mission_id")
                if not mid:
                    continue
                try:
                    mission = self._missions.get(mid)
                except Exception:  # noqa: BLE001
                    mission = None
                if mission is None:
                    continue
                title = getattr(mission, "title", None)
                meta = getattr(mission, "metadata", None) or {}
                if title:
                    row["mission_title"] = title
                if isinstance(meta, dict) and meta.get("program_id"):
                    row.setdefault("owner", {})["program"] = meta.get("program_id")
        return summary

    def _record_tick_timing(self, worker: Worker, duration_ms: float) -> None:
        try:
            meta = dict(worker.metadata or {})
            ops = update_timing_ops(
                ops_meta(worker),
                duration_ms=duration_ms,
                expected_ms=expected_tick_ms(
                    worker.type, ops_meta(worker), dict(worker.metadata or {})
                ),
                clear_wait=True,
            )
            meta["ops"] = ops
            self._repo.update_metadata(worker.id, meta)
        except Exception:  # noqa: BLE001 - timing must never break a tick
            self._logger.debug("failed to record tick timing for %s", worker.id, exc_info=True)

    def _record_wait(self, worker: Worker, reason: str) -> None:
        try:
            meta = dict(worker.metadata or {})
            meta["ops"] = update_wait_ops(ops_meta(worker), reason=reason)
            self._repo.update_metadata(worker.id, meta)
        except Exception:  # noqa: BLE001
            self._logger.debug("failed to record wait for %s", worker.id, exc_info=True)

    # --- the tick (registered as the `worker_tick` handler) -------------

    def worker_tick(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        worker_id = (payload or {}).get("worker_id")
        if not worker_id:
            return {"skipped": "no worker_id"}
        worker = self._repo.get(worker_id)
        if worker is None:
            return {"skipped": "unknown worker"}
        if worker.status not in WORKER_TICKABLE:
            return {"skipped": worker.status}
        if self._in_backoff(worker):
            return {"skipped": "backoff", "worker_id": worker.id}

        impl = self._types.get(worker.type)
        if impl is None:
            # No running code for this type — block it rather than crash-loop.
            self._repo.set_status(worker.id, WORKER_PAUSED, health=HEALTH_BLOCKED)
            self._journal(
                worker.mission_id, "worker_blocked",
                f"no registered code for type {worker.type!r}", {"worker_id": worker.id},
            )
            return {"skipped": "unknown type", "worker_id": worker.id}

        # Host-respect gate first: under pressure, defer (job stays scheduled).
        if self._host_guard is not None:
            try:
                ok, reason = self._host_guard.can_run_tick(worker_type=worker.type)
            except Exception as exc:  # noqa: BLE001 - never block ticks on guard bugs
                self._logger.debug("host_guard check failed: %s", exc)
                ok, reason = True, "host_guard_error"
            if not ok:
                self._record_wait(worker, "host_pressure")
                self._emit(
                    "WorkerDeferred",
                    worker,
                    reason=reason,
                    cause="host_pressure",
                )
                return {
                    "skipped": "host_pressure",
                    "reason": reason,
                    "worker_id": worker.id,
                }

        # Cross-mission admission (A7/§D.4): defer this tick if the mission is over its concurrency cap
        # or loses arbitration for a scarce global slot. Deferral is temporary + aged (never starved).
        demand = self._demand_for(worker.mission_id, worker=worker)

        # IR-RO10: Should run *now*? (timing policy — Complements Host Guard Can?).
        if self._work_admission is not None:
            try:
                timing = self._work_admission.should_run_now(
                    service_class=getattr(demand, "service_class", None),
                )
            except Exception as exc:  # noqa: BLE001 - never block ticks on policy bugs
                self._logger.debug("work_admission check failed: %s", exc)
                timing = None
            if timing is not None and not timing.allowed:
                self._record_wait(worker, "schedule")
                self._emit(
                    "WorkerDeferred",
                    worker,
                    reason=timing.reason,
                    cause="schedule_window",
                    run_at_hint=timing.run_at_hint,
                )
                return {
                    "skipped": "schedule_window",
                    "reason": timing.reason,
                    "run_at_hint": timing.run_at_hint,
                    "worker_id": worker.id,
                }

        verdict = self._arbiter.try_admit(demand)
        if not verdict.admitted:
            if self._host_guard is not None:
                try:
                    self._host_guard.note_deferred(verdict.reason)
                except Exception:  # noqa: BLE001
                    pass
            self._record_wait(worker, "budget")
            self._emit("WorkerThrottled", worker, reason=verdict.reason, score=round(verdict.score, 4))
            return {"skipped": "budget", "reason": verdict.reason, "worker_id": worker.id}

        lease_token: str | None = None
        if self._reservations is not None:
            try:
                from atlas.core.resources.reservations import ReservationRequest

                decision = self._reservations.acquire(ReservationRequest.from_worker_meta(worker))
                if not decision.allowed:
                    self._arbiter.release(worker.mission_id)
                    self._record_wait(worker, "reservation")
                    self._emit(
                        "WorkerThrottled",
                        worker,
                        reason=decision.reason,
                        cause="reservation",
                    )
                    return {
                        "skipped": "reservation",
                        "reason": decision.reason,
                        "worker_id": worker.id,
                    }
                lease_token = decision.lease.token if decision.lease else None
            except Exception as exc:  # noqa: BLE001 - never block ticks on reservation bugs
                self._logger.debug("reservation acquire failed: %s", exc)

        try:
            worker = self._maybe_upgrade(worker, impl)
            inputs = [i.payload for i in self._repo.drain_inputs(worker.id)]
            config, config_version = self._load_config(worker)
            state = self._checkpoints.load(_CHECKPOINT_OWNER, worker.id) or {}

            def _mid_save(partial: dict[str, Any]) -> None:
                try:
                    self._checkpoints.save(_CHECKPOINT_OWNER, worker.id, partial or {})
                except Exception:  # noqa: BLE001
                    self._logger.debug("mid-tick checkpoint save failed", exc_info=True)

            mem_session = None
            memory_check = None
            if self._memory_watchdog is not None and hasattr(self._memory_watchdog, "begin_tick"):
                try:
                    budget = int(getattr(demand, "ram_mb", None) or self._default_tick_ram_mb)
                    mem_session = self._memory_watchdog.begin_tick(
                        worker_id=worker.id,
                        worker_type=worker.type,
                        budget_mb=budget,
                    )
                    memory_check = mem_session.check
                except Exception:  # noqa: BLE001
                    self._logger.debug("memory watchdog begin_tick failed", exc_info=True)

            ctx = TickContext(
                worker_id=worker.id,
                mission_id=worker.mission_id,
                config=config,
                config_version=config_version,
                state=state,
                inputs=inputs,
                save_checkpoint=_mid_save,
                memory_check=memory_check,
            )
            started = time.monotonic()
            try:
                result = impl.do_tick(ctx)
            except Exception as exc:  # noqa: BLE001 - a worker failure is data, not a crash
                self._record_tick_timing(worker, (time.monotonic() - started) * 1000.0)
                return self._on_failure(worker, exc)
            self._record_tick_timing(worker, (time.monotonic() - started) * 1000.0)
            return self._on_success(
                worker, impl, result, config_version, mem_session=mem_session
            )
        finally:
            self._arbiter.release(worker.mission_id)
            if self._reservations is not None:
                try:
                    self._reservations.release(lease_token, worker_id=worker.id)
                except Exception:  # noqa: BLE001
                    pass

    # --- tick outcome handling ------------------------------------------

    def _on_success(
        self,
        worker,
        impl,
        result,
        config_version,
        *,
        mem_session: Any | None = None,
    ) -> dict[str, Any]:
        self._checkpoints.save(_CHECKPOINT_OWNER, worker.id, result.state)
        self._repo.record_success(worker.id, config_version=config_version)
        if getattr(impl, "journal_ticks", False) and result.note:
            self._journal(worker.mission_id, "worker_tick", result.note, {"worker_id": worker.id})
        self._emit("WorkerTick", worker, note=result.note)
        if result.done:
            self._repo.set_status(worker.id, WORKER_STOPPED)
            self._toggle_schedule(worker, enabled=False)
            self._journal(
                worker.mission_id, "worker_done", result.note or "worker reported done",
                {"worker_id": worker.id},
            )
            self._emit("WorkerDone", worker, note=result.note)
            return {"worker_id": worker.id, "ticked": True, "done": True}

        # IR-RO11: cooperative memory pause — durable queue; Host Guard resumes.
        state = result.state if isinstance(result.state, dict) else {}
        mem_action = state.get("memory_action")
        if not mem_action and mem_session is not None:
            last = getattr(mem_session, "last_verdict", None)
            if last is not None and not getattr(last, "ok", True):
                mem_action = getattr(last, "action", None)
        if mem_action == "pause_worker":
            reason = str(
                state.get("memory_reason")
                or "IR-RO11 memory budget / host pressure"
            )
            try:
                meta = dict(worker.metadata or {})
                meta["queued_for_capacity"] = True
                meta["queue_reason"] = reason
                self._repo.update_metadata(worker.id, meta)
            except Exception:  # noqa: BLE001
                pass
            self.pause(worker.id, reason=f"memory_watchdog: {reason}")
            self._emit("WorkerMemoryPaused", worker, reason=reason, action=mem_action)
            return {
                "worker_id": worker.id,
                "ticked": True,
                "done": False,
                "memory_action": mem_action,
                "reason": reason,
            }
        if mem_action == "yield_tick":
            return {
                "worker_id": worker.id,
                "ticked": True,
                "done": False,
                "memory_action": mem_action,
                "reason": state.get("memory_reason"),
            }
        return {"worker_id": worker.id, "ticked": True, "done": False}

    def _on_failure(self, worker, exc: Exception) -> dict[str, Any]:
        error = f"{type(exc).__name__}: {exc}"
        new_count = worker.restart_count + 1
        if new_count >= CRASH_PAUSE_AFTER:
            # Crash loop: stop retrying (B4) — operator must resume.
            self._repo.record_failure(
                worker.id, status=WORKER_PAUSED, health=HEALTH_BLOCKED, backoff_seconds=None
            )
            self._toggle_schedule(worker, enabled=False)
            self._journal(
                worker.mission_id, "worker_paused",
                f"crash loop after {new_count} failures: {error}",
                {"worker_id": worker.id, "restart_count": new_count, "error": error},
            )
            self._emit("WorkerPaused", worker, error=error, restart_count=new_count)
            self._logger.error("worker %s paused after %d failures: %s", worker.id, new_count, error)
        else:
            delay = backoff_for(new_count)
            self._repo.record_failure(
                worker.id, status=WORKER_RECOVERING, health=HEALTH_RECOVERING,
                backoff_seconds=delay,
            )
            self._journal(
                worker.mission_id, "worker_recovering",
                f"tick failed (retry {new_count} in {delay:.0f}s): {error}",
                {"worker_id": worker.id, "restart_count": new_count, "backoff": delay, "error": error},
            )
            self._emit("WorkerFailed", worker, error=error, retry=new_count, backoff=delay)
            self._logger.warning(
                "worker %s tick failed (%s); retry %d in %.0fs", worker.id, error, new_count, delay
            )
        return {"worker_id": worker.id, "failed": True, "error": error, "restart_count": new_count}

    # --- helpers --------------------------------------------------------

    def _maybe_upgrade(self, worker: Worker, impl: PersistentWorker) -> Worker:
        if impl.VERSION != worker.worker_version:
            self._repo.set_version(worker.id, impl.VERSION)
            self._journal(
                worker.mission_id, "worker_upgraded",
                f"worker upgraded v{worker.worker_version}→v{impl.VERSION}",
                {"worker_id": worker.id, "from": worker.worker_version, "to": impl.VERSION},
            )
            self._emit("WorkerUpgraded", worker, to_version=impl.VERSION)
            return self._repo.get(worker.id) or worker
        return worker

    def _load_config(self, worker: Worker) -> tuple[dict[str, Any], int | None]:
        if self._config_repo is None:
            return {}, worker.config_version
        active = self._config_repo.get_active(worker.mission_id)
        if active is None:
            return {}, None
        if active.version != worker.config_version:
            self._journal(
                worker.mission_id, "config_picked_up",
                f"worker picked up config v{active.version}",
                {"worker_id": worker.id, "config_version": active.version},
            )
        return dict(active.document), active.version

    def _demand_for(self, mission_id: str, *, worker: Any | None = None) -> MissionDemand:
        """Project the mission's arbitration inputs (priority/deadline/importance/caps) for admission.

        A missing mission (or repo) yields an unconstrained demand, so non-mission/uncapped work is
        admitted exactly as before (back-compatible with the Phase-A per-mission-cap behaviour).
        Default ``ram_mb`` from host-respect config applies when the mission has no budget reserve.

        When mission metadata lacks ``service_class`` / ``program_id`` (older missions), fall back
        to the worker type's :class:`WorkResourceProfile` and worker/config metadata so Market
        realtime work (paper_trading) is not misclassified as BATCH.
        """
        host_ram: int | None = None
        if self._resources is not None:
            try:
                from atlas.core.resources.monitor import read_snapshot

                snap = read_snapshot(self._logger)
                if snap.mem_available_kb is not None:
                    host_ram = int(snap.mem_available_kb) // 1024
            except Exception:  # noqa: BLE001 - host snapshot is advisory
                host_ram = None
        demand: MissionDemand | None = None
        if self._missions is not None:
            try:
                mission = self._missions.get(mission_id)
            except Exception:  # noqa: BLE001 - arbitration lookup must not break a tick
                mission = None
            if mission is not None:
                demand = demand_from_mission(mission, host_available_ram_mb=host_ram)
                if demand.ram_mb is None and self._default_tick_ram_mb:
                    demand = MissionDemand(
                        mission_id=demand.mission_id,
                        effective_priority=demand.effective_priority,
                        deadline=demand.deadline,
                        importance=demand.importance,
                        max_concurrent_tasks=demand.max_concurrent_tasks or 1,
                        llm_units_per_window=demand.llm_units_per_window,
                        llm_window_seconds=demand.llm_window_seconds,
                        estimated_llm_units=demand.estimated_llm_units,
                        ram_mb=self._default_tick_ram_mb,
                        host_available_ram_mb=host_ram,
                        service_class=demand.service_class,
                        wait_since=demand.wait_since,
                        confidence_score=demand.confidence_score,
                        program_id=demand.program_id,
                        uses_llm=demand.uses_llm,
                        llm_weight=demand.llm_weight,
                        research_progress=demand.research_progress,
                    )
                elif demand.max_concurrent_tasks is None:
                    demand = MissionDemand(
                        mission_id=demand.mission_id,
                        effective_priority=demand.effective_priority,
                        deadline=demand.deadline,
                        importance=demand.importance,
                        max_concurrent_tasks=1,
                        llm_units_per_window=demand.llm_units_per_window,
                        llm_window_seconds=demand.llm_window_seconds,
                        estimated_llm_units=demand.estimated_llm_units,
                        ram_mb=demand.ram_mb,
                        host_available_ram_mb=host_ram,
                        service_class=demand.service_class,
                        wait_since=demand.wait_since,
                        confidence_score=demand.confidence_score,
                        program_id=demand.program_id,
                        uses_llm=demand.uses_llm,
                        llm_weight=demand.llm_weight,
                        research_progress=demand.research_progress,
                    )
        if demand is None:
            demand = MissionDemand(
                mission_id=str(mission_id),
                max_concurrent_tasks=1,
                ram_mb=self._default_tick_ram_mb,
                host_available_ram_mb=host_ram,
            )
        return self._enrich_demand_from_worker(demand, worker)

    def _enrich_demand_from_worker(
        self, demand: MissionDemand, worker: Any | None
    ) -> MissionDemand:
        """Fill service_class / program_id from worker type profile when mission meta is thin."""
        if worker is None:
            return demand
        wtype = getattr(worker, "type", None) or ""
        meta = getattr(worker, "metadata", None)
        meta = meta if isinstance(meta, dict) else {}
        sc = demand.service_class
        prog = demand.program_id
        uses_llm = demand.uses_llm
        llm_weight = demand.llm_weight
        if not sc and wtype:
            try:
                from atlas.missions.templates.resources import resources_for

                prof = resources_for(str(wtype))
                sc = prof.service_class
                if not uses_llm:
                    uses_llm, llm_weight = _llm_pair_from_profile(prof.llm)
            except Exception:  # noqa: BLE001
                pass
        if not prog:
            prog = meta.get("program_id") or meta.get("program")
        if not prog and self._config_repo is not None:
            try:
                active = self._config_repo.get_active(getattr(worker, "mission_id", None))
                doc = getattr(active, "document", None) if active is not None else None
                if isinstance(doc, dict) and doc.get("program_id"):
                    prog = doc.get("program_id")
            except Exception:  # noqa: BLE001
                pass
        if (
            sc == demand.service_class
            and prog == demand.program_id
            and uses_llm == demand.uses_llm
            and llm_weight == demand.llm_weight
        ):
            return demand
        return MissionDemand(
            mission_id=demand.mission_id,
            effective_priority=demand.effective_priority,
            deadline=demand.deadline,
            importance=demand.importance,
            max_concurrent_tasks=demand.max_concurrent_tasks,
            llm_units_per_window=demand.llm_units_per_window,
            llm_window_seconds=demand.llm_window_seconds,
            estimated_llm_units=demand.estimated_llm_units,
            ram_mb=demand.ram_mb,
            host_available_ram_mb=demand.host_available_ram_mb,
            service_class=str(sc) if sc else demand.service_class,
            wait_since=demand.wait_since,
            confidence_score=demand.confidence_score,
            program_id=str(prog) if prog else demand.program_id,
            uses_llm=uses_llm,
            llm_weight=llm_weight,
            research_progress=demand.research_progress,
        )

    def _in_backoff(self, worker: Worker) -> bool:
        if worker.status != WORKER_RECOVERING or worker.next_retry_at is None:
            return False
        return self._now() < worker.next_retry_at

    def _toggle_schedule(self, worker: Worker, *, enabled: bool) -> None:
        if self._schedules is None or not worker.schedule_id:
            return
        try:
            if enabled:
                self._schedules.enable(worker.schedule_id)
            else:
                self._schedules.disable(worker.schedule_id)
        except Exception:  # noqa: BLE001 - schedule toggle must not fail a lifecycle op
            self._logger.exception("failed to toggle schedule for worker %s", worker.id)

    def _active_config_version(self, mission_id: str) -> int | None:
        if self._config_repo is None:
            return None
        active = self._config_repo.get_active(mission_id)
        return active.version if active else None

    def _now(self) -> datetime:
        if self._clock is not None:
            try:
                return self._clock.now()
            except Exception:  # noqa: BLE001 - fall back to wall clock
                pass
        return datetime.now(timezone.utc)

    def _require(self, worker_id: UUID | str) -> Worker:
        worker = self._repo.get(worker_id)
        if worker is None:
            raise WorkerError("worker not found", worker_id=str(worker_id))
        return worker

    def _require_type(self, worker_type: str) -> PersistentWorker:
        impl = self._types.get(worker_type)
        if impl is None:
            raise WorkerError(
                f"unknown worker type: {worker_type!r}", known=self.known_types()
            )
        return impl

    def _journal(
        self, mission_id: str, action: str, reason: str, refs: dict[str, Any] | None = None
    ) -> None:
        if self._missions is None:
            return
        try:
            self._missions.add_journal(mission_id, action, reason, refs or {})
        except Exception:  # noqa: BLE001 - journaling must not break a tick
            self._logger.exception("failed to journal %s for mission %s", action, mission_id)

    def _emit(self, event_type: str, worker: Worker, **extra: Any) -> None:
        if self._events is None:
            return
        try:
            self._events.emit(
                event_type,
                {
                    "worker_id": worker.id,
                    "mission_id": worker.mission_id,
                    "type": worker.type,
                    **extra,
                },
                source=self.name,
            )
        except Exception:  # noqa: BLE001 - telemetry must never break a tick
            self._logger.exception("failed to emit %s", event_type)

    # --- lifecycle (kernel service) ------------------------------------

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def health_check(self) -> HealthStatus:
        try:
            counts = self._repo.count_by_status()
        except Exception as exc:  # noqa: BLE001 - health probe must not raise
            return HealthStatus.fail(f"worker repo unreachable: {exc}")
        running = counts.get(WORKER_RUNNING, 0) + counts.get(WORKER_RECOVERING, 0)
        detail = f"{running} active worker(s); {len(self._types)} type(s) registered"
        data = {"counts": counts, "types": self.known_types()}
        if counts.get("failed"):
            return HealthStatus.degraded_status(detail + f", {counts['failed']} failed", **data)
        return HealthStatus.ok(detail, **data)
