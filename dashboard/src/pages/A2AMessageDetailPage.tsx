import { FormEvent, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getA2AMessageContext } from '../api/a2a'
import { createTask } from '../api/tasks'
import MetricCard from '../components/MetricCard'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'
import type { A2AMessage, A2AMessageContext } from '../types/a2a'

function severityTone(severity: string): 'neutral' | 'healthy' | 'warning' | 'incident' {
  if (severity === 'critical' || severity === 'error') return 'incident'
  if (severity === 'warning') return 'warning'
  return 'neutral'
}

function messageTone(message: A2AMessage): 'neutral' | 'healthy' | 'warning' | 'incident' | 'network' {
  if (message.severity === 'critical' || message.severity === 'error' || message.status === 'failed') return 'incident'
  if (message.severity === 'warning' || message.hop_count >= message.max_hops) return 'warning'
  return 'network'
}

function messageLabel(message: A2AMessage) {
  return message.message_type ?? message.event_type
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
  return to ? <Link className="a2a-workspace-link" to={to}>{label}</Link> : <span className="a2a-workspace-link disabled">{label}</span>
}

export default function A2AMessageDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [context, setContext] = useState<A2AMessageContext | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  function load() {
    if (!id) return
    getA2AMessageContext(id)
      .then((result) => {
        setContext(result)
        setError(null)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }

  useEffect(() => {
    load()
  }, [id])

  async function createFollowUpTask(event: FormEvent) {
    event.preventDefault()
    if (!context) return
    const created = await createTask({
      title: `A2A follow-up: ${messageLabel(context.message)}`,
      description: [
        `A2A event: ${context.message.id}`,
        `Message: ${context.message.message_id ?? '-'}`,
        `Route: ${context.message.from_agent ?? '-'} -> ${context.message.to_agent ?? '-'}`,
        context.message.trace_id ? `Trace: ${context.message.trace_id}` : '',
        context.message.task_id ? `Related task: ${context.message.task_id}` : '',
        payloadText(context.message.payload),
      ].filter(Boolean).join('\n'),
      priority: context.suggested_actions.find((action) => action.kind === 'task')?.priority ?? 'normal',
      assign_to: context.message.to_agent ?? context.message.from_agent ?? undefined,
    })
    setMessage(`Created task ${created.id}`)
  }

  if (!context) return <main className="ops-page empty-state">{error ?? 'Loading A2A message.'}</main>

  const envelope = context.message

  return (
    <main className="ops-page">
      <PageHeader
        title="A2A Message"
        description={`${envelope.from_agent ?? '-'} -> ${envelope.to_agent ?? '-'} · ${envelope.message_id ?? envelope.id}`}
        actions={<StatusPill label={messageLabel(envelope)} tone={messageTone(envelope)} />}
      />

      {error ? <div className="panel-warning">{error}</div> : null}
      {message ? <div className="panel-warning">{message}</div> : null}

      <section className="metric-grid">
        <MetricCard label="Thread" value={context.metrics.thread_count} detail="Correlated messages" />
        <MetricCard label="Failures" value={context.metrics.failure_count} detail="Failed/dead-letter events" tone={context.metrics.failure_count ? 'incident' : 'neutral'} />
        <MetricCard label="Loop warnings" value={context.metrics.loop_warnings} detail={`${envelope.hop_count}/${envelope.max_hops} hops`} tone={context.metrics.loop_warnings ? 'warning' : 'neutral'} />
        <MetricCard label="Logs" value={context.metrics.log_count} detail="Related events" />
        <MetricCard label="Audit" value={context.metrics.audit_count} detail="Governance records" />
        <MetricCard label="Decisions" value={context.metrics.decision_count} detail="Linked decisions" />
      </section>

      <section className="a2a-detail-layout">
        <section className="ops-panel">
          <h2>Workspace Links</h2>
          <div className="a2a-link-grid">
            <WorkspaceLink to="/a2a" label="A2A Network" />
            <WorkspaceLink to={context.links.from_agent} label="From Agent" />
            <WorkspaceLink to={context.links.to_agent} label="To Agent" />
            <WorkspaceLink to={context.links.task} label="Task" />
            <WorkspaceLink to={context.links.trace} label="Trace" />
            <WorkspaceLink to={context.links.logs} label="Logs" />
            <WorkspaceLink to={context.links.audit} label="Audit" />
          </div>
        </section>

        <section className="ops-panel">
          <h2>Actions</h2>
          <form className="a2a-action-row" onSubmit={createFollowUpTask}>
            <button type="submit">Create follow-up task</button>
            {envelope.trace_id ? <Link to={`/traces/${encodeURIComponent(envelope.trace_id)}`}>Inspect trace</Link> : null}
          </form>
        </section>
      </section>

      <section className="a2a-detail-layout">
        <section className="ops-panel">
          <h2>Thread</h2>
          <div className="a2a-thread-list">
            {context.thread.map((item) => (
              <article className="a2a-thread-row" key={item.id}>
                <div>
                  <StatusPill label={messageLabel(item)} tone={messageTone(item)} />
                  <strong>{item.from_agent ?? '-'} {'->'} {item.to_agent ?? '-'}</strong>
                  <span>{timeLabel(item.ts)} · {item.message_id ?? item.id}</span>
                </div>
                <span>{item.hop_count}/{item.max_hops}</span>
              </article>
            ))}
            {context.thread.length === 0 ? <div className="empty-state">No thread messages found.</div> : null}
          </div>
        </section>

        <section className="ops-panel">
          <h2>Envelope</h2>
          <div className="a2a-envelope-grid">
            <span>Event</span><strong>{envelope.id}</strong>
            <span>Correlation</span><strong>{envelope.correlation_id ?? '-'}</strong>
            <span>Root</span><strong>{envelope.root_correlation_id ?? '-'}</strong>
            <span>Parent</span><strong>{envelope.parent_correlation_id ?? '-'}</strong>
            <span>Mode</span><strong>{envelope.mode}</strong>
            <span>Status</span><strong>{envelope.status}</strong>
          </div>
        </section>
      </section>

      <section className="ops-panel">
        <h2>Payload</h2>
        <pre className="a2a-payload">{JSON.stringify(envelope.payload, null, 2)}</pre>
      </section>

      <section className="a2a-detail-layout">
        <section className="ops-panel">
          <h2>Related Logs</h2>
          <div className="a2a-related-list">
            {context.related_logs.slice(0, 10).map((event) => (
              <article className="a2a-related-row" key={event.id}>
                <div>
                  <StatusPill label={event.severity} tone={severityTone(event.severity)} />
                  <Link to={`/logs/${encodeURIComponent(event.id)}`}>{event.event_type}</Link>
                  <span>{timeLabel(event.ts)} · {event.source}</span>
                </div>
              </article>
            ))}
            {context.related_logs.length === 0 ? <div className="empty-state">No related logs found.</div> : null}
          </div>
        </section>

        <section className="ops-panel">
          <h2>Trace, Audit & Decisions</h2>
          <div className="a2a-related-list">
            {context.traces.map((trace) => (
              <article className="a2a-related-row" key={trace.trace_id}>
                <div>
                  <StatusPill label={trace.status} tone={trace.status === 'ok' ? 'healthy' : 'incident'} />
                  <Link to={`/traces/${encodeURIComponent(trace.trace_id)}`}>{trace.trace_id}</Link>
                  <span>{trace.duration_ms}ms · {trace.span_count} spans · ${trace.cost_usd.toFixed(4)}</span>
                </div>
              </article>
            ))}
            {context.decisions.map((decision) => (
              <article className="a2a-related-row" key={decision.id}>
                <div>
                  <StatusPill label={decision.status} tone={decision.status === 'approved' ? 'healthy' : 'warning'} />
                  <strong>{decision.title}</strong>
                  <span>{decision.summary}</span>
                </div>
              </article>
            ))}
            {context.audit_entries.slice(0, 8).map((entry) => (
              <article className="a2a-related-row" key={`audit:${entry.id}`}>
                <div>
                  <StatusPill label={entry.category} tone={entry.category === 'security' ? 'incident' : 'network'} />
                  <strong>{entry.action}</strong>
                  <span>{timeLabel(entry.ts)} · {entry.source}</span>
                </div>
              </article>
            ))}
            {context.traces.length === 0 && context.decisions.length === 0 && context.audit_entries.length === 0 ? <div className="empty-state">No trace, audit, or decision records found.</div> : null}
          </div>
        </section>
      </section>
    </main>
  )
}
