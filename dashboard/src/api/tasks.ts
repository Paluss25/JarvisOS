import { apiGet, apiPost, apiPatch } from './client'

export interface Task {
  id: string
  title: string
  description: string
  status: string
  state: string
  priority: string
  assigned_to: string | null
  assigned_agent: string | null
  parent_id: string | null
  depends_on: string[]
  assignment_mode: string
  retry_count: number
  max_retries: number
  created_at: string
  assigned_at: string | null
  started_at: string | null
  completed_at: string | null
  updated_at: string
  summary: string | null
}

export interface TaskContext {
  task: Task
  metrics: {
    trace_count: number
    log_count: number
    audit_count: number
    decision_count: number
    artifact_count: number
  }
  links: {
    agent: string | null
    chat: string | null
    cockpit: string | null
    traces: string
    logs: string
    audit: string
  }
  traces: Array<{
    trace_id: string
    agent_id: string | null
    status: string
    duration_ms: number
    span_count: number
    cost_usd: number
  }>
  logs: Array<{
    id: string
    ts: string
    event_type: string
    severity: string
    agent_id: string | null
    trace_id: string | null
    payload: Record<string, unknown>
  }>
  audit_entries: Array<{
    id: number
    ts: string
    category: string
    agent_id: string | null
    action: string
    source: string
    detail: Record<string, unknown>
  }>
  decisions: Array<{
    id: string
    ts: string
    agent_id: string
    trace_id: string | null
    title: string
    summary: string
    status: string
  }>
  artifacts: Array<{
    event_id: string | null
    name: string
    path: string | null
    kind: 'artifact' | 'output'
    preview?: string
  }>
}

export interface TaskCreate {
  title: string
  description: string
  priority?: string
  assign_to?: string
  depends_on?: string[]
}

export function listTasks(filters?: { status?: string; state?: string; agent?: string }): Promise<Task[]> {
  const params = new URLSearchParams()
  if (filters?.status) params.set('status', filters.status)
  if (filters?.state) params.set('state', filters.state)
  if (filters?.agent) params.set('assigned_to', filters.agent)
  return apiGet<Task[]>(`/tasks?${params}`)
}

export function getTask(id: string): Promise<Task> {
  return apiGet<Task>(`/tasks/${id}`)
}

export function getTaskContext(id: string): Promise<TaskContext> {
  return apiGet<TaskContext>(`/tasks/${id}/context`)
}

export function createTask(req: TaskCreate): Promise<Task> {
  return apiPost<Task>('/tasks', req)
}

export function assignTask(id: string, agentId: string): Promise<Task> {
  return apiPost<Task>(`/tasks/${id}/assign`, { agent_id: agentId })
}

export function patchTask(id: string, patch: Partial<Pick<Task, 'state' | 'summary'>>): Promise<Task> {
  return apiPatch<Task>(`/tasks/${id}`, patch)
}
