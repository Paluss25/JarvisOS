import type { CfoDecision } from './cfo'
import type { IncidentContext } from './logs'

export type MemorySummary = {
  event_count: number
  query_count: number
  write_count: number
  daily_log_count: number
  conflict_count: number
  decision_promotions: number
  agent_count: number
  domain_count: number
}

export type MemoryEvent = {
  id: string
  ts: string
  event_type: string
  severity: string
  agent_id: string | null
  task_id: string | null
  trace_id: string | null
  source: string
  kind: string
  domain: string | null
  key: string | null
  scope: string | null
  payload: Record<string, unknown>
  links: {
    detail: string
  }
}

export type MemoryData = {
  summary: MemorySummary
  events: MemoryEvent[]
  decisions: CfoDecision[]
}

export type MemoryEventContext = {
  event: MemoryEvent
  metrics: {
    related_event_count: number
    trace_count: number
    audit_count: number
    decision_count: number
    promotion_count: number
  }
  links: {
    agent: string | null
    chat: string | null
    task: string | null
    trace: string | null
    logs: string
    audit: string
  }
  diagnostics: Array<{
    kind: string
    label: string
    tone: 'neutral' | 'healthy' | 'warning' | 'incident'
  }>
  related_events: MemoryEvent[]
  traces: Array<{
    trace_id: string
    task_id: string | null
    agent_id: string | null
    status: string
    duration_ms: number
    span_count: number
    cost_usd: number
  }>
  audit_entries: IncidentContext['audit_entries']
  decisions: CfoDecision[]
}
