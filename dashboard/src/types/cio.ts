import type { LogEvent } from './logs'

export type CioSummary = {
  event_count: number
  tool_events: number
  skill_events: number
  deploy_events: number
  backup_events: number
  health_events: number
  incident_events: number
  failed_events: number
}

export type CioCockpitData = {
  summary: CioSummary
  events: LogEvent[]
  incidents: LogEvent[]
  tool_events: LogEvent[]
}
