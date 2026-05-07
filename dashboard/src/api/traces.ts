import { apiGet } from './client'
import type { TraceDetail, TraceSummary } from '../types/trace'

export function listTraces(filters?: { agent_id?: string; task_id?: string }): Promise<TraceSummary[]> {
  const params = new URLSearchParams()
  if (filters?.agent_id) params.set('agent_id', filters.agent_id)
  if (filters?.task_id) params.set('task_id', filters.task_id)
  const suffix = params.toString() ? `?${params.toString()}` : ''
  return apiGet<TraceSummary[]>(`/traces${suffix}`)
}

export function getTrace(traceId: string): Promise<TraceDetail> {
  return apiGet<TraceDetail>(`/traces/${encodeURIComponent(traceId)}`)
}
