import { apiGet, apiPost } from './client'

export interface ChatAttachment {
  kind: 'task' | 'trace' | 'log' | 'memory'
  id: string
  href: string
}

export interface ChatContext {
  agent_id: string
  metrics: {
    attachment_count: number
  }
  links: Record<string, string | null>
  attachments: ChatAttachment[]
}

export interface ChatA2AEvent {
  id: string
  ts: string
  event_type: string
  severity: string
  task_id: string | null
  trace_id: string | null
  message_id: string
  correlation_id: string
  from_agent: string
  to_agent: string
  message_type: string
  mode: string
  status: string
  payload: Record<string, unknown>
}

export interface ChatDecision {
  id: string
  ts: string
  agent_id: string
  task_id: string | null
  trace_id: string | null
  title: string
  summary: string
  decision_type: string
  status: string
  evidence: unknown[]
  payload: Record<string, unknown>
}

export function getChatContext(params: {
  agent_id: string
  task_id?: string
  trace_id?: string
  log_event_id?: string
  memory_event_id?: string
}): Promise<ChatContext> {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value) query.set(key, value)
  })
  return apiGet<ChatContext>(`/chat/context?${query.toString()}`)
}

export function forwardChatA2A(body: {
  from_agent: string
  to_agent: string
  message: string
  task_id?: string
  trace_id?: string
  context?: ChatContext
}): Promise<ChatA2AEvent> {
  return apiPost<ChatA2AEvent>('/chat/a2a', body)
}

export function saveChatDecision(body: {
  agent_id: string
  reply: string
  title?: string
  task_id?: string
  trace_id?: string
  message_id?: string
  context?: ChatContext
}): Promise<ChatDecision> {
  return apiPost<ChatDecision>('/chat/decisions', body)
}
