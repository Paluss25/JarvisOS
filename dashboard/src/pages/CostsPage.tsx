import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getCostSummary } from '../api/costs'
import MetricCard from '../components/MetricCard'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'
import type { CostGroup, CostSummary } from '../types/costs'

function money(value: number): string {
  return `$${value.toFixed(4)}`
}

function GroupTable({
  title,
  rows,
  linkTasks = false,
  linkTraces = false,
}: {
  title: string
  rows: CostGroup[]
  linkTasks?: boolean
  linkTraces?: boolean
}) {
  return (
    <section className="ops-panel">
      <h2>{title}</h2>
      <div className="cost-table">
        <div className="cost-table-head">
          <span>Key</span>
          <span>Cost</span>
          <span>Tokens</span>
          <span>In/Out</span>
          <span>Spans</span>
          <span>Duration</span>
        </div>
        {rows.map((row) => (
          <div className="cost-table-row" key={row.key}>
            <span>
              {linkTasks && row.key !== 'unknown' ? <Link to={row.links?.detail ?? `/tasks/${encodeURIComponent(row.key)}`}>{row.key}</Link>
                : linkTraces && row.key !== 'unknown' ? <Link to={row.links?.detail ?? `/costs/traces/${encodeURIComponent(row.key)}`}>{row.key}</Link>
                  : row.key}
            </span>
            <span>{money(row.cost_usd)}</span>
            <span>{row.tokens.toLocaleString()}</span>
            <span>{row.input_tokens.toLocaleString()} / {row.output_tokens.toLocaleString()}</span>
            <span>{row.span_count}</span>
            <span>{row.duration_ms.toLocaleString()}ms</span>
          </div>
        ))}
        {rows.length === 0 ? <div className="empty-state">No cost data recorded.</div> : null}
      </div>
    </section>
  )
}

export default function CostsPage() {
  const [summary, setSummary] = useState<CostSummary | null>(null)
  const [agentFilter, setAgentFilter] = useState('')
  const [taskFilter, setTaskFilter] = useState('')
  const [error, setError] = useState<string | null>(null)

  function load() {
    getCostSummary({
      agent_id: agentFilter.trim() || undefined,
      task_id: taskFilter.trim() || undefined,
    })
      .then((result) => {
        setSummary(result)
        setError(null)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }

  useEffect(() => {
    load()
  }, [])

  return (
    <main className="ops-page">
      <PageHeader
        title="Costs"
        description="Model spend, token usage, latency, and breakdowns from trace spans."
        actions={<StatusPill label={error ? 'API degraded' : `${summary?.span_count ?? 0} spans`} tone={error ? 'warning' : 'ai'} />}
      />

      <section className="filter-row">
        <input value={agentFilter} onChange={(event) => setAgentFilter(event.target.value)} placeholder="agent_id" />
        <input value={taskFilter} onChange={(event) => setTaskFilter(event.target.value)} placeholder="task_id" />
        <button onClick={load}>Filter</button>
      </section>

      {error ? <div className="panel-warning">{error}</div> : null}

      <section className="metric-grid">
        <MetricCard label="Total cost" value={summary ? money(summary.total_cost_usd) : '-'} detail="USD from spans" />
        <MetricCard label="Tokens" value={summary?.tokens.toLocaleString() ?? '-'} detail="Input + output" />
        <MetricCard label="Input" value={summary?.input_tokens.toLocaleString() ?? '-'} detail="Prompt tokens" />
        <MetricCard label="Output" value={summary?.output_tokens.toLocaleString() ?? '-'} detail="Completion tokens" />
        <MetricCard label="p95 latency" value={summary ? `${summary.p95_latency_ms}ms` : '-'} detail="Nearest-rank span latency" tone={summary?.p95_latency_ms ? 'warning' : 'neutral'} />
        <MetricCard label="Traces" value={summary?.top_traces.length ?? '-'} detail="Costed traces" />
      </section>

      <section className="cost-grid">
        <GroupTable title="Top Traces" rows={summary?.top_traces ?? []} linkTraces />
        <GroupTable title="By Agent" rows={summary?.by_agent ?? []} />
        <GroupTable title="By Model" rows={summary?.by_model ?? []} />
        <GroupTable title="By Task" rows={summary?.by_task ?? []} linkTasks />
        <GroupTable title="By Session" rows={summary?.by_session ?? []} />
      </section>
    </main>
  )
}
