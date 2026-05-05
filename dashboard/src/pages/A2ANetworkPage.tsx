import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { getA2ASummary } from '../api/a2a'
import MetricCard from '../components/MetricCard'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'
import type { A2AData, A2AMessage } from '../types/a2a'

function severityTone(severity: string): 'neutral' | 'healthy' | 'warning' | 'incident' {
  if (severity === 'critical' || severity === 'error') return 'incident'
  if (severity === 'warning') return 'warning'
  return 'neutral'
}

function messageLabel(message: A2AMessage): string {
  return message.message_type ?? message.event_type
}

export default function A2ANetworkPage() {
  const [data, setData] = useState<A2AData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getA2ASummary()
      .then((result) => {
        setData(result)
        setError(null)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [])

  const edges = useMemo(() => {
    const counts = new Map<string, { from: string; to: string; count: number; failures: number }>()
    for (const message of data?.messages ?? []) {
      if (!message.from_agent || !message.to_agent) continue
      const key = `${message.from_agent}->${message.to_agent}`
      const current = counts.get(key) ?? { from: message.from_agent, to: message.to_agent, count: 0, failures: 0 }
      current.count += 1
      if (message.severity === 'error' || message.severity === 'critical' || message.status === 'failed') current.failures += 1
      counts.set(key, current)
    }
    return [...counts.values()].sort((a, b) => b.count - a.count)
  }, [data])

  const summary = data?.summary

  return (
    <main className="ops-page">
      <PageHeader
        title="A2A Network"
        description="Agent-to-agent traffic, async chains, loops, and failed message warnings."
        actions={<StatusPill label={error ? 'API degraded' : `${summary?.message_count ?? 0} messages`} tone={error ? 'warning' : 'network'} />}
      />

      {error ? <div className="panel-warning">{error}</div> : null}

      <section className="metric-grid">
        <MetricCard label="Messages" value={summary?.message_count ?? '-'} detail="Latest A2A events" />
        <MetricCard label="Edges" value={summary?.edge_count ?? '-'} detail="Active agent links" tone={summary?.edge_count ? 'healthy' : 'neutral'} />
        <MetricCard label="Requests" value={summary?.request_count ?? '-'} detail="Inter-agent asks" />
        <MetricCard label="Responses" value={summary?.response_count ?? '-'} detail="Completed replies" />
        <MetricCard label="Async" value={summary?.async_count ?? '-'} detail="Fire-and-continue" tone={summary?.async_count ? 'warning' : 'neutral'} />
        <MetricCard label="Warnings" value={(summary?.failure_count ?? 0) + (summary?.loop_warnings ?? 0)} detail="Failures and loops" tone={(summary?.failure_count || summary?.loop_warnings) ? 'incident' : 'neutral'} />
      </section>

      <section className="a2a-layout">
        <section className="ops-panel">
          <h2>Network Edges</h2>
          <div className="a2a-edge-list">
            {edges.map((edge) => (
              <div className="a2a-edge-row" key={`${edge.from}->${edge.to}`}>
                <span>{edge.from}</span>
                <strong>→</strong>
                <span>{edge.to}</span>
                <StatusPill label={`${edge.count} msg`} tone={edge.failures ? 'incident' : 'network'} />
              </div>
            ))}
            {edges.length === 0 ? <div className="empty-state">No A2A edges recorded.</div> : null}
          </div>
        </section>

        <section className="ops-panel">
          <h2>Message Table</h2>
          <div className="a2a-table">
            <div className="a2a-table-head">
              <span>Time</span>
              <span>Type</span>
              <span>Route</span>
              <span>Mode</span>
              <span>Hop</span>
              <span>Trace</span>
              <span>Task</span>
            </div>
            {(data?.messages ?? []).map((message) => (
              <div className="a2a-table-row" key={message.id}>
                <span>{new Date(message.ts).toLocaleString()}</span>
                <span><StatusPill label={messageLabel(message)} tone={severityTone(message.severity)} /></span>
                <span>{message.from_agent ?? '-'} → {message.to_agent ?? '-'}</span>
                <span>{message.mode}</span>
                <span>{message.hop_count}/{message.max_hops}</span>
                <span>{message.trace_id ? <Link to={`/traces/${encodeURIComponent(message.trace_id)}`}>{message.trace_id}</Link> : '-'}</span>
                <span>{message.task_id ? <Link to={`/tasks/${encodeURIComponent(message.task_id)}`}>{message.task_id}</Link> : '-'}</span>
              </div>
            ))}
            {!error && (data?.messages.length ?? 0) === 0 ? <div className="empty-state">No A2A messages recorded.</div> : null}
          </div>
        </section>
      </section>
    </main>
  )
}
