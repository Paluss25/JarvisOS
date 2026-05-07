import { apiGet } from './client'
import type { ControlSummary } from '../types/control'

export function getControlSummary(): Promise<ControlSummary> {
  return apiGet<ControlSummary>('/control/summary')
}
