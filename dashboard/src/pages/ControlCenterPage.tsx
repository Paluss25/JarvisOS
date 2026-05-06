import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getControlSummary } from '../api/control'
import MetricCard from '../components/MetricCard'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'
import type { ControlIncident, ControlSummary, ControlTaskCard } from '../types/control'

function taskTone(status: string): 'neutral' | 'healthy' | 'warning' | 'incident' {
  if (status === 'done') return 'healthy'
  if (status === 'blocked' || status === 'failed') return 'incident'
  if (status === 'needs_review' || status === 'running' || status === 'waiting') return 'warning'
  return 'neutral'
}

function severityTone(severity: string): 'neutral' | 'healthy' | 'warning' | 'incident' {
  if (severity === 'critical' || severity === 'error') return 'incident'
  if (severity === 'warning') return 'warning'
  return 'neutral'
}

function timeLabel(value: string | null) {
  return value ? new Date(value).toLocaleString() : '-'
}

function TaskQueue({ title, rows, empty }: { title: string; rows: ControlTaskCard[]; empty: string }) {
  return (
    <section className="ops-panel">
      <h2>{title}</h2>
      <div className="control-task-list">
        {rows.map((task) => (
          <article className="control-task-row" key={task.id}>
            <div>
              <StatusPill label={task.status} tone={taskTone(task.status)} />
              <Link to={task.href}>{task.title}</Link>
              <span>{task.priority} · {timeLabel(task.created_at)}</span>
            </div>
            {task.agent_href ? <Link to={task.agent_href}>{task.agent_id}</Link> : <span>-</span>}
          </article>
        ))}
        {rows.length === 0 ? <div className="empty-state">{empty}</div> : null}
      </div>
    </section>
  )
}

function IncidentFeed({ rows }: { rows: ControlIncident[] }) {
  return (
    <section className="ops-panel">
      <h2>Incidents</h2>
      <div className="control-feed-list">
        {rows.map((event, index) => (
          <article className="control-feed-row" key={event.id ?? `${event.ts}:${index}`}>
            <div>
              <StatusPill label={event.severity} tone={severityTone(event.severity)} />
              {event.detail_href ? <Link to={event.detail_href}>{event.event_type}</Link> : <strong>{event.event_type}</strong>}
              <span>{event.summary} · {event.agent_id ?? '-'}</span>
            </div>
            <div className="control-feed-actions">
              {event.task_href ? <Link to={event.task_href}>task</Link> : null}
              {event.trace_href ? <Link to={event.trace_href}>trace</Link> : null}
            </div>
          </article>
        ))}
        {rows.length === 0 ? <div className="empty-state">No active incidents.</div> : null}
      </div>
    </section>
  )
}

export default function ControlCenterPage() {
  const [summary, setSummary] = useState<ControlSummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getControlSummary()
      .then((result) => {
        setSummary(result)
        setError(null)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [])

  return (
    <main className="ops-page">
      <PageHeader
        title="Control Center"
        description="Global JarvisOS operations, agent health, active work, incidents, decisions, slow traces, and daily model spend."
        actions={<StatusPill label={error ? 'API degraded' : 'Live'} tone={error ? 'warning' : 'healthy'} />}
      />

      {error ? <div className="panel-warning">{error}</div> : null}

      <section className="metric-grid">
        <MetricCard label="Agents running" value={summary ? `${summary.agents.running}/${summary.agents.total}` : '...'} tone={summary?.agents.not_running ? 'warning' : 'healthy'} />
        <MetricCard label="Open tasks" value={summary?.tasks.open ?? '...'} detail={`${summary?.tasks.running ?? 0} running`} />
        <MetricCard label="Needs review" value={summary?.tasks.needs_review ?? '...'} detail="Operator decisions" tone={summary?.tasks.needs_review ? 'warning' : 'neutral'} />
        <MetricCard label="Blocked/failed" value={summary?.tasks.blocked ?? '...'} detail="Requires triage" tone={summary?.tasks.blocked ? 'incident' : 'neutral'} />
        <MetricCard label="Active incidents" value={summary?.incidents.active ?? '...'} tone={summary?.incidents.critical ? 'incident' : 'neutral'} />
        <MetricCard label="Cost today" value={summary ? `$${summary.costs.today_usd.toFixed(2)}` : '...'} detail={`${summary?.costs.tokens_today ?? 0} tokens`} />
      </section>

      <section className="control-hero-grid">
        <TaskQueue title="Work In Progress" rows={summary?.work_in_progress ?? []} empty="No active work in progress." />
        <TaskQueue title="Needs Review" rows={summary?.needs_review ?? []} empty="No tasks waiting for review." />
      </section>

      <section className="control-hero-grid">
        <IncidentFeed rows={summary?.incident_feed ?? []} />

        <section className="ops-panel">
          <h2>Agent Spotlight</h2>
          <div className="control-agent-list">
            {(summary?.agent_spotlight ?? []).map((agent) => (
              <article className="control-agent-row" key={agent.id}>
                <StatusPill label={agent.status} tone={agent.status === 'running' ? 'healthy' : 'incident'} />
                <Link to={agent.href}>{agent.id}</Link>
                <Link to={agent.cockpit_href}>cockpit</Link>
              </article>
            ))}
            {(summary?.agent_spotlight.length ?? 0) === 0 ? <div className="empty-state">No agents registered.</div> : null}
          </div>
        </section>
      </section>

      <section className="control-hero-grid">
        <section className="ops-panel">
          <h2>Slow Traces</h2>
          <div className="control-trace-list">
            {(summary?.slow_traces ?? []).map((trace) => (
              <article className="control-trace-row" key={trace.trace_id}>
                <div>
                  <StatusPill label={trace.status} tone={trace.status === 'ok' ? 'healthy' : 'incident'} />
                  <Link to={trace.href}>{trace.trace_id}</Link>
                  <span>{trace.duration_ms}ms · ${trace.cost_usd.toFixed(4)} · {trace.agent_id ?? '-'}</span>
                </div>
                {trace.task_href ? <Link to={trace.task_href}>task</Link> : null}
              </article>
            ))}
            {(summary?.slow_traces.length ?? 0) === 0 ? <div className="empty-state">No trace spans recorded today.</div> : null}
          </div>
        </section>

        <section className="ops-panel">
          <h2><Link to="/decisions">Recent Decisions</Link></h2>
          <div className="control-feed-list">
            {(summary?.recent_decisions ?? []).map((decision) => (
              <article className="control-feed-row" key={decision.id}>
                <div>
                  <StatusPill label={decision.status} tone={decision.status === 'approved' ? 'healthy' : 'warning'} />
                  <Link to={decision.detail_href ?? `/decisions/${encodeURIComponent(decision.id)}`}>{decision.title}</Link>
                  <span>{timeLabel(decision.ts)} · {decision.agent_id}</span>
                </div>
                <div className="control-feed-actions">
                  {decision.href ? <Link to={decision.href}>task</Link> : null}
                  {decision.trace_href ? <Link to={decision.trace_href}>trace</Link> : null}
                </div>
              </article>
            ))}
            {(summary?.recent_decisions.length ?? 0) === 0 ? <div className="empty-state">No recent decisions recorded.</div> : null}
          </div>
        </section>
      </section>

      <section className="ops-panel">
        <h2>Recent Audit</h2>
        <div className="ops-list">
          {(summary?.recent_audit ?? []).map((row, index) => (
            <div className="ops-row" key={`${row.ts}-${index}`}>
              <span>{new Date(row.ts).toLocaleString()}</span>
              <strong>{row.action}</strong>
              <span>{row.agent_id ?? row.category}</span>
            </div>
          ))}
          {summary && summary.recent_audit.length === 0 ? <div className="empty-state">No recent audit entries.</div> : null}
        </div>
      </section>
    </main>
  )
}
