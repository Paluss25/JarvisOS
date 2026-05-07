import PageHeader from '../PageHeader'
import StatusPill from '../StatusPill'
import CockpitPanel from './CockpitPanel'
import type { CockpitConfig } from '../../types/cockpit'

export default function CockpitShell({ config }: { config: CockpitConfig }) {
  return (
    <main className="ops-page">
      <PageHeader
        title={config.title}
        description={config.subtitle}
        actions={<StatusPill label={config.agentId} tone="ai" />}
      />
      <div className="cockpit-sections">
        {config.sections.map((section) => (
          <section key={section.id} className="cockpit-section">
            <h2>{section.label}</h2>
            <div className="cockpit-panel-grid">
              {section.panels.map((panel) => (
                <CockpitPanel key={panel.id} panel={panel} />
              ))}
            </div>
          </section>
        ))}
      </div>
    </main>
  )
}
