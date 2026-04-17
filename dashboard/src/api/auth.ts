import { apiFetch } from './client'

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface UserProfile {
  username: string
  role: string
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  const resp = await apiFetch('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}))
    throw new Error((err as { detail?: string }).detail ?? 'Login failed')
  }
  return resp.json()
}

export async function getMe(): Promise<UserProfile> {
  const resp = await apiFetch('/auth/me')
  if (!resp.ok) throw new Error('Not authenticated')
  return resp.json()
}
