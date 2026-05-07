import type { CfoDecision } from './cfo'
import type { IncidentContext, LogEvent } from './logs'

export type Decision = CfoDecision

export type DecisionContext = {
  decision: Decision
  metrics: {
    evidence_count: number
    payload_key_count: number
    related_log_count: number
    trace_count: number
    audit_count: number
  }
  links: {
    agent: string | null
    chat: string | null
    cockpit: string | null
    task: string | null
    trace: string | null
    logs: string
    audit: string
  }
  evidence: Array<Record<string, unknown>>
  related_logs: LogEvent[]
  traces: IncidentContext['traces']
  audit_entries: IncidentContext['audit_entries']
}
