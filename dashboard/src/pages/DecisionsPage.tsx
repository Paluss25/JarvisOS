import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { listDecisions } from '../api/decisions'
import MetricCard from '../components/MetricCard'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'
import type { Decision } from '../types/decisions'

function statusTone(status: string): 'neutral' | 'healthy' | 'warning' | 'incident' {
  if (status === 'approved') return 'healthy'
  if (status === 'rejected') return 'incident'
  if (status === 'proposed') return 'warning'
  return 'neutral'
}

function timeLabel(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString() : '-'
}

export default function DecisionsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [decisions, setDecisions] = useState<Decision[]>([])
  const [error, setError] = useState<string | null>(null)

  const filters = useMemo(() => ({
    agent_id: searchParams.get('agent_id') ?? '',
    status: searchParams.get('status') ?? '',
    trace_id: searchParams.get('trace_id') ?? '',
    task_id: searchParams.get('task_id') ?? '',
  }), [searchParams])

  useEffect(() => {
    listDecisions({
      agent_id: filters.agent_id || undefined,
      status: filters.status || undefined,
      trace_id: filters.trace_id || undefined,
      task_id: filters.task_id || undefined,
      limit: 200,
    })
      .then((result) => {
        setDecisions(result)
        setError(null)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [filters])

  function updateFilter(key: keyof typeof filters, value: string) {
    const next = new URLSearchParams(searchParams)
    if (value) next.set(key, value)
    else next.delete(key)
    setSearchParams(next)
  }

  const approved = decisions.filter((decision) => decision.status === 'approved').length
  const proposed = decisions.filter((decision) => decision.status === 'proposed').length
  const rejected = decisions.filter((decision) => decision.status === 'rejected').length
  const evidence = decisions.reduce((count, decision) => count + decision.evidence.length, 0)

  return (
    <main className="ops-page">
      <PageHeader
        title="Decision Ledger"
        description="Agent decisions, saved chat replies, approvals, evidence, and linked operational context."
        actions={<StatusPill label={error ? 'API degraded' : `${decisions.length} records`} tone={error ? 'warning' : 'ai'} />}
      />

      {error ? <div className="panel-warning">{error}</div> : null}

      <section className="metric-grid">
        <MetricCard label="Decisions" value={decisions.length} detail="Current result set" />
        <MetricCard label="Approved" value={approved} tone={approved ? 'healthy' : 'neutral'} />
        <MetricCard label="Proposed" value={proposed} tone={proposed ? 'warning' : 'neutral'} />
        <MetricCard label="Rejected" value={rejected} tone={rejected ? 'incident' : 'neutral'} />
        <MetricCard label="Evidence" value={evidence} detail="Attached records" />
      </section>

      <section className="ops-panel">
        <h2>Filters</h2>
        <div className="decision-filter-grid">
          <input value={filters.agent_id} onChange={(event) => updateFilter('agent_id', event.target.value)} placeholder="agent_id" />
          <input value={filters.status} onChange={(event) => updateFilter('status', event.target.value)} placeholder="status" />
          <input value={filters.task_id} onChange={(event) => updateFilter('task_id', event.target.value)} placeholder="task_id" />
          <input value={filters.trace_id} onChange={(event) => updateFilter('trace_id', event.target.value)} placeholder="trace_id" />
        </div>
      </section>

      <section className="ops-panel">
        <h2>Ledger</h2>
        <div className="decision-ledger-table">
          <div className="decision-ledger-head">
            <span>Time</span>
            <span>Status</span>
            <span>Type</span>
            <span>Decision</span>
            <span>Agent</span>
            <span>Context</span>
          </div>
          {decisions.map((decision) => (
            <div className="decision-ledger-row" key={decision.id}>
              <span>{timeLabel(decision.ts)}</span>
              <span><StatusPill label={decision.status} tone={statusTone(decision.status)} /></span>
              <span>{decision.decision_type}</span>
              <span>
                <Link to={decision.links?.detail ?? `/decisions/${encodeURIComponent(decision.id)}`}>{decision.title}</Link>
                <small>{decision.summary}</small>
              </span>
              <span>{decision.agent_id ? <Link to={`/agents/${encodeURIComponent(decision.agent_id)}`}>{decision.agent_id}</Link> : '-'}</span>
              <span className="decision-context-actions">
                {decision.task_id ? <Link to={`/tasks/${encodeURIComponent(decision.task_id)}`}>task</Link> : null}
                {decision.trace_id ? <Link to={`/traces/${encodeURIComponent(decision.trace_id)}`}>trace</Link> : null}
              </span>
            </div>
          ))}
          {decisions.length === 0 ? <div className="empty-state">No decisions found.</div> : null}
        </div>
      </section>
    </main>
  )
}
