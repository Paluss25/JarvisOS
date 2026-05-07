import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getSettingsGovernance } from '../api/settings'
import MetricCard from '../components/MetricCard'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'
import type { ApprovalClass, SettingsGovernanceData } from '../types/settings'

function riskTone(risk: ApprovalClass['risk']): 'healthy' | 'warning' | 'incident' {
  if (risk === 'high') return 'incident'
  if (risk === 'medium') return 'warning'
  return 'healthy'
}

function flag(value: boolean) {
  return value ? 'enabled' : 'disabled'
}

export default function SettingsPage() {
  const [data, setData] = useState<SettingsGovernanceData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getSettingsGovernance()
      .then((result) => {
        setData(result)
        setError(null)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [])

  const summary = data?.summary
  const modelRouting = data?.model_routing

  return (
    <main className="ops-page">
      <PageHeader
        title="Settings"
        description="Read-only governance posture for agents, approval policy, memory retention, model routing, and shared constraints."
        actions={<StatusPill label={error ? 'API degraded' : 'governance view'} tone={error ? 'warning' : 'network'} />}
      />

      {error ? <div className="panel-warning">{error}</div> : null}

      <section className="metric-grid">
        <MetricCard label="Agents" value={summary?.agent_count ?? '-'} detail={`${summary?.worker_count ?? 0} workers`} />
        <MetricCard label="Domains" value={summary?.domain_count ?? '-'} detail="Shared workspaces" />
        <MetricCard label="Users" value={summary?.user_count ?? '-'} detail="Authenticated accounts" />
        <MetricCard label="Human approvals" value={summary?.human_approval_actions ?? '-'} detail="Single approval actions" tone={summary?.human_approval_actions ? 'warning' : 'neutral'} />
        <MetricCard label="Two-step approvals" value={summary?.two_step_actions ?? '-'} detail="High risk actions" tone={summary?.two_step_actions ? 'incident' : 'neutral'} />
        <MetricCard label="Denied actions" value={summary?.denied_action_count ?? '-'} detail={`${summary?.permission_agent_count ?? 0} policy agents`} tone={summary?.denied_action_count ? 'warning' : 'neutral'} />
        <MetricCard label="Retention" value={summary ? `${summary.min_retention_days}-${summary.max_retention_days}d` : '-'} detail={`${summary?.memory_store_count ?? 0} memory stores`} />
        <MetricCard label="Config audit" value={summary?.audit_config_events ?? '-'} detail="Policy/config related events" />
      </section>

      <section className="settings-layout">
        <section className="ops-panel">
          <h2>Approval Policy</h2>
          <div className="approval-class-list">
            {(data?.approval_classes ?? []).map((item) => (
              <article className="approval-class-card" key={item.name}>
                <div>
                  <StatusPill label={item.risk} tone={riskTone(item.risk)} />
                  <strong>{item.name}</strong>
                  <p>{item.description}</p>
                </div>
                <span>{item.action_count} actions</span>
                <code>{item.actions.join(', ') || '-'}</code>
              </article>
            ))}
            {(data?.approval_classes.length ?? 0) === 0 ? <div className="empty-state">No approval policy loaded.</div> : null}
          </div>
        </section>

        <section className="ops-panel">
          <h2>Model Routing</h2>
          <div className="settings-flag-grid">
            <StatusPill label={`local first ${flag(modelRouting?.local_first ?? false)}`} tone={modelRouting?.local_first ? 'healthy' : 'warning'} />
            <StatusPill label={`cloud default ${modelRouting?.cloud_default_disabled ? 'disabled' : 'enabled'}`} tone={modelRouting?.cloud_default_disabled ? 'healthy' : 'warning'} />
            <StatusPill label={`uncertain route deny ${flag(modelRouting?.deny_if_route_uncertain ?? false)}`} tone={modelRouting?.deny_if_route_uncertain ? 'healthy' : 'warning'} />
          </div>
          <div className="model-route-list">
            {(modelRouting?.rules ?? []).map((rule) => (
              <article className="model-route-row" key={rule.id}>
                <div>
                  <strong>{rule.id}</strong>
                  <span>{JSON.stringify(rule.conditions)}</span>
                </div>
                <StatusPill label={rule.route ?? 'unknown'} tone={rule.route === 'cloud_allowed' ? 'warning' : 'healthy'} />
              </article>
            ))}
            {(modelRouting?.rules.length ?? 0) === 0 ? <div className="empty-state">No model routing rules loaded.</div> : null}
          </div>
        </section>
      </section>

      <section className="settings-layout">
        <section className="ops-panel">
          <h2>Memory Stores</h2>
          <div className="memory-policy-table">
            <div className="memory-policy-head">
              <span>Store</span>
              <span>Retention</span>
              <span>Roles</span>
              <span>Controls</span>
            </div>
            {(data?.memory_stores ?? []).map((store) => (
              <div className="memory-policy-row" key={store.name}>
                <div>
                  <strong>{store.name}</strong>
                  <p>{store.description}</p>
                </div>
                <span>{store.retention_days}d</span>
                <span>{store.access_roles.join(', ') || '-'}</span>
                <span className="settings-control-stack">
                  <StatusPill label={`vector ${flag(store.vectorization_allowed)}`} tone={store.vectorization_allowed ? 'ai' : 'neutral'} />
                  <StatusPill label={`redaction ${flag(store.redaction_required)}`} tone={store.redaction_required ? 'healthy' : 'warning'} />
                  <StatusPill label={`pii minimized ${flag(store.pii_minimized)}`} tone={store.pii_minimized ? 'healthy' : 'neutral'} />
                </span>
              </div>
            ))}
            {(data?.memory_stores.length ?? 0) === 0 ? <div className="empty-state">No memory policy stores loaded.</div> : null}
          </div>
        </section>

        <section className="ops-panel">
          <h2>Shared Constraints</h2>
          <div className="constraint-list">
            {(data?.shared_constraints ?? []).map((constraint) => (
              <div className="constraint-row" key={constraint}>
                <StatusPill label="deny" tone="incident" />
                <span>{constraint}</span>
              </div>
            ))}
            {(data?.shared_constraints.length ?? 0) === 0 ? <div className="empty-state">No shared constraints loaded.</div> : null}
          </div>
        </section>
      </section>

      <section className="settings-layout">
        <section className="ops-panel">
          <h2>Agent Permissions</h2>
          <div className="permission-table">
            <div className="permission-table-head">
              <span>Agent</span>
              <span>Description</span>
              <span>Read</span>
              <span>Write</span>
              <span>Execute</span>
              <span>Denied</span>
            </div>
            {(data?.permission_agents ?? []).map((agent) => (
              <div className="permission-table-row" key={agent.agent_id}>
                <span><Link to={`/agents/${encodeURIComponent(agent.agent_id)}`}>{agent.agent_id}</Link></span>
                <span>{agent.description}</span>
                <span>{agent.read_count}</span>
                <span>{agent.write_count}</span>
                <span>{agent.execute_count}</span>
                <span><StatusPill label={String(agent.denied_count)} tone={agent.denied_count ? 'warning' : 'healthy'} /></span>
              </div>
            ))}
            {(data?.permission_agents.length ?? 0) === 0 ? <div className="empty-state">No agent permissions loaded.</div> : null}
          </div>
        </section>

        <section className="ops-panel">
          <h2>Domains</h2>
          <div className="domain-chip-list">
            {(data?.domains ?? []).map((domain) => <StatusPill key={domain} label={domain} tone="network" />)}
            {(data?.domains.length ?? 0) === 0 ? <div className="empty-state">No shared domains detected.</div> : null}
          </div>
        </section>
      </section>
    </main>
  )
}
