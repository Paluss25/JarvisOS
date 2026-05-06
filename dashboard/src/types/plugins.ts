export type PluginSummary = {
  agent_count: number
  worker_count: number
  capability_count: number
  observed_tool_count: number
  tool_event_count: number
  skill_event_count: number
}

export type CapabilityEntry = {
  name: string
  kind: 'capability'
  agents: string[]
  domains: string[]
}

export type WorkerEntry = {
  id: string
  kind: 'worker'
  port: number
  module: string
  description: string
}

export type ObservedTool = {
  name: string
  kind: 'tool' | 'skill'
  agent_id: string | null
  event_type: string
  severity: string
  status: string
  duration_ms: number | null
  payload: Record<string, unknown>
}

export type PluginRegistryData = {
  summary: PluginSummary
  capabilities: CapabilityEntry[]
  workers: WorkerEntry[]
  observed_tools: ObservedTool[]
}
