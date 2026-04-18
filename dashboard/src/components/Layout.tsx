import { NavLink, Outlet, Navigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const navItems = [
  { to: '/agents', label: 'Agents' },
  { to: '/missions', label: 'Missions' },
  { to: '/activity', label: 'Activity' },
  { to: '/audit', label: 'Audit' },
  { to: '/settings', label: 'Settings' },
]

export default function Layout() {
  const { user, loading, logout } = useAuth()

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-950">
        <span className="text-gray-400">Loading…</span>
      </div>
    )
  }

  if (!user) return <Navigate to="/login" replace />

  return (
    <div className="flex h-screen bg-gray-950 text-white">
      {/* Sidebar */}
      <aside className="w-52 shrink-0 flex flex-col bg-gray-900 border-r border-gray-800">
        <div className="px-4 py-5 border-b border-gray-800">
          <span className="text-lg font-bold tracking-tight">JarvisOS</span>
        </div>
        <nav className="flex-1 px-2 py-4 space-y-1">
          {navItems.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `block px-3 py-2 rounded text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-blue-600 text-white'
                    : 'text-gray-300 hover:bg-gray-800 hover:text-white'
                }`
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="px-4 py-4 border-t border-gray-800">
          <p className="text-xs text-gray-500 mb-2">{user.username}</p>
          <button
            onClick={logout}
            className="text-xs text-gray-400 hover:text-white transition-colors"
          >
            Sign out
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  )
}
