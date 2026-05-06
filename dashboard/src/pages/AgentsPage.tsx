import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { listAgents, type AgentInfo, restartAgent } from '../api/agents'
import MetricCard from '../components/MetricCard'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'
import { useAuth } from '../context/AuthContext'

function statusTone(status: string): 'healthy' | 'warning' | 'incident' | 'neutral' {
  if (status === 'running') return 'healthy'
  if (status === 'stopped') return 'incident'
  if (status === 'unknown') return 'warning'
  return 'neutral'
}

function healthTone(health: string): 'healthy' | 'warning' | 'incident' | 'neutral' {
  if (health === 'ok') return 'healthy'
  if (health === 'error' || health === 'offline') return 'incident'
  if (health === 'unknown') return 'neutral'
  return 'warning'
}

function AgentCard({ agent, onRestart, isAdmin }: {
  agent: AgentInfo
  onRestart: (id: string) => void
  isAdmin: boolean
}) {
  return (
    <article className="agent-card">
      <header>
        <div>
          <Link to={agent.links?.detail ?? `/agents/${encodeURIComponent(agent.id)}`}>{agent.name}</Link>
          <span>{agent.role}</span>
        </div>
        <StatusPill label={agent.status} tone={statusTone(agent.status)} />
      </header>

      <div className="agent-card-meta">
        <span>:{agent.port}</span>
        <StatusPill label={agent.health} tone={healthTone(agent.health)} />
        <span>{agent.workspace || '-'}</span>
      </div>

      <div className="agent-chip-list">
        {agent.domains.slice(0, 4).map((domain) => <StatusPill key={domain} label={domain} tone="network" />)}
        {agent.domains.length > 4 ? <StatusPill label={`+${agent.domains.length - 4}`} /> : null}
      </div>

      <div className="agent-card-actions">
        <Link to={agent.links?.detail ?? `/agents/${encodeURIComponent(agent.id)}`}>Detail</Link>
        <Link to={agent.links?.chat ?? `/agents/${encodeURIComponent(agent.id)}/chat`}>Chat</Link>
        <Link to={agent.links?.cockpit ?? `/agents/${encodeURIComponent(agent.id)}/cockpit`}>Cockpit</Link>
        <Link to={`/traces?agent_id=${encodeURIComponent(agent.id)}`}>Traces</Link>
        <Link to={`/logs?agent_id=${encodeURIComponent(agent.id)}`}>Logs</Link>
        {isAdmin ? <button onClick={() => onRestart(agent.id)}>Restart</button> : null}
      </div>
    </article>
  )
}

export default function AgentsPage() {
  const { isAdmin } = useAuth()
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    listAgents()
      .then((result) => {
        setAgents(result)
        setError('')
      })
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
    const interval = setInterval(load, 15_000)
    return () => clearInterval(interval)
  }, [load])

  async function handleRestart(id: string) {
    await restartAgent(id)
    setTimeout(load, 1500)
  }

  const filtered = agents.filter((agent) => {
    const needle = query.trim().toLowerCase()
    if (!needle) return true
    return [
      agent.id,
      agent.name,
      agent.role,
      agent.workspace,
      ...agent.domains,
      ...agent.capabilities,
    ].some((value) => value.toLowerCase().includes(needle))
  })

  const running = agents.filter(agent => agent.status === 'running').length
  const stopped = agents.filter(agent => agent.status === 'stopped').length
  const degraded = agents.filter(agent => agent.health !== 'ok' && agent.health !== 'unknown').length
  const capabilities = new Set(agents.flatMap(agent => agent.capabilities)).size
  const domains = new Set(agents.flatMap(agent => agent.domains)).size

  return (
    <main className="ops-page">
      <PageHeader
        title="Agent Fleet"
        description="Operational roster for every JarvisOS agent with direct links into chat, cockpit, traces, logs, tasks, memory, costs, and plugins."
        actions={<StatusPill label={error ? 'API degraded' : `${agents.length} agents`} tone={error ? 'warning' : 'trace'} />}
      />

      {error ? <div className="panel-warning">{error}</div> : null}

      <section className="metric-grid">
        <MetricCard label="Total" value={agents.length} detail="Registered agents" />
        <MetricCard label="Running" value={running} detail="Supervisor state" tone={running ? 'healthy' : 'neutral'} />
        <MetricCard label="Stopped" value={stopped} detail="Requires attention" tone={stopped ? 'incident' : 'neutral'} />
        <MetricCard label="Degraded" value={degraded} detail="Health check issues" tone={degraded ? 'warning' : 'neutral'} />
        <MetricCard label="Capabilities" value={capabilities} detail="Unique skills" />
        <MetricCard label="Domains" value={domains} detail="Operational scopes" />
      </section>

      <section className="filter-row agent-filter-row">
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="filter agent, role, domain, capability" />
        <button onClick={load} disabled={loading}>{loading ? 'Loading' : 'Refresh'}</button>
      </section>

      <section className="agent-grid">
        {filtered.map(agent => (
          <AgentCard key={agent.id} agent={agent} onRestart={handleRestart} isAdmin={isAdmin} />
        ))}
        {!loading && filtered.length === 0 ? <div className="empty-state">No agents match this filter.</div> : null}
      </section>
    </main>
  )
}
