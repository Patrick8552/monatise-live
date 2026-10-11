-- RESEARCH ONLY. Explicit application to an isolated research DB is required.
-- Reuses PostgresDocumentStore's document contract, with database append guards.
BEGIN;
CREATE TABLE IF NOT EXISTS monatise_research_broker_documents (
    namespace TEXT NOT NULL,
    document_key TEXT NOT NULL,
    value JSONB NOT NULL,
    version BIGINT NOT NULL DEFAULT 1 CHECK (version = 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (namespace, document_key)
);
CREATE OR REPLACE FUNCTION monatise_research_broker_append_guard()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'broker research archive is append-only';
END;
$$;
DROP TRIGGER IF EXISTS broker_archive_rows ON monatise_research_broker_documents;
CREATE TRIGGER broker_archive_rows BEFORE UPDATE OR DELETE
ON monatise_research_broker_documents FOR EACH ROW
EXECUTE FUNCTION monatise_research_broker_append_guard();
DROP TRIGGER IF EXISTS broker_archive_truncate ON monatise_research_broker_documents;
CREATE TRIGGER broker_archive_truncate BEFORE TRUNCATE
ON monatise_research_broker_documents FOR EACH STATEMENT
EXECUTE FUNCTION monatise_research_broker_append_guard();
REVOKE UPDATE, DELETE, TRUNCATE ON monatise_research_broker_documents FROM PUBLIC;
COMMIT;
