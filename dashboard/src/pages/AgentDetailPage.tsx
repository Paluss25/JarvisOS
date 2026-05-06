import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getAgent, type AgentInfo, restartAgent } from '../api/agents'
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

function QuickLink({ to, label }: { to: string; label: string }) {
  return <Link className="agent-quick-link" to={to}>{label}</Link>
}

export default function AgentDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { isAdmin } = useAuth()
  const [agent, setAgent] = useState<AgentInfo | null>(null)
  const [error, setError] = useState<string | null>(null)

  function load() {
    if (!id) return
    getAgent(id)
      .then((result) => {
        setAgent(result)
        setError(null)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }

  useEffect(() => {
    load()
  }, [id])

  if (!agent) {
    return <main className="ops-page empty-state">{error ?? 'Loading agent.'}</main>
  }

  async function handleRestart() {
    if (!agent) return
    await restartAgent(agent.id)
    setTimeout(load, 1500)
  }

  return (
    <main className="ops-page">
      <PageHeader
        title={agent.name}
        description={`${agent.role} · ${agent.workspace || 'workspace unknown'}`}
        actions={
          <>
            <StatusPill label={agent.status} tone={statusTone(agent.status)} />
            <StatusPill label={agent.health} tone={healthTone(agent.health)} />
            {isAdmin ? <button className="ops-button" onClick={handleRestart}>Restart</button> : null}
          </>
        }
      />

      {error ? <div className="panel-warning">{error}</div> : null}

      <section className="metric-grid">
        <MetricCard label="Port" value={`:${agent.port}`} detail={agent.supervisord_state ?? 'Supervisor unknown'} />
        <MetricCard label="Domains" value={agent.domains.length} detail="Operational scopes" />
        <MetricCard label="Capabilities" value={agent.capabilities.length} detail="Enabled skills" />
        <MetricCard label="Context input" value={agent.context_usage?.input_tokens.toLocaleString() ?? '-'} detail="Latest reported tokens" />
        <MetricCard label="Context output" value={agent.context_usage?.output_tokens.toLocaleString() ?? '-'} detail="Latest reported tokens" />
        <MetricCard label="Uptime" value={agent.uptime_seconds != null ? `${Math.floor(agent.uptime_seconds / 60)}m` : '-'} detail="Runtime reported" />
      </section>

      <section className="agent-detail-layout">
        <section className="ops-panel">
          <h2>Operational Links</h2>
          <div className="agent-link-grid">
            <QuickLink to={`/agents/${encodeURIComponent(agent.id)}/chat`} label="Chat" />
            <QuickLink to={`/agents/${encodeURIComponent(agent.id)}/cockpit`} label="Cockpit" />
            <QuickLink to={`/tasks?agent_id=${encodeURIComponent(agent.id)}`} label="Tasks" />
            <QuickLink to={`/traces?agent_id=${encodeURIComponent(agent.id)}`} label="Traces" />
            <QuickLink to={`/logs?agent_id=${encodeURIComponent(agent.id)}`} label="Logs" />
            <QuickLink to={`/costs?agent_id=${encodeURIComponent(agent.id)}`} label="Costs" />
            <QuickLink to={`/memory?agent_id=${encodeURIComponent(agent.id)}`} label="Memory" />
            <QuickLink to={`/plugins?agent_id=${encodeURIComponent(agent.id)}`} label="Plugins" />
            <QuickLink to={`/audit?agent_id=${encodeURIComponent(agent.id)}`} label="Audit" />
          </div>
        </section>

        <section className="ops-panel">
          <h2>Identity</h2>
          <div className="agent-identity-grid">
            <span>ID</span><strong>{agent.id}</strong>
            <span>Role</span><strong>{agent.role}</strong>
            <span>Workspace</span><strong>{agent.workspace || '-'}</strong>
            <span>Supervisor</span><strong>{agent.supervisord_state ?? '-'}</strong>
          </div>
        </section>
      </section>

      <section className="agent-detail-layout">
        <section className="ops-panel">
          <h2>Domains</h2>
          <div className="agent-chip-list">
            {agent.domains.map((domain) => <StatusPill key={domain} label={domain} tone="network" />)}
            {agent.domains.length === 0 ? <div className="empty-state">No domains configured.</div> : null}
          </div>
        </section>

        <section className="ops-panel">
          <h2>Capabilities</h2>
          <div className="agent-chip-list">
            {agent.capabilities.map((capability) => <StatusPill key={capability} label={capability} tone="ai" />)}
            {agent.capabilities.length === 0 ? <div className="empty-state">No capabilities configured.</div> : null}
          </div>
        </section>
      </section>
    </main>
  )
}
