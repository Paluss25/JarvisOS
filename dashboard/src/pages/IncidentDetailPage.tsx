import { FormEvent, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { createTask } from '../api/tasks'
import { getIncidentContext } from '../api/logs'
import MetricCard from '../components/MetricCard'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'
import AuditEntryRow from '../components/AuditEntryRow'
import DecisionEntryRow from '../components/DecisionEntryRow'
import type { IncidentContext } from '../types/logs'

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
  return to ? <Link className="incident-workspace-link" to={to}>{label}</Link> : <span className="incident-workspace-link disabled">{label}</span>
}

export default function IncidentDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [context, setContext] = useState<IncidentContext | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [taskMessage, setTaskMessage] = useState<string | null>(null)

  function load() {
    if (!id) return
    getIncidentContext(id)
      .then((result) => {
        setContext(result)
        setError(null)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }

  useEffect(() => {
    load()
  }, [id])

  async function createResponseTask(event: FormEvent) {
    event.preventDefault()
    if (!context) return
    const title = `Incident response: ${String(context.incident.payload.title ?? context.incident.event_type)}`
    const description = [
      payloadText(context.incident.payload.description),
      `Incident: ${context.incident.id}`,
      context.incident.trace_id ? `Trace: ${context.incident.trace_id}` : '',
      context.incident.task_id ? `Related task: ${context.incident.task_id}` : '',
    ].filter(Boolean).join('\n')
    const task = await createTask({
      title,
      description,
      priority: context.incident.severity === 'critical' ? 'urgent' : 'high',
      assign_to: context.incident.agent_id ?? undefined,
    })
    setTaskMessage(`Created task ${task.id}`)
  }

  if (!context) return <main className="ops-page empty-state">{error ?? 'Loading incident.'}</main>

  const incident = context.incident
  const title = String(incident.payload.title ?? incident.event_type)
  const status = String(incident.payload.status ?? 'open')

  return (
    <main className="ops-page">
      <PageHeader
        title={title}
        description={payloadText(incident.payload.description) || `Incident ${incident.id}`}
        actions={
          <>
            <StatusPill label={incident.severity} tone={severityTone(incident.severity)} />
            <StatusPill label={status} tone={status === 'open' ? 'warning' : 'healthy'} />
          </>
        }
      />

      {error ? <div className="panel-warning">{error}</div> : null}
      {taskMessage ? <div className="panel-warning">{taskMessage}</div> : null}

      <section className="metric-grid">
        <MetricCard label="Related logs" value={context.metrics.log_count} detail="Correlated platform events" />
        <MetricCard label="Traces" value={context.metrics.trace_count} detail="Execution paths" />
        <MetricCard label="Audit" value={context.metrics.audit_count} detail="Governance records" />
        <MetricCard label="Decisions" value={context.metrics.decision_count} detail="Linked decisions" />
        <MetricCard label="Agent" value={incident.agent_id ?? '-'} detail="Owner candidate" />
        <MetricCard label="Created" value={timeLabel(incident.ts)} detail={incident.source} />
      </section>

      <section className="incident-workspace-layout">
        <section className="ops-panel">
          <h2>Workspace Links</h2>
          <div className="incident-link-grid">
            <WorkspaceLink to="/incidents" label="Incident List" />
            <WorkspaceLink to={context.links.agent} label="Agent" />
            <WorkspaceLink to={context.links.task} label="Task" />
            <WorkspaceLink to={context.links.trace} label="Trace" />
            <WorkspaceLink to={context.links.logs} label="Logs" />
            <WorkspaceLink to={context.links.audit} label="Audit" />
            <WorkspaceLink to={context.links.ciso} label="CISO Cockpit" />
            <WorkspaceLink to={context.links.cio} label="CIO Cockpit" />
          </div>
        </section>

        <section className="ops-panel">
          <h2>Response Task</h2>
          <form className="incident-response-form" onSubmit={createResponseTask}>
            <p>Create a response task from this incident, preserving trace/task references in the description.</p>
            <button type="submit">Create response task</button>
          </form>
        </section>
      </section>

      <section className="incident-workspace-layout">
        <section className="ops-panel">
          <h2>Related Logs</h2>
          <div className="incident-event-list">
            {context.related_logs.slice(0, 12).map((event) => (
              <article className="incident-event-row" key={event.id}>
                <div>
                  <StatusPill label={event.severity} tone={severityTone(event.severity)} />
                  <strong>{event.event_type}</strong>
                  <span>{timeLabel(event.ts)} · {event.agent_id ?? '-'}</span>
                </div>
                {event.trace_id ? <Link to={`/traces/${encodeURIComponent(event.trace_id)}`}>trace</Link> : null}
              </article>
            ))}
            {context.related_logs.length === 0 ? <div className="empty-state">No related logs found.</div> : null}
          </div>
        </section>

        <section className="ops-panel">
          <h2>Traces</h2>
          <div className="incident-trace-list">
            {context.traces.map((trace) => (
              <article className="incident-trace-row" key={trace.trace_id}>
                <StatusPill label={trace.status} tone={trace.status === 'ok' ? 'healthy' : 'incident'} />
                <Link to={`/traces/${encodeURIComponent(trace.trace_id)}`}>{trace.trace_id}</Link>
                <span>{trace.duration_ms}ms · {trace.span_count} spans · ${trace.cost_usd.toFixed(4)}</span>
              </article>
            ))}
            {context.traces.length === 0 ? <div className="empty-state">No traces found.</div> : null}
          </div>
        </section>
      </section>

      <section className="incident-workspace-layout">
        <section className="ops-panel">
          <h2>Audit</h2>
          <div className="incident-event-list">
            {context.audit_entries.slice(0, 10).map((entry) => (
              <AuditEntryRow className="incident-event-row" entry={entry} key={entry.id} />
            ))}
            {context.audit_entries.length === 0 ? <div className="empty-state">No audit entries found.</div> : null}
          </div>
        </section>

        <section className="ops-panel">
          <h2>Decisions</h2>
          <div className="incident-event-list">
            {context.decisions.map((decision) => (
              <DecisionEntryRow className="incident-event-row" decision={decision} key={decision.id} />
            ))}
            {context.decisions.length === 0 ? <div className="empty-state">No decisions found.</div> : null}
          </div>
        </section>
      </section>
    </main>
  )
}
