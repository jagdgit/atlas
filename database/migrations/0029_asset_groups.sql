-- Atlas Migration 0029: Asset relationships / groups (Phase C · PHASE_C_PLAN §C.2, §5.9)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- (The Phase C plan penciled this as migration 0035, assuming other Phase-C migrations landed
-- first; it is renumbered here to the next sequential slot, 0029.)
--
-- Assets rarely stand alone: a code repo, its design doc, and the chat where it was discussed are
-- *related*. An **asset group** ties related assets together so knowledge extracted from one can be
-- correlated with the others (P9 explainability, and the groundwork for §C-Personal's "everything
-- about topic X"). A group is a lightweight, named bag of asset memberships — NOT ownership: assets
-- live independently in `asset.assets` and may belong to many groups (or none). Deleting a group
-- deletes only its memberships (ON DELETE CASCADE), never the assets.

CREATE TABLE IF NOT EXISTS asset.groups (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind        TEXT NOT NULL,            -- project | topic | conversation | source | ...
    name        TEXT NOT NULL,            -- logical label, unique within a kind
    metadata    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT asset_groups_kind_name_uniq UNIQUE (kind, name)
);

CREATE INDEX IF NOT EXISTS idx_asset_groups_kind ON asset.groups (kind);

CREATE TABLE IF NOT EXISTS asset.group_members (
    group_id    UUID NOT NULL REFERENCES asset.groups(id)  ON DELETE CASCADE,
    asset_id    UUID NOT NULL REFERENCES asset.assets(id)  ON DELETE CASCADE,
    role        TEXT,                     -- primary | reference | transcript | ... (optional)
    metadata    JSONB NOT NULL DEFAULT '{}',
    added_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (group_id, asset_id)
);

-- "which groups is this asset in?" is a hot reverse lookup.
CREATE INDEX IF NOT EXISTS idx_asset_group_members_asset ON asset.group_members (asset_id);
