-- Atlas Migration 0001: Extensions, Schemas, and Security
-- Idempotent: safe to re-run

-- Extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

-- Schemas (already exist from manual setup; IF NOT EXISTS keeps this safe)
CREATE SCHEMA IF NOT EXISTS system AUTHORIZATION atlas;
CREATE SCHEMA IF NOT EXISTS knowledge AUTHORIZATION atlas;
CREATE SCHEMA IF NOT EXISTS memory AUTHORIZATION atlas;
CREATE SCHEMA IF NOT EXISTS scheduler AUTHORIZATION atlas;
CREATE SCHEMA IF NOT EXISTS audit AUTHORIZATION atlas;

-- Prevent accidental object creation in public (ADR-0014)
REVOKE CREATE ON SCHEMA public FROM atlas;
REVOKE ALL ON SCHEMA public FROM PUBLIC;

-- ...but atlas still needs to USE extension types/operators that install into
-- public (e.g. pgvector's `vector` type and `<=>` operator). USAGE allows
-- referencing them; CREATE remains revoked so no objects land in public.
GRANT USAGE ON SCHEMA public TO atlas;

-- Strict search_path for atlas role (public last, for extension objects only)
ALTER ROLE atlas SET search_path TO system, knowledge, memory, scheduler, audit, public;
