-- migrations/001_tasks.sql
CREATE TABLE IF NOT EXISTS tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_id       UUID REFERENCES tasks(id),
    title           TEXT NOT NULL,
    description     TEXT,
    created_by      TEXT NOT NULL,
    assigned_to     TEXT,
    assignment_mode TEXT NOT NULL DEFAULT 'pending',
    status          TEXT NOT NULL DEFAULT 'pending',
    priority        TEXT NOT NULL DEFAULT 'normal',
    depends_on      UUID[],
    retry_count     INT NOT NULL DEFAULT 0,
    max_retries     INT NOT NULL DEFAULT 3,
    summary         TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    assigned_at     TIMESTAMPTZ,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    duration_ms     BIGINT
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_agent ON tasks (assigned_to, status);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks (parent_id);
