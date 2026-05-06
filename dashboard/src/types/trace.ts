import type { IncidentContext, LogEvent } from './logs'

export type TraceSummary = {
  trace_id: string
  agent_id: string | null
  task_id: string | null
  session_id: string | null
  status: string
  started_at: string
  ended_at: string | null
  duration_ms: number
  span_count: number
  input_tokens: number
  output_tokens: number
  cost_usd: number
}

export type TraceSpan = {
  trace_id: string
  span_id: string
  parent_span_id: string | null
  ts_start: string
  ts_end: string | null
  operation: string
  agent_id: string | null
  task_id: string | null
  session_id: string | null
  status: string
  duration_ms: number
  input_tokens: number
  output_tokens: number
  cost_usd: number
  model: string | null
  provider: string | null
  payload: Record<string, unknown>
  children: TraceSpan[]
}

export type TraceDetail = {
  summary: TraceSummary
  spans: TraceSpan[]
  flat_spans: TraceSpan[]
  waterfall: Array<{
    span_id: string
    operation: string
    status: string
    offset_ms: number
    duration_ms: number
  }>
  metrics: {
    span_count: number
    error_count: number
    log_count: number
    audit_count: number
    decision_count: number
    token_count: number
    cost_usd: number
  }
  links: {
    agent: string | null
    chat: string | null
    task: string | null
    logs: string
    audit: string
    costs: string
  }
  logs: LogEvent[]
  audit_entries: IncidentContext['audit_entries']
  decisions: IncidentContext['decisions']
}
