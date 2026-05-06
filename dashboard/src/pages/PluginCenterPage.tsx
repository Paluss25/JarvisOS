import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getPluginRegistry } from '../api/plugins'
import MetricCard from '../components/MetricCard'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'
import type { PluginRegistryData } from '../types/plugins'

function toneForStatus(status: string): 'neutral' | 'healthy' | 'warning' | 'incident' {
  if (status === 'ok' || status === 'success') return 'healthy'
  if (status === 'failed' || status === 'error') return 'incident'
  if (status === 'unknown') return 'neutral'
  return 'warning'
}

export default function PluginCenterPage() {
  const [data, setData] = useState<PluginRegistryData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getPluginRegistry()
      .then((result) => {
        setData(result)
        setError(null)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [])

  const summary = data?.summary

  return (
    <main className="ops-page">
      <PageHeader
        title="Plugin Center"
        description="Read-only registry of agent capabilities, workers, observed tools, and skills."
        actions={<StatusPill label={error ? 'API degraded' : 'read-only'} tone={error ? 'warning' : 'network'} />}
      />

      {error ? <div className="panel-warning">{error}</div> : null}

      <section className="metric-grid">
        <MetricCard label="Agents" value={summary?.agent_count ?? '-'} detail="Registry agents" />
        <MetricCard label="Workers" value={summary?.worker_count ?? '-'} detail="Worker runtimes" />
        <MetricCard label="Capabilities" value={summary?.capability_count ?? '-'} detail="Unique capabilities" />
        <MetricCard label="Observed tools" value={summary?.observed_tool_count ?? '-'} detail="Recent tool/skill events" />
        <MetricCard label="Tool events" value={summary?.tool_event_count ?? '-'} detail="Observed tool calls" />
        <MetricCard label="Skill events" value={summary?.skill_event_count ?? '-'} detail="Observed skill usage" />
      </section>

      <section className="plugin-layout">
        <section className="ops-panel">
          <h2>Capabilities</h2>
          <div className="plugin-table">
            <div className="plugin-table-head">
              <span>Name</span>
              <span>Agents</span>
              <span>Domains</span>
            </div>
            {(data?.capabilities ?? []).map((capability) => (
              <div className="plugin-table-row" key={capability.name}>
                <strong>{capability.name}</strong>
                <span>{capability.agents.map((agent) => <Link key={agent} to={`/agents/${agent}`}>{agent}</Link>)}</span>
                <span>{capability.domains.join(', ') || '-'}</span>
              </div>
            ))}
            {(data?.capabilities.length ?? 0) === 0 ? <div className="empty-state">No capabilities registered.</div> : null}
          </div>
        </section>

        <section className="ops-panel">
          <h2>Workers</h2>
          <div className="worker-list">
            {(data?.workers ?? []).map((worker) => (
              <article className="worker-card" key={worker.id}>
                <StatusPill label={`:${worker.port}`} tone="network" />
                <strong>{worker.id}</strong>
                <p>{worker.description}</p>
                <span>{worker.module}</span>
              </article>
            ))}
            {(data?.workers.length ?? 0) === 0 ? <div className="empty-state">No workers registered.</div> : null}
          </div>
        </section>
      </section>

      <section className="ops-panel">
        <h2>Observed Tools & Skills</h2>
        <div className="observed-tool-table">
          <div className="observed-tool-head">
            <span>Name</span>
            <span>Kind</span>
            <span>Agent</span>
            <span>Status</span>
            <span>Event</span>
            <span>Duration</span>
          </div>
          {(data?.observed_tools ?? []).map((tool, index) => (
            <div className="observed-tool-row" key={`${tool.name}:${tool.agent_id}:${index}`}>
              <strong>{tool.name}</strong>
              <span>{tool.kind}</span>
              <span>{tool.agent_id ? <Link to={`/agents/${tool.agent_id}`}>{tool.agent_id}</Link> : '-'}</span>
              <span><StatusPill label={tool.status} tone={toneForStatus(tool.status)} /></span>
              <span>{tool.event_type}</span>
              <span>{tool.duration_ms ? `${tool.duration_ms}ms` : '-'}</span>
            </div>
          ))}
          {(data?.observed_tools.length ?? 0) === 0 ? <div className="empty-state">No observed tool or skill events.</div> : null}
        </div>
      </section>
    </main>
  )
}
