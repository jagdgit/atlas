"""Retention for the high-churn tick tables (O6).

Why this exists: on 2026-10-07 the root filesystem hit 100% (828 MB free) and Postgres
began failing queries with ``DiskFull``. Atlas's own database was 40 GB of the 93 GB
used, and 28 GB of that was three tables holding **~37 million rows each**, accumulated
since 2026-07-11 with nothing ever deleting them:

    audit.events          37,329,615 rows   12 GB
    scheduler.task_runs   36,962,729 rows    9 GB
    scheduler.tasks       36,960,401 rows  7.4 GB

``audit.retention_days: 90`` had been in ``config/defaults.yaml`` the whole time and was
read by nothing — a promise with no implementation. The scheduler tables had no
retention setting at all. The cost compounded through backups: each nightly ``pg_dump``
was 11.8 GB and growing, so seven retained dumps held 76 GB of mostly expired ticks.

Design notes:

* **Deletes are batched.** A single ``DELETE`` over 30 million rows would hold one
  transaction open for the whole run, write WAL faster than it can be archived, and on
  an already-full disk is as likely to make things worse as better. Each batch is its
  own transaction with a bounded row count.
* **``scheduler.tasks`` only.** ``task_runs.task_id`` is
  ``REFERENCES tasks(id) ON DELETE CASCADE``, so pruning parent tasks removes their runs
  in the same statement. Deleting runs separately would be redundant work.
* **Terminal-and-uninteresting rows only.** ``pending``/``running`` are live work and
  ``failed`` rows are the evidence an operator needs after an incident, so only
  ``completed`` and ``cancelled`` are eligible.
* **Dry run by default.** This deletes history irreversibly, so it reports what it would
  remove and changes nothing until an operator sets ``retention.enabled: true``.
* Space is **not** returned to the filesystem by ``DELETE`` — it becomes reusable inside
  the table, which stops the growth. Returning it needs ``VACUUM FULL`` (or
  ``pg_repack``) and free space roughly equal to the table, so it is a separate,
  operator-run step.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

# One batch per statement. 20k keeps each transaction short enough that a tick waiting
# on the same table is not noticeably delayed.
_BATCH_ROWS = 20_000
# Ceiling per run, so a scheduled prune has a bounded worst case instead of trying to
# delete 30 million rows in one tick.
_MAX_BATCHES = 50


@dataclass(frozen=True)
class RetentionRule:
    """One table's policy. ``where`` further narrows what is eligible."""

    table: str
    timestamp_column: str
    days: int
    where: str = ""
    # Documented reason this rule is safe to apply, surfaced in the report.
    note: str = ""


@dataclass
class RetentionOutcome:
    dry_run: bool = True
    rules: list[dict[str, Any]] = field(default_factory=list)
    deleted_total: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "rules": self.rules,
            "deleted_total": self.deleted_total,
            "errors": self.errors,
        }


def default_rules(
    *,
    audit_days: int,
    scheduler_days: int,
    health_days: int,
) -> tuple[RetentionRule, ...]:
    return (
        RetentionRule(
            table="scheduler.tasks",
            timestamp_column="created_at",
            days=scheduler_days,
            # `failed` is deliberately retained: it is the evidence trail for incidents
            # like the `no handler registered` outage, which was diagnosed from exactly
            # these rows.
            where="status IN ('completed', 'cancelled')",
            note="cascades to scheduler.task_runs; keeps failed/pending/running",
        ),
        RetentionRule(
            table="audit.events",
            timestamp_column="created_at",
            days=audit_days,
            # `processed_at IS NOT NULL` was the obvious guard and it is a permanent
            # no-op here: all 37,329,934 rows are `status='pending'` with
            # `processed_at` never set, because nothing consumes this table. So
            # eligibility is by *event type* instead — the tick telemetry below is 99.3%
            # of the table and carries no decision history. Anything else
            # (DecisionMade, KernelStarted, and every future type) is retained, so a
            # new event type is kept by default rather than silently pruned.
            where=(
                "(processed_at IS NOT NULL OR event_type IN "
                "('TaskCompleted', 'WorkerTick', 'SchedulesFired', 'WorkerThrottled'))"
            ),
            note="processed events plus tick telemetry; keeps DecisionMade and unknown types",
        ),
        RetentionRule(
            table="system.health",
            timestamp_column="checked_at",
            days=health_days,
            note="per-service health samples; 8.9 GB of TOAST at discovery",
        ),
    )


class RetentionManager:
    """Prunes expired rows from the tick tables, in bounded batches."""

    def __init__(
        self,
        db: Any,
        rules: tuple[RetentionRule, ...],
        *,
        enabled: bool = False,
        batch_rows: int = _BATCH_ROWS,
        max_batches: int = _MAX_BATCHES,
        enqueue: Any = None,
        count_pending: Any = None,
        interval_seconds: float = 3600.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self._db = db
        self._rules = rules
        self._enabled = enabled
        self._batch_rows = max(1, int(batch_rows))
        self._max_batches = max(1, int(max_batches))
        self._enqueue = enqueue
        self._count_pending = count_pending
        self._interval = float(interval_seconds)
        self._logger = logger or logging.getLogger("atlas.ops.retention")

    # --- counting -------------------------------------------------------
    def _expired_count(self, rule: RetentionRule) -> int:
        clause = f" AND {rule.where}" if rule.where else ""
        sql = (
            f"SELECT count(*) FROM {rule.table} "
            f"WHERE {rule.timestamp_column} < now() - interval '{int(rule.days)} days'"
            f"{clause}"
        )
        with self._db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                row = cur.fetchone()
        return int(row[0]) if row else 0

    def _delete_batch(self, rule: RetentionRule) -> int:
        """Delete up to ``batch_rows`` expired rows; return how many went."""
        clause = f" AND {rule.where}" if rule.where else ""
        # ctid is the cheapest stable handle for "some bounded set of matching rows"
        # and avoids assuming the table has a single-column primary key.
        sql = (
            f"DELETE FROM {rule.table} WHERE ctid IN ("
            f"SELECT ctid FROM {rule.table} "
            f"WHERE {rule.timestamp_column} < now() - interval '{int(rule.days)} days'"
            f"{clause} LIMIT {self._batch_rows})"
        )
        with self._db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                return int(cur.rowcount or 0)

    # --- the task -------------------------------------------------------
    def prune(self) -> RetentionOutcome:
        outcome = RetentionOutcome(dry_run=not self._enabled)
        for rule in self._rules:
            if rule.days <= 0:
                continue
            entry: dict[str, Any] = {
                "table": rule.table,
                "days": rule.days,
                "note": rule.note,
                "expired": 0,
                "deleted": 0,
            }
            try:
                entry["expired"] = self._expired_count(rule)
            except Exception as exc:  # noqa: BLE001 - one bad rule must not stop the rest
                message = f"{rule.table}: {type(exc).__name__}: {exc}"
                outcome.errors.append(message)
                self._logger.warning("retention count failed for %s", message)
                outcome.rules.append(entry)
                continue

            if entry["expired"] and self._enabled:
                deleted = 0
                try:
                    for _ in range(self._max_batches):
                        batch = self._delete_batch(rule)
                        deleted += batch
                        if batch < self._batch_rows:
                            break
                except Exception as exc:  # noqa: BLE001
                    message = f"{rule.table}: {type(exc).__name__}: {exc}"
                    outcome.errors.append(message)
                    self._logger.warning("retention delete failed for %s", message)
                entry["deleted"] = deleted
                outcome.deleted_total += deleted

            outcome.rules.append(entry)

        if outcome.dry_run:
            pending = sum(int(r["expired"]) for r in outcome.rules)
            if pending:
                # Loud on purpose: a silent dry run is how `audit.retention_days` sat
                # unimplemented for three months.
                self._logger.warning(
                    "retention DRY RUN: %d expired row(s) across %d table(s) would be "
                    "deleted; set retention.enabled=true to apply. Detail: %s",
                    pending,
                    len([r for r in outcome.rules if r["expired"]]),
                    "; ".join(
                        f"{r['table']}={r['expired']}" for r in outcome.rules if r["expired"]
                    ),
                )
        else:
            self._logger.info(
                "retention pruned %d row(s): %s",
                outcome.deleted_total,
                "; ".join(f"{r['table']}={r['deleted']}" for r in outcome.rules),
            )
        return outcome

    def prune_task(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Scheduler entry point."""
        return self.prune().as_dict()
