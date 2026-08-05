"""ARMF Phase B — Ops cleanup toolkit (zombie / long no-progress retirement).

**Constitution:** Host congestion is handled by **defer / queue / raise capacity** —
never by stopping a Program worker mid-job. Accepted program work is not dropped
(Host Respect / RESOURCE_OS). Cleanup may only retire:

* orphan demo zombies (default: ``hello_watcher``), and
* unprotected long no-progress workers,

and **never** Market / Engineering / Personal / Archive workers unless the operator
explicitly sets ``include_protected=True`` (Ops checkbox).

Always dry-run first; apply archives missions (non-destructive — keeps journal,
configs, checkpoints).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from atlas.ops.worker_states import STARVE_AFTER_SECONDS, classify_worker

# B2 defaults
DEFAULT_ZOMBIE_TYPES: frozenset[str] = frozenset({"hello_watcher"})
DEFAULT_MIN_STARVATION_AGE_SECONDS = STARVE_AFTER_SECONDS  # 6h — same as starved

# B4 — never auto-kill without checkbox
PROTECTED_PROGRAMS: frozenset[str] = frozenset(
    {
        "market_intelligence",
        "engineering_intelligence",
        "personal_intelligence",
    }
)
PROTECTED_WORKER_TYPES: frozenset[str] = frozenset(
    {
        "owner_knowledge",
        "paper_trading",
        "decision_simulation",
        "portfolio_ledger",
        "market_observer",
        # Personal / Career — never retire mid-program without include_protected
        "career_observer",
        "career_research",
        "job_watcher",
        "personal_mentor",
        # Engineering continuous learning
        "repo_watcher",
        "engineering_mentor",
    }
)
PROTECTED_SERVICE_CLASSES: frozenset[str] = frozenset({"archive"})

# Workers already terminal — nothing to clean.
_TERMINAL_WORKER = frozenset({"stopped", "failed"})


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def is_protected_worker(row: dict[str, Any]) -> bool:
    """True if Market / Eng / Personal / Archive — requires include_protected."""
    owner = row.get("owner") if isinstance(row.get("owner"), dict) else {}
    prog = str(owner.get("program") or "").strip()
    if prog in PROTECTED_PROGRAMS:
        return True
    wtype = str(row.get("type") or "")
    if wtype in PROTECTED_WORKER_TYPES:
        return True
    sc = str(row.get("service_class") or "").lower()
    if sc in PROTECTED_SERVICE_CLASSES or "archive" in sc:
        return True
    return False


def select_cleanup_candidates(
    workers: list[Any],
    *,
    now: datetime | None = None,
    zombie_types: frozenset[str] | set[str] | None = None,
    min_starvation_age_seconds: float = DEFAULT_MIN_STARVATION_AGE_SECONDS,
    include_protected: bool = False,
    worker_ids: set[str] | frozenset[str] | None = None,
    mission_ids: set[str] | frozenset[str] | None = None,
) -> dict[str, Any]:
    """Classify cleanup candidates (pure — no I/O).

    Returns ``candidates``, ``skipped`` (protected / filtered), and summary counts.
    """
    now = _aware(now) or datetime.now(timezone.utc)
    zombies = frozenset(zombie_types) if zombie_types is not None else DEFAULT_ZOMBIE_TYPES
    id_filter = frozenset(str(x) for x in worker_ids) if worker_ids else None
    mid_filter = frozenset(str(x) for x in mission_ids) if mission_ids else None

    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    seen_missions: set[str] = set()

    for w in workers:
        row = classify_worker(w, now=now)
        wid = str(row.get("id") or "")
        mid = str(row.get("mission_id") or "") or None
        wtype = str(row.get("type") or "")
        status = str(row.get("status") or "")
        age = row.get("starvation_age_seconds")
        age_f = float(age) if age is not None else None

        if id_filter is not None and wid not in id_filter:
            continue
        if mid_filter is not None and (not mid or mid not in mid_filter):
            continue
        if status in _TERMINAL_WORKER:
            skipped.append({**_candidate_base(row), "skip_reason": f"already_{status}"})
            continue

        protected = is_protected_worker(row)
        reason = None
        # When the operator passes an explicit zombie_types list, only match those
        # types (do not also pull every long-no-progress worker into the candidate set).
        explicit_zombies = zombie_types is not None
        if wtype in zombies:
            reason = f"zombie_type:{wtype}"
        elif (not explicit_zombies) and age_f is not None and age_f >= float(min_starvation_age_seconds):
            reason = f"long_no_progress:{int(age_f)}s"
        else:
            skipped.append({**_candidate_base(row), "skip_reason": "not_matching_policy"})
            continue

        if protected and not include_protected and wtype not in zombies:
            # hello_watcher always eligible; other long-noprogress on protected programs need checkbox
            skipped.append(
                {
                    **_candidate_base(row),
                    "skip_reason": "protected_requires_checkbox",
                    "protected": True,
                    "match_reason": reason,
                }
            )
            continue

        # Even hello_watcher under a protected program label: still cleanable (zombie),
        # but note protection for operator visibility.
        entry = {
            **_candidate_base(row),
            "reason": reason,
            "protected": protected,
            "action": "archive_mission" if mid else "stop_worker",
        }
        candidates.append(entry)
        if mid:
            seen_missions.add(mid)

    return {
        "version": "armf.b1",
        "policy": {
            "zombie_types": sorted(zombies),
            "min_starvation_age_seconds": float(min_starvation_age_seconds),
            "include_protected": bool(include_protected),
            "protected_programs": sorted(PROTECTED_PROGRAMS),
        },
        "candidates": candidates,
        "skipped": skipped[:50],
        "counts": {
            "candidates": len(candidates),
            "missions": len(seen_missions),
            "skipped": len(skipped),
            "protected_skipped": sum(
                1 for s in skipped if s.get("skip_reason") == "protected_requires_checkbox"
            ),
        },
    }


def _candidate_base(row: dict[str, Any]) -> dict[str, Any]:
    owner = row.get("owner") if isinstance(row.get("owner"), dict) else {}
    return {
        "worker_id": row.get("id"),
        "mission_id": row.get("mission_id"),
        "type": row.get("type"),
        "status": row.get("status"),
        "ops_state": row.get("ops_state"),
        "wait_reason": row.get("wait_reason"),
        "starvation_age_seconds": row.get("starvation_age_seconds"),
        "program": owner.get("program"),
        "service_class": row.get("service_class"),
    }


class OpsCleanupService:
    """Preview + apply Ops cleanup (ARMF Phase B)."""

    name = "ops_cleanup"
    VERSION = "armf.b1"

    def __init__(
        self,
        *,
        workers: Any | None = None,
        missions: Any | None = None,
        clock: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._workers = workers
        self._missions = missions
        self._clock = clock
        self._logger = logger or logging.getLogger("atlas.ops.cleanup")

    def preview(
        self,
        *,
        zombie_types: list[str] | None = None,
        min_starvation_age_seconds: float = DEFAULT_MIN_STARVATION_AGE_SECONDS,
        include_protected: bool = False,
        worker_ids: list[str] | None = None,
        mission_ids: list[str] | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        return self.run(
            dry_run=True,
            zombie_types=zombie_types,
            min_starvation_age_seconds=min_starvation_age_seconds,
            include_protected=include_protected,
            worker_ids=worker_ids,
            mission_ids=mission_ids,
            limit=limit,
        )

    def run(
        self,
        *,
        dry_run: bool = True,
        zombie_types: list[str] | None = None,
        min_starvation_age_seconds: float = DEFAULT_MIN_STARVATION_AGE_SECONDS,
        include_protected: bool = False,
        worker_ids: list[str] | None = None,
        mission_ids: list[str] | None = None,
        reason: str = "",
        limit: int = 500,
    ) -> dict[str, Any]:
        if self._workers is None or not hasattr(self._workers, "list_workers"):
            return {
                "dry_run": dry_run,
                "ok": False,
                "error": "workers unavailable",
                "candidates": [],
                "applied": [],
                "counts": {"candidates": 0, "missions": 0, "applied": 0, "errors": 0},
            }

        now = None
        if self._clock is not None and hasattr(self._clock, "now"):
            try:
                now = self._clock.now()
            except Exception:  # noqa: BLE001
                now = None

        try:
            rows = self._workers.list_workers(limit=max(1, limit))
        except TypeError:
            rows = self._workers.list_workers()
        ztypes = frozenset(zombie_types) if zombie_types else None
        selection = select_cleanup_candidates(
            rows,
            now=now,
            zombie_types=ztypes,
            min_starvation_age_seconds=min_starvation_age_seconds,
            include_protected=include_protected,
            worker_ids=set(worker_ids) if worker_ids else None,
            mission_ids=set(mission_ids) if mission_ids else None,
        )

        # Enrich mission titles + already-archived flags when possible
        if self._missions is not None:
            for c in selection["candidates"]:
                mid = c.get("mission_id")
                if not mid:
                    continue
                title = self._mission_title(mid)
                if title:
                    c["mission_title"] = title
                st = self._mission_status(str(mid))
                if st == "archived":
                    c["mission_status"] = "archived"
                    c["note"] = "mission already archived — apply will stop orphan worker only"

        out: dict[str, Any] = {
            "dry_run": bool(dry_run),
            "ok": True,
            **selection,
            "applied": [],
            "errors": [],
        }

        if dry_run:
            out["message"] = (
                f"Dry-run: would archive {selection['counts']['missions']} mission(s) "
                f"covering {selection['counts']['candidates']} worker(s)."
            )
            return out

        # Apply — archive each distinct mission once; stop orphan workers without mission.
        archive_reason = (reason or "").strip() or "ops_cleanup:armf_phase_b"
        applied: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        archived_missions: set[str] = set()

        for c in selection["candidates"]:
            mid = c.get("mission_id")
            wid = c.get("worker_id")
            try:
                if mid and mid not in archived_missions:
                    if self._missions is None or not hasattr(self._missions, "archive"):
                        raise RuntimeError("missions.archive unavailable")
                    # Idempotent: missions already archived must not error — stop orphan workers.
                    already = self._mission_status(mid)
                    if already == "archived":
                        archived_missions.add(str(mid))
                        self._stop_worker_quiet(wid, archive_reason)
                        applied.append(
                            {
                                "action": "already_archived",
                                "mission_id": str(mid),
                                "worker_id": wid,
                                "type": c.get("type"),
                                "status": "archived",
                                "reason": c.get("reason"),
                            }
                        )
                        continue
                    try:
                        mission = self._missions.archive(mid, archive_reason)
                    except Exception as exc:  # noqa: BLE001
                        # Race / repeat apply: treat archived→archived as success.
                        msg = str(exc).lower()
                        if "archived" in msg and ("→ archived" in msg or "-> archived" in msg):
                            archived_missions.add(str(mid))
                            self._stop_worker_quiet(wid, archive_reason)
                            applied.append(
                                {
                                    "action": "already_archived",
                                    "mission_id": str(mid),
                                    "worker_id": wid,
                                    "type": c.get("type"),
                                    "status": "archived",
                                    "reason": c.get("reason"),
                                }
                            )
                            continue
                        raise
                    archived_missions.add(str(mid))
                    status = getattr(mission, "status", None) or (
                        mission.get("status") if isinstance(mission, dict) else None
                    )
                    applied.append(
                        {
                            "action": "archive_mission",
                            "mission_id": str(mid),
                            "worker_id": wid,
                            "type": c.get("type"),
                            "status": status,
                            "reason": c.get("reason"),
                        }
                    )
                elif not mid and wid:
                    if not hasattr(self._workers, "stop_worker"):
                        raise RuntimeError("workers.stop_worker unavailable")
                    self._workers.stop_worker(wid, archive_reason)
                    applied.append(
                        {
                            "action": "stop_worker",
                            "mission_id": None,
                            "worker_id": wid,
                            "type": c.get("type"),
                            "reason": c.get("reason"),
                        }
                    )
                elif mid and mid in archived_missions:
                    self._stop_worker_quiet(wid, archive_reason)
                    applied.append(
                        {
                            "action": "already_archived_with_peer",
                            "mission_id": str(mid),
                            "worker_id": wid,
                            "type": c.get("type"),
                            "reason": c.get("reason"),
                        }
                    )
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("cleanup apply failed for %s/%s: %s", mid, wid, exc)
                errors.append(
                    {
                        "mission_id": mid,
                        "worker_id": wid,
                        "error": str(exc),
                    }
                )

        out["applied"] = applied
        out["errors"] = errors
        out["counts"] = {
            **selection["counts"],
            "applied": len(
                [
                    a
                    for a in applied
                    if a["action"]
                    in ("archive_mission", "stop_worker", "already_archived", "already_archived_with_peer")
                ]
            ),
            "errors": len(errors),
        }
        out["ok"] = len(errors) == 0
        out["message"] = (
            f"Applied: archived {len(archived_missions)} mission(s); "
            f"{len(errors)} error(s)."
        )
        return out

    def _mission_status(self, mid: str) -> str | None:
        try:
            m = None
            if hasattr(self._missions, "get"):
                m = self._missions.get(mid)
            elif hasattr(self._missions, "get_mission"):
                view = self._missions.get_mission(mid)
                if isinstance(view, dict):
                    m = view.get("mission") or view
                else:
                    m = view
            if m is None:
                return None
            return str(getattr(m, "status", None) or (m.get("status") if isinstance(m, dict) else "") or "")
        except Exception:  # noqa: BLE001
            return None

    def _stop_worker_quiet(self, wid: str | None, reason: str) -> None:
        if not wid or self._workers is None or not hasattr(self._workers, "stop_worker"):
            return
        try:
            self._workers.stop_worker(wid, reason)
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("cleanup stop_worker %s: %s", wid, exc)

    def _mission_title(self, mid: str) -> str | None:
        try:
            if hasattr(self._missions, "get"):
                m = self._missions.get(mid)
                if m is not None:
                    return getattr(m, "title", None) or (
                        m.get("title") if isinstance(m, dict) else None
                    )
            if hasattr(self._missions, "get_mission"):
                view = self._missions.get_mission(mid)
                if isinstance(view, dict):
                    m = view.get("mission") or {}
                    if isinstance(m, dict):
                        return m.get("title")
                    return getattr(m, "title", None)
        except Exception:  # noqa: BLE001
            return None
        return None
