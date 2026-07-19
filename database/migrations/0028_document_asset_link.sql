-- Atlas Migration 0028: Document ↔ Asset link (Phase C · PHASE_C_PLAN §C.2, P8/P11)
-- Idempotent: safe to re-run. Applied by the atlas app role via `atlas-db migrate`.
--
-- Unified ingestion (P11): a `knowledge.documents` row is the *chunked/embedded* product of
-- reading a source **Asset** (Asset → Reader → Artifact → chunks). Link each document back to the
-- (asset_id, asset_version) it was derived from so that:
--   * retrieval hits are traceable to the raw bytes they came from (P9, explainability);
--   * re-derivation (improved chunker/embedder) can find the source asset;
--   * "which documents came from this asset?" is a fast, indexed lookup.
--
-- These are **soft references** (no cross-schema FK into `asset.*`, matching 0019/0027) and
-- NULLABLE: inline notes, web text, and all pre-Phase-C documents have no backing asset and stay
-- valid. They are provenance, never a visibility/delete filter.

ALTER TABLE knowledge.documents ADD COLUMN IF NOT EXISTS asset_id      UUID;     -- soft ref → asset.assets(id)
ALTER TABLE knowledge.documents ADD COLUMN IF NOT EXISTS asset_version INTEGER;  -- which version was read

CREATE INDEX IF NOT EXISTS idx_knowledge_documents_asset
    ON knowledge.documents (asset_id, asset_version)
    WHERE asset_id IS NOT NULL;
