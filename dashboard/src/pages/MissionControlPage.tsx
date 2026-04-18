import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { listTasks, Task, createTask } from '../api/tasks'
import { useAuth } from '../context/AuthContext'

const COLUMNS: { state: string; label: string; color: string }[] = [
  { state: 'pending',  label: 'Pending',  color: 'border-gray-600' },
  { state: 'assigned', label: 'Assigned', color: 'border-blue-600' },
  { state: 'running',  label: 'Running',  color: 'border-yellow-500' },
  { state: 'done',     label: 'Done',     color: 'border-green-600' },
  { state: 'failed',   label: 'Failed',   color: 'border-red-600' },
]

function TaskCard({ task }: { task: Task }) {
  return (
    <Link
      to={`/missions/${task.id}`}
      className="block bg-gray-800 hover:bg-gray-750 rounded-lg p-3 text-sm transition-colors"
    >
      <div className="font-medium text-white mb-1 line-clamp-2">{task.title}</div>
      {task.assigned_agent && (
        <div className="text-xs text-gray-400">{task.assigned_agent}</div>
      )}
      {task.retry_count > 0 && (
        <div className="text-xs text-yellow-400 mt-1">Retries: {task.retry_count}/{task.max_retries}</div>
      )}
    </Link>
  )
}

export default function MissionControlPage() {
  const { isAdmin } = useAuth()
  const [tasks, setTasks] = useState<Task[]>([])
  const [showCreate, setShowCreate] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [newDesc, setNewDesc] = useState('')

  const load = useCallback(() => {
    listTasks().then(setTasks)
  }, [])

  useEffect(() => {
    load()
    const iv = setInterval(load, 10_000)
    return () => clearInterval(iv)
  }, [load])

  async function handleCreate() {
    if (!newTitle.trim()) return
    await createTask({ title: newTitle.trim(), description: newDesc.trim() })
    setNewTitle('')
    setNewDesc('')
    setShowCreate(false)
    load()
  }

  const byState = (state: string) => tasks.filter(t => t.state === state)

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Mission Control</h1>
        {isAdmin && (
          <button
            onClick={() => setShowCreate(v => !v)}
            className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 rounded transition-colors"
          >
            + New Task
          </button>
        )}
      </div>

      {showCreate && (
        <div className="mb-6 bg-gray-900 rounded-xl border border-gray-800 p-4 space-y-3 max-w-lg">
          <h2 className="font-semibold">Create Task</h2>
          <input
            className="w-full px-3 py-2 rounded bg-gray-800 text-white border border-gray-700 focus:outline-none focus:border-blue-500 text-sm"
            placeholder="Title"
            value={newTitle}
            onChange={e => setNewTitle(e.target.value)}
          />
          <textarea
            className="w-full px-3 py-2 rounded bg-gray-800 text-white border border-gray-700 focus:outline-none focus:border-blue-500 text-sm"
            placeholder="Description"
            rows={3}
            value={newDesc}
            onChange={e => setNewDesc(e.target.value)}
          />
          <div className="flex gap-2">
            <button onClick={handleCreate} className="px-4 py-1.5 text-sm bg-blue-600 hover:bg-blue-500 rounded">Create</button>
            <button onClick={() => setShowCreate(false)} className="px-4 py-1.5 text-sm bg-gray-800 hover:bg-gray-700 rounded">Cancel</button>
          </div>
        </div>
      )}

      <div className="flex gap-4 overflow-x-auto pb-4">
        {COLUMNS.map(({ state, label, color }) => (
          <div key={state} className={`min-w-52 flex-1 flex flex-col border-t-2 ${color}`}>
            <div className="flex items-center justify-between px-1 py-2 mb-2">
              <span className="text-sm font-semibold text-gray-300">{label}</span>
              <span className="text-xs text-gray-500 bg-gray-800 rounded-full px-2 py-0.5">{byState(state).length}</span>
            </div>
            <div className="space-y-2">
              {byState(state).map(t => <TaskCard key={t.id} task={t} />)}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
