import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listTraces } from '../api/traces'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'
import type { TraceSummary } from '../types/trace'

export default function TraceExplorerPage() {
  const [traces, setTraces] = useState<TraceSummary[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listTraces()
      .then(setTraces)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [])

  return (
    <main className="ops-page">
      <PageHeader
        title="Trace Explorer"
        description="Inspect agent runs, tool calls, model usage, cost, and execution status."
        actions={<StatusPill label={error ? 'API degraded' : `${traces.length} traces`} tone={error ? 'warning' : 'trace'} />}
      />

      {error ? <div className="panel-warning">{error}</div> : null}

      <section className="ops-panel">
        <div className="trace-table">
          <div className="trace-table-head">
            <span>Trace</span>
            <span>Agent</span>
            <span>Status</span>
            <span>Spans</span>
            <span>Duration</span>
            <span>Tokens</span>
            <span>Cost</span>
          </div>
          {traces.map((trace) => (
            <Link className="trace-table-row" to={`/traces/${encodeURIComponent(trace.trace_id)}`} key={trace.trace_id}>
              <span>{trace.trace_id}</span>
              <span>{trace.agent_id ?? '-'}</span>
              <span>{trace.status}</span>
              <span>{trace.span_count}</span>
              <span>{trace.duration_ms} ms</span>
              <span>{trace.input_tokens + trace.output_tokens}</span>
              <span>${trace.cost_usd.toFixed(4)}</span>
            </Link>
          ))}
          {!error && traces.length === 0 ? <div className="empty-state">No traces found.</div> : null}
        </div>
      </section>
    </main>
  )
}
