import { useState } from 'react'
import { SSEProvider, useSSE, SSEEvent } from '../components/SSEProvider'

const TYPE_COLORS: Record<string, string> = {
  'task:created':     'text-blue-400',
  'task:assigned':    'text-purple-400',
  'task:running':     'text-yellow-400',
  'task:done':        'text-green-400',
  'task:failed':      'text-red-400',
  'a2a':              'text-cyan-400',
  'agent:restarted':  'text-orange-400',
  'unknown':          'text-gray-400',
}

function EventRow({ event }: { event: SSEEvent }) {
  const color = TYPE_COLORS[event.type] ?? TYPE_COLORS.unknown
  return (
    <div className="flex gap-3 py-2 border-b border-gray-800 text-sm">
      <span className="text-gray-500 shrink-0 w-24 text-xs">{new Date(event.ts).toLocaleTimeString()}</span>
      <span className={`shrink-0 w-32 font-mono text-xs ${color}`}>{event.type}</span>
      <span className="text-gray-300 break-all">{JSON.stringify(event.data)}</span>
    </div>
  )
}

function Feed() {
  const { events, connected } = useSSE()
  const [filter, setFilter] = useState('')

  const filtered = filter
    ? events.filter(e => e.type.includes(filter) || JSON.stringify(e.data).includes(filter))
    : events

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold">Activity Feed</h1>
        <span className={`text-xs px-2 py-1 rounded-full ${connected ? 'bg-green-900 text-green-400' : 'bg-gray-800 text-gray-400'}`}>
          {connected ? 'Live' : 'Disconnected'}
        </span>
      </div>
      <input
        className="w-full max-w-sm px-3 py-2 rounded bg-gray-800 text-white border border-gray-700 focus:outline-none focus:border-blue-500 text-sm mb-4"
        placeholder="Filter events…"
        value={filter}
        onChange={e => setFilter(e.target.value)}
      />
      <div className="font-mono max-h-[70vh] overflow-y-auto">
        {filtered.length === 0 && <p className="text-gray-500 text-sm">No events yet.</p>}
        {filtered.map(e => <EventRow key={e.id} event={e} />)}
      </div>
    </div>
  )
}

export default function ActivityFeedPage() {
  return (
    <SSEProvider>
      <Feed />
    </SSEProvider>
  )
}
