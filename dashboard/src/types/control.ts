export type ControlSummary = {
  agents: {
    total: number
    running: number
    not_running: number
  }
  tasks: {
    open: number
    total: number
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
}
