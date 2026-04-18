import { useState, useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'
import { getAgent, AgentInfo, restartAgent, chatAgent } from '../api/agents'
import { apiGet } from '../api/client'
import { useAuth } from '../context/AuthContext'

type Tab = 'overview' | 'memory' | 'chat'

export default function AgentDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { isAdmin } = useAuth()
  const [agent, setAgent] = useState<AgentInfo | null>(null)
  const [tab, setTab] = useState<Tab>('overview')
  const [dailyLog, setDailyLog] = useState('')
  const [chatInput, setChatInput] = useState('')
  const [chatMessages, setChatMessages] = useState<{ role: 'user' | 'agent', text: string }[]>([])
  const [chatLoading, setChatLoading] = useState(false)
  const chatEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!id) return
    getAgent(id).then(setAgent)
  }, [id])

  useEffect(() => {
    if (tab === 'memory' && id) {
      apiGet<{ content: string }>(`/agents/${id}/memory/daily`)
        .then(d => setDailyLog(d.content ?? ''))
        .catch(() => setDailyLog('Could not load memory log'))
    }
  }, [tab, id])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatMessages])

  async function handleSendChat() {
    if (!id || !chatInput.trim()) return
    const msg = chatInput.trim()
    setChatInput('')
    setChatMessages(m => [...m, { role: 'user', text: msg }])
    setChatLoading(true)
    try {
      const { response } = await chatAgent(id, msg)
      setChatMessages(m => [...m, { role: 'agent', text: response }])
    } catch (e) {
      setChatMessages(m => [...m, { role: 'agent', text: `Error: ${String(e)}` }])
    } finally {
      setChatLoading(false)
    }
  }

  if (!agent) return <div className="p-6 text-gray-400">Loading…</div>

  return (
    <div className="p-6 max-w-4xl">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold">{agent.name}</h1>
        {isAdmin && (
          <button
            onClick={() => restartAgent(agent.id).then(() => getAgent(agent.id).then(setAgent))}
            className="px-3 py-1.5 text-sm rounded bg-gray-800 hover:bg-gray-700 transition-colors"
          >
            Restart
          </button>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-4 mb-6 border-b border-gray-800">
        {(['overview', 'memory', 'chat'] as Tab[]).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`pb-2 text-sm font-medium capitalize transition-colors ${
              tab === t ? 'border-b-2 border-blue-500 text-white' : 'text-gray-400 hover:text-white'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <dl className="grid grid-cols-2 gap-4 text-sm">
          {[
            ['ID', agent.id],
            ['Role', agent.role],
            ['Port', agent.port],
            ['Status', agent.status],
            ['Health', agent.health],
            ['Uptime', agent.uptime_seconds != null ? `${Math.floor(agent.uptime_seconds / 60)}m` : '—'],
          ].map(([label, value]) => (
            <div key={String(label)} className="bg-gray-900 rounded-lg p-3">
              <dt className="text-gray-500 text-xs mb-1">{label}</dt>
              <dd className="text-white font-medium">{String(value)}</dd>
            </div>
          ))}
        </dl>
      )}

      {tab === 'memory' && (
        <pre className="text-xs text-gray-300 bg-gray-900 rounded-lg p-4 overflow-auto max-h-[60vh] whitespace-pre-wrap">
          {dailyLog || '(empty)'}
        </pre>
      )}

      {tab === 'chat' && (
        <div className="flex flex-col h-[60vh]">
          <div className="flex-1 overflow-y-auto space-y-3 pr-1 mb-3">
            {chatMessages.map((m, i) => (
              <div key={i} className={`max-w-xl rounded-lg p-3 text-sm ${m.role === 'user' ? 'ml-auto bg-blue-700' : 'bg-gray-800'}`}>
                {m.text}
              </div>
            ))}
            {chatLoading && <div className="bg-gray-800 rounded-lg p-3 text-sm text-gray-400">Thinking…</div>}
            <div ref={chatEndRef} />
          </div>
          <div className="flex gap-2">
            <input
              className="flex-1 px-3 py-2 rounded bg-gray-800 text-white border border-gray-700 focus:outline-none focus:border-blue-500 text-sm"
              value={chatInput}
              onChange={e => setChatInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && !e.shiftKey && handleSendChat()}
              placeholder="Message…"
            />
            <button
              onClick={handleSendChat}
              disabled={chatLoading}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded text-sm transition-colors"
            >
              Send
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
