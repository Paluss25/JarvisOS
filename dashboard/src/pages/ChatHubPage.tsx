import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { chatAgent, listAgents, type AgentInfo } from '../api/agents'
import { createTask } from '../api/tasks'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'

type ChatMessage = {
  id: string
  agent_id: string
  role: 'operator' | 'agent'
  text: string
  ts: string
}

function agentLabel(agent: AgentInfo): string {
  return agent.name ?? agent.id
}

export default function ChatHubPage() {
  const { id } = useParams()
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [agentId, setAgentId] = useState(id ?? 'ceo')
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    listAgents()
      .then((result) => {
        setAgents(result)
        if (!id && result.length > 0) setAgentId(result[0].id)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [id])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const activeAgent = useMemo(
    () => agents.find((agent) => agent.id === agentId),
    [agents, agentId],
  )

  async function handleSend() {
    const text = input.trim()
    if (!agentId || !text) return
    const now = new Date().toISOString()
    setInput('')
    setMessages((current) => [
      ...current,
      { id: `${now}:operator`, agent_id: agentId, role: 'operator', text, ts: now },
    ])
    setLoading(true)
    try {
      const result = await chatAgent(agentId, text)
      setMessages((current) => [
        ...current,
        {
          id: `${new Date().toISOString()}:agent`,
          agent_id: agentId,
          role: 'agent',
          text: result.response ?? JSON.stringify(result),
          ts: new Date().toISOString(),
        },
      ])
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  async function createTaskFromMessage(message: ChatMessage) {
    const title = message.text.length > 88 ? `${message.text.slice(0, 85)}...` : message.text
    await createTask({
      title,
      description: `Created from Chat Hub message to ${message.agent_id} at ${message.ts}.\n\n${message.text}`,
      priority: 'normal',
      assign_to: message.agent_id,
    })
  }

  return (
    <main className="ops-page chat-hub-page">
      <PageHeader
        title="Chat Hub"
        description="Direct agent chat with task creation from important messages."
        actions={<StatusPill label={error ? 'API degraded' : activeAgent ? activeAgent.id : agentId} tone={error ? 'warning' : 'ai'} />}
      />

      {error ? <div className="panel-warning">{error}</div> : null}

      <section className="chat-hub-layout">
        <aside className="chat-agent-list">
          <header>Agents</header>
          {agents.map((agent) => (
            <button
              className={agent.id === agentId ? 'active' : ''}
              key={agent.id}
              onClick={() => setAgentId(agent.id)}
            >
              <strong>{agentLabel(agent)}</strong>
              <span>{agent.id}</span>
            </button>
          ))}
        </aside>

        <section className="chat-panel">
          <header>
            <div>
              <strong>{activeAgent ? agentLabel(activeAgent) : agentId}</strong>
              <span>Direct chat</span>
            </div>
            <StatusPill label={loading ? 'thinking' : 'ready'} tone={loading ? 'warning' : 'healthy'} />
          </header>

          <div className="chat-message-list">
            {messages.map((message) => (
              <article className={`chat-message chat-message-${message.role}`} key={message.id}>
                <div>
                  <strong>{message.role === 'operator' ? 'Operator' : message.agent_id}</strong>
                  <span>{new Date(message.ts).toLocaleString()}</span>
                </div>
                <p>{message.text}</p>
                <button onClick={() => createTaskFromMessage(message)}>Create task</button>
              </article>
            ))}
            {loading ? <div className="chat-thinking">Waiting for agent response...</div> : null}
            {messages.length === 0 && !loading ? <div className="empty-state">No messages in this thread.</div> : null}
            <div ref={endRef} />
          </div>

          <footer>
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) handleSend()
              }}
              placeholder="Message the selected agent..."
              rows={3}
            />
            <button disabled={loading || !input.trim()} onClick={handleSend}>Send</button>
          </footer>
        </section>
      </section>
    </main>
  )
}
