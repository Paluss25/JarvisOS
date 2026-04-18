-- Migration 003: audit_log table with monthly range partitioning
-- Apply: psql $JARVIOS_POSTGRES_URL -f migrations/003_audit_log.sql

CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    category    TEXT NOT NULL,
    agent_id    TEXT,
    user_id     TEXT,
    action      TEXT NOT NULL,
    detail      JSONB,
    source      TEXT NOT NULL,
    PRIMARY KEY (id, ts)
) PARTITION BY RANGE (ts);

-- Initial partitions — add new ones monthly
CREATE TABLE IF NOT EXISTS audit_log_2026_04 PARTITION OF audit_log
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');

CREATE TABLE IF NOT EXISTS audit_log_2026_05 PARTITION OF audit_log
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');

CREATE TABLE IF NOT EXISTS audit_log_2026_06 PARTITION OF audit_log
    FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');

CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log (ts DESC);
CREATE INDEX IF NOT EXISTS idx_audit_agent ON audit_log (agent_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_audit_category ON audit_log (category, ts DESC);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log (user_id, ts DESC);
