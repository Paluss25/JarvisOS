import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { assignTask, getTaskContext, type TaskContext } from '../api/tasks'
import { listAgents, type AgentInfo } from '../api/agents'
import MetricCard from '../components/MetricCard'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'
import AuditEntryRow from '../components/AuditEntryRow'
import DecisionEntryRow from '../components/DecisionEntryRow'
import { useAuth } from '../context/AuthContext'

function statusTone(status: string): 'neutral' | 'healthy' | 'warning' | 'incident' {
  if (status === 'done') return 'healthy'
  if (status === 'failed' || status === 'blocked') return 'incident'
  if (status === 'running' || status === 'needs_review' || status === 'waiting') return 'warning'
  return 'neutral'
}

function severityTone(severity: string): 'neutral' | 'healthy' | 'warning' | 'incident' {
  if (severity === 'critical' || severity === 'error') return 'incident'
  if (severity === 'warning') return 'warning'
  return 'neutral'
}

function safeDate(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString() : '-'
}

function ContextLink({ to, label }: { to: string | null; label: string }) {
  return to ? <Link className="task-context-link" to={to}>{label}</Link> : <span className="task-context-link disabled">{label}</span>
}

export default function TaskDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { isAdmin } = useAuth()
  const [context, setContext] = useState<TaskContext | null>(null)
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [assignTo, setAssignTo] = useState('')
  const [error, setError] = useState<string | null>(null)

  function load() {
    if (!id) return
    getTaskContext(id)
      .then((result) => {
        setContext(result)
        setAssignTo(result.task.assigned_agent ?? '')
        setError(null)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
    listAgents().then(setAgents).catch(() => setAgents([]))
  }

  useEffect(() => {
    load()
  }, [id])

  async function handleAssign() {
    if (!id || !assignTo) return
    await assignTask(id, assignTo)
    load()
  }

  if (!context) return <main className="ops-page empty-state">{error ?? 'Loading task.'}</main>

  const { task, metrics } = context

  return (
    <main className="ops-page">
      <PageHeader
        title={task.title}
        description={task.description || 'No description provided.'}
        actions={<StatusPill label={task.status} tone={statusTone(task.status)} />}
      />

      {error ? <div className="panel-warning">{error}</div> : null}

      <section className="metric-grid">
        <MetricCard label="Traces" value={metrics.trace_count} detail="Execution traces" />
        <MetricCard label="Logs" value={metrics.log_count} detail="Correlated events" />
        <MetricCard label="Audit" value={metrics.audit_count} detail="Governance records" />
        <MetricCard label="Decisions" value={metrics.decision_count} detail="Linked decisions" />
        <MetricCard label="Artifacts" value={metrics.artifact_count} detail="Outputs and files" />
        <MetricCard label="Retries" value={`${task.retry_count}/${task.max_retries}`} detail={task.assignment_mode} tone={task.retry_count ? 'warning' : 'neutral'} />
      </section>

      <section className="task-detail-layout">
        <section className="ops-panel">
          <h2>Work Context</h2>
          <div className="task-context-grid">
            <ContextLink to="/tasks" label="Task Board" />
            <ContextLink to={context.links.agent} label="Agent" />
            <ContextLink to={context.links.chat} label="Chat" />
            <ContextLink to={context.links.cockpit} label="Cockpit" />
            <ContextLink to={context.links.traces} label="Traces" />
            <ContextLink to={context.links.logs} label="Logs" />
            <ContextLink to={context.links.audit} label="Audit" />
          </div>
        </section>

        <section className="ops-panel">
          <h2>Assignment</h2>
          <div className="task-assignment-panel">
            <div>
              <span>Assigned agent</span>
              <strong>{task.assigned_agent ? <Link to={`/agents/${encodeURIComponent(task.assigned_agent)}`}>{task.assigned_agent}</Link> : '-'}</strong>
            </div>
            <div>
              <span>Priority</span>
              <strong>{task.priority}</strong>
            </div>
            <div>
              <span>Created</span>
              <strong>{safeDate(task.created_at)}</strong>
            </div>
            <div>
              <span>Updated</span>
              <strong>{safeDate(task.updated_at)}</strong>
            </div>
            {isAdmin ? (
              <div className="task-assign-row">
                <select value={assignTo} onChange={e => setAssignTo(e.target.value)}>
                  <option value="">Assign to agent...</option>
                  {agents.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                </select>
                <button onClick={handleAssign}>Assign</button>
              </div>
            ) : null}
          </div>
        </section>
      </section>

      {task.summary ? (
        <section className="ops-panel">
          <h2>Summary</h2>
          <p className="task-summary">{task.summary}</p>
        </section>
      ) : null}

      <section className="task-detail-layout">
        <section className="ops-panel">
          <h2>Traces</h2>
          <div className="task-mini-table">
            <div className="task-mini-head">
              <span>Trace</span>
              <span>Status</span>
              <span>Spans</span>
              <span>Duration</span>
              <span>Cost</span>
            </div>
            {context.traces.map((trace) => (
              <div className="task-mini-row" key={trace.trace_id}>
                <Link to={`/traces/${encodeURIComponent(trace.trace_id)}`}>{trace.trace_id}</Link>
                <StatusPill label={trace.status} tone={trace.status === 'ok' ? 'healthy' : 'incident'} />
                <span>{trace.span_count}</span>
                <span>{trace.duration_ms}ms</span>
                <span>${trace.cost_usd.toFixed(4)}</span>
              </div>
            ))}
            {context.traces.length === 0 ? <div className="empty-state">No traces linked.</div> : null}
          </div>
        </section>

        <section className="ops-panel">
          <h2>Artifacts & Outputs</h2>
          <div className="artifact-list">
            {context.artifacts.map((artifact, index) => (
              <article className="artifact-row" key={`${artifact.event_id}:${index}`}>
                <StatusPill label={artifact.kind} tone={artifact.kind === 'artifact' ? 'trace' : 'ai'} />
                <strong>{artifact.name}</strong>
                <span>{artifact.path ?? artifact.preview ?? '-'}</span>
              </article>
            ))}
            {context.artifacts.length === 0 ? <div className="empty-state">No artifacts or output payloads detected.</div> : null}
          </div>
        </section>
      </section>

      <section className="task-detail-layout">
        <section className="ops-panel">
          <h2>Recent Logs</h2>
          <div className="task-event-list">
            {context.logs.slice(0, 8).map((event) => (
              <article className="task-event-row" key={event.id}>
                <div>
                  <StatusPill label={event.severity} tone={severityTone(event.severity)} />
                  <strong>{event.event_type}</strong>
                  <span>{safeDate(event.ts)} · {event.agent_id ?? '-'}</span>
                </div>
                {event.trace_id ? <Link to={`/traces/${encodeURIComponent(event.trace_id)}`}>trace</Link> : null}
              </article>
            ))}
            {context.logs.length === 0 ? <div className="empty-state">No logs linked.</div> : null}
          </div>
        </section>

        <section className="ops-panel">
          <h2>Audit & Decisions</h2>
          <div className="task-event-list">
            {context.decisions.map((decision) => (
              <DecisionEntryRow className="task-event-row" decision={decision} key={decision.id} />
            ))}
            {context.audit_entries.slice(0, 6).map((entry) => (
              <AuditEntryRow className="task-event-row" entry={entry} key={`audit:${entry.id}`} />
            ))}
            {context.decisions.length === 0 && context.audit_entries.length === 0 ? <div className="empty-state">No audit or decision records linked.</div> : null}
          </div>
        </section>
      </section>
    </main>
  )
}
