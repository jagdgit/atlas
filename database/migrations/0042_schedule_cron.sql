-- Atlas Migration 0042: Cron schedules (OI-A1)
-- Idempotent. Extends scheduler.schedules with kind + cron_expr; interval rows unchanged.
-- Cron rows keep interval_seconds as a sentinel (>=1) unused for advance; next_run_at is
-- computed from cron_expr in ScheduleRepository.claim_due.

ALTER TABLE scheduler.schedules
    ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'interval',
    ADD COLUMN IF NOT EXISTS cron_expr TEXT;

-- Drop old interval-only check; replace with kind-aware constraint.
ALTER TABLE scheduler.schedules DROP CONSTRAINT IF EXISTS schedules_interval_check;
ALTER TABLE scheduler.schedules DROP CONSTRAINT IF EXISTS schedules_kind_check;
ALTER TABLE scheduler.schedules DROP CONSTRAINT IF EXISTS schedules_cron_check;

ALTER TABLE scheduler.schedules
    ADD CONSTRAINT schedules_kind_check
        CHECK (kind IN ('interval', 'cron')),
    ADD CONSTRAINT schedules_interval_check
        CHECK (interval_seconds >= 1),
    ADD CONSTRAINT schedules_cron_check
        CHECK (
            (kind = 'interval' AND cron_expr IS NULL)
            OR (kind = 'cron' AND cron_expr IS NOT NULL AND length(trim(cron_expr)) > 0)
        );

CREATE INDEX IF NOT EXISTS idx_schedules_kind
    ON scheduler.schedules (kind) WHERE enabled;
