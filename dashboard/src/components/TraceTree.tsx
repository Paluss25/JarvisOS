import StatusPill from './StatusPill'
import type { TraceSpan } from '../types/trace'

function statusTone(status: string): 'healthy' | 'warning' | 'incident' {
  if (status === 'ok') return 'healthy'
  if (status === 'error' || status === 'failed') return 'incident'
  return 'warning'
}

function TraceNode({ span, depth = 0 }: { span: TraceSpan; depth?: number }) {
  return (
    <div className="trace-node" style={{ '--trace-depth': depth } as React.CSSProperties}>
      <div className="trace-node-main">
        <div>
          <div className="trace-operation">{span.operation}</div>
          <div className="trace-meta">
            <span>{span.span_id}</span>
            {span.agent_id ? <span>agent {span.agent_id}</span> : null}
            {span.model ? <span>{span.model}</span> : null}
          </div>
        </div>
        <div className="trace-node-stats">
          <StatusPill label={span.status} tone={statusTone(span.status)} />
          <span>{span.duration_ms} ms</span>
          <span>{span.input_tokens + span.output_tokens} tok</span>
          <span>${span.cost_usd.toFixed(4)}</span>
        </div>
      </div>
      {span.children.length ? (
        <div className="trace-children">
          {span.children.map((child) => (
            <TraceNode key={child.span_id} span={child} depth={depth + 1} />
          ))}
        </div>
      ) : null}
    </div>
  )
}

export default function TraceTree({ spans }: { spans: TraceSpan[] }) {
  if (!spans.length) {
    return <div className="empty-state">No spans recorded for this trace.</div>
  }

  return (
    <div className="trace-tree">
      {spans.map((span) => (
        <TraceNode key={span.span_id} span={span} />
      ))}
    </div>
  )
}
