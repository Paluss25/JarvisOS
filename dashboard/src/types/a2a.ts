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

export type A2AData = {
  summary: A2ASummary
  messages: A2AMessage[]
}
