import { useEffect, useState } from 'react'
import { getControlSummary } from '../api/control'
import MetricCard from '../components/MetricCard'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'
import type { ControlSummary } from '../types/control'

export default function ControlCenterPage() {
  const [summary, setSummary] = useState<ControlSummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getControlSummary()
      .then(setSummary)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [])

  return (
    <main className="ops-page">
      <PageHeader
        title="Control Center"
        description="Global JarvisOS operations, agent health, active work, incidents, and costs."
        actions={<StatusPill label={error ? 'API degraded' : 'Live'} tone={error ? 'warning' : 'healthy'} />}
      />

      {error ? <div className="panel-warning">{error}</div> : null}

      <section className="metric-grid">
        <MetricCard label="Agents running" value={summary ? `${summary.agents.running}/${summary.agents.total}` : '...'} />
        <MetricCard label="Open tasks" value={summary?.tasks.open ?? '...'} />
        <MetricCard
          label="Active incidents"
          value={summary?.incidents.active ?? '...'}
          tone={summary?.incidents.critical ? 'incident' : 'neutral'}
        />
        <MetricCard label="Cost today" value={summary ? `$${summary.costs.today_usd.toFixed(2)}` : '...'} />
      </section>

      <section className="ops-panel">
        <h2>Recent audit</h2>
        <div className="ops-list">
          {(summary?.recent_audit ?? []).map((row, index) => (
            <div className="ops-row" key={`${row.ts}-${index}`}>
              <span>{new Date(row.ts).toLocaleString()}</span>
              <strong>{row.action}</strong>
              <span>{row.agent_id ?? row.category}</span>
            </div>
          ))}
          {summary && summary.recent_audit.length === 0 ? (
            <div className="empty-state">No recent audit entries.</div>
          ) : null}
        </div>
      </section>
    </main>
  )
}
