export default function MetricCard({
  label,
  value,
  detail,
  tone = 'neutral',
}: {
  label: string
  value: string | number
  detail?: string
  tone?: 'neutral' | 'healthy' | 'warning' | 'incident'
}) {
  return (
    <section className={`metric-card metric-${tone}`}>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      {detail ? <div className="metric-detail">{detail}</div> : null}
    </section>
  )
}
