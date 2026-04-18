import { useState, useEffect } from 'react'
import { apiGet, apiPost, apiDelete } from '../api/client'
import { useAuth } from '../context/AuthContext'

type SettingsTab = 'agents' | 'domains' | 'users'

interface Domain {
  name: string
  agents: string[]
}

interface UserEntry {
  username: string
  role: string
}

function AgentCreationTab() {
  const [form, setForm] = useState({ id: '', name: '', role: '', port: '8002', telegram_token_env: '' })
  const [msg, setMsg] = useState('')

  async function handleSubmit() {
    try {
      await apiPost('/agents', { ...form, port: Number(form.port) })
      setMsg('Agent created.')
      setForm({ id: '', name: '', role: '', port: '8002', telegram_token_env: '' })
    } catch (e) {
      setMsg(`Error: ${String(e)}`)
    }
  }

  return (
    <div className="max-w-md space-y-3">
      <h2 className="font-semibold text-lg mb-3">Create Agent</h2>
      {(['id', 'name', 'role', 'port', 'telegram_token_env'] as const).map(field => (
        <div key={field}>
          <label className="block text-xs text-gray-400 mb-1 capitalize">{field.replace('_', ' ')}</label>
          <input
            className="w-full px-3 py-2 rounded bg-gray-800 text-white border border-gray-700 focus:outline-none focus:border-blue-500 text-sm"
            value={form[field]}
            onChange={e => setForm(f => ({ ...f, [field]: e.target.value }))}
          />
        </div>
      ))}
      {msg && <p className={`text-sm ${msg.startsWith('Error') ? 'text-red-400' : 'text-green-400'}`}>{msg}</p>}
      <button onClick={handleSubmit} className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 rounded transition-colors">
        Create Agent
      </button>
    </div>
  )
}

function DomainsTab() {
  const [domains, setDomains] = useState<Domain[]>([])
  const [newName, setNewName] = useState('')
  const [grantDomain, setGrantDomain] = useState('')
  const [grantAgent, setGrantAgent] = useState('')
  const [grantMode, setGrantMode] = useState<'read' | 'write'>('read')

  useEffect(() => {
    apiGet<Domain[]>('/domains').then(setDomains)
  }, [])

  async function createDomain() {
    await apiPost('/domains', { name: newName })
    setNewName('')
    apiGet<Domain[]>('/domains').then(setDomains)
  }

  async function grant() {
    await apiPost(`/domains/${grantDomain}/grant`, { agent_id: grantAgent, mode: grantMode })
    apiGet<Domain[]>('/domains').then(setDomains)
  }

  async function deleteDomain(name: string) {
    await apiDelete(`/domains/${name}`)
    apiGet<Domain[]>('/domains').then(setDomains)
  }

  return (
    <div className="max-w-lg space-y-6">
      <div>
        <h2 className="font-semibold text-lg mb-3">Domains</h2>
        <div className="space-y-2 mb-4">
          {domains.map(d => (
            <div key={d.name} className="flex items-center justify-between bg-gray-900 rounded-lg px-4 py-3">
              <div>
                <span className="font-medium">{d.name}</span>
                <span className="text-xs text-gray-400 ml-2">{d.agents.join(', ') || 'no agents'}</span>
              </div>
              <button onClick={() => deleteDomain(d.name)} className="text-xs text-red-400 hover:text-red-300">Delete</button>
            </div>
          ))}
        </div>
        <div className="flex gap-2">
          <input
            className="flex-1 px-3 py-2 rounded bg-gray-800 text-white border border-gray-700 focus:outline-none focus:border-blue-500 text-sm"
            placeholder="New domain name"
            value={newName}
            onChange={e => setNewName(e.target.value)}
          />
          <button onClick={createDomain} className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 rounded transition-colors">Create</button>
        </div>
      </div>

      <div>
        <h2 className="font-semibold mb-3">Grant Access</h2>
        <div className="flex gap-2 flex-wrap">
          <input className="px-3 py-2 rounded bg-gray-800 text-white border border-gray-700 text-sm focus:outline-none" placeholder="Domain" value={grantDomain} onChange={e => setGrantDomain(e.target.value)} />
          <input className="px-3 py-2 rounded bg-gray-800 text-white border border-gray-700 text-sm focus:outline-none" placeholder="Agent ID" value={grantAgent} onChange={e => setGrantAgent(e.target.value)} />
          <select value={grantMode} onChange={e => setGrantMode(e.target.value as 'read' | 'write')} className="px-3 py-2 rounded bg-gray-800 text-white border border-gray-700 text-sm focus:outline-none">
            <option value="read">read</option>
            <option value="write">write</option>
          </select>
          <button onClick={grant} className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 rounded transition-colors">Grant</button>
        </div>
      </div>
    </div>
  )
}

function UsersTab() {
  const [users, setUsers] = useState<UserEntry[]>([])
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<'admin' | 'viewer'>('viewer')
  const [msg, setMsg] = useState('')

  useEffect(() => {
    apiGet<UserEntry[]>('/users').then(setUsers).catch(() => setUsers([]))
  }, [])

  async function createUser() {
    try {
      await apiPost('/users', { username, password, role })
      setMsg('User created.')
      setUsername(''); setPassword('')
      apiGet<UserEntry[]>('/users').then(setUsers)
    } catch (e) {
      setMsg(`Error: ${String(e)}`)
    }
  }

  return (
    <div className="max-w-md space-y-4">
      <h2 className="font-semibold text-lg mb-3">Users</h2>
      <div className="space-y-1 mb-4">
        {users.map(u => (
          <div key={u.username} className="flex items-center justify-between bg-gray-900 rounded-lg px-4 py-3">
            <span className="font-medium">{u.username}</span>
            <span className="text-xs text-gray-400 bg-gray-800 px-2 py-0.5 rounded">{u.role}</span>
          </div>
        ))}
      </div>
      <h3 className="font-medium">Create User</h3>
      <input className="w-full px-3 py-2 rounded bg-gray-800 text-white border border-gray-700 focus:outline-none focus:border-blue-500 text-sm" placeholder="Username" value={username} onChange={e => setUsername(e.target.value)} />
      <input className="w-full px-3 py-2 rounded bg-gray-800 text-white border border-gray-700 focus:outline-none focus:border-blue-500 text-sm" type="password" placeholder="Password" value={password} onChange={e => setPassword(e.target.value)} />
      <select value={role} onChange={e => setRole(e.target.value as 'admin' | 'viewer')} className="w-full px-3 py-2 rounded bg-gray-800 text-white border border-gray-700 focus:outline-none text-sm">
        <option value="viewer">viewer</option>
        <option value="admin">admin</option>
      </select>
      {msg && <p className={`text-sm ${msg.startsWith('Error') ? 'text-red-400' : 'text-green-400'}`}>{msg}</p>}
      <button onClick={createUser} className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 rounded transition-colors">Create User</button>
    </div>
  )
}

export default function SettingsPage() {
  const { isAdmin } = useAuth()
  const [tab, setTab] = useState<SettingsTab>('agents')

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-6">Settings</h1>
      <div className="flex gap-4 mb-6 border-b border-gray-800">
        {(['agents', 'domains', ...(isAdmin ? ['users'] : [])] as SettingsTab[]).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`pb-2 text-sm font-medium capitalize transition-colors ${tab === t ? 'border-b-2 border-blue-500 text-white' : 'text-gray-400 hover:text-white'}`}
          >
            {t}
          </button>
        ))}
      </div>
      {tab === 'agents' && <AgentCreationTab />}
      {tab === 'domains' && <DomainsTab />}
      {tab === 'users' && isAdmin && <UsersTab />}
    </div>
  )
}
