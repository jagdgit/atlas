-- Atlas Migration 0040: Decision approval gate (Phase D · PHASE_D_PLAN §D.3 / P14)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- P14 — Atlas recommends; the operator decides. A decision that would **act on the world**
-- (side-effecting) is not applied automatically: the Decision Engine marks it `requires_approval` and
-- an approval is **proposed** here. The operator **approves** or **rejects**; only on approval is the
-- action **applied** (by a registered ActionApplier for that mission type), capturing before/after
-- snapshots so it can be **reverted**. Read/advice/simulation decisions never enter this table (DD3).
--
-- Lifecycle:  proposed → approved → applied → reverted
--                     ↘ rejected
-- Append-a-history-by-mutation-of-one-row: the single row carries who/when at each step; the durable
-- audit trail of the state changes lives in `audit.events` (every transition is emitted). Snapshots are
-- refs/small state, not copies (A8).

CREATE SCHEMA IF NOT EXISTS decision AUTHORIZATION atlas;

CREATE TABLE IF NOT EXISTS decision.approvals (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_id   UUID,                              -- soft ref → decision.decisions(id)
    mission_id    UUID,                              -- soft ref → mission.missions(id) (provenance)
    mission_type  TEXT NOT NULL,                     -- selects the ActionApplier at apply time
    action        JSONB NOT NULL DEFAULT '{}',       -- the side-effecting action awaiting the gate
    status        TEXT NOT NULL DEFAULT 'proposed',  -- proposed | approved | rejected | applied | reverted
    note          TEXT,
    requested_by  TEXT,
    requested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_by    TEXT,                              -- who approved/rejected
    decided_at    TIMESTAMPTZ,
    applied_at    TIMESTAMPTZ,
    before        JSONB,                             -- world state before apply (for revert)
    after         JSONB,                             -- world state after apply (for revert)
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT approvals_status_check
        CHECK (status IN ('proposed', 'approved', 'rejected', 'applied', 'reverted'))
);

-- Hot paths: the operator's pending queue, and a decision's / mission's approval history.
CREATE INDEX IF NOT EXISTS idx_approvals_pending  ON decision.approvals (requested_at DESC)
    WHERE status = 'proposed';
CREATE INDEX IF NOT EXISTS idx_approvals_decision ON decision.approvals (decision_id);
CREATE INDEX IF NOT EXISTS idx_approvals_mission  ON decision.approvals (mission_id, requested_at DESC);
