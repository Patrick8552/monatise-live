BEGIN;

-- Durable storage for the native POST /api/tradingview/webhook endpoint.
-- fingerprint is a sha256 of the raw request body: an exact-duplicate
-- delivery (TradingView retry, or a captured-and-replayed request) hits the
-- UNIQUE constraint and is rejected via ON CONFLICT DO NOTHING rather than
-- silently accepted twice. No REVOKE DELETE (unlike monatise_application_streams):
-- these rows are explicitly meant to be pruned on a retention schedule, not
-- kept as an immutable audit trail -- the audit trail for receipt/rejection
-- events lives in monatise_application_streams via the audit log instead.
CREATE TABLE IF NOT EXISTS monatise_tradingview_alerts (
    id BIGSERIAL PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    symbol TEXT NOT NULL,
    payload JSONB NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_monatise_tradingview_alerts_fingerprint
    ON monatise_tradingview_alerts (fingerprint);

-- Supports GET /api/tradingview/signals filtering by symbol, newest first.
CREATE INDEX IF NOT EXISTS idx_monatise_tradingview_alerts_symbol_received
    ON monatise_tradingview_alerts (symbol, received_at DESC);

-- Supports the retention job's `WHERE received_at < NOW() - INTERVAL '...'`.
CREATE INDEX IF NOT EXISTS idx_monatise_tradingview_alerts_received
    ON monatise_tradingview_alerts (received_at);

COMMIT;
