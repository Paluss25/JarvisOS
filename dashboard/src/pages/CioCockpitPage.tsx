import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { getCioCockpit } from '../api/cockpits'
import MetricCard from '../components/MetricCard'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'
import type { CioCockpitData } from '../types/cio'
import type { LogEvent } from '../types/logs'

function eventTitle(event: LogEvent): string {
  const label = event.payload.service ?? event.payload.tool ?? event.payload.skill ?? event.payload.name
  return typeof label === 'string' ? label : event.event_type
}

function eventDetail(event: LogEvent): string {
  const message = event.payload.message ?? event.payload.summary ?? event.payload.status
  return typeof message === 'string' ? message : event.source
}

function severityTone(severity: string): 'neutral' | 'healthy' | 'warning' | 'incident' {
  if (severity === 'critical' || severity === 'error') return 'incident'
  if (severity === 'warning') return 'warning'
  return 'neutral'
}

function EventList({ events, empty }: { events: LogEvent[]; empty: string }) {
  return (
    <div className="cio-event-list">
      {events.map((event) => (
        <div className="cio-event-row" key={event.id}>
          <div>
            <StatusPill label={event.severity} tone={severityTone(event.severity)} />
            <strong>{eventTitle(event)}</strong>
            <p>{event.event_type} · {eventDetail(event)}</p>
          </div>
          <div className="cio-event-meta">
            <span>{new Date(event.ts).toLocaleString()}</span>
            {event.trace_id ? <Link to={`/traces/${encodeURIComponent(event.trace_id)}`}>{event.trace_id}</Link> : null}
          </div>
        </div>
      ))}
      {events.length === 0 ? <div className="empty-state">{empty}</div> : null}
    </div>
  )
}

export default function CioCockpitPage() {
  const [data, setData] = useState<CioCockpitData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getCioCockpit()
      .then((result) => {
        setData(result)
        setError(null)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [])

  const summary = data?.summary
  const operationalTone = useMemo(() => {
    if (!summary) return 'neutral'
    if (summary.failed_events > 0 || summary.incident_events > 0) return 'incident'
    if (summary.backup_events > 0 || summary.deploy_events > 0) return 'warning'
    return 'healthy'
  }, [summary])

  return (
    <main className="ops-page">
      <PageHeader
        title="CIO Cockpit"
        description="Homelab operations, tools, skills, deploys, backups, health checks, and incidents."
        actions={<StatusPill label={error ? 'API degraded' : 'cio'} tone={error ? 'warning' : operationalTone} />}
      />

      {error ? <div className="panel-warning">{error}</div> : null}

      <section className="metric-grid">
        <MetricCard label="Ops events" value={summary?.event_count ?? '-'} detail="Latest CIO operational events" />
        <MetricCard label="Tools" value={summary?.tool_events ?? '-'} detail="Tool executions" tone={summary?.tool_events ? 'healthy' : 'neutral'} />
        <MetricCard label="Skills" value={summary?.skill_events ?? '-'} detail="Agent skills used" tone={summary?.skill_events ? 'healthy' : 'neutral'} />
        <MetricCard label="Deploys" value={summary?.deploy_events ?? '-'} detail="Deploy and release events" tone={summary?.deploy_events ? 'warning' : 'neutral'} />
        <MetricCard label="Backups" value={summary?.backup_events ?? '-'} detail="Backup operations" tone={summary?.backup_events ? 'warning' : 'neutral'} />
        <MetricCard label="Failures" value={summary?.failed_events ?? '-'} detail="Error or critical events" tone={summary?.failed_events ? 'incident' : 'neutral'} />
      </section>

      <section className="cio-layout">
        <section className="ops-panel">
          <h2>Operations Stream</h2>
          <EventList events={data?.events ?? []} empty="No CIO operational events recorded." />
        </section>

        <div className="cio-side">
          <section className="ops-panel">
            <h2>Tools & Skills</h2>
            <EventList events={data?.tool_events ?? []} empty="No CIO tool or skill events recorded." />
          </section>

          <section className="ops-panel">
            <h2>Incidents</h2>
            <EventList events={data?.incidents ?? []} empty="No CIO failed events recorded." />
          </section>
        </div>
      </section>
    </main>
  )
}
