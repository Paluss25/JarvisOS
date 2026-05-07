import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import MetricCard from '../components/MetricCard'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'
import { listAudit } from '../api/audit'
import type { AuditEntry } from '../types/audit'

const CATEGORIES = ['', 'agent', 'platform', 'security', 'memory', 'task']

function categoryTone(category: string): 'neutral' | 'healthy' | 'warning' | 'incident' | 'trace' | 'ai' | 'network' {
  if (category === 'security') return 'incident'
  if (category === 'task') return 'warning'
  if (category === 'memory') return 'ai'
  if (category === 'agent') return 'trace'
  if (category === 'platform') return 'network'
  return 'neutral'
}

function detailPreview(detail: Record<string, unknown>) {
  const preview = JSON.stringify(detail ?? {})
  return preview.length > 150 ? `${preview.slice(0, 147)}...` : preview
}

export default function AuditLogPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(0)
  const [category, setCategory] = useState('')
  const [agentId, setAgentId] = useState('')
  const [action, setAction] = useState('')
  const [source, setSource] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const limit = 50

  const load = useCallback(() => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(page * limit) })
    if (category) params.set('category', category)
    if (agentId.trim()) params.set('agent_id', agentId.trim())
    if (action.trim()) params.set('action', action.trim())
    if (source.trim()) params.set('source', source.trim())
    setLoading(true)
    listAudit(params)
      .then((r) => {
        setEntries(r.items ?? [])
        setTotal(r.total ?? 0)
        setError(null)
      })
      .catch((err) => {
        setEntries([])
        setTotal(0)
        setError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => setLoading(false))
  }, [category, agentId, action, source, page])

  useEffect(() => { load() }, [load])

  const visibleSecurity = entries.filter(entry => entry.category === 'security').length
  const visibleTask = entries.filter(entry => entry.category === 'task').length
  const visibleAgent = entries.filter(entry => entry.agent_id).length
  const visibleSources = new Set(entries.map(entry => entry.source).filter(Boolean)).size
  const rangeStart = total === 0 ? 0 : page * limit + 1
  const rangeEnd = Math.min((page + 1) * limit, total)

  return (
    <main className="ops-page">
      <PageHeader
        title="Audit Log"
        description="Governance trail for agent actions, platform events, security findings, memory writes, and task operations."
        actions={<StatusPill label={error ? 'API degraded' : `${total} records`} tone={error ? 'warning' : 'network'} />}
      />

      <section className="filter-row audit-filter-row">
        <select
          value={category}
          onChange={e => { setCategory(e.target.value); setPage(0) }}
        >
          {CATEGORIES.map(c => <option key={c} value={c}>{c || 'All categories'}</option>)}
        </select>
        <input
          placeholder="agent_id"
          value={agentId}
          onChange={e => { setAgentId(e.target.value); setPage(0) }}
        />
        <input
          placeholder="action"
          value={action}
          onChange={e => { setAction(e.target.value); setPage(0) }}
        />
        <input
          placeholder="source"
          value={source}
          onChange={e => { setSource(e.target.value); setPage(0) }}
        />
        <button onClick={load} disabled={loading}>{loading ? 'Loading' : 'Filter'}</button>
      </section>

      {error ? <div className="panel-warning">{error}</div> : null}

      <section className="metric-grid">
        <MetricCard label="Total records" value={total} detail="Rows matching filters" />
        <MetricCard label="Visible page" value={entries.length} detail={`${rangeStart}-${rangeEnd}`} />
        <MetricCard label="Security" value={visibleSecurity} detail="Visible security rows" tone={visibleSecurity ? 'incident' : 'neutral'} />
        <MetricCard label="Task ops" value={visibleTask} detail="Visible task rows" tone={visibleTask ? 'warning' : 'neutral'} />
        <MetricCard label="Agent-linked" value={visibleAgent} detail="Rows tied to agents" />
        <MetricCard label="Sources" value={visibleSources} detail="Distinct visible sources" />
      </section>

      <section className="ops-panel">
        <h2>Entries</h2>
        <div className="audit-table">
          <div className="audit-table-head">
            <span>Time</span>
            <span>Category</span>
            <span>Action</span>
            <span>Agent</span>
            <span>User</span>
            <span>Source</span>
            <span>Detail</span>
          </div>
          {loading ? <div className="empty-state">Loading audit entries.</div> : null}
          {!loading && entries.length === 0 ? <div className="empty-state">No audit entries match these filters.</div> : null}
          {!loading && entries.map(e => (
            <div key={e.id} className="audit-table-row">
              <span>{new Date(e.ts).toLocaleString()}</span>
              <span><StatusPill label={e.category} tone={categoryTone(e.category)} /></span>
              <strong><Link to={`/audit/${e.id}`}>{e.action}</Link></strong>
              <span>{e.agent_id ? <Link to={`/agents/${encodeURIComponent(e.agent_id)}`}>{e.agent_id}</Link> : '-'}</span>
              <span>{e.user_id ?? '-'}</span>
              <span>{e.source ?? '-'}</span>
              <code>{detailPreview(e.detail)}</code>
            </div>
          ))}
        </div>
      </section>

      <nav className="audit-pagination">
        <button
          disabled={page === 0}
          onClick={() => setPage(p => p - 1)}
        >
          Prev
        </button>
        <span>{rangeStart}-{rangeEnd} of {total}</span>
        <button
          disabled={(page + 1) * limit >= total}
          onClick={() => setPage(p => p + 1)}
        >
          Next
        </button>
      </nav>
    </main>
  )
}
