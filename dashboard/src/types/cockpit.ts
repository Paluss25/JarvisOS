export type CockpitPanelKind =
  | 'metric-grid'
  | 'timeline'
  | 'decision-ledger'
  | 'task-list'
  | 'market-watch'
  | 'infra-map'
  | 'security-queue'
  | 'action-list'

export type CockpitPanelConfig = {
  id: string
  title: string
  kind: CockpitPanelKind
  description?: string
}

export type CockpitConfig = {
  agentId: string
  title: string
  subtitle: string
  sections: Array<{
    id: string
    label: string
    panels: CockpitPanelConfig[]
  }>
}
