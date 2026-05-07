import { Link } from 'react-router-dom'
import StatusPill from './StatusPill'

type DecisionLike = {
  id: string
  status: string
  title: string
  summary: string
  trace_id?: string | null
  links?: {
    detail?: string
  }
}

function statusTone(status: string): 'neutral' | 'healthy' | 'warning' | 'incident' {
  if (status === 'approved') return 'healthy'
  if (status === 'rejected') return 'incident'
  if (status === 'proposed') return 'warning'
  return 'neutral'
}

export default function DecisionEntryRow({ decision, className }: { decision: DecisionLike; className: string }) {
  const detailHref = decision.links?.detail ?? `/decisions/${encodeURIComponent(decision.id)}`

  return (
    <article className={className}>
      <div className="decision-entry-row-main">
        <StatusPill label={decision.status} tone={statusTone(decision.status)} />
        <Link className="decision-entry-title" to={detailHref}>{decision.title}</Link>
        <span>{decision.summary}</span>
      </div>
      {decision.trace_id ? <Link to={`/traces/${encodeURIComponent(decision.trace_id)}`}>trace</Link> : null}
    </article>
  )
}
