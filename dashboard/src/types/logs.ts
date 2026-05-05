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
