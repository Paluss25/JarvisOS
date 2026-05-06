export type LogEvent = {
  id: string
  ts: string
  event_type: string
  severity: string
  agent_id: string | null
  task_id: string | null
  session_id: string | null
  trace_id: string | null
  span_id: string | null
  source: string
  payload: Record<string, unknown>
}

export type IncidentCreate = {
  title: string
  severity: string
  description?: string
  agent_id?: string
  task_id?: string
  trace_id?: string
}

export type IncidentContext = {
  incident: LogEvent
  metrics: {
    log_count: number
    audit_count: number
    decision_count: number
    trace_count: number
  }
  links: {
    agent: string | null
    task: string | null
    trace: string | null
    logs: string
    audit: string
    ciso: string
    cio: string
  }
  related_logs: LogEvent[]
  audit_entries: Array<{
    id: number
    ts: string
    category: string
    agent_id: string | null
    action: string
    source: string
    detail: Record<string, unknown>
    links?: {
      detail: string
    }
  }>
  decisions: Array<{
    id: string
    ts: string
    agent_id: string
    task_id: string | null
    trace_id: string | null
    title: string
    summary: string
    status: string
    links?: {
      detail: string
    }
  }>
  traces: Array<{
    trace_id: string
    task_id: string | null
    agent_id: string | null
    status: string
    duration_ms: number
    span_count: number
    cost_usd: number
  }>
}

export type LogContext = {
  event: LogEvent
  metrics: {
    related_log_count: number
    audit_count: number
    decision_count: number
    trace_count: number
  }
  links: {
    agent: string | null
    chat: string | null
    task: string | null
    trace: string | null
    logs: string
    audit: string
  }
  suggested_actions: Array<{
    kind: 'incident' | 'task'
    label: string
    severity?: string
    priority?: string
  }>
  related_logs: LogEvent[]
  audit_entries: IncidentContext['audit_entries']
  decisions: IncidentContext['decisions']
  traces: IncidentContext['traces']
}
