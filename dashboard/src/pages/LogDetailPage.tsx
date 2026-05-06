import { FormEvent, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { createIncident, getLogContext } from '../api/logs'
import { createTask } from '../api/tasks'
import MetricCard from '../components/MetricCard'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'
import AuditEntryRow from '../components/AuditEntryRow'
import DecisionEntryRow from '../components/DecisionEntryRow'
import type { LogContext } from '../types/logs'

function severityTone(severity: string): 'neutral' | 'healthy' | 'warning' | 'incident' {
  if (severity === 'critical' || severity === 'error') return 'incident'
  if (severity === 'warning') return 'warning'
  return 'neutral'
}

function timeLabel(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString() : '-'
}

function payloadText(value: unknown) {
  if (typeof value === 'string') return value
  if (value == null) return ''
  return JSON.stringify(value)
}

function WorkspaceLink({ to, label }: { to: string | null; label: string }) {
  return to ? <Link className="log-workspace-link" to={to}>{label}</Link> : <span className="log-workspace-link disabled">{label}</span>
}

export default function LogDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [context, setContext] = useState<LogContext | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  function load() {
    if (!id) return
    getLogContext(id)
      .then((result) => {
        setContext(result)
        setError(null)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }

  useEffect(() => {
    load()
  }, [id])

  async function createIncidentFromLog(event: FormEvent) {
    event.preventDefault()
    if (!context) return
    const created = await createIncident({
      title: `Log triage: ${context.event.event_type}`,
      severity: context.event.severity === 'info' ? 'warning' : context.event.severity,
      description: payloadText(context.event.payload.message ?? context.event.payload.summary ?? context.event.payload),
      agent_id: context.event.agent_id ?? undefined,
      task_id: context.event.task_id ?? undefined,
      trace_id: context.event.trace_id ?? undefined,
    })
    setMessage(`Created incident ${created.id}`)
  }

  async function createTaskFromLog(event: FormEvent) {
    event.preventDefault()
    if (!context) return
    const task = await createTask({
      title: `Triage log: ${context.event.event_type}`,
      description: [
        `Event: ${context.event.id}`,
        `Severity: ${context.event.severity}`,
        context.event.trace_id ? `Trace: ${context.event.trace_id}` : '',
        context.event.task_id ? `Related task: ${context.event.task_id}` : '',
        payloadText(context.event.payload),
      ].filter(Boolean).join('\n'),
      priority: context.event.severity === 'critical' ? 'urgent' : context.event.severity === 'error' ? 'high' : 'normal',
      assign_to: context.event.agent_id ?? undefined,
    })
    setMessage(`Created task ${task.id}`)
  }

  if (!context) return <main className="ops-page empty-state">{error ?? 'Loading log event.'}</main>

  const event = context.event

  return (
    <main className="ops-page">
      <PageHeader
        title={event.event_type}
        description={`Event ${event.id} · ${event.source}`}
        actions={<StatusPill label={event.severity} tone={severityTone(event.severity)} />}
      />

      {error ? <div className="panel-warning">{error}</div> : null}
      {message ? <div className="panel-warning">{message}</div> : null}

      <section className="metric-grid">
        <MetricCard label="Related logs" value={context.metrics.related_log_count} detail="Same trace/task/agent" />
        <MetricCard label="Traces" value={context.metrics.trace_count} detail="Execution paths" />
        <MetricCard label="Audit" value={context.metrics.audit_count} detail="Governance records" />
        <MetricCard label="Decisions" value={context.metrics.decision_count} detail="Linked decisions" />
        <MetricCard label="Agent" value={event.agent_id ?? '-'} detail="Emitter" />
        <MetricCard label="Time" value={timeLabel(event.ts)} detail={event.session_id ?? '-'} />
      </section>

      <section className="log-workspace-layout">
        <section className="ops-panel">
          <h2>Workspace Links</h2>
          <div className="log-link-grid">
            <WorkspaceLink to="/logs" label="Logs" />
            <WorkspaceLink to={context.links.agent} label="Agent" />
            <WorkspaceLink to={context.links.chat} label="Chat" />
            <WorkspaceLink to={context.links.task} label="Task" />
            <WorkspaceLink to={context.links.trace} label="Trace" />
            <WorkspaceLink to={context.links.audit} label="Audit" />
          </div>
        </section>

        <section className="ops-panel">
          <h2>Triage Actions</h2>
          <div className="log-action-grid">
            <form onSubmit={createIncidentFromLog}>
              <button type="submit">Create incident</button>
            </form>
            <form onSubmit={createTaskFromLog}>
              <button type="submit">Create task</button>
            </form>
          </div>
        </section>
      </section>

      <section className="ops-panel">
        <h2>Payload</h2>
        <pre className="log-payload">{JSON.stringify(event.payload, null, 2)}</pre>
      </section>

      <section className="log-workspace-layout">
        <section className="ops-panel">
          <h2>Related Logs</h2>
          <div className="log-event-list">
            {context.related_logs.slice(0, 12).map((item) => (
              <article className="log-event-row" key={item.id}>
                <div>
                  <StatusPill label={item.severity} tone={severityTone(item.severity)} />
                  <Link to={`/logs/${encodeURIComponent(item.id)}`}>{item.event_type}</Link>
                  <span>{timeLabel(item.ts)} · {item.agent_id ?? '-'}</span>
                </div>
                {item.trace_id ? <Link to={`/traces/${encodeURIComponent(item.trace_id)}`}>trace</Link> : null}
              </article>
            ))}
            {context.related_logs.length === 0 ? <div className="empty-state">No related logs found.</div> : null}
          </div>
        </section>

        <section className="ops-panel">
          <h2>Traces</h2>
          <div className="log-trace-list">
            {context.traces.map((trace) => (
              <article className="log-trace-row" key={trace.trace_id}>
                <StatusPill label={trace.status} tone={trace.status === 'ok' ? 'healthy' : 'incident'} />
                <Link to={`/traces/${encodeURIComponent(trace.trace_id)}`}>{trace.trace_id}</Link>
                <span>{trace.duration_ms}ms · {trace.span_count} spans · ${trace.cost_usd.toFixed(4)}</span>
              </article>
            ))}
            {context.traces.length === 0 ? <div className="empty-state">No traces found.</div> : null}
          </div>
        </section>
      </section>

      <section className="log-workspace-layout">
        <section className="ops-panel">
          <h2>Audit</h2>
          <div className="log-event-list">
            {context.audit_entries.slice(0, 10).map((entry) => (
              <AuditEntryRow className="log-event-row" entry={entry} key={entry.id} />
            ))}
            {context.audit_entries.length === 0 ? <div className="empty-state">No audit entries found.</div> : null}
          </div>
        </section>

        <section className="ops-panel">
          <h2>Decisions</h2>
          <div className="log-event-list">
            {context.decisions.map((decision) => (
              <DecisionEntryRow className="log-event-row" decision={decision} key={decision.id} />
            ))}
            {context.decisions.length === 0 ? <div className="empty-state">No decisions found.</div> : null}
          </div>
        </section>
      </section>
    </main>
  )
}
