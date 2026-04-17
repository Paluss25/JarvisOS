import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getTask, Task, assignTask } from '../api/tasks'
import { listAgents, AgentInfo } from '../api/agents'
import { useAuth } from '../context/AuthContext'

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="bg-gray-900 rounded-lg p-3">
      <dt className="text-xs text-gray-500 mb-1">{label}</dt>
      <dd className="text-sm text-white">{value ?? '—'}</dd>
    </div>
  )
}

export default function TaskDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { isAdmin } = useAuth()
  const [task, setTask] = useState<Task | null>(null)
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [assignTo, setAssignTo] = useState('')

  useEffect(() => {
    if (!id) return
    getTask(id).then(t => { setTask(t); setAssignTo(t.assigned_agent ?? '') })
    listAgents().then(setAgents)
  }, [id])

  async function handleAssign() {
    if (!id || !assignTo) return
    const updated = await assignTask(id, assignTo)
    setTask(updated)
  }

  if (!task) return <div className="p-6 text-gray-400">Loading…</div>

  return (
    <div className="p-6 max-w-3xl">
      <Link to="/missions" className="text-sm text-gray-400 hover:text-white mb-4 inline-block">
        &larr; Mission Control
      </Link>
      <h1 className="text-2xl font-bold mb-1">{task.title}</h1>
      <p className="text-gray-400 text-sm mb-6">{task.description}</p>

      <dl className="grid grid-cols-2 gap-3 mb-6">
        <Field label="ID" value={task.id} />
        <Field label="State" value={task.state} />
        <Field label="Priority" value={String(task.priority)} />
        <Field label="Assigned Agent" value={task.assigned_agent} />
        <Field label="Parent" value={task.parent_id} />
        <Field label="Retries" value={`${task.retry_count} / ${task.max_retries}`} />
        <Field label="Created" value={new Date(task.created_at).toLocaleString()} />
        <Field label="Updated" value={new Date(task.updated_at).toLocaleString()} />
      </dl>

      {task.summary && (
        <div className="mb-6">
          <h2 className="text-sm font-semibold text-gray-400 mb-2">Summary</h2>
          <p className="text-sm text-gray-200 bg-gray-900 rounded-lg p-4">{task.summary}</p>
        </div>
      )}

      {isAdmin && (
        <div className="flex gap-2">
          <select
            value={assignTo}
            onChange={e => setAssignTo(e.target.value)}
            className="px-3 py-2 rounded bg-gray-800 text-white border border-gray-700 text-sm focus:outline-none focus:border-blue-500"
          >
            <option value="">Assign to agent…</option>
            {agents.map(a => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
          <button
            onClick={handleAssign}
            className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 rounded transition-colors"
          >
            Assign
          </button>
        </div>
      )}
    </div>
  )
}
