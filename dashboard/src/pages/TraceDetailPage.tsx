import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getTrace } from '../api/traces'
import MetricCard from '../components/MetricCard'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'
import TraceTree from '../components/TraceTree'
import type { TraceDetail } from '../types/trace'

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
            <MetricCard label="Status" value={trace.summary.status} tone={trace.summary.status === 'ok' ? 'healthy' : 'incident'} />
            <MetricCard label="Spans" value={trace.summary.span_count} />
            <MetricCard label="Duration" value={`${trace.summary.duration_ms} ms`} />
            <MetricCard label="Cost" value={`$${trace.summary.cost_usd.toFixed(4)}`} />
          </section>

          <section className="ops-panel">
            <div className="trace-detail-meta">
              <StatusPill label={trace.summary.agent_id ?? 'no agent'} tone="ai" />
              <StatusPill label={trace.summary.session_id ?? 'no session'} tone="trace" />
              {trace.summary.task_id ? <StatusPill label={`task ${trace.summary.task_id}`} tone="network" /> : null}
            </div>
            <TraceTree spans={trace.spans} />
          </section>
        </>
      ) : !error ? (
        <div className="empty-state">Loading trace...</div>
      ) : null}
    </main>
  )
}
