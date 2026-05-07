import type { CockpitConfig } from '../types/cockpit'

export const cioCockpit: CockpitConfig = {
  agentId: 'cio',
  title: 'CIO Homelab Cockpit',
  subtitle: 'Infrastructure, deployments, runbooks, services, capacity, and incidents.',
  sections: [
    {
      id: 'infrastructure',
      label: 'Infrastructure',
      panels: [
        { id: 'infra-map', title: 'Infrastructure map', kind: 'infra-map' },
        { id: 'capacity', title: 'Capacity', kind: 'metric-grid' },
      ],
    },
    {
      id: 'operations',
      label: 'Operations',
      panels: [
        { id: 'incidents', title: 'Incidents', kind: 'timeline' },
        { id: 'runbooks', title: 'Runbooks', kind: 'action-list' },
      ],
    },
  ],
}
