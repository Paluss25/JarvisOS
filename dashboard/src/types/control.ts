export type ControlSummary = {
  agents: {
    total: number
    running: number
    not_running: number
  }
  tasks: {
    open: number
    total: number
    running: number
    needs_review: number
    blocked: number
  }
  incidents: {
    critical: number
    active: number
  }
  costs: {
    today_usd: number
    tokens_today: number
  }
  recent_audit: Array<{
    ts: string
    category: string
    agent_id?: string | null
    action: string
    detail: unknown
    source: string
  }>
  work_in_progress: ControlTaskCard[]
  needs_review: ControlTaskCard[]
  incident_feed: ControlIncident[]
  recent_decisions: ControlDecision[]
  slow_traces: ControlTrace[]
  agent_spotlight: ControlAgentSpotlight[]
}

export type ControlTaskCard = {
  id: string
  title: string
  status: string
  priority: string
  agent_id: string | null
  created_at: string | null
  href: string
  agent_href: string | null
}

export type ControlIncident = {
  id: string | null
  ts: string | null
  severity: string
  event_type: string
  agent_id: string | null
  task_id: string | null
  trace_id: string | null
  summary: string
  task_href: string | null
  trace_href: string | null
}

export type ControlDecision = {
  id: string
  ts: string | null
  agent_id: string
  task_id: string | null
  trace_id: string | null
  title: string
  status: string
  detail_href: string | null
  href: string | null
  trace_href: string | null
}

export type ControlTrace = {
  trace_id: string
  task_id: string | null
  agent_id: string | null
  duration_ms: number
  input_tokens: number
  output_tokens: number
  cost_usd: number
  status: string
  href: string
  task_href: string | null
}

export type ControlAgentSpotlight = {
  id: string
  status: string
  href: string
  cockpit_href: string
}
