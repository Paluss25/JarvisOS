import { apiGet } from './client'
import type { ActivitySummary } from '../types/activity'

export function getActivitySummary(filters?: {
  agent_id?: string
  severity?: string
  event_type?: string
  limit?: number
}): Promise<ActivitySummary> {
  const params = new URLSearchParams()
  if (filters?.agent_id) params.set('agent_id', filters.agent_id)
  if (filters?.severity) params.set('severity', filters.severity)
  if (filters?.event_type) params.set('event_type', filters.event_type)
  if (filters?.limit) params.set('limit', String(filters.limit))
  return apiGet<ActivitySummary>(`/activity/summary?${params}`)
}
