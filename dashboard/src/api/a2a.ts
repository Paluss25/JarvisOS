import { apiGet } from './client'
import type { A2AData } from '../types/a2a'

export function getA2ASummary(): Promise<A2AData> {
  return apiGet<A2AData>('/a2a/summary')
}
