import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getToolContext } from '../api/plugins'
import MetricCard from '../components/MetricCard'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'
import AuditEntryRow from '../components/AuditEntryRow'
import DecisionEntryRow from '../components/DecisionEntryRow'
import type { ObservedTool, ToolContext } from '../types/plugins'

function toneForStatus(status: string): 'neutral' | 'healthy' | 'warning' | 'incident' {
  if (status === 'ok' || status === 'success') return 'healthy'
  if (status === 'failed' || status === 'error') return 'incident'
  if (status === 'unknown') return 'neutral'
  return 'warning'
}

function timeLabel(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString() : '-'
}

function WorkspaceLink({ to, label }: { to: string | null; label: string }) {
  return to ? <Link className="plugin-workspace-link" to={to}>{label}</Link> : <span className="plugin-workspace-link disabled">{label}</span>
}

function EventPayload({ event }: { event: ObservedTool }) {
  return (
    <details className="plugin-payload">
      <summary>{event.event_type} · {event.id ?? event.name}</summary>
      <pre>{JSON.stringify(event.payload, null, 2)}</pre>
    </details>
  )
}

export default function PluginToolDetailPage() {
  const { kind, name } = useParams<{ kind: 'tool' | 'skill'; name: string }>()
  const [context, setContext] = useState<ToolContext | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!name || (kind !== 'tool' && kind !== 'skill')) return
    getToolContext(name, kind)
      .then((result) => {
        setContext(result)
        setError(null)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [kind, name])

  if (!context) return <main className="ops-page empty-state">{error ?? 'Loading tool workspace.'}</main>

  return (
    <main className="ops-page">
      <PageHeader
        title={context.tool.name}
        description={`${context.tool.kind} workspace · read-only registry and observed usage`}
        actions={<StatusPill label={context.tool.read_only ? 'read-only' : 'mutable'} tone="network" />}
      />

      {error ? <div className="panel-warning">{error}</div> : null}

      <section className="metric-grid">
        <MetricCard label="Agents" value={context.metrics.agent_count} detail="Registered or observed owners" />
        <MetricCard label="Events" value={context.metrics.event_count} detail="Observed tool/skill usage" />
        <MetricCard label="Failures" value={context.metrics.failure_count} detail="Recent failed events" tone={context.metrics.failure_count ? 'incident' : 'neutral'} />
        <MetricCard label="Traces" value={context.metrics.trace_count} detail="Linked execution traces" />
        <MetricCard label="Audit" value={context.metrics.audit_count} detail="Governance records" />
        <MetricCard label="Avg duration" value={context.metrics.avg_duration_ms ? `${context.metrics.avg_duration_ms} ms` : '-'} detail="Observed events" />
      </section>

      <section className="plugin-detail-layout">
        <section className="ops-panel">
          <h2>Workspace Links</h2>
          <div className="plugin-link-grid">
            <WorkspaceLink to="/plugins" label="Plugin Center" />
            <WorkspaceLink to={context.links.logs} label="Logs" />
            <WorkspaceLink to={context.links.audit} label="Audit" />
            <WorkspaceLink to={context.links.first_trace} label="First Trace" />
            <WorkspaceLink to={context.links.first_task} label="First Task" />
          </div>
        </section>

        <section className="ops-panel">
          <h2>Diagnostics</h2>
          <div className="plugin-diagnostic-list">
            {context.diagnostics.map((item) => (
              <article className="plugin-diagnostic-row" key={`${item.kind}:${item.label}`}>
                <StatusPill label={item.label} tone={item.tone} />
                <strong>{item.count}</strong>
              </article>
            ))}
            {context.diagnostics.length === 0 ? <div className="empty-state">No diagnostics raised.</div> : null}
          </div>
        </section>
      </section>

      <section className="plugin-detail-layout">
        <section className="ops-panel">
          <h2>Agents</h2>
          <div className="plugin-agent-list">
            {context.agents.map((agent) => (
              <article className="plugin-agent-row" key={agent.id}>
                <Link to={`/agents/${encodeURIComponent(agent.id)}`}>{agent.id}</Link>
                <span>{agent.domains.join(', ') || '-'}</span>
                <small>{agent.capabilities.join(', ') || '-'}</small>
              </article>
            ))}
            {context.agents.length === 0 ? <div className="empty-state">No registered agent owner.</div> : null}
          </div>
        </section>

        <section className="ops-panel">
          <h2>Traces</h2>
          <div className="plugin-trace-list">
            {context.traces.map((trace) => (
              <article className="plugin-trace-row" key={trace.trace_id}>
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
        <h2>Observed Events</h2>
        <div className="plugin-event-table">
          <div className="plugin-event-head">
            <span>Time</span>
            <span>Status</span>
            <span>Agent</span>
            <span>Trace</span>
            <span>Task</span>
            <span>Duration</span>
          </div>
          {context.events.map((event, index) => (
            <div className="plugin-event-row" key={`${event.id}:${index}`}>
              <span>{timeLabel(event.ts)}</span>
              <span><StatusPill label={event.status} tone={toneForStatus(event.status)} /></span>
              <span>{event.agent_id ? <Link to={`/agents/${encodeURIComponent(event.agent_id)}`}>{event.agent_id}</Link> : '-'}</span>
              <span>{event.trace_id ? <Link to={`/traces/${encodeURIComponent(event.trace_id)}`}>{event.trace_id}</Link> : '-'}</span>
              <span>{event.task_id ? <Link to={`/tasks/${encodeURIComponent(event.task_id)}`}>{event.task_id}</Link> : '-'}</span>
              <span>{event.duration_ms ? `${event.duration_ms}ms` : '-'}</span>
            </div>
          ))}
          {context.events.length === 0 ? <div className="empty-state">No observed events.</div> : null}
        </div>
      </section>

      <section className="plugin-detail-layout">
        <section className="ops-panel">
          <h2>Payloads</h2>
          <div className="plugin-payload-list">
            {context.events.slice(0, 8).map((event, index) => <EventPayload key={`${event.id}:payload:${index}`} event={event} />)}
            {context.events.length === 0 ? <div className="empty-state">No payloads recorded.</div> : null}
          </div>
        </section>

        <section className="ops-panel">
          <h2>Audit & Decisions</h2>
          <div className="plugin-related-list">
            {context.decisions.map((decision) => (
              <DecisionEntryRow className="plugin-related-row" decision={decision} key={decision.id} />
            ))}
            {context.audit_entries.slice(0, 8).map((entry) => (
              <AuditEntryRow className="plugin-related-row" entry={entry} key={`audit:${entry.id}`} />
            ))}
            {context.decisions.length === 0 && context.audit_entries.length === 0 ? <div className="empty-state">No audit or decision records linked.</div> : null}
          </div>
        </section>
      </section>
    </main>
  )
}
