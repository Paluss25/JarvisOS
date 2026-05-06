import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getTrace } from '../api/traces'
import MetricCard from '../components/MetricCard'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'
import TraceTree from '../components/TraceTree'
import type { TraceDetail, TraceSpan } from '../types/trace'

function statusTone(status: string): 'neutral' | 'healthy' | 'warning' | 'incident' {
  if (status === 'ok') return 'healthy'
  if (status === 'error' || status === 'failed') return 'incident'
  if (status === 'running' || status === 'pending') return 'warning'
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

function payloadPreview(payload: Record<string, unknown>) {
  return JSON.stringify(payload, null, 2)
}

function WorkspaceLink({ to, label }: { to: string | null; label: string }) {
  return to ? <Link className="trace-workspace-link" to={to}>{label}</Link> : <span className="trace-workspace-link disabled">{label}</span>
}

function SpanPayload({ span }: { span: TraceSpan }) {
  return (
    <details className="trace-span-payload">
      <summary>{span.operation} · {span.span_id}</summary>
      <pre>{payloadPreview(span.payload)}</pre>
    </details>
  )
}

export default function TraceDetailPage() {
  const { traceId } = useParams()
  const [trace, setTrace] = useState<TraceDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!traceId) return
    getTrace(traceId)
      .then(setTrace)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [traceId])

  return (
    <main className="ops-page">
      <PageHeader
        title="Trace Detail"
        description={traceId}
        actions={<Link className="text-sm text-blue-300 hover:text-blue-200" to="/traces">Back to traces</Link>}
      />

      {error ? <div className="panel-warning">{error}</div> : null}

      {trace ? (
        <>
          <section className="metric-grid">
            <MetricCard label="Status" value={trace.summary.status} tone={statusTone(trace.summary.status)} />
            <MetricCard label="Spans" value={trace.metrics.span_count} detail={`${trace.metrics.error_count} errors`} tone={trace.metrics.error_count ? 'incident' : 'neutral'} />
            <MetricCard label="Duration" value={`${trace.summary.duration_ms} ms`} detail={timeLabel(trace.summary.started_at)} />
            <MetricCard label="Tokens" value={trace.metrics.token_count} detail={`${trace.summary.input_tokens} in / ${trace.summary.output_tokens} out`} />
            <MetricCard label="Cost" value={`$${trace.metrics.cost_usd.toFixed(4)}`} detail="Trace total" />
            <MetricCard label="Context" value={trace.metrics.log_count + trace.metrics.audit_count + trace.metrics.decision_count} detail="Logs, audit, decisions" />
          </section>

          <section className="trace-detail-layout">
            <section className="ops-panel">
              <h2>Workspace Links</h2>
              <div className="trace-link-grid">
                <WorkspaceLink to="/traces" label="Trace Explorer" />
                <WorkspaceLink to={trace.links.agent} label="Agent" />
                <WorkspaceLink to={trace.links.chat} label="Chat" />
                <WorkspaceLink to={trace.links.task} label="Task" />
                <WorkspaceLink to={trace.links.logs} label="Logs" />
                <WorkspaceLink to={trace.links.audit} label="Audit" />
                <WorkspaceLink to={trace.links.costs} label="Costs" />
              </div>
            </section>

            <section className="ops-panel">
              <h2>Identity</h2>
              <div className="trace-identity-grid">
                <span>Agent</span>
                <strong>{trace.summary.agent_id ?? '-'}</strong>
                <span>Task</span>
                <strong>{trace.summary.task_id ?? '-'}</strong>
                <span>Session</span>
                <strong>{trace.summary.session_id ?? '-'}</strong>
              </div>
            </section>
          </section>

          <section className="ops-panel">
            <h2>Waterfall</h2>
            <div className="trace-waterfall">
              {trace.waterfall.map((span) => {
                const width = Math.max(3, Math.min(100, (span.duration_ms / Math.max(trace.summary.duration_ms, 1)) * 100))
                const margin = Math.min(92, (span.offset_ms / Math.max(trace.summary.duration_ms, 1)) * 100)
                return (
                  <div className="trace-waterfall-row" key={span.span_id}>
                    <div>
                      <strong>{span.operation}</strong>
                      <span>{span.span_id}</span>
                    </div>
                    <div className="trace-waterfall-track">
                      <span
                        className={`trace-waterfall-bar ${span.status === 'ok' ? 'ok' : 'error'}`}
                        style={{ marginLeft: `${margin}%`, width: `${width}%` }}
                      />
                    </div>
                    <StatusPill label={`${span.duration_ms} ms`} tone={statusTone(span.status)} />
                  </div>
                )
              })}
              {trace.waterfall.length === 0 ? <div className="empty-state">No waterfall data.</div> : null}
            </div>
          </section>

          <section className="trace-detail-layout">
            <section className="ops-panel">
              <h2>Span Tree</h2>
              <TraceTree spans={trace.spans} />
            </section>

            <section className="ops-panel">
              <h2>Span Payloads</h2>
              <div className="trace-payload-list">
                {trace.flat_spans.map((span) => (
                  <SpanPayload key={span.span_id} span={span} />
                ))}
                {trace.flat_spans.length === 0 ? <div className="empty-state">No span payloads recorded.</div> : null}
              </div>
            </section>
          </section>

          <section className="trace-detail-layout">
            <section className="ops-panel">
              <h2>Correlated Logs</h2>
              <div className="trace-event-list">
                {trace.logs.slice(0, 12).map((event) => (
                  <article className="trace-event-row" key={event.id}>
                    <div>
                      <StatusPill label={event.severity} tone={severityTone(event.severity)} />
                      <Link to={`/logs/${encodeURIComponent(event.id)}`}>{event.event_type}</Link>
                      <span>{timeLabel(event.ts)} · {event.source}</span>
                    </div>
                    {event.span_id ? <span>{event.span_id}</span> : null}
                  </article>
                ))}
                {trace.logs.length === 0 ? <div className="empty-state">No logs linked.</div> : null}
              </div>
            </section>

            <section className="ops-panel">
              <h2>Audit & Decisions</h2>
              <div className="trace-event-list">
                {trace.decisions.map((decision) => (
                  <article className="trace-event-row" key={decision.id}>
                    <div>
                      <StatusPill label={decision.status} tone={decision.status === 'approved' ? 'healthy' : 'warning'} />
                      <strong>{decision.title}</strong>
                      <span>{decision.summary}</span>
                    </div>
                  </article>
                ))}
                {trace.audit_entries.slice(0, 8).map((entry) => (
                  <article className="trace-event-row" key={`audit:${entry.id}`}>
                    <div>
                      <StatusPill label={entry.category} tone={entry.category === 'security' ? 'incident' : 'network'} />
                      <strong>{entry.action}</strong>
                      <span>{timeLabel(entry.ts)} · {entry.source}</span>
                    </div>
                  </article>
                ))}
                {trace.decisions.length === 0 && trace.audit_entries.length === 0 ? <div className="empty-state">No audit or decision records linked.</div> : null}
              </div>
            </section>
          </section>
        </>
      ) : !error ? (
        <div className="empty-state">Loading trace...</div>
      ) : null}
    </main>
  )
}
