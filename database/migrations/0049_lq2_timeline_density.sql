-- Atlas Migration 0049: LQ.2 denser evolution checkpoints (day3, day14)
-- Idempotent. Widens decision.revisits checkpoint CHECK; keeps DI.2 names.

ALTER TABLE decision.revisits
    DROP CONSTRAINT IF EXISTS decision_revisits_checkpoint_check;

ALTER TABLE decision.revisits
    ADD CONSTRAINT decision_revisits_checkpoint_check
    CHECK (checkpoint IN (
        'day1', 'day3', 'week1', 'day14', 'month1', 'quarter', 'exit'
    ));
