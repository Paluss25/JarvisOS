import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import AgentsPage from './pages/AgentsPage'
import AgentDetailPage from './pages/AgentDetailPage'
import MissionControlPage from './pages/MissionControlPage'
import TaskDetailPage from './pages/TaskDetailPage'
import ActivityFeedPage from './pages/ActivityFeedPage'
import AuditLogPage from './pages/AuditLogPage'
import SettingsPage from './pages/SettingsPage'

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<Layout />}>
            <Route path="/" element={<Navigate to="/agents" replace />} />
            <Route path="/agents" element={<AgentsPage />} />
            <Route path="/agents/:id" element={<AgentDetailPage />} />
            <Route path="/missions" element={<MissionControlPage />} />
            <Route path="/missions/:id" element={<TaskDetailPage />} />
            <Route path="/activity" element={<ActivityFeedPage />} />
            <Route path="/audit" element={<AuditLogPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
