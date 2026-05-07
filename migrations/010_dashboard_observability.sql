CREATE TABLE IF NOT EXISTS platform_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    agent_id TEXT,
    task_id UUID,
    session_id TEXT,
    trace_id TEXT,
    span_id TEXT,
    parent_span_id TEXT,
    tool_call_id TEXT,
    a2a_message_id TEXT,
    decision_id UUID,
    source TEXT NOT NULL DEFAULT 'platform',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_platform_events_ts ON platform_events (ts DESC);
CREATE INDEX IF NOT EXISTS idx_platform_events_agent_ts ON platform_events (agent_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_platform_events_task_ts ON platform_events (task_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_platform_events_trace ON platform_events (trace_id);

CREATE TABLE IF NOT EXISTS trace_spans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id TEXT NOT NULL,
    span_id TEXT NOT NULL,
    parent_span_id TEXT,
    ts_start TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ts_end TIMESTAMPTZ,
    operation TEXT NOT NULL,
    agent_id TEXT,
    task_id UUID,
    session_id TEXT,
    status TEXT NOT NULL DEFAULT 'ok',
    duration_ms INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd NUMERIC(12, 6),
    model TEXT,
    provider TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE(trace_id, span_id)
);

CREATE INDEX IF NOT EXISTS idx_trace_spans_trace ON trace_spans (trace_id, ts_start ASC);
CREATE INDEX IF NOT EXISTS idx_trace_spans_agent ON trace_spans (agent_id, ts_start DESC);

CREATE TABLE IF NOT EXISTS decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    agent_id TEXT NOT NULL,
    task_id UUID,
    trace_id TEXT,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    decision_type TEXT NOT NULL DEFAULT 'operational',
    confidence NUMERIC(4, 3),
    status TEXT NOT NULL DEFAULT 'proposed',
    evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_decisions_agent_ts ON decisions (agent_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_decisions_task ON decisions (task_id);
