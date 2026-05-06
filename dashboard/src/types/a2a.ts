import type { IncidentContext, LogEvent } from './logs'

export type A2ASummary = {
  message_count: number
  request_count: number
  response_count: number
  notification_count: number
  async_count: number
  failure_count: number
  loop_warnings: number
  edge_count: number
}

export type A2AMessage = {
  id: string
  ts: string
  event_type: string
  severity: string
  task_id: string | null
  trace_id: string | null
  message_id: string | null
  correlation_id: string | null
  root_correlation_id: string | null
  parent_correlation_id: string | null
  from_agent: string | null
  to_agent: string | null
  message_type: string | null
  mode: string
  hop_count: number
  max_hops: number
  status: string
  payload: Record<string, unknown>
}

export type A2AEdge = {
  from_agent: string
  to_agent: string
  message_count: number
  failure_count: number
  last_seen: string | null
}

export type A2AData = {
  summary: A2ASummary
  messages: A2AMessage[]
  edges: A2AEdge[]
}

export type A2AMessageContext = {
  message: A2AMessage
  metrics: {
    thread_count: number
    failure_count: number
    loop_warnings: number
    log_count: number
    trace_count: number
    audit_count: number
    decision_count: number
  }
  links: {
    from_agent: string | null
    to_agent: string | null
    task: string | null
    trace: string | null
    logs: string
    audit: string
  }
  suggested_actions: Array<{
    kind: 'task' | 'trace'
    label: string
    priority?: string
    trace_id?: string
  }>
  thread: A2AMessage[]
  related_logs: LogEvent[]
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
  decisions: IncidentContext['decisions']
}
