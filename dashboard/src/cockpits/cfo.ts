import type { CockpitConfig } from '../types/cockpit'

export const cfoCockpit: CockpitConfig = {
  agentId: 'cfo',
  title: 'CFO Cockpit',
  subtitle: 'Financial research, decisions, markets, crypto, and Italian tax evidence.',
  sections: [
    {
      id: 'overview',
      label: 'Overview',
      panels: [
        { id: 'liquidity', title: 'Liquidity', kind: 'metric-grid' },
        { id: 'open-approvals', title: 'Open approvals', kind: 'task-list' },
      ],
    },
    {
      id: 'markets',
      label: 'Markets',
      panels: [
        { id: 'market-watch', title: 'Market watch', kind: 'market-watch' },
      ],
    },
    {
      id: 'decisions',
      label: 'Decisions',
      panels: [
        { id: 'decision-ledger', title: 'Decision ledger', kind: 'decision-ledger' },
      ],
    },
  ],
}
