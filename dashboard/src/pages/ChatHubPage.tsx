import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { chatAgent, listAgents, type AgentInfo } from '../api/agents'
import { forwardChatA2A, getChatContext, saveChatDecision, type ChatContext } from '../api/chat'
import { createTask } from '../api/tasks'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'

type ChatMessage = {
  id: string
  agent_id: string
  role: 'operator' | 'agent'
  text: string
  ts: string
  context?: ChatContext
}

type ContextInputs = {
  task_id: string
  trace_id: string
  log_event_id: string
  memory_event_id: string
}

function agentLabel(agent: AgentInfo): string {
  return agent.name ?? agent.id
}

export default function ChatHubPage() {
  const { id } = useParams()
  const [searchParams] = useSearchParams()
  const searchKey = searchParams.toString()
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [agentId, setAgentId] = useState(id ?? searchParams.get('agent_id') ?? 'ceo')
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [contextInputs, setContextInputs] = useState<ContextInputs>({
    task_id: '',
    trace_id: '',
    log_event_id: '',
    memory_event_id: '',
  })
  const [chatContext, setChatContext] = useState<ChatContext | null>(null)
  const [targetAgentId, setTargetAgentId] = useState('')
  const [notice, setNotice] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    listAgents()
      .then((result) => {
        setAgents(result)
        if (!id && !searchParams.get('agent_id') && result.length > 0) setAgentId(result[0].id)
        const firstTarget = result.find((agent) => agent.id !== (id ?? searchParams.get('agent_id') ?? result[0]?.id))
        setTargetAgentId(firstTarget?.id ?? result[0]?.id ?? '')
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [id, searchKey])

  useEffect(() => {
    const nextAgent = id ?? searchParams.get('agent_id')
    if (nextAgent) setAgentId(nextAgent)
    setContextInputs({
      task_id: searchParams.get('task_id') ?? '',
      trace_id: searchParams.get('trace_id') ?? '',
      log_event_id: searchParams.get('log_event_id') ?? '',
      memory_event_id: searchParams.get('memory_event_id') ?? '',
    })
  }, [id, searchKey])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const activeAgent = useMemo(
    () => agents.find((agent) => agent.id === agentId),
    [agents, agentId],
  )

  useEffect(() => {
    if (!agentId) return
    getChatContext({
      agent_id: agentId,
      task_id: contextInputs.task_id.trim() || undefined,
      trace_id: contextInputs.trace_id.trim() || undefined,
      log_event_id: contextInputs.log_event_id.trim() || undefined,
      memory_event_id: contextInputs.memory_event_id.trim() || undefined,
    })
      .then((context) => {
        setChatContext(context)
        setError(null)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [agentId, contextInputs])

  const availableTargets = useMemo(
    () => agents.filter((agent) => agent.id !== agentId),
    [agents, agentId],
  )

  useEffect(() => {
    if (!targetAgentId || targetAgentId === agentId) {
      setTargetAgentId(availableTargets[0]?.id ?? '')
    }
  }, [agentId, availableTargets, targetAgentId])

  async function handleSend() {
    const text = input.trim()
    if (!agentId || !text) return
    const now = new Date().toISOString()
    const context = chatContext ?? undefined
    setInput('')
    setNotice(null)
    setMessages((current) => [
      ...current,
      { id: `${now}:operator`, agent_id: agentId, role: 'operator', text, ts: now, context },
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
          context,
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
      description: [
        `Created from Chat Hub message to ${message.agent_id} at ${message.ts}.`,
        message.context?.attachments.length ? `Context: ${message.context.attachments.map((item) => `${item.kind}:${item.id}`).join(', ')}` : '',
        '',
        message.text,
      ].filter(Boolean).join('\n'),
      priority: 'normal',
      assign_to: message.agent_id,
    })
    setNotice('Task created from chat message.')
  }

  async function forwardMessage(message: ChatMessage) {
    if (!targetAgentId) return
    const event = await forwardChatA2A({
      from_agent: message.agent_id,
      to_agent: targetAgentId,
      message: message.text,
      task_id: message.context?.attachments.find((item) => item.kind === 'task')?.id,
      trace_id: message.context?.attachments.find((item) => item.kind === 'trace')?.id,
      context: message.context,
    })
    setNotice(`A2A ${event.status} for ${event.to_agent}: ${event.message_id}`)
  }

  async function saveDecisionFromMessage(message: ChatMessage) {
    const decision = await saveChatDecision({
      agent_id: message.agent_id,
      reply: message.text,
      title: `Chat decision - ${message.agent_id}`,
      task_id: message.context?.attachments.find((item) => item.kind === 'task')?.id,
      trace_id: message.context?.attachments.find((item) => item.kind === 'trace')?.id,
      message_id: message.id,
      context: message.context,
    })
    setNotice(`Decision saved: ${decision.title}`)
  }

  function updateContextInput(key: keyof ContextInputs, value: string) {
    setContextInputs((current) => ({ ...current, [key]: value }))
  }

  return (
    <main className="ops-page chat-hub-page">
      <PageHeader
        title="Chat Hub"
        description="Agent chat workspace with operational context and A2A handoff."
        actions={<StatusPill label={error ? 'API degraded' : activeAgent ? activeAgent.id : agentId} tone={error ? 'warning' : 'ai'} />}
      />

      {error ? <div className="panel-warning">{error}</div> : null}
      {notice ? <div className="panel-success">{notice}</div> : null}

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

          <section className="chat-context-panel">
            <header>Context</header>
            <label>
              <span>Task</span>
              <input value={contextInputs.task_id} onChange={(event) => updateContextInput('task_id', event.target.value)} placeholder="task uuid" />
            </label>
            <label>
              <span>Trace</span>
              <input value={contextInputs.trace_id} onChange={(event) => updateContextInput('trace_id', event.target.value)} placeholder="trace id" />
            </label>
            <label>
              <span>Log</span>
              <input value={contextInputs.log_event_id} onChange={(event) => updateContextInput('log_event_id', event.target.value)} placeholder="event uuid" />
            </label>
            <label>
              <span>Memory</span>
              <input value={contextInputs.memory_event_id} onChange={(event) => updateContextInput('memory_event_id', event.target.value)} placeholder="event uuid" />
            </label>

            {chatContext ? (
              <div className="chat-context-links">
                <strong>{chatContext.metrics.attachment_count} attachments</strong>
                <div>
                  <Link to={chatContext.links.cockpit ?? `/agents/${agentId}/cockpit`}>Cockpit</Link>
                  <Link to={chatContext.links.logs ?? '/logs'}>Logs</Link>
                  <Link to={chatContext.links.a2a ?? '/a2a'}>A2A</Link>
                </div>
                {chatContext.attachments.map((item) => (
                  <Link key={`${item.kind}:${item.id}`} to={item.href}>{item.kind}: {item.id}</Link>
                ))}
              </div>
            ) : null}
          </section>
        </aside>

        <section className="chat-panel">
          <header>
            <div>
              <strong>{activeAgent ? agentLabel(activeAgent) : agentId}</strong>
              <span>{chatContext?.attachments.length ? 'Context attached' : 'Direct chat'}</span>
            </div>
            <StatusPill label={loading ? 'thinking' : 'ready'} tone={loading ? 'warning' : 'healthy'} />
          </header>

          <div className="chat-message-list">
            {messages.map((message) => (
              <article className={`chat-message chat-message-${message.role}`} key={message.id}>
                <div className="chat-message-meta">
                  <strong>{message.role === 'operator' ? 'Operator' : message.agent_id}</strong>
                  <span>{new Date(message.ts).toLocaleString()}</span>
                </div>
                <p>{message.text}</p>
                {message.context?.attachments.length ? (
                  <div className="chat-message-context">
                    {message.context.attachments.map((item) => (
                      <Link key={`${message.id}:${item.kind}:${item.id}`} to={item.href}>{item.kind}</Link>
                    ))}
                  </div>
                ) : null}
                <div className="chat-message-actions">
                  <button onClick={() => createTaskFromMessage(message)}>Task</button>
                  <button disabled={!targetAgentId} onClick={() => forwardMessage(message)}>A2A</button>
                  {message.role === 'agent' ? <button onClick={() => saveDecisionFromMessage(message)}>Decision</button> : null}
                </div>
              </article>
            ))}
            {loading ? <div className="chat-thinking">Waiting for agent response...</div> : null}
            {messages.length === 0 && !loading ? <div className="empty-state">No messages in this thread.</div> : null}
            <div ref={endRef} />
          </div>

          <footer>
            <select value={targetAgentId} onChange={(event) => setTargetAgentId(event.target.value)} title="A2A target agent">
              {availableTargets.map((agent) => (
                <option key={agent.id} value={agent.id}>{agent.id}</option>
              ))}
            </select>
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
