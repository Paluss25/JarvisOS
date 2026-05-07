import type { CockpitPanelConfig } from '../../types/cockpit'

export default function CockpitPanel({ panel }: { panel: CockpitPanelConfig }) {
  return (
    <section className="cockpit-panel">
      <header>
        <h3>{panel.title}</h3>
        {panel.description ? <p>{panel.description}</p> : null}
      </header>
      <div className="empty-state">Panel data source: {panel.kind}</div>
    </section>
  )
}
