import { createContext, useContext, useEffect, useState, useRef, ReactNode } from 'react'

export interface SSEEvent {
  id: string
  type: string
  data: unknown
  ts: string
}

interface SSEContextValue {
  events: SSEEvent[]
  connected: boolean
}

const SSEContext = createContext<SSEContextValue>({ events: [], connected: false })

export function SSEProvider({ children }: { children: ReactNode }) {
  const [events, setEvents] = useState<SSEEvent[]>([])
  const [connected, setConnected] = useState(false)
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    const token = localStorage.getItem('access_token')
    if (!token) return

    let cancelled = false

    async function connect() {
      try {
        const resp = await fetch('/api/events/ticket', {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
        })
        if (!resp.ok || cancelled) return
        const data = await resp.json()
        const es = new EventSource(`/api/events?ticket=${encodeURIComponent(data.ticket)}`)
        esRef.current = es

        es.onopen = () => setConnected(true)
        es.onerror = () => setConnected(false)

        es.onmessage = (e) => {
          try {
            const payload = JSON.parse(e.data)
            if (payload === ':keepalive') return
            const event: SSEEvent = {
              id: crypto.randomUUID(),
              type: payload.type ?? 'unknown',
              data: payload,
              ts: new Date().toISOString(),
            }
            setEvents(prev => [event, ...prev].slice(0, 200))
          } catch {
            // ignore malformed events
          }
        }
      } catch {
        setConnected(false)
      }
    }
    connect()

    return () => {
      cancelled = true
      esRef.current?.close()
      setConnected(false)
    }
  }, [])

  return (
    <SSEContext.Provider value={{ events, connected }}>
      {children}
    </SSEContext.Provider>
  )
}

export function useSSE(): SSEContextValue {
  return useContext(SSEContext)
}
