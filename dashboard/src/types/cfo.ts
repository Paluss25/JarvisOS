import type { LogEvent } from './logs'

export type CfoDecision = {
  id: string
  ts: string
  agent_id: string
  task_id: string | null
  trace_id: string | null
  title: string
  summary: string
  decision_type: string
  confidence: number | null
  status: string
  evidence: Array<Record<string, unknown>>
  payload: Record<string, unknown>
}

export type CfoSummary = {
  decision_count: number
  open_approvals: number
  approved_decisions: number
  rejected_decisions: number
  market_alerts: number
  tax_alerts: number
  critical_alerts: number
}

export type CfoCockpitData = {
  summary: CfoSummary
  decisions: CfoDecision[]
  alerts: LogEvent[]
}
