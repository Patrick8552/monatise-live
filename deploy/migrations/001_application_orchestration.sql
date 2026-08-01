BEGIN;

CREATE TABLE IF NOT EXISTS monatise_application_documents (
    namespace TEXT NOT NULL,
    document_key TEXT NOT NULL,
    value JSONB NOT NULL,
    version BIGINT NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (namespace, document_key)
);

CREATE TABLE IF NOT EXISTS monatise_application_streams (
    sequence BIGSERIAL PRIMARY KEY,
    stream TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_monatise_stream_created
    ON monatise_application_streams (stream, created_at DESC);

REVOKE UPDATE, DELETE ON monatise_application_streams FROM PUBLIC;
COMMIT;
