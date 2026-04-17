import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { listAgents, AgentInfo, restartAgent } from '../api/agents'
import { useAuth } from '../context/AuthContext'

const STATUS_COLORS: Record<string, string> = {
  running: 'bg-green-500',
  stopped: 'bg-red-500',
  unknown: 'bg-gray-500',
}

function AgentCard({ agent, onRestart, isAdmin }: {
  agent: AgentInfo
  onRestart: (id: string) => void
  isAdmin: boolean
}) {
  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-5 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <Link to={`/agents/${agent.id}`} className="text-lg font-semibold hover:text-blue-400 transition-colors">
          {agent.name}
        </Link>
        <span className={`w-2.5 h-2.5 rounded-full ${STATUS_COLORS[agent.status] ?? 'bg-gray-500'}`} title={agent.status} />
      </div>
      <p className="text-sm text-gray-400">{agent.role}</p>
      <div className="text-xs text-gray-500 space-y-1">
        <div>Port: {agent.port}</div>
        <div>Health: <span className={agent.health === 'ok' ? 'text-green-400' : 'text-yellow-400'}>{agent.health}</span></div>
        {agent.uptime_seconds != null && (
          <div>Uptime: {Math.floor(agent.uptime_seconds / 60)}m</div>
        )}
        {agent.context_usage && (
          <div>Context: {agent.context_usage.input_tokens.toLocaleString()} in / {agent.context_usage.output_tokens.toLocaleString()} out</div>
        )}
      </div>
      {isAdmin && (
        <button
          onClick={() => onRestart(agent.id)}
          className="mt-1 text-xs px-3 py-1.5 rounded bg-gray-800 hover:bg-gray-700 transition-colors text-gray-300"
        >
          Restart
        </button>
      )}
    </div>
  )
}

export default function AgentsPage() {
  const { isAdmin } = useAuth()
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    listAgents()
      .then(setAgents)
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

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-6">Agents</h1>
      {loading && <p className="text-gray-400">Loading…</p>}
      {error && <p className="text-red-400">{error}</p>}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {agents.map(a => (
          <AgentCard key={a.id} agent={a} onRestart={handleRestart} isAdmin={isAdmin} />
        ))}
      </div>
    </div>
  )
}
