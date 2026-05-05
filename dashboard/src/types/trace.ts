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
}
