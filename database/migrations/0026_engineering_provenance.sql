-- Atlas Migration 0026: Engineering provenance — stable repo identity + asset link (Phase B · PHASE_B_PLAN §B.1, BB12/P2)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- Phase B grows Engineering Intelligence into the roadmap pipeline (Asset Store → Readers →
-- Knowledge). B.1 is the seam: a learned repository stops being "just a filesystem path" and
-- gains a **durable identity** independent of where it lives, plus a **provenance link** to the
-- raw bytes it was distilled from (an `asset.assets` `git_repo` version). No new tables — we only
-- extend `learning.repositories` (P5/P7: extend, don't proliferate schema).
--
--   * repo_uid          — stable Repository UUID (BB12), independent of path / remote URL / clone
--                         location. Resolved from the git **root-commit** → normalized remote →
--                         a path-derived UUID, so moving/re-cloning a repo keeps the same id.
--   * root_commit       — the git first-commit hash used to derive repo_uid (NULL for non-git).
--   * normalized_remote — normalized remote URL (creds stripped, .git trimmed), when known.
--   * asset_id          — soft ref → asset.assets(id): the `git_repo` asset this was distilled
--     asset_version       from, and its version. Lets a better reader later re-extract from the
--                         stored bytes (a re-extraction, never a re-download — P8/Assets≠Knowledge).
--
-- All columns are nullable so pre-Phase-B rows remain valid; cross-schema refs are deliberately
-- soft (no FK into asset.*), matching the house pattern (0019/0024).

ALTER TABLE learning.repositories ADD COLUMN IF NOT EXISTS repo_uid          UUID;
ALTER TABLE learning.repositories ADD COLUMN IF NOT EXISTS root_commit       TEXT;
ALTER TABLE learning.repositories ADD COLUMN IF NOT EXISTS normalized_remote TEXT;
ALTER TABLE learning.repositories ADD COLUMN IF NOT EXISTS asset_id          UUID;   -- soft ref → asset.assets(id)
ALTER TABLE learning.repositories ADD COLUMN IF NOT EXISTS asset_version     INTEGER;

-- One active learned row per repository identity (mirrors the root-based partial unique index).
CREATE UNIQUE INDEX IF NOT EXISTS uq_learning_repositories_repo_uid_active
    ON learning.repositories (repo_uid)
    WHERE status = 'active' AND repo_uid IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_learning_repositories_repo_uid
    ON learning.repositories (repo_uid);
