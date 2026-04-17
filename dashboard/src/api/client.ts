const API_BASE = '/api'

async function refreshToken(): Promise<boolean> {
  const rt = localStorage.getItem('refresh_token')
  if (!rt) return false
  try {
    const resp = await fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: rt }),
    })
    if (!resp.ok) return false
    const data = await resp.json()
    localStorage.setItem('access_token', data.access_token)
    if (data.refresh_token) localStorage.setItem('refresh_token', data.refresh_token)
    return true
  } catch {
    return false
  }
}

export async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const token = localStorage.getItem('access_token')
  const headers = new Headers(options.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (!headers.has('Content-Type') && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }

  let resp = await fetch(`${API_BASE}${path}`, { ...options, headers })

  if (resp.status === 401) {
    const refreshed = await refreshToken()
    if (refreshed) {
      headers.set('Authorization', `Bearer ${localStorage.getItem('access_token')}`)
      resp = await fetch(`${API_BASE}${path}`, { ...options, headers })
    }
  }
  return resp
}

export async function apiGet<T>(path: string): Promise<T> {
  const resp = await apiFetch(path)
  if (!resp.ok) throw new Error(`GET ${path} failed: ${resp.status}`)
  return resp.json()
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const resp = await apiFetch(path, { method: 'POST', body: JSON.stringify(body) })
  if (!resp.ok) throw new Error(`POST ${path} failed: ${resp.status}`)
  return resp.json()
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const resp = await apiFetch(path, { method: 'PATCH', body: JSON.stringify(body) })
  if (!resp.ok) throw new Error(`PATCH ${path} failed: ${resp.status}`)
  return resp.json()
}

export async function apiDelete(path: string): Promise<void> {
  const resp = await apiFetch(path, { method: 'DELETE' })
  if (!resp.ok) throw new Error(`DELETE ${path} failed: ${resp.status}`)
}
