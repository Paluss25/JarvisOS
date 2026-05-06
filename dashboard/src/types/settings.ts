export type SettingsSummary = {
  agent_count: number
  worker_count: number
  domain_count: number
  user_count: number | null
  approval_class_count: number
  human_approval_actions: number
  two_step_actions: number
  memory_store_count: number
  min_retention_days: number
  max_retention_days: number
  permission_agent_count: number
  denied_action_count: number
  model_rule_count: number
  shared_constraint_count: number
  audit_config_events: number
}

export type ApprovalClass = {
  name: string
  description: string
  action_count: number
  actions: string[]
  risk: 'low' | 'medium' | 'high'
}

export type MemoryStore = {
  name: string
  description: string
  retention_days: number
  access_roles: string[]
  vectorization_allowed: boolean
  redaction_required: boolean
  pii_minimized: boolean
}

export type PermissionAgent = {
  agent_id: string
  description: string
  read_count: number
  write_count: number
  execute_count: number
  denied_count: number
}

export type ModelRouteRule = {
  id: string
  route: string
  conditions: Record<string, unknown>
}

export type ModelRouting = {
  local_first: boolean
  cloud_default_disabled: boolean
  deny_if_route_uncertain: boolean
  rule_count: number
  rules: ModelRouteRule[]
}

export type SettingsGovernanceData = {
  summary: SettingsSummary
  approval_classes: ApprovalClass[]
  memory_stores: MemoryStore[]
  permission_agents: PermissionAgent[]
  model_routing: ModelRouting
  shared_constraints: string[]
  domains: string[]
}
