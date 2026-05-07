export type ActivityItem = {
  id: string
  ts: string
  kind: 'platform_event' | 'audit'
  label: string
  severity: string
  agent_id: string | null
  task_id: string | null
  trace_id: string | null
  span_id: string | null
  source: string
  preview: string
  payload: Record<string, unknown>
  links: {
    detail: string | null
    agent: string | null
    chat: string | null
    task: string | null
    trace: string | null
    audit: string | null
  }
}

export type ActivitySummary = {
  metrics: {
    total_count: number
    platform_event_count: number
    audit_count: number
    critical_count: number
    error_count: number
    warning_count: number
    agent_count: number
  }
  items: ActivityItem[]
}
