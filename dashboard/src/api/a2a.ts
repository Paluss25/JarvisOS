import { apiGet } from './client'
import type { A2AData, A2AMessageContext } from '../types/a2a'

export function getA2ASummary(): Promise<A2AData> {
  return apiGet<A2AData>('/a2a/summary')
}

export function getA2AMessages(filters?: { agent_id?: string; limit?: number }): Promise<A2AData> {
  const params = new URLSearchParams()
  if (filters?.agent_id) params.set('agent_id', filters.agent_id)
  if (filters?.limit) params.set('limit', String(filters.limit))
  const suffix = params.toString() ? `?${params.toString()}` : ''
  return apiGet<A2AData>(`/a2a/messages${suffix}`)
}

export function getA2AMessageContext(eventId: string): Promise<A2AMessageContext> {
  return apiGet<A2AMessageContext>(`/a2a/messages/${encodeURIComponent(eventId)}`)
}
