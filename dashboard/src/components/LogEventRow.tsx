import { Link } from 'react-router-dom'
import StatusPill from './StatusPill'

type LogEventLike = {
  id: string
  ts: string
  event_type: string
  severity: string
  agent_id?: string | null
  source?: string | null
  trace_id?: string | null
  links?: {
    detail?: string
  }
}

function timeLabel(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString() : '-'
}

function severityTone(severity: string): 'neutral' | 'healthy' | 'warning' | 'incident' {
  if (severity === 'critical' || severity === 'error') return 'incident'
  if (severity === 'warning') return 'warning'
  return 'neutral'
}

export default function LogEventRow({ event, className }: { event: LogEventLike; className: string }) {
  const detailHref = event.links?.detail ?? `/logs/${encodeURIComponent(event.id)}`
  const actor = event.agent_id ?? event.source ?? '-'

  return (
    <article className={className}>
      <div className="log-entry-row-main">
        <StatusPill label={event.severity} tone={severityTone(event.severity)} />
        <Link className="log-entry-title" to={detailHref}>{event.event_type}</Link>
        <span>{timeLabel(event.ts)} · {actor}</span>
      </div>
      {event.trace_id ? <Link to={`/traces/${encodeURIComponent(event.trace_id)}`}>trace</Link> : null}
    </article>
  )
}
