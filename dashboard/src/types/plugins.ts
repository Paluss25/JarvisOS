import type { IncidentContext } from './logs'

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
  id: string | null
  ts: string | null
  name: string
  kind: 'tool' | 'skill'
  agent_id: string | null
  task_id: string | null
  trace_id: string | null
  event_type: string
  severity: string
  source: string
  status: string
  duration_ms: number | null
  payload: Record<string, unknown>
  links: {
    detail: string
  }
}

export type PluginRegistryData = {
  summary: PluginSummary
  capabilities: CapabilityEntry[]
  workers: WorkerEntry[]
  observed_tools: ObservedTool[]
}

export type ToolContext = {
  tool: {
    name: string
    kind: 'tool' | 'skill'
    read_only: boolean
  }
  metrics: {
    agent_count: number
    event_count: number
    failure_count: number
    trace_count: number
    audit_count: number
    decision_count: number
    avg_duration_ms: number | null
  }
  links: {
    logs: string
    audit: string
    first_trace: string | null
    first_task: string | null
  }
  agents: Array<{
    id: string
    domains: string[]
    capabilities: string[]
  }>
  diagnostics: Array<{
    kind: string
    label: string
    count: number
    tone: 'neutral' | 'healthy' | 'warning' | 'incident'
  }>
  events: ObservedTool[]
  traces: Array<{
    trace_id: string
    task_id: string | null
    agent_id: string | null
    status: string
    duration_ms: number
    span_count: number
    cost_usd: number
  }>
  audit_entries: IncidentContext['audit_entries']
  decisions: IncidentContext['decisions']
}
