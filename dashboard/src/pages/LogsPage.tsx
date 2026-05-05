import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listLogs } from '../api/logs'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'
import type { LogEvent } from '../types/logs'

export default function LogsPage() {
  const [events, setEvents] = useState<LogEvent[]>([])
  const [traceFilter, setTraceFilter] = useState('')
  const [agentFilter, setAgentFilter] = useState('')
  const [error, setError] = useState<string | null>(null)

  function load() {
    listLogs({
      trace_id: traceFilter.trim() || undefined,
      agent_id: agentFilter.trim() || undefined,
    })
      .then(setEvents)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }

  useEffect(() => {
    load()
  }, [])

  return (
    <main className="ops-page">
      <PageHeader
        title="Logs"
        description="Normalized JarvisOS platform events filtered by agent, trace, task, severity, and source."
        actions={<StatusPill label={error ? 'API degraded' : `${events.length} events`} tone={error ? 'warning' : 'trace'} />}
      />

      <section className="filter-row">
        <input value={agentFilter} onChange={(event) => setAgentFilter(event.target.value)} placeholder="agent_id" />
        <input value={traceFilter} onChange={(event) => setTraceFilter(event.target.value)} placeholder="trace_id" />
        <button onClick={load}>Filter</button>
      </section>

      {error ? <div className="panel-warning">{error}</div> : null}

      <section className="ops-panel">
        <div className="log-table">
          <div className="log-table-head">
            <span>Time</span>
            <span>Severity</span>
            <span>Type</span>
            <span>Agent</span>
            <span>Trace</span>
            <span>Source</span>
          </div>
          {events.map((event) => (
            <div className="log-table-row" key={event.id}>
              <span>{new Date(event.ts).toLocaleString()}</span>
              <span>{event.severity}</span>
              <span>{event.event_type}</span>
              <span>{event.agent_id ?? '-'}</span>
              <span>{event.trace_id ? <Link to={`/traces/${encodeURIComponent(event.trace_id)}`}>{event.trace_id}</Link> : '-'}</span>
              <span>{event.source}</span>
            </div>
          ))}
          {!error && events.length === 0 ? <div className="empty-state">No events found.</div> : null}
        </div>
      </section>
    </main>
  )
}
