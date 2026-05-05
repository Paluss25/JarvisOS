import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { createTask, listTasks, type Task } from '../api/tasks'
import MetricCard from '../components/MetricCard'
import PageHeader from '../components/PageHeader'
import StatusPill from '../components/StatusPill'
import { useAuth } from '../context/AuthContext'

const COLUMNS = [
  { status: 'backlog', label: 'Backlog', aliases: ['pending', 'backlog'] },
  { status: 'assigned', label: 'Assigned', aliases: ['assigned'] },
  { status: 'running', label: 'Running', aliases: ['running'] },
  { status: 'waiting', label: 'Waiting', aliases: ['waiting', 'needs_review'] },
  { status: 'blocked', label: 'Blocked', aliases: ['blocked', 'failed'] },
  { status: 'done', label: 'Done', aliases: ['done'] },
]

const PRIORITIES = ['low', 'normal', 'high', 'urgent']
const AGENTS = ['ceo', 'cfo', 'cio', 'ciso', 'cos', 'dos', 'eia', 'mt']

function statusTone(status: string): 'neutral' | 'healthy' | 'warning' | 'incident' | 'trace' {
  if (status === 'done') return 'healthy'
  if (status === 'running') return 'trace'
  if (status === 'waiting' || status === 'needs_review' || status === 'assigned') return 'warning'
  if (status === 'blocked' || status === 'failed') return 'incident'
  return 'neutral'
}

function TaskCard({ task }: { task: Task }) {
  return (
    <Link to={`/tasks/${task.id}`} className="task-card">
      <div className="task-card-head">
        <StatusPill label={task.status} tone={statusTone(task.status)} />
        <span>{task.priority}</span>
      </div>
      <strong>{task.title}</strong>
      {task.description ? <p>{task.description}</p> : null}
      <div className="task-card-meta">
        <span>{task.assigned_to ?? 'unassigned'}</span>
        <span>{new Date(task.created_at).toLocaleDateString()}</span>
      </div>
    </Link>
  )
}

export default function TaskBoardPage() {
  const { isAdmin } = useAuth()
  const [tasks, setTasks] = useState<Task[]>([])
  const [error, setError] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [priority, setPriority] = useState('normal')
  const [assignTo, setAssignTo] = useState('')
  const [agentFilter, setAgentFilter] = useState('')

  const load = useCallback(() => {
    listTasks({ agent: agentFilter || undefined })
      .then((result) => {
        setTasks(result)
        setError(null)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [agentFilter])

  useEffect(() => {
    load()
  }, [load])

  async function handleCreate() {
    const cleanTitle = title.trim()
    if (!cleanTitle) return
    const task = await createTask({
      title: cleanTitle,
      description: description.trim(),
      priority,
      assign_to: assignTo || undefined,
    })
    setTasks((current) => [task, ...current])
    setTitle('')
    setDescription('')
    setPriority('normal')
    setAssignTo('')
    setShowCreate(false)
  }

  const metrics = useMemo(() => {
    const open = tasks.filter((task) => !['done'].includes(task.status)).length
    const blocked = tasks.filter((task) => ['blocked', 'failed'].includes(task.status)).length
    const review = tasks.filter((task) => ['waiting', 'needs_review'].includes(task.status)).length
    return { open, blocked, review }
  }, [tasks])

  function columnTasks(aliases: string[]) {
    return tasks.filter((task) => aliases.includes(task.status))
  }

  return (
    <main className="ops-page">
      <PageHeader
        title="Task Board"
        description="Create, assign, and track JarvisOS work across all agents."
        actions={<StatusPill label={error ? 'API degraded' : `${tasks.length} tasks`} tone={error ? 'warning' : 'trace'} />}
      />

      <section className="metric-grid">
        <MetricCard label="Open" value={metrics.open} detail="Not completed" />
        <MetricCard label="Waiting review" value={metrics.review} detail="Needs operator attention" tone={metrics.review ? 'warning' : 'neutral'} />
        <MetricCard label="Blocked" value={metrics.blocked} detail="Failed or blocked" tone={metrics.blocked ? 'incident' : 'neutral'} />
      </section>

      <section className="task-toolbar">
        <select value={agentFilter} onChange={(event) => setAgentFilter(event.target.value)}>
          <option value="">All agents</option>
          {AGENTS.map((agent) => <option key={agent} value={agent}>{agent}</option>)}
        </select>
        <button onClick={load}>Refresh</button>
        {isAdmin ? <button onClick={() => setShowCreate((value) => !value)}>+ New task</button> : null}
      </section>

      {error ? <div className="panel-warning">{error}</div> : null}

      {showCreate ? (
        <section className="ops-panel task-create-panel">
          <h2>Create Task</h2>
          <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Title" />
          <textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Description" rows={3} />
          <div className="task-create-grid">
            <select value={priority} onChange={(event) => setPriority(event.target.value)}>
              {PRIORITIES.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
            <select value={assignTo} onChange={(event) => setAssignTo(event.target.value)}>
              <option value="">Auto assign</option>
              {AGENTS.map((agent) => <option key={agent} value={agent}>{agent}</option>)}
            </select>
          </div>
          <div className="page-actions">
            <button onClick={handleCreate}>Create</button>
            <button onClick={() => setShowCreate(false)}>Cancel</button>
          </div>
        </section>
      ) : null}

      <section className="task-board">
        {COLUMNS.map((column) => {
          const items = columnTasks(column.aliases)
          return (
            <section className="task-column" key={column.status}>
              <header>
                <span>{column.label}</span>
                <strong>{items.length}</strong>
              </header>
              <div className="task-column-list">
                {items.map((task) => <TaskCard key={task.id} task={task} />)}
                {items.length === 0 ? <div className="empty-state">No tasks.</div> : null}
              </div>
            </section>
          )
        })}
      </section>
    </main>
  )
}
