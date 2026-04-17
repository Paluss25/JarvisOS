import { apiGet, apiPost, apiDelete } from './client'

export interface AgentInfo {
  id: string
  name: string
  role: string
  port: number
  status: string      // running | stopped | unknown
  health: string      // ok | degraded | offline
  uptime_seconds: number | null
  context_usage: {
    input_tokens: number
    output_tokens: number
  } | null
}

export interface AgentCreateRequest {
  id: string
  name: string
  role: string
  port: number
  telegram_token_env?: string
  domains?: string[]
}

export function listAgents(): Promise<AgentInfo[]> {
  return apiGet<AgentInfo[]>('/agents')
}

export function getAgent(id: string): Promise<AgentInfo> {
  return apiGet<AgentInfo>(`/agents/${id}`)
}

export function createAgent(req: AgentCreateRequest): Promise<AgentInfo> {
  return apiPost<AgentInfo>('/agents', req)
}

export function deleteAgent(id: string): Promise<void> {
  return apiDelete(`/agents/${id}`)
}

export function restartAgent(id: string): Promise<{ status: string }> {
  return apiPost<{ status: string }>(`/agents/${id}/restart`, {})
}

export function chatAgent(id: string, message: string): Promise<{ response: string }> {
  return apiPost<{ response: string }>(`/agents/${id}/chat`, { message })
}
