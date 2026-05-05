import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { getCfoCockpit } from '../api/cockpits'
import DecisionLedger from '../components/cockpits/DecisionLedger'
import MetricCard from '../components/MetricCard'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'
import type { CfoCockpitData } from '../types/cfo'

function alertTone(severity: string): 'neutral' | 'healthy' | 'warning' | 'incident' {
  if (severity === 'critical' || severity === 'error') return 'incident'
  if (severity === 'warning') return 'warning'
  return 'neutral'
}

function payloadText(payload: Record<string, unknown>): string {
  const title = payload.title ?? payload.message ?? payload.summary
  if (typeof title === 'string') return title
  const category = payload.category
  return typeof category === 'string' ? category : 'Recorded CFO alert'
}

export default function CfoCockpitPage() {
  const [data, setData] = useState<CfoCockpitData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getCfoCockpit()
      .then((result) => {
        setData(result)
        setError(null)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [])

  const summary = data?.summary
  const operationalTone = useMemo(() => {
    if (!summary) return 'neutral'
    if (summary.critical_alerts > 0 || summary.rejected_decisions > 0) return 'incident'
    if (summary.open_approvals > 0 || summary.market_alerts > 0 || summary.tax_alerts > 0) return 'warning'
    return 'healthy'
  }, [summary])

  return (
    <main className="ops-page">
      <PageHeader
        title="CFO Cockpit"
        description="Decision ledger, audit trail, finance alerts, crypto and Italian tax control room."
        actions={<StatusPill label={error ? 'API degraded' : 'cfo'} tone={error ? 'warning' : operationalTone} />}
      />

      {error ? <div className="panel-warning">{error}</div> : null}

      <section className="metric-grid">
        <MetricCard label="Decisions" value={summary?.decision_count ?? '-'} detail="Recorded CFO decisions" />
        <MetricCard label="Open approvals" value={summary?.open_approvals ?? '-'} detail="HITL queue" tone={summary?.open_approvals ? 'warning' : 'neutral'} />
        <MetricCard label="Tax alerts" value={summary?.tax_alerts ?? '-'} detail="Italian fiscal watch" tone={summary?.tax_alerts ? 'warning' : 'neutral'} />
        <MetricCard label="Market alerts" value={summary?.market_alerts ?? '-'} detail="Finance and crypto watch" tone={summary?.market_alerts ? 'warning' : 'neutral'} />
        <MetricCard label="Critical alerts" value={summary?.critical_alerts ?? '-'} detail="Immediate review" tone={summary?.critical_alerts ? 'incident' : 'neutral'} />
      </section>

      <section className="cfo-layout">
        <section className="ops-panel">
          <h2>Decision Ledger</h2>
          <DecisionLedger decisions={data?.decisions ?? []} />
        </section>

        <section className="ops-panel">
          <h2>Alert Room</h2>
          <div className="alert-list">
            {(data?.alerts ?? []).map((alert) => (
              <div className="alert-row" key={alert.id}>
                <div>
                  <StatusPill label={alert.severity} tone={alertTone(alert.severity)} />
                  <strong>{alert.event_type}</strong>
                  <p>{payloadText(alert.payload)}</p>
                </div>
                <div className="cfo-alert-meta">
                  <span>{new Date(alert.ts).toLocaleString()}</span>
                  {alert.trace_id ? <Link to={`/traces/${encodeURIComponent(alert.trace_id)}`}>{alert.trace_id}</Link> : null}
                </div>
              </div>
            ))}
            {!error && (data?.alerts.length ?? 0) === 0 ? <div className="empty-state">No CFO alerts recorded.</div> : null}
          </div>
        </section>
      </section>
    </main>
  )
}
