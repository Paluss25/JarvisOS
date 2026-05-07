import { Link } from 'react-router-dom'
import type { CfoDecision } from '../../types/cfo'
import StatusPill from '../StatusPill'

function formatConfidence(value: number | null): string {
  if (value === null) return '-'
  return `${Math.round(value * 100)}%`
}

function evidenceLabel(evidence: Array<Record<string, unknown>>): string {
  if (evidence.length === 0) return '-'
  const first = evidence[0]
  const source = first.source ?? first.name ?? first.url
  return typeof source === 'string' ? source : `${evidence.length} item`
}

function statusTone(status: string): 'neutral' | 'healthy' | 'warning' | 'incident' {
  if (status === 'approved') return 'healthy'
  if (status === 'rejected') return 'incident'
  if (status === 'proposed' || status === 'needs_review' || status === 'pending_approval') return 'warning'
  return 'neutral'
}

export default function DecisionLedger({ decisions }: { decisions: CfoDecision[] }) {
  return (
    <div className="decision-table">
      <div className="decision-table-head">
        <span>Time</span>
        <span>Status</span>
        <span>Type</span>
        <span>Decision</span>
        <span>Confidence</span>
        <span>Evidence</span>
        <span>Trace</span>
      </div>
      {decisions.map((decision) => (
        <div className="decision-table-row" key={decision.id}>
          <span>{new Date(decision.ts).toLocaleString()}</span>
          <span><StatusPill label={decision.status} tone={statusTone(decision.status)} /></span>
          <span>{decision.decision_type}</span>
          <span>
            <strong>{decision.title}</strong>
            <small>{decision.summary}</small>
          </span>
          <span>{formatConfidence(decision.confidence)}</span>
          <span>{evidenceLabel(decision.evidence)}</span>
          <span>
            {decision.trace_id ? (
              <Link to={`/traces/${encodeURIComponent(decision.trace_id)}`}>{decision.trace_id}</Link>
            ) : (
              '-'
            )}
          </span>
        </div>
      ))}
      {decisions.length === 0 ? <div className="empty-state">No CFO decisions recorded.</div> : null}
    </div>
  )
}
