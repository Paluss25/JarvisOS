import { apiGet } from './client'
import type { MemoryData } from '../types/memory'

export function getMemorySummary(filters?: { agent_id?: string }): Promise<MemoryData> {
  const params = new URLSearchParams()
  if (filters?.agent_id) params.set('agent_id', filters.agent_id)
  const query = params.toString()
  return apiGet<MemoryData>(`/memory/summary${query ? `?${query}` : ''}`)
}
