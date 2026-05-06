import { apiGet } from './client'
import type { PluginRegistryData } from '../types/plugins'

export function getPluginRegistry(): Promise<PluginRegistryData> {
  return apiGet<PluginRegistryData>('/plugins/summary')
}
