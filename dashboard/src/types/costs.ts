import type { IncidentContext, LogEvent } from './logs'
import type { CfoDecision } from './cfo'

export type CostGroup = {
  key: string
  cost_usd: number
  tokens: number
  input_tokens: number
  output_tokens: number
  span_count: number
  duration_ms: number
}

export type CostSummary = {
  total_cost_usd: number
  input_tokens: number
  output_tokens: number
  tokens: number
  span_count: number
  p95_latency_ms: number
  by_agent: CostGroup[]
  by_model: CostGroup[]
  by_task: CostGroup[]
  by_session: CostGroup[]
  top_traces: CostGroup[]
}

export type CostSpan = {
  trace_id: string
  span_id: string
  operation: string
  status: string
  agent_id: string | null
  task_id: string | null
  session_id: string | null
  model: string | null
  provider: string | null
  duration_ms: number
  input_tokens: number
  output_tokens: number
  tokens: number
  cost_usd: number
  retry: boolean
}

export type CostTraceContext = {
  summary: {
    trace_id: string
    agent_id: string | null
    task_id: string | null
    session_id: string | null
    status: string
    total_cost_usd: number
    tokens: number
    input_tokens: number
    output_tokens: number
    span_count: number
    duration_ms: number
    p95_latency_ms: number
    retry_cost_usd: number
  }
  metrics: {
    log_count: number
    audit_count: number
    decision_count: number
    model_count: number
  }
  links: {
    trace: string
    agent: string | null
    task: string | null
    logs: string
    audit: string
  }
  anomalies: Array<{
    kind: string
    label: string
    tone: 'neutral' | 'healthy' | 'warning' | 'incident'
  }>
  model_breakdown: CostGroup[]
  spans: CostSpan[]
  related_logs: LogEvent[]
  audit_entries: IncidentContext['audit_entries']
  decisions: CfoDecision[]
}
