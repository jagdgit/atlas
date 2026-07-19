-- Atlas Migration 0025: Mission Templates (Phase A · PHASE_A_PLAN §A.5, B7)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- Reusable, versioned blueprints for instantiating missions (Docker-Compose-like): a template
-- declares its worker set + default (versioned) config schema + knowledge domains + success
-- criteria, and `instantiate(name, overrides)` produces a concrete Mission + config v1 + worker
-- rows. Built-ins are UPSERTED by name on boot (the app is the source of truth), so this table
-- ships empty and is seeded by atlas/missions/templates.
--
-- Versioning (B7): each template carries `template_version`; a mission stamps the
-- `template_id + template_version` it was instantiated from (mission.missions, 0021). Bumping a
-- built-in never mutates existing operator missions — upgrading is an explicit, later choice.

CREATE TABLE IF NOT EXISTS mission.templates (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                  TEXT NOT NULL UNIQUE,
    template_version      INTEGER NOT NULL DEFAULT 1,
    description           TEXT NOT NULL DEFAULT '',
    worker_specs          JSONB NOT NULL DEFAULT '[]',   -- [{type, interval_seconds}, …]
    config_schema_type    TEXT NOT NULL,
    config_schema_version INTEGER NOT NULL DEFAULT 1,
    default_config        JSONB NOT NULL DEFAULT '{}',
    knowledge_domains     TEXT[] NOT NULL DEFAULT '{}',
    success_criteria      JSONB NOT NULL DEFAULT '{}',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT templates_version_check CHECK (template_version >= 1)
);
