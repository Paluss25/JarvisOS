import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getAuditContext } from '../api/audit'
import MetricCard from '../components/MetricCard'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'
import type { AuditContext } from '../types/audit'

function categoryTone(category: string): 'neutral' | 'healthy' | 'warning' | 'incident' | 'trace' | 'ai' | 'network' {
  if (category === 'security') return 'incident'
  if (category === 'task') return 'warning'
  if (category === 'memory') return 'ai'
  if (category === 'agent') return 'trace'
  if (category === 'platform') return 'network'
  return 'neutral'
}

function severityTone(severity: string): 'neutral' | 'healthy' | 'warning' | 'incident' {
  if (severity === 'critical' || severity === 'error') return 'incident'
  if (severity === 'warning') return 'warning'
  return 'neutral'
}

function timeLabel(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString() : '-'
}

function WorkspaceLink({ to, label }: { to: string | null; label: string }) {
  return to ? <Link className="audit-workspace-link" to={to}>{label}</Link> : <span className="audit-workspace-link disabled">{label}</span>
}

export default function AuditDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [context, setContext] = useState<AuditContext | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    getAuditContext(id)
      .then((result) => {
        setContext(result)
        setError(null)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [id])

  if (!context) return <main className="ops-page empty-state">{error ?? 'Loading audit entry.'}</main>

  const entry = context.entry

  return (
    <main className="ops-page">
      <PageHeader
        title={entry.action}
        description={`${entry.category} · ${entry.source} · ${timeLabel(entry.ts)}`}
        actions={<StatusPill label={entry.category} tone={categoryTone(entry.category)} />}
      />

      {error ? <div className="panel-warning">{error}</div> : null}

      <section className="metric-grid">
        <MetricCard label="Detail keys" value={context.metrics.detail_key_count} />
        <MetricCard label="Logs" value={context.metrics.related_log_count} detail="Correlated events" />
        <MetricCard label="Traces" value={context.metrics.trace_count} detail="Execution traces" />
        <MetricCard label="Decisions" value={context.metrics.decision_count} detail="Linked decisions" />
        <MetricCard label="Agent" value={entry.agent_id ?? '-'} />
        <MetricCard label="User" value={entry.user_id ?? '-'} />
      </section>

      <section className="audit-detail-layout">
        <section className="ops-panel">
          <h2>Workspace Links</h2>
          <div className="audit-link-grid">
            <WorkspaceLink to="/audit" label="Audit" />
            <WorkspaceLink to={context.links.agent} label="Agent" />
            <WorkspaceLink to={context.links.chat} label="Chat" />
            <WorkspaceLink to={context.links.task} label="Task" />
            <WorkspaceLink to={context.links.trace} label="Trace" />
            <WorkspaceLink to={context.links.event} label="Event" />
            <WorkspaceLink to={context.links.decision} label="Decision" />
            <WorkspaceLink to={context.links.logs} label="Logs" />
          </div>
        </section>

        <section className="ops-panel">
          <h2>Identity</h2>
          <div className="audit-identity-grid">
            <span>Entry</span><strong>{entry.id}</strong>
            <span>Category</span><strong>{entry.category}</strong>
            <span>Source</span><strong>{entry.source}</strong>
            <span>Agent</span><strong>{entry.agent_id ?? '-'}</strong>
            <span>User</span><strong>{entry.user_id ?? '-'}</strong>
          </div>
        </section>
      </section>

      <section className="ops-panel">
        <h2>Detail Payload</h2>
        <pre className="audit-detail-payload">{JSON.stringify(entry.detail, null, 2)}</pre>
      </section>

      <section className="audit-detail-layout">
        <section className="ops-panel">
          <h2>Related Logs</h2>
          <div className="audit-related-list">
            {context.related_logs.slice(0, 12).map((event) => (
              <article className="audit-related-row" key={event.id}>
                <StatusPill label={event.severity} tone={severityTone(event.severity)} />
                <Link to={`/logs/${encodeURIComponent(event.id)}`}>{event.event_type}</Link>
                <span>{timeLabel(event.ts)} · {event.agent_id ?? event.source}</span>
              </article>
            ))}
            {context.related_logs.length === 0 ? <div className="empty-state">No related logs found.</div> : null}
          </div>
        </section>

        <section className="ops-panel">
          <h2>Traces & Decisions</h2>
          <div className="audit-related-list">
            {context.traces.map((trace) => (
              <article className="audit-related-row" key={trace.trace_id}>
                <StatusPill label={trace.status} tone={trace.status === 'ok' ? 'healthy' : 'incident'} />
                <Link to={`/traces/${encodeURIComponent(trace.trace_id)}`}>{trace.trace_id}</Link>
                <span>{trace.duration_ms}ms · {trace.span_count} spans · ${trace.cost_usd.toFixed(4)}</span>
              </article>
            ))}
            {context.decisions.map((decision) => (
              <article className="audit-related-row" key={decision.id}>
                <StatusPill label={decision.status} tone={decision.status === 'approved' ? 'healthy' : 'warning'} />
                <Link to={`/decisions/${encodeURIComponent(decision.id)}`}>{decision.title}</Link>
                <span>{decision.summary}</span>
              </article>
            ))}
            {context.traces.length === 0 && context.decisions.length === 0 ? <div className="empty-state">No trace or decision records found.</div> : null}
          </div>
        </section>
      </section>
    </main>
  )
}
