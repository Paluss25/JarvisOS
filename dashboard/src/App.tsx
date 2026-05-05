import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import AgentsPage from './pages/AgentsPage'
import AgentDetailPage from './pages/AgentDetailPage'
import TaskBoardPage from './pages/TaskBoardPage'
import TaskDetailPage from './pages/TaskDetailPage'
import TraceDetailPage from './pages/TraceDetailPage'
import TraceExplorerPage from './pages/TraceExplorerPage'
import ActivityFeedPage from './pages/ActivityFeedPage'
import A2ANetworkPage from './pages/A2ANetworkPage'
import AuditLogPage from './pages/AuditLogPage'
import CockpitPage from './pages/CockpitPage'
import ChatHubPage from './pages/ChatHubPage'
import ControlCenterPage from './pages/ControlCenterPage'
import IncidentsPage from './pages/IncidentsPage'
import LogsPage from './pages/LogsPage'
import SettingsPage from './pages/SettingsPage'

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<Layout />}>
            <Route path="/" element={<Navigate to="/control-center" replace />} />
            <Route path="/control-center" element={<ControlCenterPage />} />
            <Route path="/agents" element={<AgentsPage />} />
            <Route path="/agents/:id" element={<AgentDetailPage />} />
            <Route path="/agents/:id/chat" element={<ChatHubPage />} />
            <Route path="/agents/:id/cockpit" element={<CockpitPage />} />
            <Route path="/chat" element={<ChatHubPage />} />
            <Route path="/tasks" element={<TaskBoardPage />} />
            <Route path="/tasks/:id" element={<TaskDetailPage />} />
            <Route path="/missions" element={<Navigate to="/tasks" replace />} />
            <Route path="/missions/:id" element={<TaskDetailPage />} />
            <Route path="/traces" element={<TraceExplorerPage />} />
            <Route path="/traces/:traceId" element={<TraceDetailPage />} />
            <Route path="/logs" element={<LogsPage />} />
            <Route path="/incidents" element={<IncidentsPage />} />
            <Route path="/activity" element={<ActivityFeedPage />} />
            <Route path="/a2a" element={<A2ANetworkPage />} />
            <Route path="/audit" element={<AuditLogPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
