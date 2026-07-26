"""Resource Planner + Admission Contracts (IR-RO1).

Planning OS asks *what* to do. Resource Planner answers *can/should we accept it into
the Mission Queue?* with an explicit ``AdmissionContract`` — not an implicit bool.

Statuses:
  accepted            — enqueue / start (``run_mode`` immediate | deferred_until)
  deferred            — accepted into Atlas but not started yet (capacity / schedule)
  rejected            — do not create work
  needs_confirmation  — show estimate; operator must confirm before create

Host Guard remains the *tick-time* safety net. This module owns *start-time* admission.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATUS_ACCEPTED = "accepted"
STATUS_DEFERRED = "deferred"
STATUS_REJECTED = "rejected"
STATUS_NEEDS_CONFIRMATION = "needs_confirmation"

# Archive confirm thresholds (conservative defaults for shared desktops).
CONFIRM_FILE_COUNT = 5_000
CONFIRM_DURATION_SECONDS = 2 * 3600  # 2h
CONFIRM_STORAGE_GROWTH_MB = 500.0
CONFIRM_BYTES = 2 * 1024**3  # 2 GiB scanned

# Walk caps — estimate must stay cheap.
MAX_FILES_COUNTED = 50_000
MAX_WALK_SECONDS = 8.0

PENDING_TTL_SECONDS = 3600


@dataclass(frozen=True)
class WorkEstimate:
    file_count: int | None = None
    byte_count: int | None = None
    duration_seconds: float | None = None
    storage_growth_mb: float | None = None
    embedding_mb: float | None = None
    ram_mb: int | None = None
    concurrency: int | None = None
    risk: str | None = None  # low | medium | high
    truncated: bool = False
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["notes"] = list(self.notes)
        return d


@dataclass(frozen=True)
class AdmissionContract:
    status: str
    reason: str = ""
    run_mode: str | None = None  # immediate | deferred_until
    run_at: datetime | None = None
    estimate: WorkEstimate | None = None
    confirmation_token: str | None = None
    program_id: str | None = None
    mission_template: str | None = None
    intent: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "run_mode": self.run_mode,
            "run_at": self.run_at.isoformat() if self.run_at else None,
            "estimate": self.estimate.as_dict() if self.estimate else None,
            "confirmation_token": self.confirmation_token,
            "program_id": self.program_id,
            "mission_template": self.mission_template,
            "intent": self.intent,
        }

    @property
    def allows_create(self) -> bool:
        return self.status in (STATUS_ACCEPTED, STATUS_DEFERRED)


@dataclass
class _PendingAdmission:
    token: str
    path: str
    kind: str
    estimate: WorkEstimate
    program_id: str
    mission_template: str
    created_at: float
    fingerprint: str


class ResourcePlanner:
    """Proactive cost estimate + Admission Contract (IR-RO1)."""

    name = "resource_planner"
    VERSION = "ro1.1"

    def __init__(
        self,
        *,
        host_guard: Any | None = None,
        storage_pressure: Any | None = None,
        clock: Any | None = None,
        logger: logging.Logger | None = None,
        confirm_file_count: int = CONFIRM_FILE_COUNT,
        confirm_duration_seconds: float = CONFIRM_DURATION_SECONDS,
        confirm_storage_growth_mb: float = CONFIRM_STORAGE_GROWTH_MB,
    ) -> None:
        self._host_guard = host_guard
        self._storage_pressure = storage_pressure
        self._clock = clock
        self._logger = logger or logging.getLogger("atlas.resources.planner")
        self._confirm_files = int(confirm_file_count)
        self._confirm_duration = float(confirm_duration_seconds)
        self._confirm_growth = float(confirm_storage_growth_mb)
        self._lock = threading.Lock()
        self._pending: dict[str, _PendingAdmission] = {}

    # --- estimates -------------------------------------------------------

    def estimate_archive(
        self,
        path: str | Path,
        *,
        kind: str = "document",
        files_per_tick: int = 40,
        tick_interval_seconds: float = 60.0,
        embed: bool = False,
        ram_mb: int = 512,
    ) -> WorkEstimate:
        """Cheap filesystem sample for Owner Knowledge / archive walks."""
        root = Path(path).expanduser()
        if not root.exists():
            return WorkEstimate(risk="high", notes=("path_missing",))

        files = 0
        bytes_total = 0
        truncated = False
        deadline = time.monotonic() + MAX_WALK_SECONDS
        try:
            if root.is_file():
                files = 1
                try:
                    bytes_total = root.stat().st_size
                except OSError:
                    bytes_total = 0
            else:
                for p in root.rglob("*"):
                    if time.monotonic() > deadline:
                        truncated = True
                        break
                    if files >= MAX_FILES_COUNTED:
                        truncated = True
                        break
                    try:
                        if not p.is_file():
                            continue
                        files += 1
                        bytes_total += int(p.stat().st_size)
                    except OSError:
                        continue
        except OSError as exc:
            self._logger.debug("archive estimate walk failed: %s", exc)
            return WorkEstimate(risk="medium", notes=(f"walk_error:{exc}",))

        fpt = max(1, int(files_per_tick or 40))
        interval = max(1.0, float(tick_interval_seconds or 60.0))
        # Wall-clock estimate assuming one archive worker.
        duration = (max(1, files) / fpt) * interval

        # Text/extract growth (no embed): ~5% of raw for documents; code lower.
        kind_l = (kind or "document").lower()
        if kind_l == "code":
            growth_ratio = 0.02
        elif kind_l == "conversation":
            growth_ratio = 0.08
        else:
            growth_ratio = 0.05
        growth_mb = (bytes_total * growth_ratio) / (1024 * 1024)
        embed_mb = 0.0
        if embed:
            # Rough embedding footprint: ~1.5 KB metadata-ish per file + 2% of bytes.
            embed_mb = (files * 0.0015) + (bytes_total * 0.02) / (1024 * 1024)
            growth_mb += embed_mb

        risk = "low"
        if truncated or files >= self._confirm_files or duration >= self._confirm_duration:
            risk = "high"
        elif files >= self._confirm_files // 5 or duration >= self._confirm_duration / 2:
            risk = "medium"

        notes: list[str] = []
        if truncated:
            notes.append("walk_truncated")
        if files == 0:
            notes.append("empty_or_unreadable")

        return WorkEstimate(
            file_count=files,
            byte_count=bytes_total,
            duration_seconds=round(duration, 1),
            storage_growth_mb=round(growth_mb, 2),
            embedding_mb=round(embed_mb, 2),
            ram_mb=int(ram_mb),
            concurrency=1,
            risk=risk,
            truncated=truncated,
            notes=tuple(notes),
        )

    # --- admission -------------------------------------------------------

    def admit_archive(
        self,
        *,
        path: str,
        kind: str = "document",
        estimate: WorkEstimate | None = None,
        files_per_tick: int = 40,
        confirm: bool = False,
        confirmation_token: str | None = None,
        force: bool = False,
        program_id: str = "personal_intelligence",
        mission_template: str = "owner_knowledge",
    ) -> AdmissionContract:
        """Admit an archive ingest request into (or toward) the Mission Queue."""
        path_s = str(Path(path).expanduser())
        est = estimate or self.estimate_archive(
            path_s, kind=kind, files_per_tick=files_per_tick
        )

        if not Path(path_s).exists():
            return AdmissionContract(
                status=STATUS_REJECTED,
                reason="path not found",
                estimate=est,
                program_id=program_id,
                mission_template=mission_template,
                intent="archive_ingest",
            )

        # IR-RO6: refuse when disk is critically full for high-growth archives.
        if self._storage_pressure is not None and est.storage_growth_mb is not None:
            try:
                growth_level = "high" if est.storage_growth_mb >= 100 else (
                    "medium" if est.storage_growth_mb >= 20 else "low"
                )
                ok, reason = self._storage_pressure.allows_growth(
                    level=growth_level, growth_mb=float(est.storage_growth_mb)
                )
                if not ok:
                    return AdmissionContract(
                        status=STATUS_REJECTED,
                        reason=reason,
                        estimate=est,
                        program_id=program_id,
                        mission_template=mission_template,
                        intent="archive_ingest",
                    )
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("storage pressure admit check failed: %s", exc)

        # Confirm token path — operator already saw the estimate.
        if confirmation_token:
            pending = self._consume_pending(confirmation_token, path_s)
            if pending is None:
                return AdmissionContract(
                    status=STATUS_REJECTED,
                    reason="invalid or expired confirmation_token",
                    estimate=est,
                    program_id=program_id,
                    mission_template=mission_template,
                    intent="archive_ingest",
                )
            est = pending.estimate

        needs = (not force and not confirm and not confirmation_token) and self._needs_confirm(est)
        if needs:
            token = self._store_pending(
                path=path_s,
                kind=kind,
                estimate=est,
                program_id=program_id,
                mission_template=mission_template,
            )
            return AdmissionContract(
                status=STATUS_NEEDS_CONFIRMATION,
                reason=self._confirm_reason(est),
                run_mode=None,
                estimate=est,
                confirmation_token=token,
                program_id=program_id,
                mission_template=mission_template,
                intent="archive_ingest",
            )

        # Capacity / host → deferred (still creates paused work — never lose accepted).
        queue_reason = self._capacity_reason(worker_type=mission_template)
        if queue_reason:
            return AdmissionContract(
                status=STATUS_DEFERRED,
                reason=queue_reason,
                run_mode="deferred_until",
                estimate=est,
                program_id=program_id,
                mission_template=mission_template,
                intent="archive_ingest",
            )

        return AdmissionContract(
            status=STATUS_ACCEPTED,
            reason="admitted",
            run_mode="immediate",
            estimate=est,
            program_id=program_id,
            mission_template=mission_template,
            intent="archive_ingest",
        )

    def admit_realtime(
        self,
        *,
        program_id: str,
        mission_template: str,
        intent: str = "realtime_tick",
    ) -> AdmissionContract:
        """Fast path for Market / timing-sensitive work — Accepted immediate."""
        return AdmissionContract(
            status=STATUS_ACCEPTED,
            reason="realtime_fast_path",
            run_mode="immediate",
            program_id=program_id,
            mission_template=mission_template,
            intent=intent,
        )

    # --- internals -------------------------------------------------------

    def _needs_confirm(self, est: WorkEstimate) -> bool:
        if est.file_count is not None and est.file_count >= self._confirm_files:
            return True
        if est.duration_seconds is not None and est.duration_seconds >= self._confirm_duration:
            return True
        if est.storage_growth_mb is not None and est.storage_growth_mb >= self._confirm_growth:
            return True
        if est.byte_count is not None and est.byte_count >= CONFIRM_BYTES:
            return True
        if est.truncated and (est.file_count or 0) >= MAX_FILES_COUNTED:
            return True
        return False

    def _confirm_reason(self, est: WorkEstimate) -> str:
        parts = []
        if est.file_count is not None:
            parts.append(f"~{est.file_count} files")
        if est.duration_seconds is not None:
            hours = est.duration_seconds / 3600.0
            parts.append(f"~{hours:.1f}h wall time")
        if est.storage_growth_mb is not None:
            parts.append(f"~{est.storage_growth_mb:.0f} MB growth")
        if est.truncated:
            parts.append("walk truncated")
        detail = ", ".join(parts) if parts else "large archive"
        return f"needs operator confirmation ({detail})"

    def _capacity_reason(self, *, worker_type: str) -> str | None:
        if self._host_guard is None:
            return None
        try:
            if hasattr(self._host_guard, "should_queue_archive_start"):
                if self._host_guard.should_queue_archive_start():
                    return "archive worker slots full"
            if hasattr(self._host_guard, "can_run_tick"):
                ok, reason = self._host_guard.can_run_tick(worker_type=worker_type)
                if not ok:
                    return reason or "host_pressure"
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("capacity check failed: %s", exc)
        return None

    def _fingerprint(self, path: str, estimate: WorkEstimate) -> str:
        raw = f"{path}|{estimate.file_count}|{estimate.byte_count}|{estimate.duration_seconds}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _store_pending(
        self,
        *,
        path: str,
        kind: str,
        estimate: WorkEstimate,
        program_id: str,
        mission_template: str,
    ) -> str:
        self._purge_expired()
        token = secrets.token_urlsafe(18)
        pending = _PendingAdmission(
            token=token,
            path=path,
            kind=kind,
            estimate=estimate,
            program_id=program_id,
            mission_template=mission_template,
            created_at=time.time(),
            fingerprint=self._fingerprint(path, estimate),
        )
        with self._lock:
            self._pending[token] = pending
        return token

    def _consume_pending(self, token: str, path: str) -> _PendingAdmission | None:
        self._purge_expired()
        with self._lock:
            pending = self._pending.pop(token, None)
        if pending is None:
            return None
        # Path must match what was estimated (resolve both).
        try:
            if Path(pending.path).resolve() != Path(path).expanduser().resolve():
                return None
        except OSError:
            if pending.path != path:
                return None
        return pending

    def _purge_expired(self) -> None:
        now = time.time()
        with self._lock:
            expired = [
                t for t, p in self._pending.items() if now - p.created_at > PENDING_TTL_SECONDS
            ]
            for t in expired:
                self._pending.pop(t, None)

    def pending_count(self) -> int:
        self._purge_expired()
        with self._lock:
            return len(self._pending)
