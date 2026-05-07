import { apiGet } from './client'
import type { Decision, DecisionContext } from '../types/decisions'

export function listDecisions(filters?: {
  agent_id?: string
  task_id?: string
  trace_id?: string
  status?: string
  limit?: number
}): Promise<Decision[]> {
  const params = new URLSearchParams()
  if (filters?.agent_id) params.set('agent_id', filters.agent_id)
  if (filters?.task_id) params.set('task_id', filters.task_id)
  if (filters?.trace_id) params.set('trace_id', filters.trace_id)
  if (filters?.status) params.set('status', filters.status)
  if (filters?.limit) params.set('limit', String(filters.limit))
  return apiGet<Decision[]>(`/decisions?${params}`)
}

export function getDecisionContext(id: string): Promise<DecisionContext> {
  return apiGet<DecisionContext>(`/decisions/${id}`)
}
