import { apiGet } from './client'
import type { PluginRegistryData, ToolContext } from '../types/plugins'

export function getPluginRegistry(): Promise<PluginRegistryData> {
  return apiGet<PluginRegistryData>('/plugins/summary')
}

export function getToolContext(name: string, kind: 'tool' | 'skill'): Promise<ToolContext> {
  return apiGet<ToolContext>(`/plugins/tools/${encodeURIComponent(name)}?kind=${encodeURIComponent(kind)}`)
}
