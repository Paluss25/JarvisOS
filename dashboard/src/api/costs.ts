import { apiGet } from './client'
import type { CostSummary } from '../types/costs'

export function getCostSummary(filters?: { agent_id?: string; task_id?: string }): Promise<CostSummary> {
  const params = new URLSearchParams()
  if (filters?.agent_id) params.set('agent_id', filters.agent_id)
  if (filters?.task_id) params.set('task_id', filters.task_id)
  const query = params.toString()
  return apiGet<CostSummary>(`/costs/summary${query ? `?${query}` : ''}`)
}
