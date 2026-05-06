import { apiGet } from './client'
import type { SettingsGovernanceData } from '../types/settings'

export function getSettingsGovernance(): Promise<SettingsGovernanceData> {
  return apiGet<SettingsGovernanceData>('/settings/summary')
}
