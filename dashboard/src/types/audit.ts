import type { Decision } from './decisions'
import type { IncidentContext, LogEvent } from './logs'

export type AuditEntry = {
  id: number
  ts: string
  category: string
  agent_id: string | null
  user_id: string | null
  action: string
  source: string
  detail: Record<string, unknown>
}

export type AuditResponse = {
  items: AuditEntry[]
  total: number
}

export type AuditContext = {
  entry: AuditEntry
  metrics: {
    detail_key_count: number
    related_log_count: number
    trace_count: number
    decision_count: number
  }
  links: {
    agent: string | null
    chat: string | null
    task: string | null
    trace: string | null
    event: string | null
    decision: string | null
    logs: string
    audit: string
  }
  related_logs: LogEvent[]
  traces: IncidentContext['traces']
  decisions: Decision[]
}
