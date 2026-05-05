import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getMemorySummary } from '../api/memory'
import MetricCard from '../components/MetricCard'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'
import type { MemoryData } from '../types/memory'

function severityTone(severity: string): 'neutral' | 'healthy' | 'warning' | 'incident' {
  if (severity === 'critical' || severity === 'error') return 'incident'
  if (severity === 'warning') return 'warning'
  return 'neutral'
}

export default function MemoryPage() {
  const [data, setData] = useState<MemoryData | null>(null)
  const [agentFilter, setAgentFilter] = useState('')
  const [error, setError] = useState<string | null>(null)

  function load() {
    getMemorySummary({ agent_id: agentFilter.trim() || undefined })
      .then((result) => {
        setData(result)
        setError(null)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }

  useEffect(() => {
    load()
  }, [])

  const summary = data?.summary

  return (
    <main className="ops-page">
      <PageHeader
        title="Memory"
        description="Memory queries, writes, daily logs, provenance, conflicts, and promoted decisions."
        actions={<StatusPill label={error ? 'API degraded' : `${summary?.event_count ?? 0} events`} tone={error ? 'warning' : 'ai'} />}
      />

      <section className="filter-row">
        <input value={agentFilter} onChange={(event) => setAgentFilter(event.target.value)} placeholder="agent_id" />
        <button onClick={load}>Filter</button>
      </section>

      {error ? <div className="panel-warning">{error}</div> : null}

      <section className="metric-grid">
        <MetricCard label="Events" value={summary?.event_count ?? '-'} detail="Memory observability events" />
        <MetricCard label="Queries" value={summary?.query_count ?? '-'} detail="Recall/search/read" />
        <MetricCard label="Writes" value={summary?.write_count ?? '-'} detail="Structured memory writes" />
        <MetricCard label="Daily logs" value={summary?.daily_log_count ?? '-'} detail="Workspace Markdown updates" />
        <MetricCard label="Conflicts" value={summary?.conflict_count ?? '-'} detail="Duplicates or conflicts" tone={summary?.conflict_count ? 'warning' : 'neutral'} />
        <MetricCard label="Promotions" value={summary?.decision_promotions ?? '-'} detail="Decisions promoted to memory" />
      </section>

      <section className="memory-layout">
        <section className="ops-panel">
          <h2>Memory Events</h2>
          <div className="memory-table">
            <div className="memory-table-head">
              <span>Time</span>
              <span>Kind</span>
              <span>Agent</span>
              <span>Domain</span>
              <span>Key</span>
              <span>Trace</span>
            </div>
            {(data?.events ?? []).map((event) => (
              <div className="memory-table-row" key={event.id}>
                <span>{new Date(event.ts).toLocaleString()}</span>
                <span><StatusPill label={event.kind} tone={severityTone(event.severity)} /></span>
                <span>{event.agent_id ? <Link to={`/agents/${encodeURIComponent(event.agent_id)}`}>{event.agent_id}</Link> : '-'}</span>
                <span>{event.domain ?? event.scope ?? '-'}</span>
                <span>{event.key ?? '-'}</span>
                <span>{event.trace_id ? <Link to={`/traces/${encodeURIComponent(event.trace_id)}`}>{event.trace_id}</Link> : '-'}</span>
              </div>
            ))}
            {!error && (data?.events.length ?? 0) === 0 ? <div className="empty-state">No memory events recorded.</div> : null}
          </div>
        </section>

        <section className="ops-panel">
          <h2>Promoted Decisions</h2>
          <div className="memory-decision-list">
            {(data?.decisions ?? []).map((decision) => (
              <article className="memory-decision" key={decision.id}>
                <StatusPill label={decision.status} tone={decision.status === 'approved' ? 'healthy' : 'warning'} />
                <strong>{decision.title}</strong>
                <p>{decision.summary}</p>
                <span>{decision.agent_id} · {new Date(decision.ts).toLocaleString()}</span>
              </article>
            ))}
            {!error && (data?.decisions.length ?? 0) === 0 ? <div className="empty-state">No memory promotion decisions recorded.</div> : null}
          </div>
        </section>
      </section>
    </main>
  )
}
