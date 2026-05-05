import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { getCisoCockpit } from '../api/cockpits'
import MetricCard from '../components/MetricCard'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'
import type { CisoCockpitData } from '../types/ciso'
import type { LogEvent } from '../types/logs'

function severityTone(severity: string): 'neutral' | 'healthy' | 'warning' | 'incident' {
  if (severity === 'critical' || severity === 'error') return 'incident'
  if (severity === 'warning') return 'warning'
  return 'neutral'
}

function eventTitle(event: LogEvent): string {
  const payload = event.payload
  const label = payload.title ?? payload.finding ?? payload.service ?? payload.principal ?? payload.tool
  return typeof label === 'string' ? label : event.event_type
}

function eventDetail(event: LogEvent): string {
  const payload = event.payload
  const detail = payload.message ?? payload.summary ?? payload.status ?? payload.category
  return typeof detail === 'string' ? detail : event.source
}

function SecurityList({ events, empty }: { events: LogEvent[]; empty: string }) {
  return (
    <div className="ciso-event-list">
      {events.map((event) => (
        <div className="ciso-event-row" key={event.id}>
          <div>
            <StatusPill label={event.severity} tone={severityTone(event.severity)} />
            <strong>{eventTitle(event)}</strong>
            <p>{event.event_type} · {eventDetail(event)}</p>
          </div>
          <div className="ciso-event-meta">
            <span>{new Date(event.ts).toLocaleString()}</span>
            {event.trace_id ? <Link to={`/traces/${encodeURIComponent(event.trace_id)}`}>{event.trace_id}</Link> : null}
          </div>
        </div>
      ))}
      {events.length === 0 ? <div className="empty-state">{empty}</div> : null}
    </div>
  )
}

export default function CisoCockpitPage() {
  const [data, setData] = useState<CisoCockpitData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getCisoCockpit()
      .then((result) => {
        setData(result)
        setError(null)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [])

  const summary = data?.summary
  const socTone = useMemo(() => {
    if (!summary) return 'neutral'
    if (summary.critical_events > 0 || summary.incident_events > 0) return 'incident'
    if (summary.open_findings > 0 || summary.alert_events > 0) return 'warning'
    return 'healthy'
  }, [summary])

  return (
    <main className="ops-page">
      <PageHeader
        title="CISO Cockpit"
        description="Security operations room for alerts, threats, vulnerabilities, identity events, policy drift, and scans."
        actions={<StatusPill label={error ? 'API degraded' : 'ciso'} tone={error ? 'warning' : socTone} />}
      />

      {error ? <div className="panel-warning">{error}</div> : null}

      <section className="metric-grid">
        <MetricCard label="Security events" value={summary?.event_count ?? '-'} detail="Latest CISO events" />
        <MetricCard label="Alerts" value={summary?.alert_events ?? '-'} detail="Security and threat alerts" tone={summary?.alert_events ? 'warning' : 'neutral'} />
        <MetricCard label="Open findings" value={summary?.open_findings ?? '-'} detail="Unresolved evidence" tone={summary?.open_findings ? 'warning' : 'neutral'} />
        <MetricCard label="Vulnerabilities" value={summary?.vulnerability_events ?? '-'} detail="Vulnerability findings" tone={summary?.vulnerability_events ? 'incident' : 'neutral'} />
        <MetricCard label="Auth events" value={summary?.auth_events ?? '-'} detail="Identity and access signals" tone={summary?.auth_events ? 'warning' : 'neutral'} />
        <MetricCard label="Critical" value={summary?.critical_events ?? '-'} detail="Immediate triage" tone={summary?.critical_events ? 'incident' : 'neutral'} />
      </section>

      <section className="ciso-layout">
        <section className="ops-panel">
          <h2>Security Stream</h2>
          <SecurityList events={data?.events ?? []} empty="No CISO security events recorded." />
        </section>

        <div className="ciso-side">
          <section className="ops-panel">
            <h2>Priority Alerts</h2>
            <SecurityList events={data?.alerts ?? []} empty="No CISO priority alerts recorded." />
          </section>

          <section className="ops-panel">
            <h2>Open Findings</h2>
            <SecurityList events={data?.findings ?? []} empty="No CISO open findings recorded." />
          </section>
        </div>
      </section>
    </main>
  )
}
