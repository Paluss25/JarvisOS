import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getCostTraceContext } from '../api/costs'
import MetricCard from '../components/MetricCard'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'
import AuditEntryRow from '../components/AuditEntryRow'
import DecisionEntryRow from '../components/DecisionEntryRow'
import type { CostTraceContext } from '../types/costs'

function money(value: number): string {
  return `$${value.toFixed(4)}`
}

function statusTone(status: string): 'neutral' | 'healthy' | 'warning' | 'incident' {
  if (status === 'ok') return 'healthy'
  if (status === 'error' || status === 'failed') return 'incident'
  return 'warning'
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
  return to ? <Link className="cost-workspace-link" to={to}>{label}</Link> : <span className="cost-workspace-link disabled">{label}</span>
}

export default function CostTraceDetailPage() {
  const { traceId } = useParams<{ traceId: string }>()
  const [context, setContext] = useState<CostTraceContext | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!traceId) return
    getCostTraceContext(traceId)
      .then((result) => {
        setContext(result)
        setError(null)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [traceId])

  if (!context) return <main className="ops-page empty-state">{error ?? 'Loading cost trace.'}</main>

  const summary = context.summary

  return (
    <main className="ops-page">
      <PageHeader
        title="Cost Trace"
        description={summary.trace_id}
        actions={<StatusPill label={summary.status} tone={statusTone(summary.status)} />}
      />

      {error ? <div className="panel-warning">{error}</div> : null}

      <section className="metric-grid">
        <MetricCard label="Total cost" value={money(summary.total_cost_usd)} detail="Trace spend" />
        <MetricCard label="Retry cost" value={money(summary.retry_cost_usd)} detail="Retry spans" tone={summary.retry_cost_usd ? 'incident' : 'neutral'} />
        <MetricCard label="Tokens" value={summary.tokens.toLocaleString()} detail={`${summary.input_tokens} in / ${summary.output_tokens} out`} />
        <MetricCard label="Duration" value={`${summary.duration_ms}ms`} detail={`${summary.span_count} spans`} />
        <MetricCard label="p95 latency" value={`${summary.p95_latency_ms}ms`} detail="Model span latency" tone={summary.p95_latency_ms >= 5000 ? 'warning' : 'neutral'} />
        <MetricCard label="Models" value={context.metrics.model_count} detail="Provider/model routes" />
      </section>

      <section className="cost-detail-layout">
        <section className="ops-panel">
          <h2>Workspace Links</h2>
          <div className="cost-link-grid">
            <WorkspaceLink to="/costs" label="Costs" />
            <WorkspaceLink to={context.links.trace} label="Trace" />
            <WorkspaceLink to={context.links.agent} label="Agent" />
            <WorkspaceLink to={context.links.chat} label="Chat" />
            <WorkspaceLink to={context.links.task} label="Task" />
            <WorkspaceLink to={context.links.logs} label="Logs" />
            <WorkspaceLink to={context.links.audit} label="Audit" />
          </div>
        </section>

        <section className="ops-panel">
          <h2>Anomalies</h2>
          <div className="cost-anomaly-list">
            {context.anomalies.map((item) => (
              <article className="cost-anomaly-row" key={`${item.kind}:${item.label}`}>
                <StatusPill label={item.label} tone={item.tone} />
              </article>
            ))}
            {context.anomalies.length === 0 ? <div className="empty-state">No cost anomalies detected.</div> : null}
          </div>
        </section>
      </section>

      <section className="cost-detail-layout">
        <section className="ops-panel">
          <h2>Model Breakdown</h2>
          <div className="cost-mini-table">
            <div className="cost-mini-head">
              <span>Model</span>
              <span>Cost</span>
              <span>Tokens</span>
              <span>Spans</span>
            </div>
            {context.model_breakdown.map((row) => (
              <div className="cost-mini-row" key={row.key}>
                <strong>{row.key}</strong>
                <span>{money(row.cost_usd)}</span>
                <span>{row.tokens.toLocaleString()}</span>
                <span>{row.span_count}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="ops-panel">
          <h2>Context</h2>
          <div className="cost-context-grid">
            <span>Agent</span><strong>{summary.agent_id ?? '-'}</strong>
            <span>Task</span><strong>{summary.task_id ?? '-'}</strong>
            <span>Session</span><strong>{summary.session_id ?? '-'}</strong>
            <span>Logs</span><strong>{context.metrics.log_count}</strong>
            <span>Audit</span><strong>{context.metrics.audit_count}</strong>
            <span>Decisions</span><strong>{context.metrics.decision_count}</strong>
          </div>
        </section>
      </section>

      <section className="ops-panel">
        <h2>Costed Spans</h2>
        <div className="cost-span-table">
          <div className="cost-span-head">
            <span>Span</span>
            <span>Operation</span>
            <span>Model</span>
            <span>Status</span>
            <span>Cost</span>
            <span>Tokens</span>
            <span>Duration</span>
          </div>
          {context.spans.map((span) => (
            <div className="cost-span-row" key={span.span_id}>
              <span>{span.span_id}</span>
              <span>{span.operation}{span.retry ? ' · retry' : ''}</span>
              <span>{[span.provider, span.model].filter(Boolean).join('/') || '-'}</span>
              <span><StatusPill label={span.status} tone={statusTone(span.status)} /></span>
              <span>{money(span.cost_usd)}</span>
              <span>{span.tokens.toLocaleString()}</span>
              <span>{span.duration_ms}ms</span>
            </div>
          ))}
        </div>
      </section>

      <section className="cost-detail-layout">
        <section className="ops-panel">
          <h2>Related Logs</h2>
          <div className="cost-related-list">
            {context.related_logs.slice(0, 10).map((event) => (
              <article className="cost-related-row" key={event.id}>
                <StatusPill label={event.severity} tone={severityTone(event.severity)} />
                <Link to={`/logs/${encodeURIComponent(event.id)}`}>{event.event_type}</Link>
                <span>{timeLabel(event.ts)} · {event.source}</span>
              </article>
            ))}
            {context.related_logs.length === 0 ? <div className="empty-state">No related logs found.</div> : null}
          </div>
        </section>

        <section className="ops-panel">
          <h2>Audit & Decisions</h2>
          <div className="cost-related-list">
            {context.decisions.map((decision) => (
              <DecisionEntryRow className="cost-related-row" decision={decision} key={decision.id} />
            ))}
            {context.audit_entries.slice(0, 8).map((entry) => (
              <AuditEntryRow className="cost-related-row" entry={entry} key={`audit:${entry.id}`} />
            ))}
            {context.decisions.length === 0 && context.audit_entries.length === 0 ? <div className="empty-state">No audit or decision records linked.</div> : null}
          </div>
        </section>
      </section>
    </main>
  )
}
