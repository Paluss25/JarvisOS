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
}
