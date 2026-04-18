import { apiGet, apiPost, apiPatch } from './client'

export interface Task {
  id: string
  title: string
  description: string
  state: string
  priority: number
  assigned_agent: string | null
  parent_id: string | null
  retry_count: number
  max_retries: number
  created_at: string
  updated_at: string
  summary: string | null
}

export interface TaskCreate {
  title: string
  description: string
  priority?: number
  assigned_agent?: string
  parent_id?: string
}

export function listTasks(filters?: { state?: string; agent?: string }): Promise<Task[]> {
  const params = new URLSearchParams()
  if (filters?.state) params.set('state', filters.state)
  if (filters?.agent) params.set('agent_id', filters.agent)
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
