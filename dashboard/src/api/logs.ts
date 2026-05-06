import { apiGet, apiPost } from './client'
import type { IncidentContext, IncidentCreate, LogEvent } from '../types/logs'

export function listLogs(filters?: {
  agent_id?: string
  task_id?: string
  trace_id?: string
  severity?: string
  event_type?: string
}): Promise<LogEvent[]> {
  const params = new URLSearchParams()
  if (filters?.agent_id) params.set('agent_id', filters.agent_id)
  if (filters?.task_id) params.set('task_id', filters.task_id)
  if (filters?.trace_id) params.set('trace_id', filters.trace_id)
  if (filters?.severity) params.set('severity', filters.severity)
  if (filters?.event_type) params.set('event_type', filters.event_type)
  const suffix = params.toString() ? `?${params.toString()}` : ''
  return apiGet<LogEvent[]>(`/logs${suffix}`)
}

export function listIncidents(status?: string): Promise<LogEvent[]> {
  const suffix = status ? `?status=${encodeURIComponent(status)}` : ''
  return apiGet<LogEvent[]>(`/incidents${suffix}`)
}

export function createIncident(body: IncidentCreate): Promise<LogEvent> {
  return apiPost<LogEvent>('/incidents', body)
}

export function getIncidentContext(id: string): Promise<IncidentContext> {
  return apiGet<IncidentContext>(`/incidents/${id}`)
}
