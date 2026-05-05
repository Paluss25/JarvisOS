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

export function createTask(req: TaskCreate): Promise<Task> {
  return apiPost<Task>('/tasks', req)
}

export function assignTask(id: string, agentId: string): Promise<Task> {
  return apiPost<Task>(`/tasks/${id}/assign`, { agent_id: agentId })
}

export function patchTask(id: string, patch: Partial<Pick<Task, 'state' | 'summary'>>): Promise<Task> {
  return apiPatch<Task>(`/tasks/${id}`, patch)
}
