import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { getActivitySummary } from '../api/activity'
import MetricCard from '../components/MetricCard'
import PageHeader from '../components/PageHeader'
import { SSEProvider, useSSE, type SSEEvent } from '../components/SSEProvider'
import StatusPill from '../components/StatusPill'
import type { ActivityItem, ActivitySummary } from '../types/activity'

function severityTone(severity: string): 'neutral' | 'healthy' | 'warning' | 'incident' | 'network' {
  if (severity === 'critical' || severity === 'error') return 'incident'
  if (severity === 'warning') return 'warning'
  if (severity === 'info') return 'network'
  return 'neutral'
}

function timeLabel(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString() : '-'
}

function compactPayload(value: unknown) {
  if (value == null) return ''
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

function ActivityRow({ item }: { item: ActivityItem }) {
  return (
    <article className="activity-row">
      <div>
        <StatusPill label={item.severity} tone={severityTone(item.severity)} />
        <strong>{item.label}</strong>
        <span>{timeLabel(item.ts)} · {item.kind} · {item.source}</span>
      </div>
      <p>{item.preview || compactPayload(item.payload)}</p>
      <nav>
        {item.links.detail ? <Link to={item.links.detail}>detail</Link> : null}
        {item.links.agent ? <Link to={item.links.agent}>agent</Link> : null}
        {item.links.chat ? <Link to={item.links.chat}>chat</Link> : null}
        {item.links.task ? <Link to={item.links.task}>task</Link> : null}
        {item.links.trace ? <Link to={item.links.trace}>trace</Link> : null}
        {item.links.audit ? <Link to={item.links.audit}>audit</Link> : null}
      </nav>
    </article>
  )
}

function LiveEventRow({ event }: { event: SSEEvent }) {
  return (
    <article className="activity-live-row">
      <strong>{event.type}</strong>
      <span>{new Date(event.ts).toLocaleTimeString()}</span>
      <p>{compactPayload(event.data)}</p>
    </article>
  )
}

function ActivityWorkspace() {
  const { events, connected } = useSSE()
  const [searchParams, setSearchParams] = useSearchParams()
  const [summary, setSummary] = useState<ActivitySummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  const filters = useMemo(() => ({
    agent_id: searchParams.get('agent_id') ?? '',
    severity: searchParams.get('severity') ?? '',
    event_type: searchParams.get('event_type') ?? '',
  }), [searchParams])

  useEffect(() => {
    getActivitySummary({
      agent_id: filters.agent_id || undefined,
      severity: filters.severity || undefined,
      event_type: filters.event_type || undefined,
      limit: 200,
    })
      .then((result) => {
        setSummary(result)
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

  const metrics = summary?.metrics

  return (
    <main className="ops-page">
      <PageHeader
        title="Activity Feed"
        description="Historical platform events, audit records, and live SSE activity with links into operational workspaces."
        actions={<StatusPill label={connected ? 'Live connected' : 'Live offline'} tone={connected ? 'healthy' : 'warning'} />}
      />

      {error ? <div className="panel-warning">{error}</div> : null}

      <section className="metric-grid">
        <MetricCard label="Activity" value={metrics?.total_count ?? '...'} detail="Events and audit" />
        <MetricCard label="Platform events" value={metrics?.platform_event_count ?? '...'} />
        <MetricCard label="Audit records" value={metrics?.audit_count ?? '...'} />
        <MetricCard label="Critical" value={metrics?.critical_count ?? '...'} tone={metrics?.critical_count ? 'incident' : 'neutral'} />
        <MetricCard label="Warnings" value={(metrics?.warning_count ?? 0) + (metrics?.error_count ?? 0)} detail="Warnings + errors" tone={(metrics?.warning_count ?? 0) + (metrics?.error_count ?? 0) ? 'warning' : 'neutral'} />
        <MetricCard label="Agents" value={metrics?.agent_count ?? '...'} detail="Active emitters" />
      </section>

      <section className="ops-panel">
        <h2>Filters</h2>
        <div className="activity-filter-grid">
          <input value={filters.agent_id} onChange={(event) => updateFilter('agent_id', event.target.value)} placeholder="agent_id" />
          <input value={filters.severity} onChange={(event) => updateFilter('severity', event.target.value)} placeholder="severity" />
          <input value={filters.event_type} onChange={(event) => updateFilter('event_type', event.target.value)} placeholder="event_type" />
        </div>
      </section>

      <section className="activity-layout">
        <section className="ops-panel">
          <h2>Historical Activity</h2>
          <div className="activity-list">
            {(summary?.items ?? []).map((item) => <ActivityRow key={`${item.kind}:${item.id}:${item.ts}`} item={item} />)}
            {summary && summary.items.length === 0 ? <div className="empty-state">No activity found.</div> : null}
          </div>
        </section>

        <aside className="ops-panel">
          <h2>Live Stream</h2>
          <div className="activity-live-list">
            {events.slice(0, 20).map((event) => <LiveEventRow key={event.id} event={event} />)}
            {events.length === 0 ? <div className="empty-state">No live events in this browser session.</div> : null}
          </div>
        </aside>
      </section>
    </main>
  )
}

export default function ActivityFeedPage() {
  return (
    <SSEProvider>
      <ActivityWorkspace />
    </SSEProvider>
  )
}
