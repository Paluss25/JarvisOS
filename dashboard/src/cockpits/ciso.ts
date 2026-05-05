import type { CockpitConfig } from '../types/cockpit'

export const cisoCockpit: CockpitConfig = {
  agentId: 'ciso',
  title: 'CISO Security Cockpit',
  subtitle: 'Security posture, SOC queue, vulnerabilities, identity, compliance, and response.',
  sections: [
    {
      id: 'posture',
      label: 'Posture',
      panels: [
        { id: 'risk-score', title: 'Risk score', kind: 'metric-grid' },
        { id: 'soc-queue', title: 'SOC queue', kind: 'security-queue' },
      ],
    },
    {
      id: 'response',
      label: 'Response',
      panels: [
        { id: 'incidents', title: 'Incident response', kind: 'timeline' },
        { id: 'security-actions', title: 'Security automations', kind: 'action-list' },
      ],
    },
  ],
}
