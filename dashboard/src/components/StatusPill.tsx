type StatusTone = 'neutral' | 'healthy' | 'warning' | 'incident' | 'trace' | 'ai' | 'network'

const toneClass: Record<StatusTone, string> = {
  neutral: 'status-pill status-neutral',
  healthy: 'status-pill status-healthy',
  warning: 'status-pill status-warning',
  incident: 'status-pill status-incident',
  trace: 'status-pill status-trace',
  ai: 'status-pill status-ai',
  network: 'status-pill status-network',
}

export default function StatusPill({ label, tone = 'neutral' }: { label: string; tone?: StatusTone }) {
  return <span className={toneClass[tone]}>{label}</span>
}
