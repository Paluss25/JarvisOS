import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getDecisionContext } from '../api/decisions'
import MetricCard from '../components/MetricCard'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'
import type { DecisionContext } from '../types/decisions'

function statusTone(status: string): 'neutral' | 'healthy' | 'warning' | 'incident' {
  if (status === 'approved') return 'healthy'
  if (status === 'rejected') return 'incident'
  if (status === 'proposed') return 'warning'
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
  return to ? <Link className="decision-workspace-link" to={to}>{label}</Link> : <span className="decision-workspace-link disabled">{label}</span>
}

export default function DecisionDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [context, setContext] = useState<DecisionContext | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    getDecisionContext(id)
      .then((result) => {
        setContext(result)
        setError(null)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [id])

  if (!context) return <main className="ops-page empty-state">{error ?? 'Loading decision.'}</main>

  const decision = context.decision

  return (
    <main className="ops-page">
      <PageHeader
        title={decision.title}
        description={`${decision.decision_type} · ${decision.agent_id} · ${timeLabel(decision.ts)}`}
        actions={<StatusPill label={decision.status} tone={statusTone(decision.status)} />}
      />

      {error ? <div className="panel-warning">{error}</div> : null}

      <section className="metric-grid">
        <MetricCard label="Evidence" value={context.metrics.evidence_count} detail="Attached items" />
        <MetricCard label="Payload keys" value={context.metrics.payload_key_count} detail="Structured fields" />
        <MetricCard label="Logs" value={context.metrics.related_log_count} detail="Correlated events" />
        <MetricCard label="Traces" value={context.metrics.trace_count} detail="Execution traces" />
        <MetricCard label="Audit" value={context.metrics.audit_count} detail="Governance records" />
        <MetricCard label="Confidence" value={decision.confidence == null ? '-' : `${Math.round(decision.confidence * 100)}%`} />
      </section>

      <section className="decision-detail-layout">
        <section className="ops-panel">
          <h2>Workspace Links</h2>
          <div className="decision-link-grid">
            <WorkspaceLink to="/decisions" label="Ledger" />
            <WorkspaceLink to={context.links.agent} label="Agent" />
            <WorkspaceLink to={context.links.chat} label="Chat" />
            <WorkspaceLink to={context.links.cockpit} label="Cockpit" />
            <WorkspaceLink to={context.links.task} label="Task" />
            <WorkspaceLink to={context.links.trace} label="Trace" />
            <WorkspaceLink to={context.links.logs} label="Logs" />
            <WorkspaceLink to={context.links.audit} label="Audit" />
          </div>
        </section>

        <section className="ops-panel">
          <h2>Summary</h2>
          <p className="decision-summary">{decision.summary}</p>
        </section>
      </section>

      <section className="decision-detail-layout">
        <section className="ops-panel">
          <h2>Evidence</h2>
          <div className="decision-evidence-list">
            {context.evidence.map((item, index) => (
              <article className="decision-evidence-row" key={`${index}:${JSON.stringify(item).slice(0, 32)}`}>
                <strong>{String(item.kind ?? item.source ?? `evidence-${index + 1}`)}</strong>
                <pre>{JSON.stringify(item, null, 2)}</pre>
              </article>
            ))}
            {context.evidence.length === 0 ? <div className="empty-state">No evidence attached.</div> : null}
          </div>
        </section>

        <section className="ops-panel">
          <h2>Payload</h2>
          <pre className="decision-payload">{JSON.stringify(decision.payload, null, 2)}</pre>
        </section>
      </section>

      <section className="decision-detail-layout">
        <section className="ops-panel">
          <h2>Related Logs</h2>
          <div className="decision-related-list">
            {context.related_logs.slice(0, 10).map((event) => (
              <article className="decision-related-row" key={event.id}>
                <StatusPill label={event.severity} tone={severityTone(event.severity)} />
                <Link to={`/logs/${encodeURIComponent(event.id)}`}>{event.event_type}</Link>
                <span>{timeLabel(event.ts)} · {event.agent_id ?? event.source}</span>
              </article>
            ))}
            {context.related_logs.length === 0 ? <div className="empty-state">No related logs found.</div> : null}
          </div>
        </section>

        <section className="ops-panel">
          <h2>Traces & Audit</h2>
          <div className="decision-related-list">
            {context.traces.map((trace) => (
              <article className="decision-related-row" key={trace.trace_id}>
                <StatusPill label={trace.status} tone={trace.status === 'ok' ? 'healthy' : 'incident'} />
                <Link to={`/traces/${encodeURIComponent(trace.trace_id)}`}>{trace.trace_id}</Link>
                <span>{trace.duration_ms}ms · {trace.span_count} spans · ${trace.cost_usd.toFixed(4)}</span>
              </article>
            ))}
            {context.audit_entries.slice(0, 8).map((entry) => (
              <article className="decision-related-row" key={`audit:${entry.id}`}>
                <StatusPill label={entry.category} tone={entry.category === 'security' ? 'incident' : 'network'} />
                <strong>{entry.action}</strong>
                <span>{timeLabel(entry.ts)} · {entry.source}</span>
              </article>
            ))}
            {context.traces.length === 0 && context.audit_entries.length === 0 ? <div className="empty-state">No trace or audit records found.</div> : null}
          </div>
        </section>
      </section>
    </main>
  )
}
