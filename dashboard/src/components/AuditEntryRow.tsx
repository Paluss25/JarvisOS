import { Link } from 'react-router-dom'
import StatusPill from './StatusPill'

type AuditEntryLike = {
  id: number
  ts: string
  category: string
  action: string
  source: string
  links?: {
    detail?: string
  }
}

function timeLabel(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString() : '-'
}

function toneForCategory(category: string): 'neutral' | 'healthy' | 'warning' | 'incident' | 'network' {
  if (category === 'security') return 'incident'
  if (category === 'task' || category === 'memory') return 'network'
  if (category === 'platform') return 'warning'
  return 'neutral'
}

export default function AuditEntryRow({ entry, className }: { entry: AuditEntryLike; className: string }) {
  const detailHref = entry.links?.detail ?? `/audit/${entry.id}`

  return (
    <article className={className} key={`audit:${entry.id}`}>
      <div className="audit-entry-row-main">
        <StatusPill label={entry.category} tone={toneForCategory(entry.category)} />
        <Link className="audit-entry-action" to={detailHref}>{entry.action}</Link>
        <span>{timeLabel(entry.ts)} · {entry.source}</span>
      </div>
    </article>
  )
}
