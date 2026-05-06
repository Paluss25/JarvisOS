import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getMemoryEventContext } from '../api/memory'
import MetricCard from '../components/MetricCard'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'
import type { MemoryEvent, MemoryEventContext } from '../types/memory'

function severityTone(severity: string): 'neutral' | 'healthy' | 'warning' | 'incident' {
  if (severity === 'critical' || severity === 'error') return 'incident'
  if (severity === 'warning') return 'warning'
  return 'neutral'
}

function timeLabel(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString() : '-'
}

function WorkspaceLink({ to, label }: { to: string | null; label: string }) {
  return to ? <Link className="memory-workspace-link" to={to}>{label}</Link> : <span className="memory-workspace-link disabled">{label}</span>
}

function MemoryPayload({ event }: { event: MemoryEvent }) {
  return (
    <details className="memory-payload">
      <summary>{event.kind} · {event.id}</summary>
      <pre>{JSON.stringify(event.payload, null, 2)}</pre>
    </details>
  )
}

export default function MemoryEventDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [context, setContext] = useState<MemoryEventContext | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    getMemoryEventContext(id)
      .then((result) => {
        setContext(result)
        setError(null)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [id])

  if (!context) return <main className="ops-page empty-state">{error ?? 'Loading memory event.'}</main>

  const event = context.event

  return (
    <main className="ops-page">
      <PageHeader
        title={event.kind}
        description={`${event.source} · ${event.domain ?? event.scope ?? 'global'} · ${event.key ?? event.id}`}
        actions={<StatusPill label={event.severity} tone={severityTone(event.severity)} />}
      />

      {error ? <div className="panel-warning">{error}</div> : null}

      <section className="metric-grid">
        <MetricCard label="Related events" value={context.metrics.related_event_count} detail="Same key/domain/scope/trace" />
        <MetricCard label="Traces" value={context.metrics.trace_count} detail="Execution provenance" />
        <MetricCard label="Audit" value={context.metrics.audit_count} detail="Governance records" />
        <MetricCard label="Decisions" value={context.metrics.decision_count} detail="Linked decisions" />
        <MetricCard label="Promotions" value={context.metrics.promotion_count} detail="Decision-to-memory records" />
        <MetricCard label="Agent" value={event.agent_id ?? '-'} detail={event.task_id ?? '-'} />
      </section>

      <section className="memory-detail-layout">
        <section className="ops-panel">
          <h2>Workspace Links</h2>
          <div className="memory-link-grid">
            <WorkspaceLink to="/memory" label="Memory" />
            <WorkspaceLink to={context.links.agent} label="Agent" />
            <WorkspaceLink to={context.links.chat} label="Chat" />
            <WorkspaceLink to={context.links.task} label="Task" />
            <WorkspaceLink to={context.links.trace} label="Trace" />
            <WorkspaceLink to={context.links.logs} label="Logs" />
            <WorkspaceLink to={context.links.audit} label="Audit" />
          </div>
        </section>

        <section className="ops-panel">
          <h2>Diagnostics</h2>
          <div className="memory-diagnostic-list">
            {context.diagnostics.map((item) => (
              <article className="memory-diagnostic-row" key={`${item.kind}:${item.label}`}>
                <StatusPill label={item.label} tone={item.tone} />
              </article>
            ))}
            {context.diagnostics.length === 0 ? <div className="empty-state">No diagnostics raised.</div> : null}
          </div>
        </section>
      </section>

      <section className="memory-detail-layout">
        <section className="ops-panel">
          <h2>Provenance</h2>
          <div className="memory-provenance-grid">
            <span>Event</span><strong>{event.id}</strong>
            <span>Type</span><strong>{event.event_type}</strong>
            <span>Source</span><strong>{event.source}</strong>
            <span>Domain</span><strong>{event.domain ?? '-'}</strong>
            <span>Scope</span><strong>{event.scope ?? '-'}</strong>
            <span>Key</span><strong>{event.key ?? '-'}</strong>
            <span>Time</span><strong>{timeLabel(event.ts)}</strong>
          </div>
        </section>

        <section className="ops-panel">
          <h2>Traces</h2>
          <div className="memory-trace-list">
            {context.traces.map((trace) => (
              <article className="memory-trace-row" key={trace.trace_id}>
                <StatusPill label={trace.status} tone={trace.status === 'ok' ? 'healthy' : 'incident'} />
                <Link to={`/traces/${encodeURIComponent(trace.trace_id)}`}>{trace.trace_id}</Link>
                <span>{trace.duration_ms}ms · {trace.span_count} spans · ${trace.cost_usd.toFixed(4)}</span>
              </article>
            ))}
            {context.traces.length === 0 ? <div className="empty-state">No traces linked.</div> : null}
          </div>
        </section>
      </section>

      <section className="ops-panel">
        <h2>Related Memory Events</h2>
        <div className="memory-related-table">
          <div className="memory-related-head">
            <span>Time</span>
            <span>Kind</span>
            <span>Agent</span>
            <span>Domain</span>
            <span>Key</span>
            <span>Trace</span>
          </div>
          {context.related_events.map((item) => (
            <div className="memory-related-row" key={item.id}>
              <span>{timeLabel(item.ts)}</span>
              <span><StatusPill label={item.kind} tone={severityTone(item.severity)} /></span>
              <span>{item.agent_id ? <Link to={`/agents/${encodeURIComponent(item.agent_id)}`}>{item.agent_id}</Link> : '-'}</span>
              <span>{item.domain ?? item.scope ?? '-'}</span>
              <span>{item.key ?? '-'}</span>
              <span>{item.trace_id ? <Link to={`/traces/${encodeURIComponent(item.trace_id)}`}>{item.trace_id}</Link> : '-'}</span>
            </div>
          ))}
          {context.related_events.length === 0 ? <div className="empty-state">No related memory events.</div> : null}
        </div>
      </section>

      <section className="memory-detail-layout">
        <section className="ops-panel">
          <h2>Payloads</h2>
          <div className="memory-payload-list">
            {context.related_events.slice(0, 8).map((item) => <MemoryPayload key={`payload:${item.id}`} event={item} />)}
            {context.related_events.length === 0 ? <div className="empty-state">No payloads recorded.</div> : null}
          </div>
        </section>

        <section className="ops-panel">
          <h2>Audit & Decisions</h2>
          <div className="memory-context-list">
            {context.decisions.map((decision) => (
              <article className="memory-context-row" key={decision.id}>
                <StatusPill label={decision.status} tone={decision.status === 'approved' ? 'healthy' : 'warning'} />
                <strong>{decision.title}</strong>
                <span>{decision.summary}</span>
              </article>
            ))}
            {context.audit_entries.slice(0, 8).map((entry) => (
              <article className="memory-context-row" key={`audit:${entry.id}`}>
                <StatusPill label={entry.category} tone={entry.category === 'security' ? 'incident' : 'network'} />
                <strong>{entry.action}</strong>
                <span>{timeLabel(entry.ts)} · {entry.source}</span>
              </article>
            ))}
            {context.decisions.length === 0 && context.audit_entries.length === 0 ? <div className="empty-state">No audit or decision records linked.</div> : null}
          </div>
        </section>
      </section>
    </main>
  )
}
