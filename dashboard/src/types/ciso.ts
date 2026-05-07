import type { LogEvent } from './logs'

export type CisoSummary = {
  event_count: number
  alert_events: number
  incident_events: number
  vulnerability_events: number
  auth_events: number
  policy_events: number
  scan_events: number
  critical_events: number
  open_findings: number
}

export type CisoCockpitData = {
  summary: CisoSummary
  events: LogEvent[]
  alerts: LogEvent[]
  findings: LogEvent[]
}
