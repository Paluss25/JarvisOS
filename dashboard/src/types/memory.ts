import type { CfoDecision } from './cfo'

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
}

export type MemoryData = {
  summary: MemorySummary
  events: MemoryEvent[]
  decisions: CfoDecision[]
}
