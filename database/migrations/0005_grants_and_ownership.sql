-- Atlas Migration 0005: Ownership and Grants
--
-- Migrations 0001-0004 were bootstrapped as the postgres superuser, so their
-- objects are owned by postgres. The atlas application role needs to own (and
-- therefore fully control) everything in the Atlas schemas.
--
-- This migration reassigns ownership of all tables, sequences, and views in the
-- Atlas-managed schemas to the atlas role. It is idempotent and safe to re-run;
-- it also covers any objects added by future superuser-run migrations.
--
-- Run as: sudo -u postgres psql -d atlas -f database/migrations/0005_grants_and_ownership.sql

DO $$
DECLARE
    r RECORD;
    target_schemas TEXT[] := ARRAY['system', 'knowledge', 'memory', 'scheduler', 'audit'];
BEGIN
    -- Tables
    FOR r IN
        SELECT schemaname, tablename
        FROM pg_tables
        WHERE schemaname = ANY(target_schemas)
    LOOP
        EXECUTE format('ALTER TABLE %I.%I OWNER TO atlas', r.schemaname, r.tablename);
    END LOOP;

    -- Sequences
    FOR r IN
        SELECT sequence_schema, sequence_name
        FROM information_schema.sequences
        WHERE sequence_schema = ANY(target_schemas)
    LOOP
        EXECUTE format('ALTER SEQUENCE %I.%I OWNER TO atlas', r.sequence_schema, r.sequence_name);
    END LOOP;

    -- Views
    FOR r IN
        SELECT schemaname, viewname
        FROM pg_views
        WHERE schemaname = ANY(target_schemas)
    LOOP
        EXECUTE format('ALTER VIEW %I.%I OWNER TO atlas', r.schemaname, r.viewname);
    END LOOP;
END $$;
