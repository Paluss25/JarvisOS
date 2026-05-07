import { apiGet } from './client'
import type { MemoryData, MemoryEventContext } from '../types/memory'

export function getMemorySummary(filters?: { agent_id?: string }): Promise<MemoryData> {
  const params = new URLSearchParams()
  if (filters?.agent_id) params.set('agent_id', filters.agent_id)
  const query = params.toString()
  return apiGet<MemoryData>(`/memory/summary${query ? `?${query}` : ''}`)
}

export function getMemoryEventContext(eventId: string): Promise<MemoryEventContext> {
  return apiGet<MemoryEventContext>(`/memory/events/${encodeURIComponent(eventId)}`)
}
