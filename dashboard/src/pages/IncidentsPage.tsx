import { FormEvent, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { createIncident, listIncidents } from '../api/logs'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'
import type { LogEvent } from '../types/logs'

export default function IncidentsPage() {
  const [incidents, setIncidents] = useState<LogEvent[]>([])
  const [title, setTitle] = useState('')
  const [severity, setSeverity] = useState('warning')
  const [traceId, setTraceId] = useState('')
  const [error, setError] = useState<string | null>(null)

  function load() {
    listIncidents()
      .then(setIncidents)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }

  useEffect(() => {
    load()
  }, [])

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    try {
      await createIncident({
        title,
        severity,
        trace_id: traceId.trim() || undefined,
      })
      setTitle('')
      setTraceId('')
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <main className="ops-page">
      <PageHeader
        title="Incidents"
        description="Operational incident records tied to JarvisOS events, traces, tasks, and audit context."
        actions={<StatusPill label={error ? 'API degraded' : `${incidents.length} incidents`} tone={error ? 'warning' : 'incident'} />}
      />

      <form className="incident-form" onSubmit={submit}>
        <input required value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Incident title" />
        <select value={severity} onChange={(event) => setSeverity(event.target.value)}>
          <option value="warning">warning</option>
          <option value="error">error</option>
          <option value="critical">critical</option>
        </select>
        <input value={traceId} onChange={(event) => setTraceId(event.target.value)} placeholder="trace_id optional" />
        <button type="submit">Create incident</button>
      </form>

      {error ? <div className="panel-warning">{error}</div> : null}

      <section className="ops-panel">
        <div className="log-table">
          <div className="log-table-head">
            <span>Time</span>
            <span>Severity</span>
            <span>Title</span>
            <span>Agent</span>
            <span>Trace</span>
            <span>Status</span>
          </div>
          {incidents.map((incident) => (
            <div className="log-table-row" key={incident.id}>
              <span>{new Date(incident.ts).toLocaleString()}</span>
              <span>{incident.severity}</span>
              <span><Link to={`/incidents/${encodeURIComponent(incident.id)}`}>{String(incident.payload.title ?? incident.event_type)}</Link></span>
              <span>{incident.agent_id ?? '-'}</span>
              <span>{incident.trace_id ? <Link to={`/traces/${encodeURIComponent(incident.trace_id)}`}>{incident.trace_id}</Link> : '-'}</span>
              <span>{String(incident.payload.status ?? 'open')}</span>
            </div>
          ))}
          {!error && incidents.length === 0 ? <div className="empty-state">No incidents found.</div> : null}
        </div>
      </section>
    </main>
  )
}
