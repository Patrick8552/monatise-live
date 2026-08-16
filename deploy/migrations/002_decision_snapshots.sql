BEGIN;

-- Deliberately a dedicated table, not a reuse of monatise_application_streams:
-- that table is REVOKE UPDATE, DELETE FROM PUBLIC by design, to keep the audit
-- trail immutable. Decision snapshots are the opposite -- high-volume,
-- large-payload, and explicitly meant to be pruned on a retention schedule --
-- so they get their own table instead of weakening the audit table's
-- immutability guarantee or competing with it for write throughput.
CREATE TABLE IF NOT EXISTS monatise_decision_snapshots (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    classification TEXT,
    schema_version INT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_monatise_decision_snapshots_symbol_interval_created
    ON monatise_decision_snapshots (symbol, interval, created_at DESC);

-- Supports the retention job's `WHERE created_at < NOW() - INTERVAL '...'`.
CREATE INDEX IF NOT EXISTS idx_monatise_decision_snapshots_created
    ON monatise_decision_snapshots (created_at);

COMMIT;
