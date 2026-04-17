import { useState, useEffect, useCallback } from 'react'
import { apiGet } from '../api/client'

interface AuditEntry {
  id: number
  ts: string
  category: string
  agent_id: string | null
  user_id: string | null
  action: string
  source: string
  detail: Record<string, unknown>
}

interface AuditResponse {
  items: AuditEntry[]
  total: number
}

const CATEGORIES = ['', 'agent', 'platform', 'security', 'memory', 'task']

export default function AuditLogPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(0)
  const [category, setCategory] = useState('')
  const [agentId, setAgentId] = useState('')
  const [loading, setLoading] = useState(false)
  const limit = 50

  const load = useCallback(() => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(page * limit) })
    if (category) params.set('category', category)
    if (agentId) params.set('agent_id', agentId)
    setLoading(true)
    apiGet<AuditResponse>(`/audit?${params}`)
      .then(r => { setEntries(r.items ?? []); setTotal(r.total ?? 0) })
      .catch(() => setEntries([]))
      .finally(() => setLoading(false))
  }, [category, agentId, page])

  useEffect(() => { load() }, [load])

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-4">Audit Log</h1>

      <div className="flex gap-3 mb-4 flex-wrap">
        <select
          value={category}
          onChange={e => { setCategory(e.target.value); setPage(0) }}
          className="px-3 py-1.5 rounded bg-gray-800 text-white border border-gray-700 text-sm focus:outline-none"
        >
          {CATEGORIES.map(c => <option key={c} value={c}>{c || 'All categories'}</option>)}
        </select>
        <input
          className="px-3 py-1.5 rounded bg-gray-800 text-white border border-gray-700 text-sm focus:outline-none focus:border-blue-500"
          placeholder="Agent ID"
          value={agentId}
          onChange={e => { setAgentId(e.target.value); setPage(0) }}
        />
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left">
          <thead>
            <tr className="border-b border-gray-800 text-gray-400 text-xs">
              <th className="py-2 pr-4">Time</th>
              <th className="py-2 pr-4">Category</th>
              <th className="py-2 pr-4">Action</th>
              <th className="py-2 pr-4">Agent</th>
              <th className="py-2 pr-4">Source</th>
              <th className="py-2">Detail</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={6} className="py-4 text-gray-500">Loading…</td></tr>
            )}
            {!loading && entries.length === 0 && (
              <tr><td colSpan={6} className="py-4 text-gray-500">No entries.</td></tr>
            )}
            {entries.map(e => (
              <tr key={e.id} className="border-b border-gray-900 hover:bg-gray-900 transition-colors">
                <td className="py-2 pr-4 text-gray-400 text-xs whitespace-nowrap">{new Date(e.ts).toLocaleString()}</td>
                <td className="py-2 pr-4 text-xs">{e.category}</td>
                <td className="py-2 pr-4 font-mono text-xs">{e.action}</td>
                <td className="py-2 pr-4 text-xs text-gray-400">{e.agent_id ?? '—'}</td>
                <td className="py-2 pr-4 text-xs text-gray-400">{e.source}</td>
                <td className="py-2 text-xs text-gray-500 font-mono truncate max-w-xs">{JSON.stringify(e.detail)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex gap-2 mt-4">
        <button
          disabled={page === 0}
          onClick={() => setPage(p => p - 1)}
          className="px-3 py-1.5 text-sm rounded bg-gray-800 hover:bg-gray-700 disabled:opacity-40 transition-colors"
        >
          Prev
        </button>
        <span className="px-3 py-1.5 text-sm text-gray-400">{page * limit + 1}–{Math.min((page + 1) * limit, total)} of {total}</span>
        <button
          disabled={(page + 1) * limit >= total}
          onClick={() => setPage(p => p + 1)}
          className="px-3 py-1.5 text-sm rounded bg-gray-800 hover:bg-gray-700 disabled:opacity-40 transition-colors"
        >
          Next
        </button>
      </div>
    </div>
  )
}
